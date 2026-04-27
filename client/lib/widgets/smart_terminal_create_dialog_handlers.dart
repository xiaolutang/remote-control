part of 'smart_terminal_create_dialog.dart';

mixin _SmartTerminalCreateDialogHandlers<T>
    on State<_SmartTerminalCreateDialog<T>>, ScrollToLatestMixin {
  TextEditingController get _intentController;
  FocusNode get _intentFocusNode;
  ScrollController get _conversationScrollController;

  CommandSequenceDraft get _draft;
  set _draft(CommandSequenceDraft value);

  set _resolvingIntent(bool value);

  set _manualConfirmationAccepted(bool value);

  set _executing(bool value);

  set _fallbackReason(String? value);

  set _pendingIntent(String? value);

  List<_ConversationStreamItem> get _pendingConversationItems;
  List<_ConversationTurn> get _turns;
  List<_ConversationStreamItem> get _executionEvents;

  void _scheduleScrollToLatest() {
    scheduleScrollToLatest(
      _conversationScrollController,
      duration: const Duration(milliseconds: 220),
    );
  }

  CommandSequenceDraft _buildCurrentDraft() {
    return _draft;
  }

  Future<void> _handleResolveIntent() async {
    final rawIntent = _intentController.text.trim();
    if (rawIntent.isEmpty) {
      return;
    }
    _beginPlanning(rawIntent);
    _intentFocusNode.requestFocus();
    _scheduleScrollToLatest();
    final resolved = await widget.controller.resolveLaunchIntent(
      rawIntent,
      onProgress: _applyPlanningProgress,
    );
    if (!mounted) {
      return;
    }
    final nextDraft = resolved.sequence ??
        CommandSequenceDraft.fromLaunchPlan(
          resolved.plan,
          provider: resolved.provider,
        );
    _completePlanning(
      rawIntent: rawIntent,
      resolved: resolved,
      nextDraft: nextDraft,
    );
    _scheduleScrollToLatest();
  }

  void _beginPlanning(String rawIntent) {
    setState(() {
      _intentController.clear();
      _resolvingIntent = true;
      _pendingIntent = rawIntent;
      _pendingConversationItems.clear();
    });
  }

  void _completePlanning({
    required String rawIntent,
    required PlannerResolutionResult resolved,
    required CommandSequenceDraft nextDraft,
  }) {
    setState(() {
      _resolvingIntent = false;
      _pendingIntent = null;
      _pendingConversationItems.clear();
      _draft = nextDraft.copyWith(intent: rawIntent);
      _fallbackReason = resolved.fallbackReason;
      _manualConfirmationAccepted = !_draft.requiresManualConfirmation;
      _turns.add(
        _ConversationTurn(
          userText: rawIntent,
          items: _mergeResolvedConversationItems(resolved),
          fallbackReason: resolved.fallbackReason,
        ),
      );
    });
  }

  void _applyPlanningProgress(AssistantPlanProgressEvent event) {
    if (!mounted) {
      return;
    }
    var changed = false;
    setState(() {
      changed = _applyAssistantDelta(event.assistantDelta) || changed;
      changed = _appendAssistantMessage(event.assistantMessage) || changed;
      changed = _upsertTraceItem(event.derivedTraceItem) || changed;
    });
    if (!changed) {
      return;
    }
    _scheduleScrollToLatest();
  }

  Future<void> _handleCreate() async {
    setState(() {
      _executing = true;
      _executionEvents.clear();
    });
    _scheduleScrollToLatest();
    final result = await widget.onCreate(_buildCurrentDraft(), _reportEvent);
    if (!mounted) {
      return;
    }
    setState(() {
      _executing = false;
    });
    _scheduleScrollToLatest();
    if (result == null) {
      return;
    }
    Navigator.of(context).pop(result);
  }

  Future<void> _reportEvent(SmartTerminalExecutionEvent event) async {
    if (!mounted) {
      return;
    }
    setState(() {
      _executionEvents.add(_ConversationStreamItem.executionEvent(event));
    });
    _scheduleScrollToLatest();
  }

  bool _applyAssistantDelta(AssistantMessageDelta? delta) {
    if (delta == null) {
      return false;
    }
    final index = _pendingConversationItems.lastIndexWhere(
      (item) => item.kind == _ConversationStreamItemKind.assistantMessage,
    );
    final nextMessage = AssistantMessage(
      type: delta.type,
      text: index >= 0 && !delta.replace
          ? '${_pendingConversationItems[index].assistantMessage?.text ?? ''}${delta.textDelta}'
          : delta.textDelta,
    );
    if (index >= 0) {
      _pendingConversationItems[index] =
          _ConversationStreamItem.assistantMessage(nextMessage);
      return true;
    }
    if (delta.textDelta.isEmpty) {
      return false;
    }
    _pendingConversationItems.add(
      _ConversationStreamItem.assistantMessage(nextMessage),
    );
    return true;
  }

  bool _appendAssistantMessage(AssistantMessage? message) {
    if (message == null || _hasAssistantMessage(message)) {
      return false;
    }
    _pendingConversationItems.add(
      _ConversationStreamItem.assistantMessage(message),
    );
    return true;
  }

  bool _hasAssistantMessage(AssistantMessage message) {
    return _pendingConversationItems.any(
      (item) =>
          item.kind == _ConversationStreamItemKind.assistantMessage &&
          item.assistantMessage?.type == message.type &&
          item.assistantMessage?.text == message.text,
    );
  }

  bool _upsertTraceItem(AssistantTraceItem? trace) {
    if (trace == null) {
      return false;
    }
    final index = _pendingConversationItems.indexWhere(
      (item) =>
          item.kind == _ConversationStreamItemKind.traceItem &&
          item.traceItem?.stage == trace.stage &&
          item.traceItem?.title == trace.title,
    );
    if (index >= 0) {
      _pendingConversationItems[index] =
          _ConversationStreamItem.traceItem(trace);
    } else {
      _pendingConversationItems.add(
        _ConversationStreamItem.traceItem(trace),
      );
    }
    return true;
  }

  List<_ConversationStreamItem> _mergeResolvedConversationItems(
    PlannerResolutionResult resolved,
  ) {
    final items = List<_ConversationStreamItem>.from(_pendingConversationItems);
    final assistantMessages = _resolvedAssistantMessages(resolved);

    for (final message in assistantMessages) {
      if (!_containsAssistantMessage(items, message)) {
        items.add(_ConversationStreamItem.assistantMessage(message));
      }
    }

    for (final trace in resolved.trace) {
      final index = items.indexWhere(
        (item) =>
            item.kind == _ConversationStreamItemKind.traceItem &&
            item.traceItem?.stage == trace.stage &&
            item.traceItem?.title == trace.title,
      );
      if (index >= 0) {
        items[index] = _ConversationStreamItem.traceItem(trace);
      } else {
        items.add(_ConversationStreamItem.traceItem(trace));
      }
    }
    return items;
  }

  bool _containsAssistantMessage(
    List<_ConversationStreamItem> items,
    AssistantMessage message,
  ) {
    return items.any(
      (item) =>
          item.kind == _ConversationStreamItemKind.assistantMessage &&
          item.assistantMessage?.type == message.type &&
          item.assistantMessage?.text == message.text,
    );
  }

  List<AssistantMessage> _resolvedAssistantMessages(
    PlannerResolutionResult resolved,
  ) {
    if (resolved.assistantMessages.isNotEmpty) {
      return resolved.assistantMessages;
    }
    return _defaultAssistantMessagesFor(resolved);
  }

  List<AssistantMessage> _defaultAssistantMessagesFor(
    PlannerResolutionResult resolved,
  ) {
    if (resolved.fallbackUsed) {
      return [
        const AssistantMessage(
          type: 'assistant',
          text: '这次没拿到智能规划结果，我先给你一组兜底命令，你确认后也能继续。',
        ),
      ];
    }
    return [
      const AssistantMessage(
        type: 'assistant',
        text: '你说目标，我来整理成一组可直接执行的命令。',
      ),
    ];
  }
}
