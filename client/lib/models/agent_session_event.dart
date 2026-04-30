import 'dart:collection';

/// Agent SSE 会话事件基类
sealed class AgentSessionEvent {
  const AgentSessionEvent();

  /// 序列化为 JSON
  Map<String, dynamic> toJson();
}

/// Agent 阶段变更事件（THINKING / ACTING / RESPONDING 等）
class PhaseChangeEvent extends AgentSessionEvent {
  const PhaseChangeEvent({
    required this.phase,
    this.description,
  });

  /// 阶段名称，如 THINKING, ACTING, RESPONDING
  final String phase;

  /// 阶段描述，如"正在分析你的意图..."
  final String? description;

  factory PhaseChangeEvent.fromJson(Map<String, dynamic> json) {
    return PhaseChangeEvent(
      phase: (json['phase'] as String? ?? '').trim(),
      description: (json['description'] as String?)?.trim(),
    );
  }

  @override
  Map<String, dynamic> toJson() => {
        'phase': phase,
        if (description != null) 'description': description,
      };
}

/// Agent 流式文本事件（逐步推送文本增量）
class StreamingTextEvent extends AgentSessionEvent {
  const StreamingTextEvent({required this.textDelta});

  /// 文本增量
  final String textDelta;

  factory StreamingTextEvent.fromJson(Map<String, dynamic> json) {
    return StreamingTextEvent(
      textDelta: (json['text_delta'] as String? ?? '').trim(),
    );
  }

  @override
  Map<String, dynamic> toJson() => {'text_delta': textDelta};
}

/// Agent 工具步骤事件
class ToolStepEvent extends AgentSessionEvent {
  const ToolStepEvent({
    required this.toolName,
    required this.description,
    required this.status,
    this.resultSummary,
  });

  /// 工具名称
  final String toolName;

  /// 步骤描述
  final String description;

  /// 状态：running / done / error
  final String status;

  /// 结果摘要（done 状态时有值）
  final String? resultSummary;

  factory ToolStepEvent.fromJson(Map<String, dynamic> json) {
    return ToolStepEvent(
      toolName: (json['tool_name'] as String? ?? '').trim(),
      description: (json['description'] as String? ?? '').trim(),
      status: (json['status'] as String? ?? 'running').trim(),
      resultSummary: (json['result_summary'] as String?)?.trim(),
    );
  }

  @override
  Map<String, dynamic> toJson() => {
        'tool_name': toolName,
        'description': description,
        'status': status,
        if (resultSummary != null) 'result_summary': resultSummary,
      };
}

/// Agent 会话创建事件
class AgentSessionCreatedEvent extends AgentSessionEvent {
  const AgentSessionCreatedEvent({
    required this.sessionId,
    this.conversationId,
    this.terminalId,
  });

  final String sessionId;
  final String? conversationId;
  final String? terminalId;

  factory AgentSessionCreatedEvent.fromJson(Map<String, dynamic> json) {
    return AgentSessionCreatedEvent(
      sessionId: (json['session_id'] as String? ?? '').trim(),
      conversationId: (json['conversation_id'] as String?)?.trim(),
      terminalId: (json['terminal_id'] as String?)?.trim(),
    );
  }

  @override
  Map<String, dynamic> toJson() => {
        'session_id': sessionId,
        if (conversationId != null) 'conversation_id': conversationId,
        if (terminalId != null) 'terminal_id': terminalId,
      };
}

/// Agent 工具调用追踪事件
@Deprecated('已由 ToolStepEvent 取代，仅保留用于 UI 过渡兼容，F108 移除')
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

  @override
  Map<String, dynamic> toJson() => {
        'tool': tool,
        'input_summary': inputSummary,
        'output_summary': outputSummary,
      };
}

/// Agent 向用户提问事件
class AgentQuestionEvent extends AgentSessionEvent {
  const AgentQuestionEvent({
    required this.question,
    required this.options,
    required this.multiSelect,
    this.questionId,
  });

  final String question;
  final List<String> options;
  final bool multiSelect;
  final String? questionId;

  factory AgentQuestionEvent.fromJson(Map<String, dynamic> json) {
    return AgentQuestionEvent(
      questionId: (json['question_id'] as String?)?.trim(),
      question: (json['question'] as String? ?? '').trim(),
      options: (json['options'] as List<dynamic>? ?? const [])
          .whereType<String>()
          .toList(growable: false),
      multiSelect: json['multi_select'] as bool? ?? false,
    );
  }

  @override
  Map<String, dynamic> toJson() => {
        if (questionId != null) 'question_id': questionId,
        'question': question,
        'options': options,
        'multi_select': multiSelect,
      };
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

/// Agent Token 使用统计
class AgentUsageData {
  const AgentUsageData({
    required this.inputTokens,
    required this.outputTokens,
    required this.totalTokens,
    required this.requests,
    required this.modelName,
  });

