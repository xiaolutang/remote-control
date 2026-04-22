import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../models/assistant_plan.dart';
import '../models/command_sequence_draft.dart';
import '../models/terminal_launch_plan.dart';
import '../services/command_planner/planner_provider.dart';
import '../services/runtime_selection_controller.dart';

part 'smart_terminal_create_dialog_models.dart';
part 'smart_terminal_create_dialog_conversation.dart';
part 'smart_terminal_create_dialog_controls.dart';
part 'smart_terminal_create_dialog_handlers.dart';
part 'smart_terminal_create_dialog_preview.dart';
part 'smart_terminal_create_dialog_shell.dart';

class SmartTerminalExecutionEvent {
  const SmartTerminalExecutionEvent({
    required this.title,
    required this.message,
    this.status = 'info',
  });

  final String title;
  final String message;
  final String status;
}

class _SmallLoadingSpinner extends StatelessWidget {
  const _SmallLoadingSpinner({
    this.size = 16,
    this.color,
  });

  final double size;
  final Color? color;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: size,
      height: size,
      child: CircularProgressIndicator(
        strokeWidth: 2,
        color: color,
      ),
    );
  }
}

Future<T?> showSmartTerminalCreateDialog<T>({
  required BuildContext context,
  required RuntimeSelectionController controller,
  required Future<T?> Function(
    CommandSequenceDraft draft,
    Future<void> Function(SmartTerminalExecutionEvent event) reportEvent,
  ) onCreate,
  bool showInitialPreview = false,
  String title = '新建智能终端',
}) {
  return showDialog<T>(
    context: context,
    builder: (context) {
      return _SmartTerminalCreateDialog<T>(
        title: title,
        controller: controller,
        onCreate: onCreate,
        showInitialPreview: showInitialPreview,
      );
    },
  );
}

class _SmartTerminalCreateDialog<T> extends StatefulWidget {
  const _SmartTerminalCreateDialog({
    required this.title,
    required this.controller,
    required this.onCreate,
    required this.showInitialPreview,
  });

  final String title;
  final RuntimeSelectionController controller;
  final Future<T?> Function(
    CommandSequenceDraft draft,
    Future<void> Function(SmartTerminalExecutionEvent event) reportEvent,
  ) onCreate;
  final bool showInitialPreview;

  @override
  State<_SmartTerminalCreateDialog<T>> createState() =>
      _SmartTerminalCreateDialogState<T>();
}

