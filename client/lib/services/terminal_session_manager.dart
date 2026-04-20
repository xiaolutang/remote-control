import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/widgets.dart';
import 'package:xterm/xterm.dart';

import 'websocket_service.dart';

/// Recovery 超时时间：如果 snapshot_complete 未在此时间内到达，
/// 自动 finishRecovery 以防止终端永久卡在 recovering 状态。
const Duration _recoveryTimeout = Duration(seconds: 5);
const Duration _postInterruptReplyHold = Duration(milliseconds: 350);
const Duration _postRecoveryReplyDrop = Duration(seconds: 2);

class _AgentExitPattern {
  const _AgentExitPattern({
    required this.exitMarkers,
    required this.uiMarkers,
    this.resumeHeader,
    this.resumeCommandPrefix,
  });

  final List<String> exitMarkers;
  final List<String> uiMarkers;
  final String? resumeHeader;
  final String? resumeCommandPrefix;
}

const List<_AgentExitPattern> _agentExitPatterns = [
  _AgentExitPattern(
    exitMarkers: [
      'Resume this session with:',
      'claude --resume ',
    ],
    uiMarkers: [
      'Claude Code v',
      'AI Usage Billing',
    ],
    resumeHeader: 'Resume this session with:',
    resumeCommandPrefix: 'claude --resume ',
  ),
  _AgentExitPattern(
    exitMarkers: [
      'To continue this session, run codex resume ',
      'codex resume ',
    ],
    uiMarkers: [
      'OpenAI Codex',
    ],
  ),
];

final List<String> _agentExitMarkers = _agentExitPatterns
    .expand((pattern) => pattern.exitMarkers)
    .toList(growable: false);
final List<String> _agentUiMarkers = _agentExitPatterns
    .expand((pattern) => [...pattern.exitMarkers, ...pattern.uiMarkers])
    .toList(growable: false);
final List<String> _agentExitNormalizationHints = <String>[
  ..._agentExitMarkers,
  ..._agentExitPatterns.expand((pattern) => pattern.uiMarkers),
];

bool _looksLikeShellPrompt(String line) {
  final trimmed = line.trimRight();
  if (trimmed.isEmpty) {
    return false;
  }
  return trimmed.endsWith('%') ||
      trimmed.endsWith(r'$') ||
      trimmed.endsWith('#');
}

bool _looksLikeShellPromptPrefix(String line) {
  final trimmed = line.trimRight();
  if (trimmed.isEmpty) {
    return false;
  }
  final promptPrefix = RegExp(r'(^|[^A-Za-z0-9_./-])[A-Za-z0-9_./:-]+[#$%] ');
  return promptPrefix.hasMatch(trimmed);
}

bool _containsLikelyShellPrompt(String data) {
  if (data.isEmpty) {
    return false;
  }
  return data
      .split('\n')
      .map((line) => line.replaceAll('\r', ''))
      .any(_looksLikeShellPrompt);
}

bool _containsAgentExitMarker(String data) {
  return _agentExitMarkers.any(data.contains);
}

bool _looksLikeAgentUiLine(String line) {
  final trimmed = line.trimRight();
  if (trimmed.isEmpty) {
    return false;
  }
  return _agentUiMarkers.any(trimmed.contains);
}

bool _mightNeedAgentExitNormalization(String data) {
  if (data.isEmpty) {
    return false;
  }
  return _containsLikelyShellPrompt(data) ||
      _agentExitNormalizationHints.any(data.contains);
}

bool _isTerminalAutoResponse(String data) {
  if (data.isEmpty || !data.startsWith('\x1b')) {
    return false;
  }
  if (data == '\x1b[?1;2c' ||
      data == '\x1b[0n' ||
      data.startsWith('\x1b[>') ||
      data.startsWith('\x1bP!|')) {
    return true;
  }
  final cursorReport = RegExp(r'^\x1b\[\d+;\d+R$');
  return cursorReport.hasMatch(data);
}

enum _TerminalReplyGuardMode {
  none,
  interrupt,
  recovery,
}

