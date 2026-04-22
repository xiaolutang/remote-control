part of 'smart_terminal_create_dialog.dart';

class _SmartTerminalDialogShell extends StatelessWidget {
  const _SmartTerminalDialogShell({
    required this.title,
    required this.horizontalInset,
    required this.compactLayout,
    required this.dialogMaxHeight,
    required this.creating,
    required this.resolvingIntent,
    required this.executing,
    required this.errorMessage,
    required this.draft,
    required this.fallbackReason,
    required this.pendingIntent,
    required this.pendingConversationItems,
    required this.turns,
    required this.executionEvents,
    required this.showFirstUseGuide,
    required this.showInitialPreview,
    required this.requiresManualConfirmation,
    required this.manualConfirmationAccepted,
    required this.submitEnabled,
    required this.onClose,
    required this.onSubmit,
    required this.onToggleManualConfirmation,
    required this.intentController,
    required this.intentFocusNode,
    required this.conversationScrollController,
    required this.onResolveIntent,
  });

  final String title;
  final double horizontalInset;
  final bool compactLayout;
  final double dialogMaxHeight;
  final bool creating;
  final bool resolvingIntent;
  final bool executing;
  final String? errorMessage;
  final CommandSequenceDraft draft;
  final String? fallbackReason;
  final String? pendingIntent;
  final List<_ConversationStreamItem> pendingConversationItems;
  final List<_ConversationTurn> turns;
  final List<_ConversationStreamItem> executionEvents;
  final bool showFirstUseGuide;
  final bool showInitialPreview;
  final bool requiresManualConfirmation;
  final bool manualConfirmationAccepted;
  final bool submitEnabled;
  final VoidCallback? onClose;
  final Future<void> Function() onSubmit;
  final ValueChanged<bool>? onToggleManualConfirmation;
  final TextEditingController intentController;
  final FocusNode intentFocusNode;
  final ScrollController conversationScrollController;
  final Future<void> Function() onResolveIntent;

  @override
  Widget build(BuildContext context) {
    final colorScheme = Theme.of(context).colorScheme;
    return Dialog(
      backgroundColor: Colors.transparent,
      elevation: 0,
      insetPadding: EdgeInsets.symmetric(
        horizontal: horizontalInset,
        vertical: 24,
      ),
      child: Semantics(
        label: title,
        container: true,
        child: Container(
          decoration: BoxDecoration(
            color: const Color(0xFFFBFCFE),
            borderRadius: BorderRadius.circular(28),
            border: Border.all(
              color: colorScheme.outlineVariant.withValues(alpha: 0.24),
            ),
            boxShadow: [
              BoxShadow(
                color: Colors.black.withValues(alpha: 0.06),
                blurRadius: 28,
                offset: const Offset(0, 18),
              ),
            ],
          ),
          child: ConstrainedBox(
            constraints: BoxConstraints(
              maxWidth: 760,
              maxHeight: dialogMaxHeight,
            ),
            child: Padding(
              padding: EdgeInsets.fromLTRB(
                compactLayout ? 16 : 20,
                compactLayout ? 12 : 14,
                compactLayout ? 16 : 20,
                compactLayout ? 14 : 16,
              ),
              child: Column(
                children: [
                  _SmartTerminalDialogHeader(
                    creating: creating,
                    onClose: onClose,
                  ),
                  const SizedBox(height: 2),
                  Expanded(
                    child: _ConversationPanel(
                      turns: turns,
                      pendingIntent: pendingIntent,
                      pendingConversationItems: pendingConversationItems,
                      executionEvents: executionEvents,
                      executing: executing,
                      scrollController: conversationScrollController,
                      currentDraft: draft,
                      fallbackReason: fallbackReason,
                      errorMessage: errorMessage,
                      showFirstUseGuide: showFirstUseGuide,
                      showPreview: showInitialPreview || turns.isNotEmpty,
                      requiresManualConfirmation: requiresManualConfirmation,
                      manualConfirmationAccepted: manualConfirmationAccepted,
                      onSubmit: onSubmit,
                      onToggleManualConfirmation: onToggleManualConfirmation,
                      creating: creating,
                      submitEnabled: submitEnabled,
                    ),
                  ),
                  const SizedBox(height: 8),
                  _SmartTerminalIntentComposer(
                    creating: creating,
                    resolvingIntent: resolvingIntent,
                    controller: intentController,
                    focusNode: intentFocusNode,
                    onResolveIntent: onResolveIntent,
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _SmartTerminalDialogHeader extends StatelessWidget {
  const _SmartTerminalDialogHeader({
    required this.creating,
    required this.onClose,
  });

  final bool creating;
  final VoidCallback? onClose;

  @override
  Widget build(BuildContext context) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.center,
      children: [
        const Spacer(),
        if (creating) ...[
          const SizedBox(width: 8),
          const _SmallLoadingSpinner(size: 14),
        ],
        IconButton(
          key: const Key('smart-create-cancel'),
          tooltip: '关闭',
          onPressed: onClose,
          icon: const Icon(Icons.close),
        ),
      ],
    );
  }
}
