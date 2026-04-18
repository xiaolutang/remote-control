import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/widgets.dart';
import 'package:xterm/xterm.dart';

import 'websocket_service.dart';

/// Terminal session 状态机枚举（F072）
enum TerminalSessionState {
  idle,
  connecting,
  recovering,
  live,
  reconnecting,
  error,
}

/// xterm Terminal 的稳定包装层（F073）
/// Coordinator 和 UI 只依赖此接口，不直接操作 xterm Terminal。
class RendererAdapter {
  RendererAdapter(this._terminal);

  final Terminal _terminal;
  final List<String> _outputBuffer = [];
  final ValueNotifier<String> outputText = ValueNotifier<String>('');

  static const int _maxBufferLines = 50;

  /// 底层 Terminal 实例的只读引用。
  /// 仅用于 TerminalView widget 构造（xterm 包硬约束）。
  /// 不要通过此引用直接操作 Terminal，应使用 RendererAdapter 的方法。
  Terminal get terminalForView => _terminal;

  /// 应用 snapshot（清空现有 buffer 后写入）
  void applySnapshot(String data) {
    _terminal.useMainBuffer();
    _terminal.mainBuffer.clear();
    _terminal.altBuffer.clear();
    _outputBuffer.clear();
    _write(data);
  }

  /// 应用 live output（直接追加写入）
  void applyLiveOutput(String data) {
    _write(data);
  }

  /// 调整 renderer 尺寸（静默 onResize 回调）
  void resize(int cols, int rows) {
    if (rows <= 0 || cols <= 0) return;
    if (_terminal.viewHeight == rows && _terminal.viewWidth == cols) return;
    final prev = _terminal.onResize;
    _terminal.onResize = null;
    try {
      _terminal.resize(cols, rows);
    } finally {
      _terminal.onResize = prev;
    }
  }

  /// 重置 renderer 状态（清空所有 buffer）
  void reset() {
    _terminal.useMainBuffer();
    _terminal.mainBuffer.clear();
    _terminal.altBuffer.clear();
    _outputBuffer.clear();
    outputText.value = '';
  }

  void _write(String data) {
    _terminal.write(data);
    _appendOutputBuffer(data);
  }

  void _appendOutputBuffer(String data) {
    if (data.isEmpty) return;
    final lines = data.split('\n');
    for (final line in lines) {
      if (line.isEmpty) continue;
      _outputBuffer.add(line);
      if (_outputBuffer.length > _maxBufferLines) {
        _outputBuffer.removeAt(0);
      }
    }
    outputText.value = _outputBuffer.join('\n');
  }

  void dispose() {
    outputText.dispose();
  }
}

class _TerminalState {
  _TerminalState(Terminal terminal) : renderer = RendererAdapter(terminal);

  final RendererAdapter renderer;
  final List<String> _pendingRecoveryFrames = [];
  bool _hasLiveOutput = false;
  bool _recovering = false;

  // F072: 显式状态机追踪
  TerminalSessionState _sessionState = TerminalSessionState.idle;
  final ValueNotifier<TerminalSessionState> _stateNotifier =
      ValueNotifier<TerminalSessionState>(TerminalSessionState.idle);

  TerminalSessionState get sessionState => _sessionState;
  ValueNotifier<TerminalSessionState> get stateNotifier => _stateNotifier;

  /// 合法的状态转换表
  static const Map<TerminalSessionState, Set<TerminalSessionState>>
      _transitions = {
    TerminalSessionState.idle: {
      TerminalSessionState.connecting,
      TerminalSessionState.recovering,
      TerminalSessionState.live,
      TerminalSessionState.error,
    },
    TerminalSessionState.connecting: {
      TerminalSessionState.recovering,
      TerminalSessionState.error,
      TerminalSessionState.idle,
    },
    TerminalSessionState.recovering: {
      TerminalSessionState.live,
      TerminalSessionState.error,
      TerminalSessionState.idle,
    },
    TerminalSessionState.live: {
      TerminalSessionState.recovering,
      TerminalSessionState.reconnecting,
      TerminalSessionState.live,
      TerminalSessionState.error,
      TerminalSessionState.idle,
    },
    TerminalSessionState.reconnecting: {
      TerminalSessionState.recovering,
      TerminalSessionState.error,
      TerminalSessionState.idle,
    },
    TerminalSessionState.error: {
      TerminalSessionState.connecting,
      TerminalSessionState.idle,
    },
  };

