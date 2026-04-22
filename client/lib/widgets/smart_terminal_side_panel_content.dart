part of 'smart_terminal_side_panel.dart';

/// 侧滑面板内部内容：会话消息流 + 意图输入框。
class _SmartTerminalSidePanelContent extends StatefulWidget {
  const _SmartTerminalSidePanelContent({
    required this.onClose,
    required this.isOpen,
  });

  final VoidCallback onClose;
  final bool isOpen;

  @override
  State<_SmartTerminalSidePanelContent> createState() =>
      _SmartTerminalSidePanelContentState();
}

class _SmartTerminalSidePanelContentState
    extends State<_SmartTerminalSidePanelContent> {
  late final TextEditingController _intentController;
  late final FocusNode _intentFocusNode;
  late final ScrollController _scrollController;

  bool _resolvingIntent = false;
  String? _pendingIntent;
  final List<_SidePanelConversationTurn> _turns = [];
  final List<_SidePanelStreamItem> _pendingItems = [];
  CommandSequenceDraft _draft =
      CommandSequenceDraft.fromLaunchPlan(const TerminalLaunchPlan(
    tool: TerminalLaunchTool.claudeCode,
    title: 'Claude',
    cwd: '~',
    command: '/bin/bash',
    entryStrategy: TerminalEntryStrategy.shellBootstrap,
    postCreateInput: '',
    source: TerminalLaunchPlanSource.recommended,
  ));
  String? _fallbackReason;
  bool _executing = false;

  @override
  void initState() {
    super.initState();
    _intentController = TextEditingController();
    _intentFocusNode = FocusNode();
    _scrollController = ScrollController();
  }

  @override
  void dispose() {
    _intentController.dispose();
    _intentFocusNode.dispose();
    _scrollController.dispose();
    super.dispose();
  }

  bool get _isConnected {
    try {
      final service = context.read<WebSocketService>();
      return service.status == ConnectionStatus.connected;
    } on ProviderNotFoundException {
      return false;
    }
  }

  void _scheduleScrollToLatest() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scrollController.hasClients) {
        _scrollController.animateTo(
          _scrollController.position.maxScrollExtent,
          duration: const Duration(milliseconds: 200),
          curve: Curves.easeOut,
        );
      }
    });
  }

  Future<void> _handleResolveIntent() async {
    final intent = _intentController.text.trim();
    if (intent.isEmpty || _resolvingIntent) return;

    _intentController.clear();
    setState(() {
      _resolvingIntent = true;
      _pendingIntent = intent;
      _pendingItems.clear();
    });
    _scheduleScrollToLatest();

    RuntimeSelectionController? controller;
    try {
      controller = context.read<RuntimeSelectionController>();
    } on ProviderNotFoundException {
      setState(() {
        _resolvingIntent = false;
        _pendingItems.add(_SidePanelStreamItem.assistantMessage(
          AssistantMessage(type: 'error', text: '无法访问终端控制器，请重试。'),
        ));
      });
      return;
    }

    final progress = <_SidePanelStreamItem>[];
    PlannerResolutionResult? resolved;
    try {
      resolved = await controller.resolveLaunchIntent(
        intent,
        onProgress: (AssistantPlanProgressEvent event) {
          if (!mounted) return;
          _applyProgress(event, progress);
        },
      );
    } catch (e) {
      if (!mounted) return;
      progress.add(_SidePanelStreamItem.assistantMessage(
        AssistantMessage(type: 'error', text: '解析意图失败：$e'),
      ));
    }

    if (!mounted) return;
    CommandSequenceDraft nextDraft;
    if (resolved != null) {
      nextDraft = resolved.sequence ??
          CommandSequenceDraft.fromLaunchPlan(
            resolved.plan,
            provider: resolved.provider,
          );
      if (resolved.fallbackUsed) {
        _fallbackReason = resolved.fallbackReason ?? '自动兜底';
      }
    } else {
      nextDraft = _draft;
    }
    setState(() {
      _resolvingIntent = false;
      _turns.add(_SidePanelConversationTurn(
        userText: intent,
        items: List.of(progress),
        fallbackReason: _fallbackReason,
      ));
      _pendingIntent = null;
      _pendingItems.clear();
      _draft = nextDraft;
    });
    _scheduleScrollToLatest();
  }

  void _applyProgress(
    AssistantPlanProgressEvent event,
    List<_SidePanelStreamItem> progress,
  ) {
    if (event.assistantMessage != null) {
      final item = _SidePanelStreamItem.assistantMessage(event.assistantMessage!);
      progress.add(item);
      setState(() => _pendingItems.add(item));
    }
    if (event.derivedTraceItem != null) {
      final item = _SidePanelStreamItem.traceItem(event.derivedTraceItem!);
      progress.add(item);
      setState(() => _pendingItems.add(item));
    }
    _scheduleScrollToLatest();
  }

  Future<void> _handleExecute() async {
    if (_executing || !_isConnected) return;
    setState(() => _executing = true);

    // 编译命令并通过 WebSocket 注入
    final plan = _draft.toLaunchPlan();
    final input = plan.postCreateInput;
    if (input.isNotEmpty) {
      try {
        final service = context.read<WebSocketService>();
        service.send(input);
      } catch (_) {
        // 注入失败不阻塞
      }
    }

    setState(() => _executing = false);
    widget.onClose(); // 执行后自动收起面板
  }

  @override
  Widget build(BuildContext context) {
    final colorScheme = Theme.of(context).colorScheme;
    final connected = _isConnected;
    final hasPendingTurn = _pendingIntent != null;
    // ignore: unused_local_variable (used below via hasPendingTurn)

    return Container(
      decoration: BoxDecoration(
        color: const Color(0xFFFBFCFE),
        borderRadius: const BorderRadius.horizontal(
          left: Radius.circular(24),
        ),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withValues(alpha: 0.12),
            blurRadius: 24,
            offset: const Offset(-4, 0),
          ),
        ],
        border: Border.all(
          color: colorScheme.outlineVariant.withValues(alpha: 0.18),
        ),
      ),
      child: Column(
        children: [
          // Header
          Container(
            padding: const EdgeInsets.fromLTRB(16, 14, 8, 14),
            decoration: BoxDecoration(
              border: Border(
                bottom: BorderSide(
                  color: colorScheme.outlineVariant.withValues(alpha: 0.14),
                ),
              ),
            ),
            child: Row(
              children: [
                Icon(Icons.auto_awesome,
                    size: 20, color: colorScheme.primary),
                const SizedBox(width: 10),
                Expanded(
                  child: Text(
                    '智能助手',
                    style: Theme.of(context).textTheme.titleSmall?.copyWith(
                          fontWeight: FontWeight.w600,
                        ),
                  ),
                ),
                IconButton(
                  key: const Key('side-panel-close'),
                  onPressed: widget.onClose,
                  icon: const Icon(Icons.close, size: 20),
                  style: IconButton.styleFrom(
                    tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                    minimumSize: const Size(36, 36),
                  ),
                ),
              ],
            ),
          ),

          // 会话消息流
          Expanded(
            child: SingleChildScrollView(
              controller: _scrollController,
              primary: false,
              padding: const EdgeInsets.fromLTRB(12, 8, 12, 4),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  if (_turns.isEmpty && _pendingIntent == null)
                    Padding(
                      padding: const EdgeInsets.symmetric(
                          vertical: 16, horizontal: 4),
                      child: Text(
                        '直接说目标，我会生成命令，确认后再执行。',
                        style: Theme.of(context).textTheme.bodySmall?.copyWith(
                              color: colorScheme.onSurfaceVariant
                                  .withValues(alpha: 0.82),
                            ),
                      ),
                    ),
                  for (final turn in _turns) ...[
                    _buildUserBubble(turn.userText),
                    const SizedBox(height: 8),
                    for (final item in turn.items) ...[
                      _buildItemBubble(item, colorScheme),
                      const SizedBox(height: 8),
                    ],
                    if (turn == _turns.last) ...[
                      _buildPreviewCard(colorScheme, connected),
                      const SizedBox(height: 8),
                    ],
                  ],
                  if (hasPendingTurn) ...[
                    _buildUserBubble(_pendingIntent!),
                    const SizedBox(height: 8),
                    if (_pendingItems.isEmpty)
                      _buildLoadingBubble('正在读取上下文...', colorScheme)
                    else
                      for (final item in _pendingItems) ...[
                        _buildItemBubble(item, colorScheme),
                        const SizedBox(height: 8),
                      ],
                    if (_resolvingIntent && _pendingItems.isNotEmpty)
                      _buildLoadingBubble('正在继续补全...', colorScheme),
                  ],
                ],
              ),
            ),
          ),

          // 底部意图输入
          Container(
            padding: const EdgeInsets.fromLTRB(12, 8, 12, 14),
            decoration: BoxDecoration(
              color: Colors.white,
              border: Border(
                top: BorderSide(
                  color: colorScheme.outlineVariant.withValues(alpha: 0.14),
                ),
              ),
            ),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.center,
              children: [
                Expanded(
                  child: ConstrainedBox(
                    constraints: const BoxConstraints(minHeight: 44),
                    child: Center(
                      child: TextField(
                        key: const Key('side-panel-intent-input'),
                        controller: _intentController,
                        focusNode: _intentFocusNode,
                        textInputAction: TextInputAction.send,
                        textAlignVertical: TextAlignVertical.center,
                        decoration: InputDecoration(
                          hintText: '说目标，例如：进入日知项目',
                          border: OutlineInputBorder(
                            borderRadius: BorderRadius.circular(16),
                            borderSide: BorderSide(
                              color:
                                  colorScheme.outlineVariant.withValues(alpha: 0.3),
                            ),
                          ),
                          enabledBorder: OutlineInputBorder(
                            borderRadius: BorderRadius.circular(16),
                            borderSide: BorderSide(
                              color:
                                  colorScheme.outlineVariant.withValues(alpha: 0.3),
                            ),
                          ),
                          focusedBorder: OutlineInputBorder(
                            borderRadius: BorderRadius.circular(16),
                            borderSide: BorderSide(
                              color: colorScheme.primary,
                            ),
                          ),
                          isDense: true,
                          contentPadding: const EdgeInsets.symmetric(
                              horizontal: 14, vertical: 10),
                        ),
                        minLines: 1,
                        maxLines: 3,
                        style: Theme.of(context).textTheme.bodyMedium,
                        onSubmitted: (_) {
                          if (!_executing && !_resolvingIntent) {
                            _handleResolveIntent();
                          }
                        },
                      ),
                    ),
                  ),
                ),
                const SizedBox(width: 8),
                SizedBox(
                  width: 44,
                  height: 44,
                  child: FilledButton(
                    key: const Key('side-panel-send'),
                    style: FilledButton.styleFrom(
                      padding: EdgeInsets.zero,
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(14),
                      ),
                      backgroundColor: const Color(0xFF1F5EFF),
                    ),
                    onPressed: _executing || _resolvingIntent
                        ? null
                        : _handleResolveIntent,
                    child: _resolvingIntent
                        ? const SizedBox(
                            width: 16,
                            height: 16,
                            child: CircularProgressIndicator(
                              strokeWidth: 2,
                              color: Colors.white,
                            ),
                          )
                        : const Icon(Icons.arrow_upward, size: 18),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildUserBubble(String text) {
    return Align(
      alignment: Alignment.centerRight,
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 280),
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
          decoration: BoxDecoration(
            color: const Color(0xFFDCE8FF),
            borderRadius: const BorderRadius.only(
              topLeft: Radius.circular(18),
              topRight: Radius.circular(18),
              bottomLeft: Radius.circular(18),
              bottomRight: Radius.circular(4),
            ),
          ),
          child: Text(text, style: Theme.of(context).textTheme.bodyMedium),
        ),
      ),
    );
  }

  Widget _buildAssistantBubble(Widget child) {
    return Align(
      alignment: Alignment.centerLeft,
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 340),
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
          decoration: BoxDecoration(
            color: Colors.white.withValues(alpha: 0.9),
            borderRadius: const BorderRadius.only(
              topLeft: Radius.circular(18),
              topRight: Radius.circular(18),
              bottomLeft: Radius.circular(4),
              bottomRight: Radius.circular(18),
            ),
            border: Border.all(
              color: Colors.black.withValues(alpha: 0.035),
            ),
          ),
          child: child,
        ),
      ),
    );
  }

  Widget _buildItemBubble(_SidePanelStreamItem item, ColorScheme colorScheme) {
    switch (item.kind) {
      case _SidePanelStreamItemKind.assistantMessage:
        return _buildAssistantBubble(
          Text(item.assistantMessage!.text,
              style: Theme.of(context).textTheme.bodySmall),
        );
      case _SidePanelStreamItemKind.traceItem:
        final trace = item.traceItem!;
        return _buildAssistantBubble(
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  _SidePanelStagePill(stage: trace.stage),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      trace.title,
                      style: Theme.of(context)
                          .textTheme
                          .bodySmall
                          ?.copyWith(fontWeight: FontWeight.w600),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 4),
              Text(
                trace.summary,
                style: Theme.of(context).textTheme.bodySmall?.copyWith(
                      color: colorScheme.onSurfaceVariant,
                      height: 1.4,
                    ),
              ),
            ],
          ),
        );
    }
  }

  Widget _buildLoadingBubble(String text, ColorScheme colorScheme) {
    return _buildAssistantBubble(
      Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          SizedBox(
            width: 14,
            height: 14,
            child: CircularProgressIndicator(
              strokeWidth: 2,
              color: colorScheme.primary,
            ),
          ),
          const SizedBox(width: 10),
          Text(text, style: Theme.of(context).textTheme.bodySmall),
        ],
      ),
    );
  }

  Widget _buildPreviewCard(ColorScheme colorScheme, bool connected) {
    final summary =
        _draft.summary.trim().isEmpty ? '准备执行命令' : _draft.summary;
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: Colors.white.withValues(alpha: 0.82),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(
          color: colorScheme.outlineVariant.withValues(alpha: 0.14),
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            summary,
            style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                  fontWeight: FontWeight.w600,
                ),
          ),
          const SizedBox(height: 4),
          Text(
            '目录 · ${_draft.cwd}    步骤 · ${_draft.steps.length}',
            style: Theme.of(context).textTheme.bodySmall?.copyWith(
                  color: colorScheme.onSurfaceVariant,
                ),
          ),
          if (!connected) ...[
            const SizedBox(height: 6),
            Text(
              '终端未连接，请先确认连接状态。',
              style: TextStyle(color: colorScheme.error, fontSize: 12),
            ),
          ],
          const SizedBox(height: 10),
          SizedBox(
            width: double.infinity,
            child: FilledButton(
              key: const Key('side-panel-execute'),
              style: FilledButton.styleFrom(
                minimumSize: const Size.fromHeight(40),
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(12),
                ),
                backgroundColor: const Color(0xFF1F5EFF),
              ),
              onPressed: connected && !_executing ? _handleExecute : null,
              child: _executing
                  ? const SizedBox(
                      width: 16,
                      height: 16,
                      child: CircularProgressIndicator(
                        strokeWidth: 2,
                        color: Colors.white,
                      ),
                    )
                  : const Text('执行'),
            ),
          ),
        ],
      ),
    );
  }
}

