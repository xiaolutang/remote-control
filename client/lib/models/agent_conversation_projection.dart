import '../utils/json_helpers.dart'
    show readBoolFromJson, readIntFromJson, readListFromJson,
        readOptionalStringFromJson, readStringFromJson;

class AgentConversationProjection {
  const AgentConversationProjection({
    required this.deviceId,
    required this.terminalId,
    required this.status,
    required this.nextEventIndex,
    required this.events,
    this.conversationId,
    this.activeSessionId,
    this.truncationEpoch = 0,
  });

  final String deviceId;
  final String terminalId;
  final String status;
  final int nextEventIndex;
  final String? conversationId;
  final String? activeSessionId;
  final List<AgentConversationEventItem> events;
  final int truncationEpoch;

  factory AgentConversationProjection.fromJson(Map<String, dynamic> json) {
    final status = readStringFromJson(json['status']);
    return AgentConversationProjection(
      deviceId: readStringFromJson(json['device_id']),
      terminalId: readStringFromJson(json['terminal_id']),
      status: status.isEmpty ? 'empty' : status,
      nextEventIndex: readIntFromJson(json['next_event_index']),
      conversationId: readOptionalStringFromJson(json['conversation_id']),
      activeSessionId: readOptionalStringFromJson(json['active_session_id']),
      truncationEpoch: readIntFromJson(json['truncation_epoch']),
      events: readListFromJson(
          json['events'], AgentConversationEventItem.fromJson),
    );
  }

  const AgentConversationProjection.empty({
    required this.deviceId,
    required this.terminalId,
  })  : status = 'empty',
        nextEventIndex = 0,
        conversationId = null,
        activeSessionId = null,
        truncationEpoch = 0,
        events = const [];
}

class AgentConversationEventItem {
  const AgentConversationEventItem({
    required this.eventIndex,
    required this.eventId,
    required this.type,
    required this.role,
    required this.payload,
    this.sessionId,
    this.questionId,
    this.clientEventId,
    this.createdAt,
  });

  final int eventIndex;
  final String eventId;
  final String type;
  final String role;
  final Map<String, dynamic> payload;
  final String? sessionId;
  final String? questionId;
  final String? clientEventId;
  final String? createdAt;

  factory AgentConversationEventItem.fromJson(Map<String, dynamic> json) {
    return AgentConversationEventItem(
      eventIndex: readIntFromJson(json['event_index']),
      eventId: readStringFromJson(json['event_id']),
      type: readStringFromJson(json['type']),
      role: readStringFromJson(json['role']),
      payload: json['payload'] is Map<String, dynamic>
          ? Map<String, dynamic>.from(json['payload'] as Map<String, dynamic>)
          : const <String, dynamic>{},
      sessionId: readOptionalStringFromJson(json['session_id']),
      questionId: readOptionalStringFromJson(json['question_id']),
      clientEventId: readOptionalStringFromJson(json['client_event_id']),
      createdAt: readOptionalStringFromJson(json['created_at']),
    );
  }
}

/// 单轮对话的阶段摘要信息
///
/// 从 phase_change / streaming_text / tool_step 事件中提取，
/// 存储在 _AgentHistoryEntry 中用于历史恢复和展示。
class TurnPhaseSummary {
  const TurnPhaseSummary({
    required this.phase,
    this.description,
    this.streamingText = '',
    this.toolSteps = const [],
  });

  /// 最后一个阶段名称（如 THINKING, ACTING, RESPONDING）
  final String phase;

  /// 阶段描述
  final String? description;

  /// 累积的流式文本
  final String streamingText;

  /// 工具步骤列表
  final List<TurnToolStep> toolSteps;

  factory TurnPhaseSummary.fromJson(Map<String, dynamic> json) {
    return TurnPhaseSummary(
      phase: readStringFromJson(json['phase']),
      description: readOptionalStringFromJson(json['description']),
      streamingText: readStringFromJson(json['streaming_text']),
      toolSteps: readListFromJson(json['tool_steps'], TurnToolStep.fromJson),
    );
  }

  Map<String, dynamic> toJson() => {
        'phase': phase,
        if (description != null) 'description': description,
        'streaming_text': streamingText,
        'tool_steps': toolSteps.map((s) => s.toJson()).toList(),
      };

  /// 创建一份副本，更新部分字段
  TurnPhaseSummary copyWith({
    String? phase,
    String? description,
    String? streamingText,
    List<TurnToolStep>? toolSteps,
  }) {
    return TurnPhaseSummary(
      phase: phase ?? this.phase,
      description: description ?? this.description,
      streamingText: streamingText ?? this.streamingText,
      toolSteps: toolSteps ?? this.toolSteps,
    );
  }
}

/// 单个工具步骤的快照
class TurnToolStep {
  const TurnToolStep({
    required this.toolName,
    required this.description,
    required this.status,
    this.resultSummary,
  });

  final String toolName;
  final String description;
  final String status;
  final String? resultSummary;

  factory TurnToolStep.fromJson(Map<String, dynamic> json) {
    final status = readStringFromJson(json['status']);
    return TurnToolStep(
      toolName: readStringFromJson(json['tool_name']),
      description: readStringFromJson(json['description']),
      status: status.isEmpty ? 'running' : status,
      resultSummary: readOptionalStringFromJson(json['result_summary']),
    );
  }

  Map<String, dynamic> toJson() => {
        'tool_name': toolName,
        'description': description,
        'status': status,
        if (resultSummary != null) 'result_summary': resultSummary,
      };
}