  void _setSessionState(TerminalSessionState newState) {
    final allowed = _transitions[_sessionState];
    if (allowed != null && allowed.contains(newState)) {
      _sessionState = newState;
      _stateNotifier.value = newState;
    } else {
      debugPrint(
        '[TerminalSessionState] illegal transition: '
        '$_sessionState -> $newState',
      );
    }
  }

  // 代理到 renderer
  ValueNotifier<String> get outputText => renderer.outputText;

  void applyRemotePtySize(int rows, int cols) => renderer.resize(cols, rows);

  void beginRecovery() {
    _recovering = true;
    _hasLiveOutput = false;
    _pendingRecoveryFrames.clear();
    // F072: 合法转换 connecting/reconnecting/idle/live -> recovering
    _setSessionState(TerminalSessionState.recovering);
  }

  void replaceWithSnapshot(String data) {
    if (!_recovering && _hasLiveOutput) {
      return;
    }
    renderer.applySnapshot(data);
  }

  void prepareForRebind() {
    beginRecovery();
  }

  void appendLiveFrame(String data) {
    if (_recovering) {
      _pendingRecoveryFrames.add(data);
      return;
    }
    if (data.isNotEmpty) {
      _hasLiveOutput = true;
    }
    renderer.applyLiveOutput(data);
  }

  void finishRecovery() {
    if (!_recovering) {
      return;
    }
    _recovering = false;
    for (final frame in _pendingRecoveryFrames) {
      renderer.applyLiveOutput(frame);
    }
    _pendingRecoveryFrames.clear();
    // F072: recovering -> live
    _setSessionState(TerminalSessionState.live);
  }

  void dispose() {
    renderer.dispose();
    _stateNotifier.dispose();
  }
}

class _TerminalBinding {
  const _TerminalBinding({
    required this.service,
    required this.connectedSubscription,
    required this.outputSubscription,
    required this.ptySubscription,
  });

  final WebSocketService service;
  final StreamSubscription<void> connectedSubscription;
  final StreamSubscription<TerminalOutputFrame> outputSubscription;
  final StreamSubscription<TerminalPtySize> ptySubscription;

  Future<void> cancel() async {
    await connectedSubscription.cancel();
    await outputSubscription.cancel();
    await ptySubscription.cancel();
  }
}

