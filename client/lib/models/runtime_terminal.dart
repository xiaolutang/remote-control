class RuntimeTerminal {
  const RuntimeTerminal({
    required this.terminalId,
    required this.title,
    required this.cwd,
    required this.command,
    required this.status,
    required this.views,
    this.updatedAt,
    this.disconnectReason,
  });

  final String terminalId;
  final String title;
  final String cwd;
  final String command;
  final String status;
  final Map<String, int> views;
  final DateTime? updatedAt;
  final String? disconnectReason;

  bool get isClosed => status == 'closed';
  bool get canAttach => !isClosed;
  bool get canClose => !isClosed;

  RuntimeTerminal copyWith({
    String? terminalId,
    String? title,
    String? cwd,
    String? command,
    String? status,
    Map<String, int>? views,
    DateTime? updatedAt,
    String? disconnectReason,
  }) {
    return RuntimeTerminal(
      terminalId: terminalId ?? this.terminalId,
      title: title ?? this.title,
      cwd: cwd ?? this.cwd,
      command: command ?? this.command,
      status: status ?? this.status,
      views: views ?? this.views,
      updatedAt: updatedAt ?? this.updatedAt,
      disconnectReason: disconnectReason ?? this.disconnectReason,
    );
  }

  factory RuntimeTerminal.fromJson(Map<String, dynamic> json) {
    final rawViews = json['views'] as Map<String, dynamic>? ?? const {};
    return RuntimeTerminal(
      terminalId: json['terminal_id'] as String? ?? '',
      title: json['title'] as String? ?? '',
      cwd: json['cwd'] as String? ?? '',
      command: json['command'] as String? ?? '',
      status: json['status'] as String? ?? 'pending',
      updatedAt: json['updated_at'] == null
          ? null
          : DateTime.tryParse(json['updated_at'] as String),
      disconnectReason: json['disconnect_reason'] as String?,
      views: rawViews.map((key, value) => MapEntry(key, value as int)),
    );
  }
}
