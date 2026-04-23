import 'dart:collection';

/// Agent SSE 会话事件基类
sealed class AgentSessionEvent {
  const AgentSessionEvent();
}

/// Agent 工具调用追踪事件
class AgentTraceEvent extends AgentSessionEvent {
  const AgentTraceEvent({
    required this.tool,
    required this.inputSummary,
    required this.outputSummary,
  });

  final String tool;
  final String inputSummary;
  final String outputSummary;

  factory AgentTraceEvent.fromJson(Map<String, dynamic> json) {
    return AgentTraceEvent(
      tool: (json['tool'] as String? ?? '').trim(),
      inputSummary: (json['input_summary'] as String? ?? '').trim(),
      outputSummary: (json['output_summary'] as String? ?? '').trim(),
    );
  }
}

/// Agent 向用户提问事件
class AgentQuestionEvent extends AgentSessionEvent {
  const AgentQuestionEvent({
    required this.question,
    required this.options,
    required this.multiSelect,
  });

  final String question;
  final List<String> options;
  final bool multiSelect;

  factory AgentQuestionEvent.fromJson(Map<String, dynamic> json) {
    return AgentQuestionEvent(
      question: (json['question'] as String? ?? '').trim(),
      options: (json['options'] as List<dynamic>? ?? const [])
          .whereType<String>()
          .toList(growable: false),
      multiSelect: json['multi_select'] as bool? ?? false,
    );
  }
}

/// Agent 结果事件中的步骤
class AgentResultStep {
  const AgentResultStep({
    required this.id,
    required this.label,
    required this.command,
  });

  final String id;
  final String label;
  final String command;

  factory AgentResultStep.fromJson(Map<String, dynamic> json) {
    return AgentResultStep(
      id: (json['id'] as String? ?? '').trim(),
      label: (json['label'] as String? ?? '').trim(),
      command: (json['command'] as String? ?? '').trim(),
    );
  }
}

/// Agent 最终结果事件
class AgentResultEvent extends AgentSessionEvent {
  AgentResultEvent({
    required this.summary,
    required this.steps,
    required this.provider,
    required this.source,
    required this.needConfirm,
    required this.aliases,
  });

  final String summary;
  final List<AgentResultStep> steps;
  final String provider;
  final String source;
  final bool needConfirm;
  final Map<String, String> aliases;

  factory AgentResultEvent.fromJson(Map<String, dynamic> json) {
    return AgentResultEvent(
      summary: (json['summary'] as String? ?? '').trim(),
      steps: (json['steps'] as List<dynamic>? ?? const [])
          .whereType<Map<String, dynamic>>()
          .map(AgentResultStep.fromJson)
          .toList(growable: false),
      provider: (json['provider'] as String? ?? 'agent').trim(),
      source: (json['source'] as String? ?? 'recommended').trim(),
      needConfirm: json['need_confirm'] as bool? ?? true,
      aliases: UnmodifiableMapView(
        (json['aliases'] as Map<String, dynamic>? ?? const {})
            .map((k, v) => MapEntry(k, v.toString())),
      ),
    );
  }
}

/// Agent 错误事件
class AgentErrorEvent extends AgentSessionEvent {
  const AgentErrorEvent({
    required this.code,
    required this.message,
  });

  final String code;
  final String message;

  factory AgentErrorEvent.fromJson(Map<String, dynamic> json) {
    return AgentErrorEvent(
      code: (json['code'] as String? ?? 'UNKNOWN').trim(),
      message: (json['message'] as String? ?? '').trim(),
    );
  }
}

/// Agent 不可用时降级事件（客户端本地生成，非服务端 SSE）
class AgentFallbackEvent extends AgentSessionEvent {
  const AgentFallbackEvent({
    required this.reason,
    required this.code,
  });

  /// 降级原因（如 "设备不在线"）
  final String reason;

  /// 服务端返回的错误码（如 "AGENT_OFFLINE"）
  final String code;
}
