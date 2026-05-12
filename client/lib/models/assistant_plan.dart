import '../utils/json_helpers.dart'
    show readBoolFromJson, readIntFromJson, readListFromJson,
        readOptionalStringFromJson, readRawStringFromJson, readStringFromJson;
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
    final provider = readStringFromJson(json['provider']);
    final source = readStringFromJson(json['source']);
    return AssistantCommandSequence(
      summary: readStringFromJson(json['summary']),
      provider: provider.isEmpty ? 'service_llm' : provider,
      source: source.isEmpty ? 'intent' : source,
      needConfirm: readBoolFromJson(json['need_confirm'], defaultValue: true),
      steps: [
        for (var index = 0; index < rawSteps.length; index++)
          CommandSequenceStep(
            id: readStringFromJson(rawSteps[index]['id']).isEmpty
                ? 'step_${index + 1}'
                : readStringFromJson(rawSteps[index]['id']),
            label: readStringFromJson(rawSteps[index]['label']).isEmpty
                ? '步骤 ${index + 1}'
                : readStringFromJson(rawSteps[index]['label']),
            command: readStringFromJson(rawSteps[index]['command']),
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
    final type = readStringFromJson(json['type']);
    return AssistantMessage(
      type: type.isEmpty ? 'assistant' : type,
      text: readStringFromJson(json['text']),
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
    final type = readStringFromJson(json['type']);
    return AssistantMessageDelta(
      type: type.isEmpty ? 'assistant' : type,
      textDelta: readRawStringFromJson(
        json['text_delta'] ?? json['text'],
      ),
      replace: readBoolFromJson(json['replace']),
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
    final stage = readStringFromJson(json['stage']);
    final title = readStringFromJson(json['title']);
    final status = readStringFromJson(json['status']);
    return AssistantTraceItem(
      stage: stage.isEmpty ? 'planner' : stage,
      title: title.isEmpty ? '规划' : title,
      status: status.isEmpty ? 'completed' : status,
      summary: readStringFromJson(json['summary']),
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
    final toolName =
        readStringFromJson(json['tool_name'] ?? json['name']);
    final status = readStringFromJson(json['status']);
    return AssistantToolCall(
      id: readStringFromJson(json['id']),
      toolName: toolName.isEmpty ? '工具' : toolName,
      status: status.isEmpty ? 'running' : status,
      summary: readOptionalStringFromJson(json['summary']),
      inputSummary: readOptionalStringFromJson(json['input_summary']),
      outputSummary: readOptionalStringFromJson(json['output_summary']),
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
    final stage = readStringFromJson(json['stage']);
    final status = readStringFromJson(json['status']);
    final title = readStringFromJson(json['title']);
    return AssistantStatusUpdate(
      stage: stage.isEmpty ? 'planner' : stage,
      status: status.isEmpty ? 'running' : status,
      title: title.isEmpty ? '处理中' : title,
      summary: readOptionalStringFromJson(json['summary']),
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
      rateLimited: readBoolFromJson(json['rate_limited']),
      budgetBlocked: readBoolFromJson(json['budget_blocked']),
      providerTimeoutMs: readIntFromJson(json['provider_timeout_ms']) == 0
          ? 12000
          : readIntFromJson(json['provider_timeout_ms']),
      retryAfter: json['retry_after'] is num
          ? (json['retry_after'] as num).toInt()
          : null,
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
      conversationId: readStringFromJson(json['conversation_id']),
      messageId: readStringFromJson(json['message_id']),
      assistantMessages: readListFromJson(
          json['assistant_messages'], AssistantMessage.fromJson),
      trace: readListFromJson(json['trace'], AssistantTraceItem.fromJson),
      commandSequence: AssistantCommandSequence.fromJson(
        json['command_sequence'] is Map<String, dynamic>
            ? json['command_sequence'] as Map<String, dynamic>
            : const <String, dynamic>{},
      ),
      fallbackUsed: readBoolFromJson(json['fallback_used']),
      fallbackReason: readOptionalStringFromJson(json['fallback_reason']),
      limits: AssistantPlanLimits.fromJson(
        json['limits'] is Map<String, dynamic>
            ? json['limits'] as Map<String, dynamic>
            : const <String, dynamic>{},
      ),
      evaluationContext:
          json['evaluation_context'] is Map<String, dynamic>
              ? json['evaluation_context'] as Map<String, dynamic>
              : const <String, dynamic>{},
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
      type: readStringFromJson(json['type']),
      assistantMessage:
          json['assistant_message'] is Map<String, dynamic>
              ? AssistantMessage.fromJson(
                  json['assistant_message'] as Map<String, dynamic>,
                )
              : null,
      assistantDelta: json['assistant_delta'] is Map<String, dynamic>
          ? AssistantMessageDelta.fromJson(
              json['assistant_delta'] as Map<String, dynamic>,
            )
          : null,
      traceItem: json['trace_item'] is Map<String, dynamic>
          ? AssistantTraceItem.fromJson(
              json['trace_item'] as Map<String, dynamic>,
            )
          : null,
      toolCall: json['tool_call'] is Map<String, dynamic>
          ? AssistantToolCall.fromJson(
              json['tool_call'] as Map<String, dynamic>,
            )
          : null,
      statusUpdate: json['status_update'] is Map<String, dynamic>
          ? AssistantStatusUpdate.fromJson(
              json['status_update'] as Map<String, dynamic>,
            )
          : json['status'] is Map<String, dynamic>
              ? AssistantStatusUpdate.fromJson(
                  json['status'] as Map<String, dynamic>,
                )
              : null,
      result: json['plan'] is Map<String, dynamic>
          ? AssistantPlanResult.fromJson(
              json['plan'] as Map<String, dynamic>,
            )
          : null,
      reason: readOptionalStringFromJson(json['reason']),
      message: readOptionalStringFromJson(json['message']),
      retryAfter: json['retry_after'] is num
          ? (json['retry_after'] as num).toInt()
          : null,
    );
  }
}