class _AgentExitNormalizationPlan {
  const _AgentExitNormalizationPlan({
    required this.lineIndices,
    required this.cursorSourceIndex,
  });

  final List<int> lineIndices;
  final int cursorSourceIndex;
}

List<int> _nonEmptyLineRange(
  List<String> lines,
  int start,
  int end,
) {
  if (start >= end) {
    return const <int>[];
  }
  return List<int>.generate(
    end - start,
    (offset) => start + offset,
  ).where((index) => lines[index].isNotEmpty).toList(growable: false);
}

int? _findLastShellPromptBefore(List<String> lines, int beforeIndex) {
  for (var i = beforeIndex - 1; i >= 0; i--) {
    if (_looksLikeShellPrompt(lines[i]) ||
        _looksLikeShellPromptPrefix(lines[i])) {
      return i;
    }
  }
  return null;
}

int _resolveExitStart(List<String> lines, int markerIndex) {
  for (final pattern in _agentExitPatterns) {
    final header = pattern.resumeHeader;
    final prefix = pattern.resumeCommandPrefix;
    if (header == null || prefix == null) {
      continue;
    }
    if (lines[markerIndex].contains(prefix) &&
        markerIndex > 0 &&
        lines[markerIndex - 1].contains(header)) {
      return markerIndex - 1;
    }
  }
  return markerIndex;
}

_AgentExitNormalizationPlan? _buildPromptFirstAgentLayout(List<String> lines) {
  final firstNonEmpty = lines.indexWhere((line) => line.trim().isNotEmpty);
  if (firstNonEmpty < 0) {
    return null;
  }
  final topLine = lines[firstNonEmpty];
  if (!_looksLikeShellPrompt(topLine)) {
    return null;
  }

  final agentStart = lines.indexWhere(
    (line) => _looksLikeAgentUiLine(line),
    firstNonEmpty + 1,
  );
  if (agentStart < 0) {
    return null;
  }

  final shellHistoryIndices = _nonEmptyLineRange(
    lines,
    firstNonEmpty + 1,
    agentStart,
  );
  if (shellHistoryIndices.isEmpty) {
    return null;
  }

  final lastHistoryLine = lines[shellHistoryIndices.last];
  if (!_looksLikeShellPrompt(lastHistoryLine) &&
      !_looksLikeShellPromptPrefix(lastHistoryLine)) {
    return null;
  }

  return _AgentExitNormalizationPlan(
    lineIndices: <int>[
      ...shellHistoryIndices,
      firstNonEmpty,
    ],
    cursorSourceIndex: firstNonEmpty,
  );
}

