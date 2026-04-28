part of 'terminal_session_manager.dart';

class _TerminalState {
  _TerminalState(Terminal terminal) : renderer = RendererAdapter(terminal);

  final RendererAdapter renderer;
  final List<String> _pendingRecoveryFrames = [];
  final List<String> _pendingSnapshotChunks = [];
  final List<String> _pendingTerminalReplies = [];
  bool _hasLiveOutput = false;
  bool _recovering = false;
  TerminalBufferKind _pendingSnapshotActiveBuffer = TerminalBufferKind.main;
  _TerminalReplyGuardMode _replyGuardMode = _TerminalReplyGuardMode.none;
  Timer? _recoveryTimeoutTimer;
  Timer? _postInterruptReplyTimer;
  void Function(String data)? _transportSink;
  bool _snapshotReplayInProgress = false;

  // F072: 显式状态机追踪
  TerminalSessionState _sessionState = TerminalSessionState.idle;
  final ValueNotifier<TerminalSessionState> _stateNotifier =
      ValueNotifier<TerminalSessionState>(TerminalSessionState.idle);

  TerminalSessionState get sessionState => _sessionState;
  ValueNotifier<TerminalSessionState> get stateNotifier => _stateNotifier;
  bool get isRecovering => _recovering;

  /// 合法的状态转换表
  static const Map<TerminalSessionState, Set<TerminalSessionState>>
      _transitions = {
    TerminalSessionState.idle: {
      TerminalSessionState.connecting,
      TerminalSessionState.reconnecting,
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
      TerminalSessionState.recovering,
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
      TerminalSessionState.reconnecting,
      TerminalSessionState.recovering,
      TerminalSessionState.idle,
    },
  };

