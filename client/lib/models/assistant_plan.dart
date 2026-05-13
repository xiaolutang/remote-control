import '../utils/json_helpers.dart'
    show readBoolFromJson, readIntFromJson, readListFromJson, readMapFromJson,
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
    final rawSteps = readListFromJson(
      json['steps'],
      (m) => m,
    );
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
      providerTimeoutMs: json['provider_timeout_ms'] != null
          ? readIntFromJson(json['provider_timeout_ms'])
          : 12000,
      retryAfter: json['retry_after'] != null
          ? readIntFromJson(json['retry_after'])
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
        readMapFromJson(json['command_sequence']),
      ),
      fallbackUsed: readBoolFromJson(json['fallback_used']),
      fallbackReason: readOptionalStringFromJson(json['fallback_reason']),
      limits: AssistantPlanLimits.fromJson(
        readMapFromJson(json['limits']),
      ),
      evaluationContext: readMapFromJson(json['evaluation_context']),
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
    final assistantMessageMap = readMapFromJson(json['assistant_message']);
    final assistantDeltaMap = readMapFromJson(json['assistant_delta']);
    final traceItemMap = readMapFromJson(json['trace_item']);
    final toolCallMap = readMapFromJson(json['tool_call']);
    final statusUpdateMap = readMapFromJson(json['status_update']);
    final statusMap = readMapFromJson(json['status']);
    final planMap = readMapFromJson(json['plan']);
    return AssistantPlanProgressEvent(
      type: readStringFromJson(json['type']),
      assistantMessage: assistantMessageMap.isNotEmpty
          ? AssistantMessage.fromJson(assistantMessageMap)
          : null,
      assistantDelta: assistantDeltaMap.isNotEmpty
          ? AssistantMessageDelta.fromJson(assistantDeltaMap)
          : null,
      traceItem: traceItemMap.isNotEmpty
          ? AssistantTraceItem.fromJson(traceItemMap)
          : null,
      toolCall: toolCallMap.isNotEmpty
          ? AssistantToolCall.fromJson(toolCallMap)
          : null,
      statusUpdate: statusUpdateMap.isNotEmpty
          ? AssistantStatusUpdate.fromJson(statusUpdateMap)
          : statusMap.isNotEmpty
              ? AssistantStatusUpdate.fromJson(statusMap)
              : null,
      result: planMap.isNotEmpty
          ? AssistantPlanResult.fromJson(planMap)
          : null,
      reason: readOptionalStringFromJson(json['reason']),
      message: readOptionalStringFromJson(json['message']),
      retryAfter: json['retry_after'] != null
          ? readIntFromJson(json['retry_after'])
          : null,
    );
  }
}