_AgentExitNormalizationPlan? _buildNormalizedAgentExitPlanFromBuffer(
  List<BufferLine> lines,
) {
  final textLines =
      lines.map((line) => line.toString().trimRight()).toList(growable: false);

  for (var i = 0; i < lines.length; i++) {
    final line = textLines[i];
    if (_agentExitMarkers.any(line.contains)) {
      final exitStart = _resolveExitStart(textLines, i);
      final promptBefore = _findLastShellPromptBefore(textLines, exitStart);
      final historyIndices = promptBefore == null
          ? const <int>[]
          : _nonEmptyLineRange(textLines, 0, promptBefore + 1);

      for (var promptIndex = exitStart;
          promptIndex < lines.length;
          promptIndex++) {
        if (_looksLikeShellPrompt(textLines[promptIndex])) {
          final exitLineIndices = _nonEmptyLineRange(
            textLines,
            exitStart,
            promptIndex + 1,
          );
          return _AgentExitNormalizationPlan(
            lineIndices: <int>[
              ...historyIndices,
              ...exitLineIndices,
            ],
            cursorSourceIndex: promptIndex,
          );
        }
      }

      if (promptBefore != null && historyIndices.isNotEmpty) {
        return _AgentExitNormalizationPlan(
          lineIndices: historyIndices,
          cursorSourceIndex: promptBefore,
        );
      }
      return null;
    }
  }
  return _buildPromptFirstAgentLayout(textLines);
}

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
  final ValueNotifier<String> _outputText = ValueNotifier<String>('');
  bool _disposed = false;
  bool _normalizingAgentExit = false;

  static const int _maxBufferLines = 50;

  /// 底层 Terminal 实例的只读引用。
  /// 仅用于 TerminalView widget 构造（xterm 包硬约束）。
  /// 不要通过此引用直接操作 Terminal，应使用 RendererAdapter 的方法。
  Terminal get terminalForView => _terminal;

  /// 输出文本的只读监听接口（不暴露可变 ValueNotifier）。
  ValueListenable<String> get outputText => _outputText;

  bool get isDisposed => _disposed;

  /// 应用 snapshot（清空现有 buffer 后写入）
  void applySnapshot(
    String data, {
    TerminalBufferKind activeBuffer = TerminalBufferKind.main,
  }) {
    if (_disposed) return;
    _terminal.mainBuffer.clear();
    _terminal.altBuffer.clear();
    switch (activeBuffer) {
      case TerminalBufferKind.main:
        _terminal.useMainBuffer();
        break;
      case TerminalBufferKind.alt:
        _terminal.useAltBuffer();
        break;
    }
    _outputBuffer.clear();
    _write(data);
  }

  /// 应用 live output（直接追加写入）
  void applyLiveOutput(String data) {
    if (_disposed) return;
    _write(data);
  }

  /// 调整 renderer 尺寸（静默 onResize 回调）
  void resize(int cols, int rows) {
    if (_disposed) return;
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
    if (_disposed) return;
    _terminal.useMainBuffer();
    _terminal.mainBuffer.clear();
    _terminal.altBuffer.clear();
    _outputBuffer.clear();
    _outputText.value = '';
  }

  void _write(String data) {
    _terminal.write(data);
    _appendOutputBuffer(data);
    if (_mightNeedAgentExitNormalization(data)) {
      _maybeNormalizeAgentExitScreen();
    }
  }

  void _appendOutputBuffer(String data) {
    if (data.isEmpty || _disposed) return;
    final lines = data.split('\n');
    for (final line in lines) {
      if (line.isEmpty) continue;
      _outputBuffer.add(line);
      if (_outputBuffer.length > _maxBufferLines) {
        _outputBuffer.removeAt(0);
      }
    }
    _outputText.value = _outputBuffer.join('\n');
  }

  void _maybeNormalizeAgentExitScreen() {
    if (_disposed || _normalizingAgentExit || _terminal.isUsingAltBuffer) {
      return;
    }

    final currentLines = _terminal.buffer.lines.toList();
    final plan = _buildNormalizedAgentExitPlanFromBuffer(currentLines);
    if (plan == null || plan.lineIndices.isEmpty) {
      return;
    }

    _normalizingAgentExit = true;
    try {
      _applyNormalizationPlan(currentLines, plan);
      final normalizedLines = _terminal.buffer.lines
          .toList()
          .map((line) => line.toString().trimRight())
          .where((line) => line.isNotEmpty)
          .toList(growable: false);
      _outputBuffer
        ..clear()
        ..addAll(normalizedLines.take(_maxBufferLines));
      _outputText.value = _outputBuffer.join('\n');
      _terminal.notifyListeners();
    } finally {
      _normalizingAgentExit = false;
    }
  }

  void _applyNormalizationPlan(
    List<BufferLine> currentLines,
    _AgentExitNormalizationPlan plan,
  ) {
    final replacement = <BufferLine>[];
    for (final index in plan.lineIndices) {
      replacement.add(_cloneBufferLine(currentLines[index]));
    }
    while (replacement.length < _terminal.viewHeight) {
      replacement.add(BufferLine(_terminal.viewWidth));
    }
    _terminal.buffer.lines.replaceWith(replacement);

    final finalCursorAbsolute =
        plan.lineIndices.indexOf(plan.cursorSourceIndex);
    final scrollBack = _terminal.buffer.lines.length - _terminal.viewHeight;
    final cursorY = (finalCursorAbsolute - scrollBack).clamp(
      0,
      _terminal.viewHeight - 1,
    );
    final cursorLine = replacement[finalCursorAbsolute];
    final cursorX = cursorLine.toString().trimRight().length.clamp(
          0,
          _terminal.viewWidth - 1,
        );
    _terminal.setCursor(cursorX, cursorY);
  }

  BufferLine _cloneBufferLine(BufferLine source) {
    final clone = BufferLine(
      source.length,
      isWrapped: source.isWrapped,
    );
    clone.data.setAll(0, source.data);
    return clone;
  }

  void dispose() {
    _disposed = true;
    _outputText.dispose();
  }
}