class _SmartTerminalCreateDialogState<T>
    extends State<_SmartTerminalCreateDialog<T>>
    with _SmartTerminalCreateDialogHandlers<T> {
  static const String _firstUseGuideSeenKey =
      'smart_terminal_create_first_use_guide_seen_v2';

  @override
  late final TextEditingController _intentController;
  @override
  late final FocusNode _intentFocusNode;
  @override
  late final ScrollController _conversationScrollController;

  @override
  late CommandSequenceDraft _draft;
  @override
  bool _resolvingIntent = false;
  @override
  bool _manualConfirmationAccepted = false;
  @override
  bool _executing = false;
  bool _showFirstUseGuide = false;
  @override
  String? _fallbackReason;
  @override
  String? _pendingIntent;
  @override
  final List<_ConversationStreamItem> _pendingConversationItems = [];
  @override
  final List<_ConversationTurn> _turns = [];
  @override
  final List<_ConversationStreamItem> _executionEvents = [];

  @override
  void initState() {
    super.initState();
    _intentController = TextEditingController();
    _intentFocusNode = FocusNode();
    _conversationScrollController = ScrollController();
    _intentController.addListener(_handleIntentChanged);
    _draft = CommandSequenceDraft.fromLaunchPlan(_fallbackLaunchPlan);
    _manualConfirmationAccepted = !_draft.requiresManualConfirmation;
    _restoreFirstUseGuide();
    _requestInitialFocus();
  }

  @override
  void dispose() {
    _intentController.dispose();
    _intentFocusNode.dispose();
    _conversationScrollController.dispose();
    super.dispose();
  }

  TerminalLaunchPlan get _fallbackLaunchPlan {
    final recommendedPlans = widget.controller.recommendedLaunchPlans;
    if (recommendedPlans.isNotEmpty) {
      return recommendedPlans.first;
    }
    return const TerminalLaunchPlan(
      tool: TerminalLaunchTool.claudeCode,
      title: 'Claude',
      cwd: '~',
      command: '/bin/bash',
      entryStrategy: TerminalEntryStrategy.shellBootstrap,
      postCreateInput: 'claude\n',
      source: TerminalLaunchPlanSource.recommended,
    );
  }

  void _requestInitialFocus() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) {
        return;
      }
      _intentFocusNode.requestFocus();
    });
  }

  bool get _creating => widget.controller.creatingTerminal || _executing;

  bool _submitEnabledFor(CommandSequenceDraft draft) {
    return !_creating &&
        !_resolvingIntent &&
        (!draft.requiresManualConfirmation || _manualConfirmationAccepted);
  }

  VoidCallback? get _closeDialog =>
      _creating ? null : () => Navigator.of(context).pop();

  ValueChanged<bool>? get _manualConfirmationHandler {
    if (_creating || _resolvingIntent) {
      return null;
    }
    return (value) {
      setState(() {
        _manualConfirmationAccepted = value;
      });
      _scheduleScrollToLatest();
    };
  }

  @override
  Widget build(BuildContext context) {
    final mediaSize = MediaQuery.sizeOf(context);
    final compactLayout = mediaSize.width < 560;
    final horizontalInset = compactLayout ? 12.0 : 24.0;
    final dialogMaxHeight = mediaSize.height * 0.9;

    return AnimatedBuilder(
      animation: widget.controller,
      builder: (context, _) {
        final draft = _buildCurrentDraft();
        return _SmartTerminalDialogShell(
          title: widget.title,
          horizontalInset: horizontalInset,
          compactLayout: compactLayout,
          dialogMaxHeight: dialogMaxHeight,
          creating: _creating,
          resolvingIntent: _resolvingIntent,
          executing: _executing,
          errorMessage: widget.controller.errorMessage,
          draft: draft,
          fallbackReason: _fallbackReason,
          pendingIntent: _pendingIntent,
          pendingConversationItems: _pendingConversationItems,
          turns: _turns,
          executionEvents: _executionEvents,
          showFirstUseGuide: _showFirstUseGuide,
          showInitialPreview: widget.showInitialPreview,
          requiresManualConfirmation: draft.requiresManualConfirmation,
          manualConfirmationAccepted: _manualConfirmationAccepted,
          onClose: _closeDialog,
          onSubmit: _handleCreate,
          onToggleManualConfirmation: _manualConfirmationHandler,
          intentController: _intentController,
          intentFocusNode: _intentFocusNode,
          conversationScrollController: _conversationScrollController,
          onResolveIntent: _handleResolveIntent,
          submitEnabled: _submitEnabledFor(draft),
        );
      },
    );
  }

  Future<void> _restoreFirstUseGuide() async {
    final prefs = await SharedPreferences.getInstance();
    final seen = prefs.getBool(_firstUseGuideSeenKey) ?? false;
    if (seen) {
      return;
    }
    await prefs.setBool(_firstUseGuideSeenKey, true);
    if (!mounted) {
      return;
    }
    setState(() {
      _showFirstUseGuide = true;
    });
  }

  void _handleIntentChanged() {
    if (!_shouldHideFirstUseGuide) {
      return;
    }
    setState(() {
      _showFirstUseGuide = false;
    });
  }

  bool get _shouldHideFirstUseGuide {
    return mounted &&
        _showFirstUseGuide &&
        _intentController.text.trim().isNotEmpty;
  }
}