  final int inputTokens;
  final int outputTokens;
  final int totalTokens;
  final int requests;
  final String modelName;

  factory AgentUsageData.fromJson(Map<String, dynamic> json) {
    return AgentUsageData(
      inputTokens: json['input_tokens'] as int? ?? 0,
      outputTokens: json['output_tokens'] as int? ?? 0,
      totalTokens: json['total_tokens'] as int? ?? 0,
      requests: json['requests'] as int? ?? 0,
      modelName: (json['model_name'] as String? ?? '').trim(),
    );
  }

  /// 简要统计标签，如 "deepseek-chat · 1900 tokens"
  String get shortLabel =>
      '${modelName.isNotEmpty ? '$modelName · ' : ''}$totalTokens tokens';
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
    this.usage,
    this.responseType = 'command',
    this.aiPrompt = '',
    this.eventId,
  });

  final String summary;
  final List<AgentResultStep> steps;
  final String provider;
  final String source;
  final bool needConfirm;
  final Map<String, String> aliases;
  final AgentUsageData? usage;

  /// 响应类型：'message' | 'command' | 'ai_prompt'，缺失或未知时默认 'command'
  final String responseType;

  /// ai_prompt 类型的 prompt 文本，用于注入终端 stdin
  final String aiPrompt;

  /// 服务端 conversation event 的真实 event_id（SSE payload 注入）
  final String? eventId;

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
        Map<String, dynamic>.from(json['aliases'] as Map? ?? const {})
            .map((k, v) => MapEntry(k, v.toString())),
      ),
      usage: json['usage'] != null
          ? AgentUsageData.fromJson(json['usage'] as Map<String, dynamic>)
          : null,
      responseType: (json['response_type'] as String? ?? 'command').trim(),
      aiPrompt: (json['ai_prompt'] as String? ?? '').trim(),
      eventId: (json['event_id'] as String?)?.trim(),
    );
  }

  @override
  Map<String, dynamic> toJson() => {
        'summary': summary,
        'steps': steps.map((s) => {'id': s.id, 'label': s.label, 'command': s.command}).toList(),
        'provider': provider,
        'source': source,
        'need_confirm': needConfirm,
        'aliases': Map<String, String>.from(aliases),
        if (usage != null)
          'usage': {
            'input_tokens': usage!.inputTokens,
            'output_tokens': usage!.outputTokens,
            'total_tokens': usage!.totalTokens,
            'requests': usage!.requests,
            'model_name': usage!.modelName,
          },
        'response_type': responseType,
        'ai_prompt': aiPrompt,
        if (eventId != null) 'event_id': eventId,
      };
}

/// Agent 助手中间消息事件（对话过程气泡，非最终结果）
///
/// 服务端在 Agent 处理过程中推送的用户可见助手回复。
/// 与 [AgentResultEvent]（responseType=message）区分：
/// assistant_message 是中间过程消息，message result 是结构化结果卡片。
@Deprecated('已由 StreamingTextEvent 取代，仅保留用于 UI 过渡兼容，F108 移除')
class AgentAssistantMessageEvent extends AgentSessionEvent {
  const AgentAssistantMessageEvent({required this.content});

  /// 助手消息文本内容
  final String content;

  factory AgentAssistantMessageEvent.fromJson(Map<String, dynamic> json) {
    return AgentAssistantMessageEvent(
      content: (json['content'] as String? ?? '').trim(),
    );
  }

  @override
  Map<String, dynamic> toJson() => {'content': content};
}

/// Agent 错误事件
class AgentErrorEvent extends AgentSessionEvent {
  const AgentErrorEvent({
    required this.code,
    required this.message,
    this.usage,
  });

  final String code;
  final String message;
  final AgentUsageData? usage;

  factory AgentErrorEvent.fromJson(Map<String, dynamic> json) {
    return AgentErrorEvent(
      code: (json['code'] as String? ?? 'UNKNOWN').trim(),
      message: (json['message'] as String? ?? '').trim(),
      usage: json['usage'] != null
          ? AgentUsageData.fromJson(json['usage'] as Map<String, dynamic>)
          : null,
    );
  }

  @override
  Map<String, dynamic> toJson() => {
        'code': code,
        'message': message,
        if (usage != null)
          'usage': {
            'input_tokens': usage!.inputTokens,
            'output_tokens': usage!.outputTokens,
            'total_tokens': usage!.totalTokens,
            'requests': usage!.requests,
            'model_name': usage!.modelName,
          },
      };
}

