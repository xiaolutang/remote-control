import '../utils/json_helpers.dart';

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
    final rawViews =
        json['views'] is Map<String, dynamic> ? json['views'] as Map<String, dynamic> : const <String, dynamic>{};
    final status = readStringFromJson(json['status']);
    return RuntimeTerminal(
      terminalId: readStringFromJson(json['terminal_id']),
      title: readStringFromJson(json['title']),
      cwd: readStringFromJson(json['cwd']),
      command: readStringFromJson(json['command']),
      status: status.isEmpty ? 'pending' : status,
      updatedAt: json['updated_at'] is String
          ? DateTime.tryParse(json['updated_at'] as String)
          : null,
      disconnectReason: json['disconnect_reason'] is String
          ? json['disconnect_reason'] as String
          : null,
      views: rawViews.map(
        (key, value) => MapEntry(key, safeIntFromMapValue(value)),
      ),
    );
  }
}
