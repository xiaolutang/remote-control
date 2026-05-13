import '../utils/json_helpers.dart';

/// 定时任务重复类型
enum ScheduledTaskRepeatType {
  once,
  daily;

  /// 将服务端字符串转换为枚举，非法值降级为 once
  static ScheduledTaskRepeatType fromString(String? value) {
    return switch (value) {
      'daily' => ScheduledTaskRepeatType.daily,
      'once' => ScheduledTaskRepeatType.once,
      _ => ScheduledTaskRepeatType.once,
    };
  }

  /// 转为服务端 API 需要的字符串
  String toApiString() => name;

  /// 中文显示标签
  String get displayLabel => switch (this) {
        ScheduledTaskRepeatType.once => '单次',
        ScheduledTaskRepeatType.daily => '每天',
      };
}

/// 定时任务状态
enum ScheduledTaskStatus { pending, executed, expired, cancelled }

/// 定时任务模型
class ScheduledTask {
  const ScheduledTask({
    required this.id,
    required this.sessionId,
    required this.terminalId,
    required this.textContent,
    required this.executeAt,
    required this.repeatType,
    required this.status,
    required this.createdAt,
    this.executedAt,
  });

  final int id;
  final String sessionId;
  final String terminalId;
  final String textContent;
  final String executeAt;
  final ScheduledTaskRepeatType repeatType;
  final ScheduledTaskStatus status;
  final String createdAt;
  final String? executedAt;

  factory ScheduledTask.fromJson(Map<String, dynamic> json) {
    return ScheduledTask(
      id: readIntFromJson(json['id']),
      sessionId: readStringFromJson(json['session_id']),
      terminalId: readStringFromJson(json['terminal_id']),
      textContent: readRawStringFromJson(json['text_content']),
      executeAt: readStringFromJson(json['execute_at']),
      repeatType: enumFromJson(
        ScheduledTaskRepeatType.values,
        json['repeat_type'],
        ScheduledTaskRepeatType.once,
      ),
      status: enumFromJson(
        ScheduledTaskStatus.values,
        json['status'],
        ScheduledTaskStatus.pending,
      ),
      createdAt: readStringFromJson(json['created_at']),
      executedAt: readOptionalStringFromJson(json['executed_at']),
    );
  }

  Map<String, dynamic> toJson() => {
        'id': id,
        'session_id': sessionId,
        'terminal_id': terminalId,
        'text_content': textContent,
        'execute_at': executeAt,
        'repeat_type': repeatType.name,
        'status': status.name,
        'created_at': createdAt,
        'executed_at': executedAt,
      };

  ScheduledTask copyWith({
    int? id,
    String? sessionId,
    String? terminalId,
    String? textContent,
    String? executeAt,
    ScheduledTaskRepeatType? repeatType,
    ScheduledTaskStatus? status,
    String? createdAt,
    String? executedAt,
  }) {
    return ScheduledTask(
      id: id ?? this.id,
      sessionId: sessionId ?? this.sessionId,
      terminalId: terminalId ?? this.terminalId,
      textContent: textContent ?? this.textContent,
      executeAt: executeAt ?? this.executeAt,
      repeatType: repeatType ?? this.repeatType,
      status: status ?? this.status,
      createdAt: createdAt ?? this.createdAt,
      executedAt: executedAt ?? this.executedAt,
    );
  }
}