  void _setSessionState(TerminalSessionState newState) {
    if (_sessionState == newState) return;
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
  ValueListenable<String> get outputText => renderer.outputText;

  void applyRemotePtySize(int rows, int cols) => renderer.resize(cols, rows);

  void bindTransportSink(void Function(String data) sink) {
    _transportSink = sink;
    renderer.terminalForView.onOutput = _handleTerminalOutput;
  }

  void beginRecovery() {
    if (_recovering) {
      _armReplyGuard(_TerminalReplyGuardMode.recovery);
      _recoveryTimeoutTimer?.cancel();
      _recoveryTimeoutTimer = Timer(_recoveryTimeout, () {
        if (_recovering) {
          debugPrint(
            '[TerminalSessionState] recovery timeout — auto-finishing recovery',
          );
          finishRecovery();
        }
      });
      _setSessionState(TerminalSessionState.recovering);
      return;
    }
    _recovering = true;
    _hasLiveOutput = false;
    _pendingRecoveryFrames.clear();
    _pendingSnapshotChunks.clear();
    _pendingSnapshotActiveBuffer = TerminalBufferKind.main;
    _armReplyGuard(_TerminalReplyGuardMode.recovery);
    // 安全网：如果 snapshot_complete 未在超时内到达，自动完成恢复
    _recoveryTimeoutTimer?.cancel();
    _recoveryTimeoutTimer = Timer(_recoveryTimeout, () {
      if (_recovering) {
        debugPrint(
          '[TerminalSessionState] recovery timeout — auto-finishing recovery',
        );
        finishRecovery();
      }
    });
    // F072: 合法转换 connecting/reconnecting/idle/live -> recovering
    _setSessionState(TerminalSessionState.recovering);
  }

  void replaceWithSnapshot(
    String data, {
    TerminalBufferKind activeBuffer = TerminalBufferKind.main,
  }) {
    if (!_recovering && _hasLiveOutput) {
      return;
    }
    _applySnapshotIfSafe(data, activeBuffer: activeBuffer);
  }

  void appendSnapshotChunk(
    String data, {
    TerminalBufferKind activeBuffer = TerminalBufferKind.main,
  }) {
    if (!_recovering && _hasLiveOutput) {
      return;
    }
    _pendingSnapshotActiveBuffer = activeBuffer;
    if (data.isNotEmpty) {
      _pendingSnapshotChunks.add(data);
    }
  }

  void prepareForRebind() {
    beginRecovery();
  }

  void appendLiveFrame(String data) {
    _observeLiveOutput(data);
    if (_recovering) {
      _pendingRecoveryFrames.add(data);
      return;
    }
    if (data.isNotEmpty) {
      _hasLiveOutput = true;
    }
    renderer.applyLiveOutput(data);
  }

  void _handleTerminalOutput(String data) {
    final sink = _transportSink;
    if (sink == null || data.isEmpty) {
      return;
    }

    final autoResponseKind = classifyTerminalAutoResponse(data);
    if (_snapshotReplayInProgress && autoResponseKind != null) {
      return;
    }

    if (data.contains('\x03')) {
      _armReplyGuard(_TerminalReplyGuardMode.interrupt);
      sink(data);
      return;
    }

    if (autoResponseKind != null &&
        _shouldSuppressAutoResponse(
          _replyGuardMode,
          autoResponseKind,
        )) {
      if (_replyGuardMode == _TerminalReplyGuardMode.interrupt) {
        _pendingTerminalReplies.add(data);
      }
      _scheduleReplyGuardTimer();
      return;
    }

    sink(data);
  }

  void _observeLiveOutput(String data) {
    if (_replyGuardMode == _TerminalReplyGuardMode.none || data.isEmpty) {
      return;
    }
    _dropPendingTerminalReplies();
  }

  void _armReplyGuard(_TerminalReplyGuardMode mode) {
    _replyGuardMode = mode;
    _pendingTerminalReplies.clear();
    _scheduleReplyGuardTimer();
  }

  Duration _replyGuardDuration(_TerminalReplyGuardMode mode) {
    return mode == _TerminalReplyGuardMode.recovery
        ? _postRecoveryReplyDrop
        : _postInterruptReplyHold;
  }

  void _scheduleReplyGuardTimer() {
    _postInterruptReplyTimer?.cancel();
    _postInterruptReplyTimer = Timer(
      _replyGuardDuration(_replyGuardMode),
      _settlePendingTerminalReplies,
    );
  }

  void _settlePendingTerminalReplies() {
    final sink = _transportSink;
    final mode = _replyGuardMode;
    final pendingReplies = mode == _TerminalReplyGuardMode.interrupt
        ? List<String>.from(_pendingTerminalReplies)
        : const <String>[];
    _clearReplyGuard();
    if (sink == null || mode == _TerminalReplyGuardMode.recovery) {
      return;
    }
    for (final reply in pendingReplies) {
      sink(reply);
    }
  }

  void _dropPendingTerminalReplies() {
    _clearReplyGuard();
  }

  void _clearReplyGuard() {
    _pendingTerminalReplies.clear();
    _replyGuardMode = _TerminalReplyGuardMode.none;
    _postInterruptReplyTimer?.cancel();
    _postInterruptReplyTimer = null;
  }

  void finishRecovery() {
    if (!_recovering) {
      return;
    }
    _recovering = false;
    _recoveryTimeoutTimer?.cancel();
    _recoveryTimeoutTimer = null;
    if (_pendingSnapshotChunks.isNotEmpty) {
      _applySnapshotIfSafe(
        _pendingSnapshotChunks.join(),
        activeBuffer: _pendingSnapshotActiveBuffer,
      );
      _pendingSnapshotChunks.clear();
    }
    for (final frame in _pendingRecoveryFrames) {
      renderer.applyLiveOutput(frame);
    }
    _pendingRecoveryFrames.clear();
    // F072: recovering -> live
    _setSessionState(TerminalSessionState.live);
  }

  void _applySnapshotIfSafe(
    String data, {
    required TerminalBufferKind activeBuffer,
  }) {
    if (_shouldPreserveLocalTerminal(data, activeBuffer: activeBuffer)) {
      if (kDebugMode) {
        debugPrint(
          '[TerminalSessionState] dropping unsafe recovery snapshot '
          'buffer=${activeBuffer.name} seq=${summarizeTerminalSequences(data)}',
        );
      }
      return;
    }
    _snapshotReplayInProgress = true;
    try {
      renderer.applySnapshot(data, activeBuffer: activeBuffer);
    } finally {
      _snapshotReplayInProgress = false;
    }
  }

  bool _shouldPreserveLocalTerminal(
    String data, {
    required TerminalBufferKind activeBuffer,
  }) {
    if (!_recovering) {
      return false;
    }
    if (activeBuffer != TerminalBufferKind.main) {
      return false;
    }
    if (!renderer.hasMeaningfulContent) {
      return false;
    }
    return alternateBufferTransitionPattern.hasMatch(data);
  }

  void dispose() {
    _recoveryTimeoutTimer?.cancel();
    _recoveryTimeoutTimer = null;
    _postInterruptReplyTimer?.cancel();
    _postInterruptReplyTimer = null;
    renderer.dispose();
    _stateNotifier.dispose();
  }
}

class _TerminalBinding {
  const _TerminalBinding({
    required this.service,
    required this.generation,
    required this.protocolSubscription,
    required this.statusListener,
  });

