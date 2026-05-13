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
