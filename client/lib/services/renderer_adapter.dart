part of 'terminal_session_manager.dart';

/// xterm Terminal 的稳定包装层（F073）
/// Coordinator 和 UI 只依赖此接口，不直接操作 xterm Terminal。
class RendererAdapter {
  RendererAdapter(this._terminal);

  final Terminal _terminal;
  final List<String> _outputBuffer = [];
  final ValueNotifier<String> _outputText = ValueNotifier<String>('');
  bool _disposed = false;

  static const int _maxBufferLines = 50;

  /// 底层 Terminal 实例的只读引用。
  /// 仅用于 TerminalView widget 构造（xterm 包硬约束）。
  /// 不要通过此引用直接操作 Terminal，应使用 RendererAdapter 的方法。
  Terminal get terminalForView => _terminal;

  /// 输出文本的只读监听接口（不暴露可变 ValueNotifier）。
  ValueListenable<String> get outputText => _outputText;

  bool get isDisposed => _disposed;

  bool get hasMeaningfulContent =>
      _bufferHasMeaningfulContent(_terminal.mainBuffer) ||
      _bufferHasMeaningfulContent(_terminal.altBuffer);

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
    final shouldLogTransition = _enableTerminalTransitionLogs &&
        terminalTransitionPattern.hasMatch(data);
    if (shouldLogTransition) {
      _logTerminalTransition('before_write', data);
    }
    _terminal.write(data);
    if (shouldLogTransition) {
      _logTerminalTransition('after_write', data);
    }
    _appendOutputBuffer(data);
  }

  void _logTerminalTransition(String stage, String data) {
    if (!kDebugMode) return;

    final buffer = _terminal.buffer;
    debugPrint(
      '[TerminalTransition] $stage '
      'buffer=${_terminal.isUsingAltBuffer ? "alt" : "main"} '
      'cursor=(${buffer.cursorX},${buffer.cursorY}) '
      'absoluteY=${buffer.absoluteCursorY} '
      'scrollBack=${buffer.scrollBack} '
      'height=${buffer.height} '
      'view=${_terminal.viewWidth}x${_terminal.viewHeight} '
      'margins=${buffer.marginTop}-${buffer.marginBottom} '
      'origin=${_terminal.originMode} '
      'seq=${summarizeTerminalSequences(data)}',
    );
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

  void dispose() {
    _disposed = true;
    _outputText.dispose();
  }

  bool _bufferHasMeaningfulContent(Buffer buffer) {
    for (var i = 0; i < buffer.lines.length; i++) {
      if (buffer.lines[i].toString().trim().isNotEmpty) {
        return true;
      }
    }
    return false;
  }
}
