import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/widgets.dart';
import 'package:xterm/xterm.dart';

import 'websocket_service.dart';
import '../utils/terminal_escape_utils.dart';

part 'terminal_session_types.dart';
part 'renderer_adapter.dart';
part 'terminal_session_state.dart';

class TerminalSessionManager extends ChangeNotifier
    with WidgetsBindingObserver {
  final Map<String, WebSocketService> _sessions = {};
  final Map<String, _TerminalState> _terminals = {};
  final Map<String, _TerminalBinding> _terminalBindings = {};
  final Map<String, int> _bindingGenerations = {};

  /// 暂停前已连接的 session keys，用于 resumeAll 时重连
  Set<String> _pausedKeys = {};

  /// 是否已注册 observer（仅移动端注册）
  bool _observerRegistered = false;

  /// F072: 当前 view 的 active terminal key
  String? _activeTerminalKey;

  TerminalSessionManager() {
    _maybeRegisterObserver();
  }

  bool get _shouldPauseOnInactive {
    if (kIsWeb) {
      return false;
    }
    switch (defaultTargetPlatform) {
      case TargetPlatform.android:
      case TargetPlatform.iOS:
        return true;
      case TargetPlatform.fuchsia:
      case TargetPlatform.linux:
      case TargetPlatform.macOS:
      case TargetPlatform.ohos:
      case TargetPlatform.windows:
        return false;
    }
  }

  /// F076: 全平台注册 WidgetsBindingObserver
  /// 桌面端也需要感知前后台切换（macOS 合盖/窗口最小化等）
  void _maybeRegisterObserver() {
    WidgetsBinding.instance.addObserver(this);
    _observerRegistered = true;
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    switch (state) {
      case AppLifecycleState.paused:
        pauseAll();
        break;
      case AppLifecycleState.inactive:
        if (_shouldPauseOnInactive) {
          pauseAll();
        }
        break;
      case AppLifecycleState.resumed:
        resumeAll();
        break;
      default:
        break;
    }
  }

  /// App 进入后台时调用：断开所有已连接的 WebSocket，但保留 session 元数据。
  /// 仅对 status == connected 的 service 调用 disconnect()。
  /// 单个 service disconnect 失败不阻塞其他 service。
  void pauseAll() {
    for (final entry in _sessions.entries) {
      if (entry.value.status == ConnectionStatus.connected) {
        _pausedKeys.add(entry.key);
        try {
          // ignore: discarded_futures — disconnect 内部异步，无需 await
          entry.value.disconnect();
        } catch (e) {
          debugPrint('[TerminalSessionManager] disconnect error: $e');
        }
      }
    }
  }

  /// App 回到前台时调用：对暂停前已连接的 service 并行恢复。
  /// F076: 使用 recoverWithRetry 状态机而非直接 service.connect()。
  /// 手动 disconnect 或 pause 后新增的 service 不受影响。
  /// 单个 service connect 失败不阻塞其他 service。
  Future<void> resumeAll() async {
    final keysToResume = _pausedKeys;
    _pausedKeys = {};
    await Future.wait(
      keysToResume.map((key) async {
        final service = _sessions[key];
        if (service != null && service.status != ConnectionStatus.connected) {
          final state = _terminals[key];
          if (state != null) {
            // F076: 通过带重试的恢复路径
            final parts = key.split('::');
            await recoverWithRetry(
              parts.isNotEmpty ? parts[0] : null,
              parts.length > 1 ? parts.sublist(1).join('::') : key,
            );
          }
          // 无 terminal state 的 service 不走恢复路径：
          // 需要先 bindTerminalOutput 创建 terminal state 后才能恢复。
        }
      }),
    );
  }

  String _key(String? deviceId, String terminalId) =>
      '${deviceId ?? ''}::$terminalId';

  WebSocketService getOrCreate(
    String? deviceId,
    String terminalId,
    WebSocketService Function() create,
  ) {
    final key = _key(deviceId, terminalId);
    final existing = _sessions[key];
    if (existing != null) {
      // 安全网：如果缓存的服务已因认证失败而永久断开，
      // 说明上次退出时未正确清理缓存，自动丢弃并重建。
      // 正常断开（如网络波动、Agent 离线）不在此列，应复用现有服务。
      if (existing.isAuthFailed) {
        debugPrint(
          '[TerminalSessionManager] evicting auth-failed session: '
          'key=$key closeCode=${existing.lastCloseCode}',
        );
        _sessions.remove(key);
        _pausedKeys.remove(key);
        unawaited(existing.disconnect());
      } else {
        return existing;
      }
    }

    final service = create();
    _sessions[key] = service;
    return service;
  }

  WebSocketService? get(String? deviceId, String terminalId) {
    return _sessions[_key(deviceId, terminalId)];
  }

  /// F073: 已废弃，上层应通过 getRendererAdapter 获取 RendererAdapter。
  /// 完整迁移在 F074（UI 瘦身）中完成。
  @Deprecated('Use getRendererAdapter instead. Will be removed in F074.')
  // ignore: unnecessary_non_null_assertion
  Terminal getOrCreateTerminal(
    String? deviceId,
    String terminalId,
    Terminal Function() create, {
    WebSocketService? service,
  }) {
    final key = _key(deviceId, terminalId);
    final state = _terminals.putIfAbsent(key, () => _TerminalState(create()));
    // F072: 新创建的 terminal 自动成为 active terminal
    _activeTerminalKey = key;
    if (service != null) {
      _sessions[key] = service;
      bindTerminalOutput(deviceId, terminalId, service);
    }
    return state.renderer._terminal;
  }

  /// F074: 创建或复用 terminal，并返回稳定的 RendererAdapter。
  RendererAdapter ensureRendererAdapter(
    String? deviceId,
    String terminalId,
    Terminal Function() create, {
    WebSocketService? service,
  }) {
    final key = _key(deviceId, terminalId);
    final state = _terminals.putIfAbsent(key, () => _TerminalState(create()));
    _activeTerminalKey = key;
    if (service != null) {
      _sessions[key] = service;
      bindTerminalOutput(deviceId, terminalId, service);
    }
    return state.renderer;
  }

  /// F073: 已废弃，上层应通过 getRendererAdapter 获取 RendererAdapter。
  @Deprecated('Use getRendererAdapter instead. Will be removed in F074.')
  Terminal? getTerminal(String? deviceId, String terminalId) {
    return _terminals[_key(deviceId, terminalId)]?.renderer._terminal;
  }

  /// F073: 获取指定 terminal 的 RendererAdapter
  RendererAdapter? getRendererAdapter(String? deviceId, String terminalId) {
    return _terminals[_key(deviceId, terminalId)]?.renderer;
  }

  ValueListenable<String>? getTerminalOutputListenable(
    String? deviceId,
    String terminalId,
  ) {
    return _terminals[_key(deviceId, terminalId)]?.outputText;
  }

  void bindTerminalOutput(
    String? deviceId,
    String terminalId,
    WebSocketService service,
  ) {
    final key = _key(deviceId, terminalId);
    final state = _terminals[key];
    if (state == null) {
      return;
    }

    // Terminal output routing belongs to coordinator/transport, not the UI.
    // This keeps key input and VT query responses bound to the session even
    // across widget rebuilds and service rebinds.
    state.bindTransportSink(service.send);

    final existing = _terminalBindings[key];
    if (existing != null && identical(existing.service, service)) {
      return;
    }

    if (existing != null) {
      if (service.status != ConnectionStatus.connected) {
        state.prepareForRebind();
      }
      unawaited(existing.cancel());
    }
    final currentRows = service.ptyRows;
    final currentCols = service.ptyCols;
    if (currentRows != null && currentCols != null) {
      state.applyRemotePtySize(currentRows, currentCols);
    }
    if (existing == null && service.status == ConnectionStatus.connected) {
      // Late-binding to an already-live transport should not fabricate a
      // recovery window. Recovery is only entered by a fresh connected event
      // or an explicit rebind, otherwise live output would stay buffered
      // forever waiting for a snapshot_complete that will never arrive.
      state._setSessionState(TerminalSessionState.live);
    } else if (existing != null &&
        service.status == ConnectionStatus.connected) {
      if (state.sessionState == TerminalSessionState.error) {
        state.beginRecovery();
      } else {
        // Rebinding to a replacement service that is already live should keep
        // the current terminal live. If the new transport later emits a fresh
        // connected event, connectedSubscription will enter recovery then.
        state._setSessionState(TerminalSessionState.live);
      }
    }
    final generation = (_bindingGenerations[key] ?? 0) + 1;
    _bindingGenerations[key] = generation;
    _terminalBindings[key] = _createTerminalBinding(
      service: service,
      generation: generation,
      key: key,
      state: state,
      bindingGenerations: _bindingGenerations,
    );
    service.addListener(_terminalBindings[key]!.statusListener);
  }

  Future<void> deactivateConflictingTerminalSessions(
    WebSocketService activeService,
  ) async {
    await _deactivateConflictingSessions(
      activeService: activeService,
      sessions: _sessions,
      terminals: _terminals,
      pausedKeys: _pausedKeys,
    );
  }

  void _disposeTerminalState(String key) {
    final binding = _terminalBindings.remove(key);
    _bindingGenerations.remove(key);
    _networkRetryCount.remove(key);
    if (binding != null) {
      unawaited(binding.cancel());
    }
    _terminals.remove(key)?.dispose();
  }

  Future<void> disconnectTerminal(String? deviceId, String terminalId) async {
    final key = _key(deviceId, terminalId);
    final service = _sessions.remove(key);
    _disposeTerminalState(key);
    if (_activeTerminalKey == key) {
      _activeTerminalKey = null;
    }
    if (service == null) {
      return;
    }
    _pausedKeys.remove(key);
    await service.disconnect();
    notifyListeners();
  }

  Future<void> disconnectAll() async {
    final sessions = _sessions.values.toList(growable: false);
    _sessions.clear();
    for (final key in _terminals.keys.toList(growable: false)) {
      _disposeTerminalState(key);
    }
    _pausedKeys = {};
    _activeTerminalKey = null;
    await Future.wait(
      sessions.map((service) async {
        await service.disconnect();
        service.dispose();
      }),
    );
    notifyListeners();
  }

  // ─── F072: 显式状态机入口点 ───────────────────────────────

  /// 连接到 terminal（首次 attach）。
  /// 状态路径：idle/connecting -> connecting -> recovering -> live
  Future<void> connectTerminal(String? deviceId, String terminalId) async {
    await _connectInternal(
        deviceId, terminalId, TerminalSessionState.connecting);
  }

  /// 切换 active terminal（只切 UI + active，不触发 recover）。
  /// 不改变任何 terminal 的 sessionState。
  void switchTerminal(String? deviceId, String terminalId) {
    final key = _key(deviceId, terminalId);
    if (!_terminals.containsKey(key)) {
      return;
    }
    _activeTerminalKey = key;
  }

  /// F074: 重连 terminal（状态推进 + connect 统一入口）。
  /// 状态路径：error/idle -> reconnecting -> (connect) -> recovering -> live
  Future<void> reconnectTerminal(String? deviceId, String terminalId) async {
    await _connectInternal(
        deviceId, terminalId, TerminalSessionState.reconnecting);
  }

  /// connectTerminal / reconnectTerminal 共享的连接逻辑。
  Future<void> _connectInternal(
    String? deviceId,
    String terminalId,
    TerminalSessionState initialState,
  ) async {
    final key = _key(deviceId, terminalId);
    final state = _terminals[key];
    if (state == null) return;

    final current = state.sessionState;
    final allowReconnectFromLive =
        initialState == TerminalSessionState.reconnecting &&
            current == TerminalSessionState.live;
    if (current != TerminalSessionState.idle &&
        current != TerminalSessionState.error &&
        !allowReconnectFromLive) {
      return;
    }

    state._setSessionState(initialState);
    _activeTerminalKey = key;

    final service = _sessions[key];
    if (service == null) {
      state._setSessionState(TerminalSessionState.error);
      return;
    }

    try {
      await service.connect();
      if (service.status != ConnectionStatus.connected) {
        if (service.isPermanentlyFailed) {
          state._setSessionState(TerminalSessionState.error);
        }
        // 临时失败：autoReconnect 仍在运行，connectedSubscription
        // 会在重连成功后触发 beginRecovery() 自然恢复
        return;
      }
      // connect 成功后，bindTerminalOutput 的 connectedSubscription
      // 会触发 beginRecovery，推动 recovering -> live
    } catch (e) {
      state._setSessionState(TerminalSessionState.error);
    }
  }

  /// 触发恢复（reconnect 或 follower re-enter 后调用）。
  /// 状态路径：live/reconnecting -> recovering -> live
  void recoverTerminal(String? deviceId, String terminalId) {
    final key = _key(deviceId, terminalId);
    final state = _terminals[key];
    if (state == null) {
      return;
    }

    final current = state.sessionState;
    if (current == TerminalSessionState.live) {
      // live -> reconnecting -> recovering
      state._setSessionState(TerminalSessionState.reconnecting);
    }
    // reconnecting -> recovering (via beginRecovery)
    state.beginRecovery();
  }

  /// F076: 网络恢复重试。在连接失败后自动重试，耗尽后进入 error。
  static const int _maxNetworkRetries = 3;
  static const Duration _networkRetryDelay = Duration(seconds: 2);
  final Map<String, int> _networkRetryCount = {};

  Future<void> recoverWithRetry(String? deviceId, String terminalId) async {
    final key = _key(deviceId, terminalId);
    final state = _terminals[key];
    final service = _sessions[key];
    if (state == null || service == null) {
      _networkRetryCount.remove(key);
      return;
    }

    // 已耗尽重试次数，收敛到 error
    final retryCount = _networkRetryCount[key] ?? 0;
    if (retryCount >= _maxNetworkRetries) {
      state._setSessionState(TerminalSessionState.error);
      _networkRetryCount.remove(key);
      return;
    }

    _networkRetryCount[key] = retryCount + 1;
    state._setSessionState(TerminalSessionState.recovering);

    try {
      await service.connect();
      // F076 fix: connect() 可能返回而不抛异常但实际连接失败
      // 检查 service 状态确认是否真正连接
      if (service.status == ConnectionStatus.connected) {
        _networkRetryCount.remove(key);
      } else {
        // 连接未成功，延迟后重试
        debugPrint(
          '[TerminalSessionManager] recovery connect returned but not connected for $key',
        );
        await Future.delayed(_networkRetryDelay);
        await recoverWithRetry(deviceId, terminalId);
      }
    } catch (e) {
      debugPrint(
        '[TerminalSessionManager] network recovery retry $retryCount for $key: $e',
      );
      // 延迟后重试
      await Future.delayed(_networkRetryDelay);
      await recoverWithRetry(deviceId, terminalId);
    }
  }

  /// 查询指定 terminal 的当前状态
  TerminalSessionState getTerminalState(String? deviceId, String terminalId) {
    return _terminals[_key(deviceId, terminalId)]?.sessionState ??
        TerminalSessionState.idle;
  }

  /// 监听指定 terminal 的状态变化
  ValueListenable<TerminalSessionState>? getTerminalStateListenable(
    String? deviceId,
    String terminalId,
  ) {
    return _terminals[_key(deviceId, terminalId)]?.stateNotifier;
  }

  /// 查询当前 active terminal key（仅测试用）
  String? get activeTerminalKeyForTest => _activeTerminalKey;

  @override
  void dispose() {
    if (_observerRegistered) {
      WidgetsBinding.instance.removeObserver(this);
      _observerRegistered = false;
    }
    // F076: 清理恢复编排状态，防止 disposed manager 继续推进恢复
    _networkRetryCount.clear();
    for (final key in _terminals.keys.toList(growable: false)) {
      _disposeTerminalState(key);
    }
    _terminals.clear();
    _terminalBindings.clear();
    _bindingGenerations.clear();
    super.dispose();
  }
}