// --- 内部模型 ---

enum _SidePanelStreamItemKind {
  assistantMessage,
  traceItem,
}

class _SidePanelStreamItem {
  const _SidePanelStreamItem._({
    required this.kind,
    this.assistantMessage,
    this.traceItem,
  });

  const _SidePanelStreamItem.assistantMessage(AssistantMessage message)
      : this._(
          kind: _SidePanelStreamItemKind.assistantMessage,
          assistantMessage: message,
        );

  const _SidePanelStreamItem.traceItem(AssistantTraceItem trace)
      : this._(
          kind: _SidePanelStreamItemKind.traceItem,
          traceItem: trace,
        );

  final _SidePanelStreamItemKind kind;
  final AssistantMessage? assistantMessage;
  final AssistantTraceItem? traceItem;
}

class _SidePanelConversationTurn {
  const _SidePanelConversationTurn({
    required this.userText,
    required this.items,
    this.fallbackReason,
  });

  final String userText;
  final List<_SidePanelStreamItem> items;
  final String? fallbackReason;
}

class _SidePanelStagePill extends StatelessWidget {
  const _SidePanelStagePill({required this.stage});

  final String stage;

  @override
  Widget build(BuildContext context) {
    final colorScheme = Theme.of(context).colorScheme;
    final (label, bg, fg) = switch (stage) {
      'tool' || 'tools' => ('工具', const Color(0xFFEAF2FF), colorScheme.primary),
      'context' => ('上下文', const Color(0xFFF4EFE6), const Color(0xFF8B5E2B)),
      'plan' || 'planner' =>
        ('思考', const Color(0xFFF2EEFF), const Color(0xFF6852C8)),
      _ => ('处理', const Color(0xFFEFF3F8), colorScheme.onSurfaceVariant),
    };
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
      decoration: BoxDecoration(
        color: bg,
        borderRadius: BorderRadius.circular(999),
      ),
      child: Text(
        label,
        style: Theme.of(context).textTheme.labelSmall?.copyWith(
              color: fg,
              fontWeight: FontWeight.w600,
              fontSize: 10,
            ),
      ),
    );
  }
}
