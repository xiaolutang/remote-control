/// 连接状态
enum ConnectionStatus {
  disconnected,
  connecting,
  connected,
  reconnecting,
  error,
}

/// 视图类型 (CONTRACT-003)
enum ViewType {
  mobile,
  desktop,
}

enum TerminalOutputKind {
  data,
  snapshot,
  snapshotChunk,
  snapshotComplete,
}

enum TerminalBufferKind {
  main,
  alt,
}

enum TerminalProtocolEventKind {
  connected,
  presence,
  snapshot,
  snapshotChunk,
  snapshotComplete,
  output,
  resize,
  closed,
}

class TerminalProtocolEvent {
  const TerminalProtocolEvent({
    required this.kind,
    this.payload,
    this.attachEpoch,
    this.recoveryEpoch,
    this.activeBuffer,
    this.ptySize,
    this.views,
    this.geometryOwnerView,
    this.terminalStatus,
  });

  final TerminalProtocolEventKind kind;
  final String? payload;
  final int? attachEpoch;
  final int? recoveryEpoch;
  final TerminalBufferKind? activeBuffer;
  final TerminalPtySize? ptySize;
  final Map<String, int>? views;
  final String? geometryOwnerView;
  final String? terminalStatus;
}

class TerminalOutputFrame {
  const TerminalOutputFrame({
    required this.kind,
    required this.payload,
    this.attachEpoch,
    this.recoveryEpoch,
    this.activeBuffer,
  });

  final TerminalOutputKind kind;
  final String payload;
  final int? attachEpoch;
  final int? recoveryEpoch;
  final TerminalBufferKind? activeBuffer;

  bool get isSnapshot =>
      kind == TerminalOutputKind.snapshot ||
      kind == TerminalOutputKind.snapshotChunk;

  bool get isSnapshotChunk => kind == TerminalOutputKind.snapshotChunk;
}

class TerminalPtySize {
  const TerminalPtySize({
    required this.rows,
    required this.cols,
  });

  final int rows;
  final int cols;
}
