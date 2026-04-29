/// 会话级 usage 累加器，在内存中累积每次 SSE result/error 事件携带的 usage 数据。
///
/// 同一终端对话中多次 agent run（每次 run 有不同 session_id）的 usage 会持续累加。
/// 仅在终端切换/面板关闭时由外部调用 reset() 归零。纯客户端内存状态，不持久化。
class SessionUsageAccumulator {
  int _inputTokens = 0;
  int _outputTokens = 0;
  int _totalTokens = 0;
  int _requests = 0;

  /// 累计 input tokens
  int get inputTokens => _inputTokens;

  /// 累计 output tokens
  int get outputTokens => _outputTokens;

  /// 累计 total tokens
  int get totalTokens => _totalTokens;

  /// 累计请求数
  int get requests => _requests;

  /// 累加一次 usage 数据。
  ///
  /// [usage] SSE 事件携带的 usage 字段，可能为 null 或部分字段缺失。
  void accumulate(Map<String, dynamic>? usage) {
    if (usage == null) return;

    _inputTokens += _readInt(usage['input_tokens']);
    _outputTokens += _readInt(usage['output_tokens']);
    _totalTokens += _readInt(usage['total_tokens']);
    _requests += _readInt(usage['requests']);
  }

  /// 归零所有累计字段。由外部在终端切换/面板关闭时调用。
  void reset() {
    _inputTokens = 0;
    _outputTokens = 0;
    _totalTokens = 0;
    _requests = 0;
  }

  /// 返回快照 Map，结构兼容展示层。
  Map<String, dynamic> toSummary() => {
        'input_tokens': _inputTokens,
        'output_tokens': _outputTokens,
        'total_tokens': _totalTokens,
        'requests': _requests,
      };
}

int _readInt(Object? value) {
  if (value is int) return value;
  if (value is num) return value.toInt();
  if (value is String) return int.tryParse(value) ?? 0;
  return 0;
}
