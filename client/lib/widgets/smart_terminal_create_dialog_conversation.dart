part of 'smart_terminal_create_dialog.dart';

class _ConversationPanel extends StatelessWidget {
  const _ConversationPanel({
    required this.turns,
    required this.pendingIntent,
    required this.pendingConversationItems,
    required this.executionEvents,
    required this.executing,
    required this.scrollController,
    required this.currentDraft,
    required this.fallbackReason,
    required this.errorMessage,
    required this.showFirstUseGuide,
    required this.showPreview,
    required this.requiresManualConfirmation,
    required this.manualConfirmationAccepted,
    required this.onSubmit,
    required this.onToggleManualConfirmation,
    required this.creating,
    required this.submitEnabled,
  });

  final List<_ConversationTurn> turns;
  final String? pendingIntent;
  final List<_ConversationStreamItem> pendingConversationItems;
  final List<_ConversationStreamItem> executionEvents;
  final bool executing;
  final ScrollController scrollController;
  final CommandSequenceDraft currentDraft;
  final String? fallbackReason;
  final String? errorMessage;
  final bool showFirstUseGuide;
  final bool showPreview;
  final bool requiresManualConfirmation;
  final bool manualConfirmationAccepted;
  final Future<void> Function() onSubmit;
  final ValueChanged<bool>? onToggleManualConfirmation;
  final bool creating;
  final bool submitEnabled;
  static const _assistantBubbleSpacing = SizedBox(height: 12);
  static const _messageSpacing = SizedBox(height: 8);

  @override
  Widget build(BuildContext context) {
    final colorScheme = Theme.of(context).colorScheme;
    final assistantBubbleColor = Colors.white.withValues(alpha: 0.9);
    return SingleChildScrollView(
      controller: scrollController,
      primary: false,
      padding: const EdgeInsets.fromLTRB(2, 8, 2, 4),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (showFirstUseGuide)
            _AssistantIntroCard(
              hasTurns: turns.isNotEmpty,
            ),
          for (var index = 0; index < turns.length; index++) ...[
            _assistantBubbleSpacing,
            ..._buildCompletedTurnWidgets(
              turns[index],
              assistantBubbleColor: assistantBubbleColor,
              includePreview: index == turns.length - 1 && showPreview,
            ),
          ],
          if (showPreview && turns.isEmpty) ...[
            SizedBox(height: showFirstUseGuide ? 12 : 0),
            _buildPreviewBubble(
              assistantBubbleColor,
              requiresManualConfirmation: requiresManualConfirmation,
              manualConfirmationAccepted: manualConfirmationAccepted,
              onToggleManualConfirmation: onToggleManualConfirmation,
            ),
          ],
          if (pendingIntent != null) ...[
            _assistantBubbleSpacing,
            _buildUserBubble(pendingIntent!),
            _messageSpacing,
            ..._buildPendingTurnWidgets(
              assistantBubbleColor: assistantBubbleColor,
            ),
          ],
          if (executing && executionEvents.isEmpty) ...[
            _assistantBubbleSpacing,
            _buildLoadingBubble(
              '正在创建终端并准备执行命令...',
              backgroundColor: assistantBubbleColor,
            ),
          ],
          for (final event in executionEvents) ...[
            _assistantBubbleSpacing,
            _buildConversationBubble(
              event,
              assistantBubbleColor: assistantBubbleColor,
              systemBubbleColor:
                  colorScheme.secondaryContainer.withValues(alpha: 0.5),
            ),
          ],
          if (errorMessage != null) ...[
            _assistantBubbleSpacing,
            _ChatBubble(
              alignment: Alignment.centerLeft,
              backgroundColor:
                  colorScheme.errorContainer.withValues(alpha: 0.72),
              child: Text(
                errorMessage!,
                key: const Key('smart-create-error-bubble'),
                style: TextStyle(color: colorScheme.onErrorContainer),
              ),
            ),
          ],
          const SizedBox(height: 4),
        ],
      ),
    );
  }

  List<Widget> _buildCompletedTurnWidgets(
    _ConversationTurn turn, {
    required Color assistantBubbleColor,
    required bool includePreview,
  }) {
    final widgets = <Widget>[
      _buildUserBubble(turn.userText),
    ];
    final orderedItems = turn.items;
    final traceIndices = <int>[
      for (var index = 0; index < orderedItems.length; index++)
        if (orderedItems[index].kind == _ConversationStreamItemKind.traceItem)
          index,
    ];
    final lastTraceIndex = traceIndices.isEmpty ? -1 : traceIndices.last;

    for (var index = 0; index < orderedItems.length; index++) {
      widgets
        ..add(_messageSpacing)
        ..add(
          _buildConversationBubble(
            orderedItems[index],
            assistantBubbleColor: assistantBubbleColor,
            fallbackReason: orderedItems[index].kind ==
                        _ConversationStreamItemKind.traceItem &&
                    index == lastTraceIndex
                ? turn.fallbackReason
                : null,
          ),
        );
    }
    if (includePreview) {
      widgets
        ..add(_messageSpacing)
        ..add(
          _buildPreviewBubble(
            assistantBubbleColor,
            requiresManualConfirmation: requiresManualConfirmation,
            manualConfirmationAccepted: manualConfirmationAccepted,
            onToggleManualConfirmation: onToggleManualConfirmation,
          ),
        );
    }
    return widgets;
  }

  Widget _buildPreviewBubble(
    Color assistantBubbleColor, {
    required bool requiresManualConfirmation,
    required bool manualConfirmationAccepted,
    required ValueChanged<bool>? onToggleManualConfirmation,
  }) {
    return _ChatBubble(
      alignment: Alignment.centerLeft,
      backgroundColor: assistantBubbleColor,
      child: _CommandSequencePreview(
        draft: currentDraft,
        fallbackReason: fallbackReason,
        requiresManualConfirmation: requiresManualConfirmation,
        manualConfirmationAccepted: manualConfirmationAccepted,
        onToggleManualConfirmation: onToggleManualConfirmation,
        onSubmit: onSubmit,
        creating: creating,
        submitEnabled: submitEnabled,
      ),
    );
  }

  List<Widget> _buildPendingTurnWidgets({
    required Color assistantBubbleColor,
  }) {
    if (pendingConversationItems.isEmpty) {
      return [
        _buildLoadingBubble(
          '正在读取上下文并整理命令...',
          backgroundColor: assistantBubbleColor,
        ),
      ];
    }

    final widgets = <Widget>[
      for (final item in pendingConversationItems) ...[
        _buildConversationBubble(
          item,
          assistantBubbleColor: assistantBubbleColor,
        ),
        _messageSpacing,
      ],
      _buildLoadingBubble(
        '正在继续补全命令步骤...',
        backgroundColor: assistantBubbleColor,
      ),
    ];
    if (widgets.last is SizedBox) {
      widgets.removeLast();
    }
    return widgets;
  }

  Widget _buildUserBubble(String text) {
    return _ChatBubble(
      alignment: Alignment.centerRight,
      backgroundColor: const Color(0xFFDCE8FF),
      child: Text(text),
    );
  }

  Widget _buildLoadingBubble(
    String text, {
    required Color backgroundColor,
  }) {
    return _ChatBubble(
      alignment: Alignment.centerLeft,
      backgroundColor: backgroundColor,
      child: Row(
        children: [
          const _SmallLoadingSpinner(),
          const SizedBox(width: 12),
          Expanded(child: Text(text)),
        ],
      ),
    );
  }

  Widget _buildConversationBubble(
    _ConversationStreamItem item, {
    required Color assistantBubbleColor,
    Color? systemBubbleColor,
    String? fallbackReason,
  }) {
    switch (item.kind) {
      case _ConversationStreamItemKind.assistantMessage:
        return _ChatBubble(
          alignment: Alignment.centerLeft,
          backgroundColor: assistantBubbleColor,
          child: Text(item.assistantMessage!.text),
        );
      case _ConversationStreamItemKind.traceItem:
        final traceItem = item.traceItem!;
        return _ChatBubble(
          alignment: Alignment.centerLeft,
          backgroundColor: assistantBubbleColor,
          child: _TraceEventView(
            item: traceItem,
            fallbackReason: fallbackReason,
          ),
        );
      case _ConversationStreamItemKind.executionEvent:
        return _ChatBubble(
          alignment: Alignment.centerLeft,
          backgroundColor: systemBubbleColor ?? const Color(0xFFEAF2FF),
          child: _ExecutionEventCard(event: item.executionEvent!),
        );
    }
  }
}

