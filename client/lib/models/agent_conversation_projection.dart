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
