import 'dart:collection';

import '../utils/json_helpers.dart'
    show readBoolFromJson, readIntFromJson, readListFromJson,
        readOptionalStringFromJson, readStringFromJson;

// --- Enums ---

/// Agent 结果响应类型
enum AgentResponseType {
  /// 纯文本消息
  message,

  /// 命令序列
  command,

  /// AI Prompt 注入
  aiPrompt;

  /// 从 JSON 字符串解析，未知值回退到 command
  static AgentResponseType fromJsonString(String? value) {
    if (value == null) return AgentResponseType.command;
    switch (value.trim()) {
      case 'message':
        return AgentResponseType.message;
      case 'ai_prompt':
        return AgentResponseType.aiPrompt;
      default:
        return AgentResponseType.command;
    }
  }

  /// 转回 JSON 字符串
  String toJsonString() => switch (this) {
        AgentResponseType.message => 'message',
        AgentResponseType.aiPrompt => 'ai_prompt',
        AgentResponseType.command => 'command',
      };
}

/// 反馈类型
enum FeedbackType {
  /// 有帮助
  helpful,

  /// 需改进
  needsImprovement,

  /// 错误报告
  errorReport;

  /// 从 JSON 字符串解析，未知值回退到 helpful
  static FeedbackType fromJsonString(String? value) {
    if (value == null) return FeedbackType.helpful;
    switch (value.trim()) {
      case 'helpful':
        return FeedbackType.helpful;
      case 'needs_improvement':
        return FeedbackType.needsImprovement;
      case 'error_report':
        return FeedbackType.errorReport;
      default:
        return FeedbackType.helpful;
    }
  }

  /// 转回 JSON 字符串
  String toJsonString() => switch (this) {
        FeedbackType.helpful => 'helpful',
        FeedbackType.needsImprovement => 'needs_improvement',
        FeedbackType.errorReport => 'error_report',
      };
}

/// 工具步骤状态
enum ToolStepStatus {
  /// 执行中
  running,

  /// 完成
  done,

  /// 错误
  error;

  /// 从 JSON 字符串解析，未知值回退到 running
  static ToolStepStatus fromJsonString(String? value) {
    if (value == null) return ToolStepStatus.running;
    switch (value.trim()) {
      case 'running':
        return ToolStepStatus.running;
      case 'done':
        return ToolStepStatus.done;
      case 'error':
        return ToolStepStatus.error;
      default:
        return ToolStepStatus.running;
    }
  }

  /// 转回 JSON 字符串
  String toJsonString() => switch (this) {
        ToolStepStatus.running => 'running',
        ToolStepStatus.done => 'done',
        ToolStepStatus.error => 'error',
      };
}

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
      phase: readStringFromJson(json['phase']),
      description: readOptionalStringFromJson(json['description']),
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
      textDelta: readStringFromJson(json['text_delta']),
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

  /// 状态
  final ToolStepStatus status;

  /// 结果摘要（done 状态时有值）
  final String? resultSummary;

  factory ToolStepEvent.fromJson(Map<String, dynamic> json) {
    return ToolStepEvent(
      toolName: readStringFromJson(json['tool_name']),
      description: readStringFromJson(json['description']),
      status: ToolStepStatus.fromJsonString(
          json['status'] is String ? json['status'] as String : null),
      resultSummary: readOptionalStringFromJson(json['result_summary']),
    );
  }

  @override
  Map<String, dynamic> toJson() => {
        'tool_name': toolName,
        'description': description,
        'status': status.toJsonString(),
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
      sessionId: readStringFromJson(json['session_id']),
      conversationId: readOptionalStringFromJson(json['conversation_id']),
      terminalId: readOptionalStringFromJson(json['terminal_id']),
    );
  }

  @override
  Map<String, dynamic> toJson() => {
        'session_id': sessionId,
        if (conversationId != null) 'conversation_id': conversationId,
        if (terminalId != null) 'terminal_id': terminalId,
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
      questionId: readOptionalStringFromJson(json['question_id']),
      question: readStringFromJson(json['question']),
      options: (json['options'] as List<dynamic>? ?? const [])
          .whereType<String>()
          .toList(growable: false),
      multiSelect: readBoolFromJson(json['multi_select']),
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
      id: readStringFromJson(json['id']),
      label: readStringFromJson(json['label']),
      command: readStringFromJson(json['command']),
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
      inputTokens: readIntFromJson(json['input_tokens']),
      outputTokens: readIntFromJson(json['output_tokens']),
      totalTokens: readIntFromJson(json['total_tokens']),
      requests: readIntFromJson(json['requests']),
      modelName: readStringFromJson(json['model_name']),
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
    this.responseType = AgentResponseType.command,
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

  /// 响应类型，缺失或未知时默认 command
  final AgentResponseType responseType;

  /// ai_prompt 类型的 prompt 文本，用于注入终端 stdin
  final String aiPrompt;

  /// 服务端 conversation event 的真实 event_id（SSE payload 注入）
  final String? eventId;

  factory AgentResultEvent.fromJson(Map<String, dynamic> json) {
    return AgentResultEvent(
      summary: readStringFromJson(json['summary']),
      steps: readListFromJson(json['steps'], AgentResultStep.fromJson),
      provider: readStringFromJson(json['provider']).isEmpty
          ? 'agent'
          : readStringFromJson(json['provider']),
      source: readStringFromJson(json['source']).isEmpty
          ? 'recommended'
          : readStringFromJson(json['source']),
      needConfirm: readBoolFromJson(json['need_confirm'], defaultValue: true),
      aliases: UnmodifiableMapView(
        json['aliases'] is Map
            ? (json['aliases'] as Map)
                .map((k, v) => MapEntry(k.toString(), v.toString()))
            : const {},
      ),
      usage: json['usage'] != null
          ? AgentUsageData.fromJson(json['usage'] as Map<String, dynamic>)
          : null,
      responseType: AgentResponseType.fromJsonString(
          json['response_type'] is String ? json['response_type'] as String : null),
      aiPrompt: readStringFromJson(json['ai_prompt']),
      eventId: readOptionalStringFromJson(json['event_id']),
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
        'response_type': responseType.toJsonString(),
        'ai_prompt': aiPrompt,
        if (eventId != null) 'event_id': eventId,
      };
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
      code: readStringFromJson(json['code']).isEmpty
          ? 'UNKNOWN'
          : readStringFromJson(json['code']),
      message: readStringFromJson(json['message']),
      usage: json['usage'] is Map<String, dynamic>
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

