import 'command_sequence_draft.dart';

class AssistantCommandSequence {
  const AssistantCommandSequence({
    required this.summary,
    required this.provider,
    required this.source,
    required this.needConfirm,
    required this.steps,
  });

  final String summary;
  final String provider;
  final String source;
  final bool needConfirm;
  final List<CommandSequenceStep> steps;

  Map<String, dynamic> toJson() => {
        'summary': summary,
        'provider': provider,
        'source': source,
        'need_confirm': needConfirm,
        'steps': [
          for (final step in steps)
            {
              'id': step.id,
              'label': step.label,
              'command': step.command,
            },
        ],
      };

  factory AssistantCommandSequence.fromJson(Map<String, dynamic> json) {
    final rawSteps = (json['steps'] as List<dynamic>? ?? const [])
        .whereType<Map<String, dynamic>>()
        .toList(growable: false);
    return AssistantCommandSequence(
      summary: (json['summary'] as String? ?? '').trim(),
      provider: (json['provider'] as String? ?? 'service_llm').trim(),
      source: (json['source'] as String? ?? 'intent').trim(),
      needConfirm: json['need_confirm'] as bool? ?? true,
      steps: [
        for (var index = 0; index < rawSteps.length; index++)
          CommandSequenceStep(
            id: (rawSteps[index]['id'] as String? ?? 'step_${index + 1}')
                .trim(),
            label: (rawSteps[index]['label'] as String? ?? '步骤 ${index + 1}')
                .trim(),
            command: (rawSteps[index]['command'] as String? ?? '').trim(),
          ),
      ],
    );
  }
}

class AssistantMessage {
  const AssistantMessage({
    required this.type,
    required this.text,
  });

  final String type;
  final String text;

  factory AssistantMessage.fromJson(Map<String, dynamic> json) {
    return AssistantMessage(
      type: (json['type'] as String? ?? 'assistant').trim(),
      text: (json['text'] as String? ?? '').trim(),
    );
  }
}

class AssistantMessageDelta {
  const AssistantMessageDelta({
    required this.type,
    required this.textDelta,
    this.replace = false,
  });

  final String type;
  final String textDelta;
  final bool replace;

  factory AssistantMessageDelta.fromJson(Map<String, dynamic> json) {
    return AssistantMessageDelta(
      type: (json['type'] as String? ?? 'assistant').trim(),
      textDelta:
          (json['text_delta'] as String? ?? json['text'] as String? ?? '')
              .trim(),
      replace: json['replace'] as bool? ?? false,
    );
  }
}

class AssistantTraceItem {
  const AssistantTraceItem({
    required this.stage,
    required this.title,
    required this.status,
    required this.summary,
  });

  final String stage;
  final String title;
  final String status;
  final String summary;

  factory AssistantTraceItem.fromJson(Map<String, dynamic> json) {
    return AssistantTraceItem(
      stage: (json['stage'] as String? ?? 'planner').trim(),
      title: (json['title'] as String? ?? '规划').trim(),
      status: (json['status'] as String? ?? 'completed').trim(),
      summary: (json['summary'] as String? ?? '').trim(),
    );
  }
}

class AssistantToolCall {
  const AssistantToolCall({
    required this.id,
    required this.toolName,
    required this.status,
    this.summary,
    this.inputSummary,
    this.outputSummary,
  });

  final String id;
  final String toolName;
  final String status;
  final String? summary;
  final String? inputSummary;
  final String? outputSummary;

  factory AssistantToolCall.fromJson(Map<String, dynamic> json) {
    return AssistantToolCall(
      id: (json['id'] as String? ?? '').trim(),
      toolName:
          (json['tool_name'] as String? ?? json['name'] as String? ?? '工具')
              .trim(),
      status: (json['status'] as String? ?? 'running').trim(),
      summary: (json['summary'] as String?)?.trim(),
      inputSummary: (json['input_summary'] as String?)?.trim(),
      outputSummary: (json['output_summary'] as String?)?.trim(),
    );
  }
}

class AssistantStatusUpdate {
  const AssistantStatusUpdate({
    required this.stage,
    required this.status,
    required this.title,
    this.summary,
  });

  final String stage;
  final String status;
  final String title;
  final String? summary;

  factory AssistantStatusUpdate.fromJson(Map<String, dynamic> json) {
    return AssistantStatusUpdate(
      stage: (json['stage'] as String? ?? 'planner').trim(),
      status: (json['status'] as String? ?? 'running').trim(),
      title: (json['title'] as String? ?? '处理中').trim(),
      summary: (json['summary'] as String?)?.trim(),
    );
  }
}

class AssistantPlanLimits {
  const AssistantPlanLimits({
    required this.rateLimited,
    required this.budgetBlocked,
    required this.providerTimeoutMs,
    this.retryAfter,
  });

  final bool rateLimited;
  final bool budgetBlocked;
  final int providerTimeoutMs;
  final int? retryAfter;

  factory AssistantPlanLimits.fromJson(Map<String, dynamic> json) {
    return AssistantPlanLimits(
      rateLimited: json['rate_limited'] as bool? ?? false,
      budgetBlocked: json['budget_blocked'] as bool? ?? false,
      providerTimeoutMs: json['provider_timeout_ms'] as int? ?? 12000,
      retryAfter: json['retry_after'] as int?,
    );
  }
}

