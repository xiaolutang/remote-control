import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/widgets.dart';
import 'package:xterm/xterm.dart';

import 'websocket_service.dart';

class _TerminalState {
  _TerminalState(this.terminal);

  final Terminal terminal;
  final ValueNotifier<String> outputText = ValueNotifier<String>('');
  final List<String> _outputBuffer = [];
  final List<String> _pendingRecoveryFrames = [];
  bool _hasLiveOutput = false;
  bool _recovering = false;

  static const int _maxBufferLines = 50;

  void applyRemotePtySize(int rows, int cols) {
    if (rows <= 0 || cols <= 0) {
      return;
    }
    if (terminal.viewHeight == rows && terminal.viewWidth == cols) {
      return;
    }
    final previousOnResize = terminal.onResize;
    terminal.onResize = null;
    try {
      terminal.resize(cols, rows);
    } finally {
      terminal.onResize = previousOnResize;
    }
  }

  void _writeFrame(String data) {
    terminal.write(data);
    appendOutput(data);
  }

  // TODO(F073): 通过 RendererAdapter 收口，不直接操作 xterm mainBuffer/altBuffer
  void _resetTerminalBuffers() {
    terminal.useMainBuffer();
    terminal.mainBuffer.clear();
    terminal.altBuffer.clear();
    _outputBuffer.clear();
  }

  void beginRecovery() {
    _recovering = true;
    _hasLiveOutput = false;
    _pendingRecoveryFrames.clear();
  }

  void replaceWithSnapshot(String data) {
    if (!_recovering && _hasLiveOutput) {
      return;
    }
    _resetTerminalBuffers();
    _writeFrame(data);
  }

  void prepareForRebind() {
    beginRecovery();
  }

  void appendLiveFrame(String data) {
    if (_recovering) {
      _pendingRecoveryFrames.add(data);
      return;
    }
    _writeFrame(data);
  }

  void finishRecovery() {
    if (!_recovering) {
      return;
    }
    _recovering = false;
    for (final frame in _pendingRecoveryFrames) {
      _writeFrame(frame);
    }
    _pendingRecoveryFrames.clear();
  }

  void appendOutput(String data) {
    if (data.isNotEmpty) {
      _hasLiveOutput = true;
    }
    final lines = data.split('\n');
    for (final line in lines) {
      if (line.isEmpty) {
        continue;
      }
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

  Terminal getOrCreateTerminal(
    String? deviceId,
    String terminalId,
    Terminal Function() create, {
    WebSocketService? service,
  }) {
    final key = _key(deviceId, terminalId);
    final state = _terminals.putIfAbsent(key, () => _TerminalState(create()));
    if (service != null) {
      bindTerminalOutput(deviceId, terminalId, service);
    }
    return state.terminal;
  }

  Terminal? getTerminal(String? deviceId, String terminalId) {
    return _terminals[_key(deviceId, terminalId)]?.terminal;
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
    await Future.wait(
      sessions.map((service) async {
        await service.disconnect();
        service.dispose();
      }),
    );
    notifyListeners();
  }

  @override
  void dispose() {
    if (_observerRegistered) {
      WidgetsBinding.instance.removeObserver(this);
      _observerRegistered = false;
    }
    super.dispose();
  }
}