class _AssistantIntroCard extends StatelessWidget {
  const _AssistantIntroCard({
    required this.hasTurns,
  });

  final bool hasTurns;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(top: 4, bottom: 4, left: 12, right: 12),
      child: Text(
        hasTurns ? '继续说你的目标，我会接着整理命令。' : '直接说目标，我会生成命令，确认后再执行。',
        key: const Key('smart-create-first-use-hint'),
        style: Theme.of(context).textTheme.bodySmall?.copyWith(
              color: Theme.of(context)
                  .colorScheme
                  .onSurfaceVariant
                  .withValues(alpha: 0.82),
            ),
      ),
    );
  }
}

class _ChatBubble extends StatelessWidget {
  const _ChatBubble({
    required this.alignment,
    required this.backgroundColor,
    required this.child,
  });

  final Alignment alignment;
  final Color backgroundColor;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    final isUser = alignment == Alignment.centerRight;
    final bubbleRadius = BorderRadius.only(
      topLeft: const Radius.circular(22),
      topRight: const Radius.circular(22),
      bottomLeft: Radius.circular(isUser ? 22 : 8),
      bottomRight: Radius.circular(isUser ? 8 : 22),
    );
    return Align(
      alignment: alignment,
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 560),
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
          decoration: BoxDecoration(
            color: backgroundColor,
            borderRadius: bubbleRadius,
            border: Border.all(
              color: Colors.black.withValues(alpha: isUser ? 0.02 : 0.035),
            ),
          ),
          child: child,
        ),
      ),
    );
  }
}
