part of 'smart_terminal_create_dialog.dart';

class _ConversationTurn {
  const _ConversationTurn({
    required this.userText,
    required this.items,
    this.fallbackReason,
  });

  final String userText;
  final List<_ConversationStreamItem> items;
  final String? fallbackReason;
}

enum _ConversationStreamItemKind {
  assistantMessage,
  traceItem,
  executionEvent,
}

class _ConversationStreamItem {
  const _ConversationStreamItem._({
    required this.kind,
    this.assistantMessage,
    this.traceItem,
    this.executionEvent,
  });

  const _ConversationStreamItem.assistantMessage(
    AssistantMessage message,
  ) : this._(
          kind: _ConversationStreamItemKind.assistantMessage,
          assistantMessage: message,
        );

  const _ConversationStreamItem.traceItem(
    AssistantTraceItem trace,
  ) : this._(
          kind: _ConversationStreamItemKind.traceItem,
          traceItem: trace,
        );

  const _ConversationStreamItem.executionEvent(
    SmartTerminalExecutionEvent event,
  ) : this._(
          kind: _ConversationStreamItemKind.executionEvent,
          executionEvent: event,
        );

  final _ConversationStreamItemKind kind;
  final AssistantMessage? assistantMessage;
  final AssistantTraceItem? traceItem;
  final SmartTerminalExecutionEvent? executionEvent;
}