class _TerminalState {
  _TerminalState(Terminal terminal) : renderer = RendererAdapter(terminal);

  final RendererAdapter renderer;
  final List<String> _pendingRecoveryFrames = [];
  final List<String> _pendingTerminalReplies = [];
  bool _hasLiveOutput = false;
  bool _recovering = false;
  _TerminalReplyGuardMode _replyGuardMode = _TerminalReplyGuardMode.none;
  Timer? _recoveryTimeoutTimer;
  Timer? _postInterruptReplyTimer;
  void Function(String data)? _transportSink;

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
    _recovering = true;
    _hasLiveOutput = false;
    _pendingRecoveryFrames.clear();
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
    renderer.applySnapshot(data, activeBuffer: activeBuffer);
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

    if (data.contains('\x03')) {
      _armReplyGuard(_TerminalReplyGuardMode.interrupt);
      sink(data);
      return;
    }

    if (_replyGuardMode != _TerminalReplyGuardMode.none &&
        _isTerminalAutoResponse(data)) {
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
    if (_containsAgentExitMarker(data) || _containsLikelyShellPrompt(data)) {
      _dropPendingTerminalReplies();
    }
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
    for (final frame in _pendingRecoveryFrames) {
      renderer.applyLiveOutput(frame);
    }
    _pendingRecoveryFrames.clear();
    // F072: recovering -> live
    _setSessionState(TerminalSessionState.live);
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
    required this.connectedSubscription,
    required this.outputSubscription,
    required this.ptySubscription,
    required this.statusListener,
  });

  final WebSocketService service;
  final int generation;
  final StreamSubscription<void> connectedSubscription;
  final StreamSubscription<TerminalOutputFrame> outputSubscription;
  final StreamSubscription<TerminalPtySize> ptySubscription;
  final void Function() statusListener;

  Future<void> cancel() async {
    await connectedSubscription.cancel();
    await outputSubscription.cancel();
    await ptySubscription.cancel();
    service.removeListener(statusListener);
  }
}

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
    _terminalBindings[key] = _TerminalBinding(
      service: service,
      generation: generation,
      connectedSubscription: service.terminalConnectedStream.listen((_) {
        if (_bindingGenerations[key] != generation) return;
        // 防止排队中的 connected 事件覆盖永久失败状态
        if (service.isPermanentlyFailed) {
          return;
        }
        if (service.status != ConnectionStatus.connected) return;
        state.beginRecovery();
      }),
      outputSubscription: service.outputFrameStream.listen((frame) {
        if (_bindingGenerations[key] != generation) return;
        if (frame.isSnapshot) {
          state.replaceWithSnapshot(
            frame.payload,
            activeBuffer: frame.activeBuffer ?? TerminalBufferKind.main,
          );
          return;
        }
        if (frame.kind == TerminalOutputKind.snapshotComplete) {
          state.finishRecovery();
          return;
        }
        state.appendLiveFrame(frame.payload);
      }),
      ptySubscription: service.ptySizeStream.listen((pty) {
        if (_bindingGenerations[key] != generation) return;
        state.applyRemotePtySize(pty.rows, pty.cols);
      }),
      statusListener: () {
        if (_bindingGenerations[key] != generation) return;
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
    service.addListener(_terminalBindings[key]!.statusListener);
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
      // 被主动断开的终端必须重置为 idle，
      // 否则切回时 connectTerminal 会因状态为 live 而拒绝重连
      final state = _terminals[entry.key];
      if (state != null && state.sessionState != TerminalSessionState.idle) {
        state._setSessionState(TerminalSessionState.idle);
      }
    }
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
