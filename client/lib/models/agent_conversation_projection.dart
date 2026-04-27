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
    return AgentConversationProjection(
      deviceId: (json['device_id'] as String? ?? '').trim(),
      terminalId: (json['terminal_id'] as String? ?? '').trim(),
      status: (json['status'] as String? ?? 'empty').trim(),
      nextEventIndex: json['next_event_index'] as int? ?? 0,
      conversationId: (json['conversation_id'] as String?)?.trim(),
      activeSessionId: (json['active_session_id'] as String?)?.trim(),
      truncationEpoch: json['truncation_epoch'] as int? ?? 0,
      events: (json['events'] as List<dynamic>? ?? const [])
          .whereType<Map<String, dynamic>>()
          .map(AgentConversationEventItem.fromJson)
          .toList(growable: false),
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
      eventIndex: json['event_index'] as int? ?? 0,
      eventId: (json['event_id'] as String? ?? '').trim(),
      type: (json['type'] as String? ?? '').trim(),
      role: (json['role'] as String? ?? '').trim(),
      payload: Map<String, dynamic>.from(
        json['payload'] as Map<String, dynamic>? ?? const {},
      ),
      sessionId: (json['session_id'] as String?)?.trim(),
      questionId: (json['question_id'] as String?)?.trim(),
      clientEventId: (json['client_event_id'] as String?)?.trim(),
      createdAt: (json['created_at'] as String?)?.trim(),
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
      phase: (json['phase'] as String? ?? '').trim(),
      description: (json['description'] as String?)?.trim(),
      streamingText: (json['streaming_text'] as String? ?? '').trim(),
      toolSteps: (json['tool_steps'] as List<dynamic>? ?? const [])
          .whereType<Map<String, dynamic>>()
          .map(TurnToolStep.fromJson)
          .toList(growable: false),
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
    return TurnToolStep(
      toolName: (json['tool_name'] as String? ?? '').trim(),
      description: (json['description'] as String? ?? '').trim(),
      status: (json['status'] as String? ?? 'running').trim(),
      resultSummary: (json['result_summary'] as String?)?.trim(),
    );
  }

  Map<String, dynamic> toJson() => {
        'tool_name': toolName,
        'description': description,
        'status': status,
        if (resultSummary != null) 'result_summary': resultSummary,
      };
}
