/// 会话级 usage 累加器，在内存中累积每次 SSE result/error 事件携带的 usage 数据。
///
/// Session 切换时自动归零。纯客户端内存状态，不持久化。
class SessionUsageAccumulator {
  int _inputTokens = 0;
  int _outputTokens = 0;
  int _totalTokens = 0;
  int _requests = 0;
  String _currentSessionId = '';

  /// 当前 session ID
  String get currentSessionId => _currentSessionId;

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
  /// [sessionId] 当前会话 ID，若与上次不同则自动 reset。
  /// [usage] SSE 事件携带的 usage 字段，可能为 null 或部分字段缺失。
  void accumulate(String sessionId, Map<String, dynamic>? usage) {
    if (sessionId != _currentSessionId) {
      reset();
      _currentSessionId = sessionId;
    }
    if (usage == null) return;

    final input = _readInt(usage['input_tokens']);
    final output = _readInt(usage['output_tokens']);
    final total = _readInt(usage['total_tokens']);
    final req = _readInt(usage['requests']);

    _inputTokens += input;
    _outputTokens += output;
    _totalTokens += total;
    _requests += req;
  }

  /// 归零所有累计字段（不含 sessionId）。
  void reset() {
    _inputTokens = 0;
    _outputTokens = 0;
    _totalTokens = 0;
    _requests = 0;
  }

  /// 返回快照 Map，结构兼容展示层。
  Map<String, dynamic> toSummary() => {
        'session_id': _currentSessionId,
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