class TerminalSessionManager extends ChangeNotifier
    with WidgetsBindingObserver {
  final Map<String, WebSocketService> _sessions = {};
  final Map<String, _TerminalState> _terminals = {};
  final Map<String, _TerminalBinding> _terminalBindings = {};

  /// 暂停前已连接的 session keys，用于 resumeAll 时重连
  Set<String> _pausedKeys = {};

  /// 是否已注册 observer（仅移动端注册）
  bool _observerRegistered = false;

  /// F072: 当前 view 的 active terminal key
  String? _activeTerminalKey;

  TerminalSessionManager() {
    _maybeRegisterObserver();
  }

  /// 仅移动端注册 WidgetsBindingObserver
  void _maybeRegisterObserver() {
    final isMobile = defaultTargetPlatform == TargetPlatform.android ||
        defaultTargetPlatform == TargetPlatform.iOS;
    if (isMobile) {
      WidgetsBinding.instance.addObserver(this);
      _observerRegistered = true;
    }
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    switch (state) {
      case AppLifecycleState.paused:
      case AppLifecycleState.inactive:
        pauseAll();
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
    _pausedKeys = {};
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

  /// App 回到前台时调用：对暂停前已连接的 service 并行调用 connect()。
  /// 手动 disconnect 或 pause 后新增的 service 不受影响。
  /// 单个 service connect 失败不阻塞其他 service。
  Future<void> resumeAll() async {
    final keysToResume = _pausedKeys;
    _pausedKeys = {};
    await Future.wait(
      keysToResume.map((key) async {
        final service = _sessions[key];
        if (service != null && service.status != ConnectionStatus.connected) {
          try {
            await service.connect();
          } catch (e) {
            debugPrint(
                '[TerminalSessionManager] resume connect error for $key: $e');
          }
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
      bindTerminalOutput(deviceId, terminalId, service);
    }
    return state.renderer._terminal;
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

    final existing = _terminalBindings[key];
    if (existing != null && identical(existing.service, service)) {
      return;
    }

    if (existing != null) {
      state.prepareForRebind();
      unawaited(existing.cancel());
    }
    final currentRows = service.ptyRows;
    final currentCols = service.ptyCols;
    if (currentRows != null && currentCols != null) {
      state.applyRemotePtySize(currentRows, currentCols);
    }
    if (existing == null && service.status == ConnectionStatus.connected) {
      state.beginRecovery();
    }
    _terminalBindings[key] = _TerminalBinding(
      service: service,
      connectedSubscription: service.terminalConnectedStream.listen((_) {
        state.beginRecovery();
      }),
      outputSubscription: service.outputFrameStream.listen((frame) {
        if (frame.isSnapshot) {
          state.replaceWithSnapshot(frame.payload);
          return;
        }
        if (frame.kind == TerminalOutputKind.snapshotComplete) {
          state.finishRecovery();
          return;
        }
        state.appendLiveFrame(frame.payload);
      }),
      ptySubscription: service.ptySizeStream.listen((pty) {
        state.applyRemotePtySize(pty.rows, pty.cols);
      }),
    );
  }

  Future<void> deactivateConflictingTerminalSessions(
    WebSocketService activeService,
  ) async {
    final activeTerminalId = activeService.terminalId;
    final activeDeviceId = activeService.deviceId;
    if ((activeTerminalId ?? '').isEmpty) {
      return;
    }

    final conflictingEntries = _sessions.entries.where((entry) {
      final candidate = entry.value;
      if (identical(candidate, activeService)) {
        return false;
      }
      if (candidate.deviceId != activeDeviceId) {
        return false;
      }
      if (candidate.viewType != activeService.viewType) {
        return false;
      }
      final candidateTerminalId = candidate.terminalId;
      if ((candidateTerminalId ?? '').isEmpty) {
        return false;
      }
      if (candidateTerminalId == activeTerminalId) {
        return false;
      }
      return candidate.status != ConnectionStatus.disconnected;
    }).toList(growable: false);

    for (final entry in conflictingEntries) {
      _pausedKeys.remove(entry.key);
      await entry.value.disconnect(notify: false);
    }
  }

  void _disposeTerminalState(String key) {
    final binding = _terminalBindings.remove(key);
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

  /// 连接到 terminal（首次 attach 或 reconnect）。
  /// 状态路径：idle/connecting -> connecting -> recovering -> live
  Future<void> connectTerminal(String? deviceId, String terminalId) async {
    final key = _key(deviceId, terminalId);
    final state = _terminals[key];
    if (state == null) {
      return;
    }

    final current = state.sessionState;
    // 只有 idle 或 error 状态才允许 connect
    if (current != TerminalSessionState.idle &&
        current != TerminalSessionState.error) {
      return;
    }

    state._setSessionState(TerminalSessionState.connecting);
    _activeTerminalKey = key;

    final service = _sessions[key];
    if (service == null) {
      state._setSessionState(TerminalSessionState.error);
      return;
    }

    try {
      await service.connect();
      // connect 成功后，bindTerminalOutput 中的 connectedSubscription
      // 会触发 beginRecovery，推动 recovering -> live
    } catch (e) {
      state._setSessionState(TerminalSessionState.error);
    }
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
    super.dispose();
  }
}