class AssistantPlanResult {
  const AssistantPlanResult({
    required this.conversationId,
    required this.messageId,
    required this.assistantMessages,
    required this.trace,
    required this.commandSequence,
    required this.fallbackUsed,
    required this.fallbackReason,
    required this.limits,
    required this.evaluationContext,
  });

  final String conversationId;
  final String messageId;
  final List<AssistantMessage> assistantMessages;
  final List<AssistantTraceItem> trace;
  final AssistantCommandSequence commandSequence;
  final bool fallbackUsed;
  final String? fallbackReason;
  final AssistantPlanLimits limits;
  final Map<String, dynamic> evaluationContext;

  factory AssistantPlanResult.fromJson(Map<String, dynamic> json) {
    return AssistantPlanResult(
      conversationId: (json['conversation_id'] as String? ?? '').trim(),
      messageId: (json['message_id'] as String? ?? '').trim(),
      assistantMessages:
          ((json['assistant_messages'] as List<dynamic>?) ?? const [])
              .whereType<Map<String, dynamic>>()
              .map(AssistantMessage.fromJson)
              .toList(growable: false),
      trace: ((json['trace'] as List<dynamic>?) ?? const [])
          .whereType<Map<String, dynamic>>()
          .map(AssistantTraceItem.fromJson)
          .toList(growable: false),
      commandSequence: AssistantCommandSequence.fromJson(
        (json['command_sequence'] as Map<String, dynamic>?) ??
            const <String, dynamic>{},
      ),
      fallbackUsed: json['fallback_used'] as bool? ?? false,
      fallbackReason: (json['fallback_reason'] as String?)?.trim(),
      limits: AssistantPlanLimits.fromJson(
        (json['limits'] as Map<String, dynamic>?) ?? const <String, dynamic>{},
      ),
      evaluationContext:
          (json['evaluation_context'] as Map<String, dynamic>?) ??
              const <String, dynamic>{},
    );
  }
}

class AssistantPlanProgressEvent {
  const AssistantPlanProgressEvent({
    required this.type,
    this.assistantMessage,
    this.assistantDelta,
    this.traceItem,
    this.toolCall,
    this.statusUpdate,
    this.result,
    this.reason,
    this.message,
    this.retryAfter,
  });

  final String type;
  final AssistantMessage? assistantMessage;
  final AssistantMessageDelta? assistantDelta;
  final AssistantTraceItem? traceItem;
  final AssistantToolCall? toolCall;
  final AssistantStatusUpdate? statusUpdate;
  final AssistantPlanResult? result;
  final String? reason;
  final String? message;
  final int? retryAfter;

  AssistantTraceItem? get derivedTraceItem {
    if (traceItem != null) {
      return traceItem;
    }
    if (toolCall != null) {
      final tool = toolCall!;
      final summaryParts = <String>[
        if ((tool.summary ?? '').isNotEmpty) tool.summary!,
        if ((tool.inputSummary ?? '').isNotEmpty) '输入: ${tool.inputSummary!}',
        if ((tool.outputSummary ?? '').isNotEmpty) '输出: ${tool.outputSummary!}',
      ];
      return AssistantTraceItem(
        stage: 'tool',
        title: tool.toolName,
        status: tool.status,
        summary: summaryParts.isEmpty ? '工具调用进行中' : summaryParts.join('\n'),
      );
    }
    if (statusUpdate != null) {
      final status = statusUpdate!;
      return AssistantTraceItem(
        stage: status.stage,
        title: status.title,
        status: status.status,
        summary: (status.summary ?? '').trim(),
      );
    }
    return null;
  }

  factory AssistantPlanProgressEvent.fromJson(Map<String, dynamic> json) {
    return AssistantPlanProgressEvent(
      type: (json['type'] as String? ?? '').trim(),
      assistantMessage:
          (json['assistant_message'] as Map<String, dynamic>?) != null
              ? AssistantMessage.fromJson(
                  json['assistant_message'] as Map<String, dynamic>,
                )
              : null,
      assistantDelta: (json['assistant_delta'] as Map<String, dynamic>?) != null
          ? AssistantMessageDelta.fromJson(
              json['assistant_delta'] as Map<String, dynamic>,
            )
          : null,
      traceItem: (json['trace_item'] as Map<String, dynamic>?) != null
          ? AssistantTraceItem.fromJson(
              json['trace_item'] as Map<String, dynamic>,
            )
          : null,
      toolCall: (json['tool_call'] as Map<String, dynamic>?) != null
          ? AssistantToolCall.fromJson(
              json['tool_call'] as Map<String, dynamic>,
            )
          : null,
      statusUpdate: ((json['status_update'] as Map<String, dynamic>?) ??
                  (json['status'] is Map<String, dynamic>
                      ? json['status'] as Map<String, dynamic>
                      : null)) !=
              null
          ? AssistantStatusUpdate.fromJson(
              ((json['status_update'] as Map<String, dynamic>?) ??
                  json['status'] as Map<String, dynamic>),
            )
          : null,
      result: (json['plan'] as Map<String, dynamic>?) != null
          ? AssistantPlanResult.fromJson(
              json['plan'] as Map<String, dynamic>,
            )
          : null,
      reason: (json['reason'] as String?)?.trim(),
      message: (json['message'] as String?)?.trim(),
      retryAfter: json['retry_after'] as int?,
    );
  }
}