  final WebSocketService service;
  final int generation;
  final StreamSubscription<TerminalProtocolEvent> protocolSubscription;
  final void Function() statusListener;

  Future<void> cancel() async {
    await protocolSubscription.cancel();
    service.removeListener(statusListener);
  }
}

/// 构建 protocol event subscription 和 status listener，
/// 从 TerminalSessionManager.bindTerminalOutput 中提取以控制主文件行数。
_TerminalBinding _createTerminalBinding({
  required WebSocketService service,
  required int generation,
  required String key,
  required _TerminalState state,
  required Map<String, int> bindingGenerations,
}) {
  return _TerminalBinding(
    service: service,
    generation: generation,
    protocolSubscription: service.eventStream.listen((event) {
      if (bindingGenerations[key] != generation) return;
      switch (event.kind) {
        case TerminalProtocolEventKind.connected:
          // 防止排队中的 connected 事件覆盖永久失败状态
          if (service.isPermanentlyFailed ||
              service.status != ConnectionStatus.connected) {
            return;
          }
          final pty = event.ptySize;
          if (pty != null) {
            state.applyRemotePtySize(pty.rows, pty.cols);
          }
          state.beginRecovery();
          return;
        case TerminalProtocolEventKind.snapshot:
          if (service.status == ConnectionStatus.connected) {
            state.beginRecovery();
          }
          state.replaceWithSnapshot(
            event.payload ?? '',
            activeBuffer: event.activeBuffer ?? TerminalBufferKind.main,
          );
          return;
        case TerminalProtocolEventKind.snapshotChunk:
          if (service.status == ConnectionStatus.connected) {
            state.beginRecovery();
          }
          state.appendSnapshotChunk(
            event.payload ?? '',
            activeBuffer: event.activeBuffer ?? TerminalBufferKind.main,
          );
          return;
        case TerminalProtocolEventKind.snapshotComplete:
          state.finishRecovery();
          return;
        case TerminalProtocolEventKind.output:
          state.appendLiveFrame(event.payload ?? '');
          return;
        case TerminalProtocolEventKind.resize:
          final pty = event.ptySize;
          if (pty != null) {
            state.applyRemotePtySize(pty.rows, pty.cols);
          }
          return;
        case TerminalProtocolEventKind.presence:
        case TerminalProtocolEventKind.closed:
          return;
      }
    }),
    statusListener: () {
      if (bindingGenerations[key] != generation) return;
      final status = service.status;
      // 只在永久不可恢复时收敛到 error：
      // - auth_failed (4001/4011)：凭证失效，需重新登录
      // - terminal_closed：服务端主动关闭终端
      // 临时断线（autoReconnect 可恢复）不干预，由 connectedSubscription
      // 在 autoReconnect 成功后调用 beginRecovery() 自然恢复。
      if (status == ConnectionStatus.disconnected ||
          status == ConnectionStatus.error) {
        if (service.isPermanentlyFailed) {
          if (state.sessionState == TerminalSessionState.live ||
              state.sessionState == TerminalSessionState.recovering ||
              state.sessionState == TerminalSessionState.reconnecting ||
              state.sessionState == TerminalSessionState.connecting) {
            state._setSessionState(TerminalSessionState.error);
          }
        }
      }
    },
  );
}

/// 冲突终端去活逻辑，从 TerminalSessionManager.deactivateConflictingTerminalSessions
/// 提取以控制主文件行数。
Future<void> _deactivateConflictingSessions({
  required WebSocketService activeService,
  required Map<String, WebSocketService> sessions,
  required Map<String, _TerminalState> terminals,
  required Set<String> pausedKeys,
}) async {
  final activeTerminalId = activeService.terminalId;
  final activeDeviceId = activeService.deviceId;
  if ((activeTerminalId ?? '').isEmpty) {
    return;
  }

  final conflictingEntries = sessions.entries.where((entry) {
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
    pausedKeys.remove(entry.key);
    await entry.value.disconnect(notify: false);
    // 被主动断开的终端必须重置为 idle，
    // 否则切回时 connectTerminal 会因状态为 live 而拒绝重连
    final state = terminals[entry.key];
    if (state != null && state.sessionState != TerminalSessionState.idle) {
      state._setSessionState(TerminalSessionState.idle);
    }
  }
}
