part of 'smart_terminal_side_panel.dart';

/// Agent 面板交互状态
enum AgentPanelState {
  /// 空闲/初始状态
  idle,

  /// Agent 正在探索（执行工具调用）
  exploring,

  /// Agent 在提问，等待用户回答
  asking,

  /// Agent 返回了最终结果
  result,

  /// Agent 会话出错
  error,

  /// Agent 不可用，已降级到 planner 模式
  fallback,
}

/// 侧滑面板内部内容：会话消息流 + 意图输入框。
class _SmartTerminalSidePanelContent extends StatefulWidget {
  const _SmartTerminalSidePanelContent({
    required this.onClose,
  });

  final VoidCallback onClose;

  @override
  State<_SmartTerminalSidePanelContent> createState() =>
      _SmartTerminalSidePanelContentState();
}

class _SmartTerminalSidePanelContentState
    extends State<_SmartTerminalSidePanelContent> {
  late final TextEditingController _intentController;
  late final FocusNode _intentFocusNode;
  late final ScrollController _scrollController;

  // --- Planner 模式状态 ---
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

  // --- Agent SSE 模式状态 ---
  AgentPanelState _agentState = AgentPanelState.idle;
  final List<AgentTraceEvent> _traces = [];
  AgentQuestionEvent? _currentQuestion;
  AgentResultEvent? _agentResult;
  AgentErrorEvent? _agentError;
  String? _activeSessionId;
  StreamSubscription<AgentSessionEvent>? _eventSubscription;
  final Set<String> _multiSelectChosen = {};
  bool _isFallbackMode = false;
  String? _agentIntent; // 当前 Agent 正在处理的意图

  @override
  void initState() {
    super.initState();
    _intentController = TextEditingController();
    _intentFocusNode = FocusNode();
    _scrollController = ScrollController();
  }

  @override
  void dispose() {
    _eventSubscription?.cancel();
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
      if (!mounted || !_scrollController.hasClients) return;
      _scrollController.animateTo(
        _scrollController.position.maxScrollExtent,
        duration: const Duration(milliseconds: 200),
        curve: Curves.easeOut,
      );
    });
  }

  // ============================================================
  // Intent 提交入口：优先尝试 Agent SSE，降级走 planner
  // ============================================================

  Future<void> _handleResolveIntent() async {
    final intent = _intentController.text.trim();
    if (intent.isEmpty || _resolvingIntent) return;

    _intentController.clear();
    _fallbackReason = null;

    // 已在降级模式，直接走 planner
    if (_isFallbackMode) {
      _resolveViaPlanner(intent);
      return;
    }

    // 尝试通过 Agent SSE 路径
    RuntimeSelectionController? controller;
    try {
      controller = context.read<RuntimeSelectionController>();
    } on ProviderNotFoundException {
      _resolveViaPlanner(intent);
      return;
    }

    final deviceId = controller.selectedDeviceId;
    if (deviceId == null || deviceId.isEmpty) {
      _resolveViaPlanner(intent);
      return;
    }

    _startAgentSession(intent: intent, controller: controller);
  }

  // ============================================================
  // Agent SSE 会话
  // ============================================================

  Future<void> _startAgentSession({
    required String intent,
    required RuntimeSelectionController controller,
  }) async {
    final deviceId = controller.selectedDeviceId!;
    final token = controller.token;
    final serverUrl = controller.serverUrl;

    setState(() {
      _agentState = AgentPanelState.exploring;
      _traces.clear();
      _currentQuestion = null;
      _agentResult = null;
      _agentError = null;
      _multiSelectChosen.clear();
      _agentIntent = intent;
      _activeSessionId = null;
    });
    _scheduleScrollToLatest();

    final service = AgentSessionService(serverUrl: serverUrl);

    try {
      final eventStream = service.runSession(
        deviceId: deviceId,
        intent: intent,
        token: token,
      );

      _eventSubscription?.cancel();
      _eventSubscription = eventStream.listen(
        (event) {
          if (!mounted) return;
          _handleAgentEvent(event, controller: controller);
        },
        onError: (Object error) {
          if (!mounted) return;
          // 网络或其他异常，降级
          _fallbackToPlannerWithError(
            intent: intent,
            controller: controller,
            reason: 'Agent 连接失败',
          );
        },
        onDone: () {
          // SSE 流正常关闭
        },
      );
    } catch (e) {
      if (!mounted) return;
      _fallbackToPlannerWithError(
        intent: intent,
        controller: controller,
        reason: 'Agent 请求失败',
      );
    }
  }

  void _handleAgentEvent(
    AgentSessionEvent event, {
    required RuntimeSelectionController controller,
  }) {
    switch (event) {
      case AgentTraceEvent trace:
        setState(() {
          _traces.add(trace);
          // 保持 exploring 状态（或者从 asking 回到 exploring）
          if (_agentState == AgentPanelState.idle ||
              _agentState == AgentPanelState.asking) {
            _agentState = AgentPanelState.exploring;
          }
        });
        _scheduleScrollToLatest();

      case AgentQuestionEvent question:
        setState(() {
          _currentQuestion = question;
          _agentState = AgentPanelState.asking;
          _multiSelectChosen.clear();
        });
        _scheduleScrollToLatest();

      case AgentResultEvent result:
        setState(() {
          _agentResult = result;
          _agentState = AgentPanelState.result;
          // 从 AgentResult 构建 CommandSequenceDraft
          _draft = _buildDraftFromAgentResult(result);
        });
        _scheduleScrollToLatest();

      case AgentErrorEvent error:
        setState(() {
          _agentError = error;
          _agentState = AgentPanelState.error;
        });
        _scheduleScrollToLatest();

      case AgentFallbackEvent fallback:
        final intent = _agentIntent;
        setState(() {
          _isFallbackMode = true;
          _agentState = AgentPanelState.fallback;
          _agentIntent = null; // 清除避免重复显示
        });
        // 然后走 planner 链路（planner 会自己管理 turns）
        if (intent != null && intent.isNotEmpty) {
          _resolveViaPlanner(intent);
        }
    }
  }

  /// Agent 降级后用 planner 解析意图
  Future<void> _fallbackToPlannerWithError({
    required String intent,
    required RuntimeSelectionController controller,
    required String reason,
  }) async {
    setState(() {
      _isFallbackMode = true;
      _agentState = AgentPanelState.fallback;
      _agentIntent = null; // 清除避免重复显示
    });
    _resolveViaPlanner(intent);
  }

  /// 从 AgentResultEvent 构建 CommandSequenceDraft
  CommandSequenceDraft _buildDraftFromAgentResult(AgentResultEvent result) {
    final steps = result.steps
        .map((s) => CommandSequenceStep(
              id: s.id,
              label: s.label,
              command: s.command,
            ))
        .toList();
    return CommandSequenceDraft(
      summary: result.summary,
      provider: result.provider,
      tool: TerminalLaunchTool.custom,
      title: result.summary,
      cwd: '~',
      shellCommand: '/bin/bash',
      steps: List.unmodifiable(steps),
      source: TerminalLaunchPlanSource.intent,
      requiresManualConfirmation: result.needConfirm,
    );
  }

  /// 用户回答 Agent 问题
  Future<void> _handleAgentRespond(String answer) async {
    if (_activeSessionId == null) return;

    RuntimeSelectionController? controller;
    try {
      controller = context.read<RuntimeSelectionController>();
    } on ProviderNotFoundException {
      return;
    }

    final deviceId = controller.selectedDeviceId;
    if (deviceId == null) return;

    setState(() {
      _agentState = AgentPanelState.exploring;
      _currentQuestion = null;
    });

    try {
      final service = AgentSessionService(serverUrl: controller.serverUrl);
      await service.respond(
        deviceId: deviceId,
        sessionId: _activeSessionId!,
        answer: answer,
        token: controller.token,
      );
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _agentError = AgentErrorEvent(
          code: 'RESPOND_FAILED',
          message: '回复失败：$e',
        );
        _agentState = AgentPanelState.error;
      });
    }
  }

  /// 执行 Agent 结果（注入命令到终端）
  Future<void> _executeAgentResult() async {
    if (_executing || !_isConnected) return;
    setState(() => _executing = true);

    final plan = _draft.toLaunchPlan();
    final input = plan.postCreateInput;
    var injectFailed = false;
    if (input.isNotEmpty) {
      try {
        final service = context.read<WebSocketService>();
        service.send(input);
      } catch (e) {
        injectFailed = true;
        if (!mounted) return;
        setState(() {
          _agentState = AgentPanelState.error;
          _agentError = AgentErrorEvent(
            code: 'INJECT_FAILED',
            message: '命令注入失败：$e',
          );
        });
      }
    }

    if (!mounted) return;
    setState(() => _executing = false);
    if (!injectFailed) {
      widget.onClose();
    }
  }

  // ============================================================
  // Planner 模式（原始逻辑，降级或 fallback 时使用）
  // ============================================================

  Future<void> _resolveViaPlanner(String intent) async {
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
      // 如果之前是 fallback 状态，完成 planner 后切回 idle
      if (_agentState == AgentPanelState.fallback) {
        _agentState = AgentPanelState.idle;
      }
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

  /// 原始执行（planner 模式）
  Future<void> _handleExecute() async {
    if (_executing || !_isConnected) return;
    setState(() => _executing = true);

    final plan = _draft.toLaunchPlan();
    final input = plan.postCreateInput;
    var injectFailed = false;
    if (input.isNotEmpty) {
      try {
        final service = context.read<WebSocketService>();
        service.send(input);
      } catch (e) {
        injectFailed = true;
        if (!mounted) return;
        _turns.add(_SidePanelConversationTurn(
          userText: '',
          items: [_SidePanelStreamItem.assistantMessage(
            AssistantMessage(type: 'error', text: '命令注入失败：$e'),
          )],
        ));
      }
    }

    if (!mounted) return;
    setState(() => _executing = false);
    if (!injectFailed) {
      widget.onClose();
    }
  }

  /// 重试 Agent 会话
  void _retryAgentSession() {
    if (_agentIntent != null) {
      RuntimeSelectionController? controller;
      try {
        controller = context.read<RuntimeSelectionController>();
      } on ProviderNotFoundException {
        return;
      }
      setState(() {
        _agentState = AgentPanelState.idle;
        _agentError = null;
      });
      _startAgentSession(intent: _agentIntent!, controller: controller);
    }
  }

  /// 切换到快速模式
  void _switchToFallbackMode() {
    final intent = _agentIntent;
    if (intent != null) {
      setState(() {
        _isFallbackMode = true;
        _agentState = AgentPanelState.fallback;
        _agentIntent = null;
      });
      _resolveViaPlanner(intent);
    }
  }

  // ============================================================
  // UI 构建
  // ============================================================

  @override
  Widget build(BuildContext context) {
    final colorScheme = Theme.of(context).colorScheme;
    final connected = _isConnected;

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
          _buildHeader(colorScheme),

          // 消息体
          Expanded(
            child: SingleChildScrollView(
              controller: _scrollController,
              primary: false,
              padding: const EdgeInsets.fromLTRB(12, 8, 12, 4),
              child: _buildBody(colorScheme, connected),
            ),
          ),

          // 底部意图输入
          _buildInputBar(colorScheme),
        ],
      ),
    );
  }

  Widget _buildHeader(ColorScheme colorScheme) {
    return Container(
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
          Icon(Icons.auto_awesome, size: 20, color: colorScheme.primary),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              '智能助手',
              style: Theme.of(context).textTheme.titleSmall?.copyWith(
                    fontWeight: FontWeight.w600,
                  ),
            ),
          ),
          if (_isFallbackMode)
            Container(
              margin: const EdgeInsets.only(right: 8),
              padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
              decoration: BoxDecoration(
                color: const Color(0xFFFFF3E0),
                borderRadius: BorderRadius.circular(999),
              ),
              child: Text(
                '快速模式',
                style: Theme.of(context).textTheme.labelSmall?.copyWith(
                      color: const Color(0xFFE65100),
                      fontWeight: FontWeight.w600,
                      fontSize: 10,
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
    );
  }

  Widget _buildBody(ColorScheme colorScheme, bool connected) {
    // Agent 活跃状态：按 agentState 分发
    if (_isAgentActive()) {
      return _buildAgentBody(colorScheme, connected);
    }

    // Planner 模式 / 降级模式：显示 turns + pending
    return _buildPlannerBody(colorScheme, connected);
  }

  bool _isAgentActive() {
    return _agentState == AgentPanelState.exploring ||
        _agentState == AgentPanelState.asking ||
        _agentState == AgentPanelState.result ||
        _agentState == AgentPanelState.error;
  }

  Widget _buildAgentBody(ColorScheme colorScheme, bool connected) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        // 用户意图气泡
        if (_agentIntent != null) ...[
          _buildUserBubble(_agentIntent!),
          const SizedBox(height: 8),
        ],

        switch (_agentState) {
          AgentPanelState.exploring => _buildExploringView(colorScheme),
          AgentPanelState.asking => _buildAskingView(colorScheme),
          AgentPanelState.result => _buildResultView(colorScheme, connected),
          AgentPanelState.error => _buildErrorView(colorScheme),
          _ => const SizedBox.shrink(),
        },
      ],
    );
  }

  /// Exploring：可折叠进度列表 + 加载指示
  Widget _buildExploringView(ColorScheme colorScheme) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (_traces.isNotEmpty)
          _buildAgentTraceExpansionTile(colorScheme),
        if (_traces.isNotEmpty) const SizedBox(height: 8),
        _buildLoadingBubble('Agent 正在分析...', colorScheme),
      ],
    );
  }

  /// 可折叠 Agent Trace 列表
  Widget _buildAgentTraceExpansionTile(ColorScheme colorScheme) {
    return Container(
      decoration: BoxDecoration(
        color: Colors.white.withValues(alpha: 0.82),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(
          color: colorScheme.outlineVariant.withValues(alpha: 0.14),
        ),
      ),
      child: ExpansionTile(
        key: const Key('agent-trace-expansion'),
        initiallyExpanded: false,
        tilePadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
        childrenPadding: const EdgeInsets.fromLTRB(12, 0, 12, 8),
        dense: true,
        title: Text(
          '探索进度 (${_traces.length})',
          style: Theme.of(context).textTheme.bodySmall?.copyWith(
                color: colorScheme.onSurfaceVariant,
                fontWeight: FontWeight.w600,
              ),
        ),
        children: [
          for (final trace in _traces) ...[
            _buildAgentTraceItem(trace, colorScheme),
            if (trace != _traces.last) const SizedBox(height: 6),
          ],
        ],
      ),
    );
  }

  /// 单个 Agent Trace 项
  Widget _buildAgentTraceItem(AgentTraceEvent trace, ColorScheme colorScheme) {
    return _buildAssistantBubble(
      Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              _SidePanelStagePill(stage: 'tool'),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  trace.tool,
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
            trace.inputSummary,
            style: Theme.of(context).textTheme.bodySmall?.copyWith(
                  color: colorScheme.onSurfaceVariant,
                  height: 1.4,
                ),
          ),
          if (trace.outputSummary.isNotEmpty) ...[
            const SizedBox(height: 2),
            Text(
              trace.outputSummary,
              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                    color: colorScheme.onSurfaceVariant.withValues(alpha: 0.7),
                    height: 1.3,
                  ),
                  maxLines: 3,
                  overflow: TextOverflow.ellipsis,
                ),
          ],
        ],
      ),
    );
  }

  /// Asking：助手气泡 + 选项 + 输入框
  Widget _buildAskingView(ColorScheme colorScheme) {
    final question = _currentQuestion;
    if (question == null) return const SizedBox.shrink();

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        // 问题气泡
        _buildAssistantBubble(
          Text(
            question.question,
            style: Theme.of(context).textTheme.bodyMedium,
          ),
        ),
        const SizedBox(height: 10),

        // 选项区域
        if (question.options.isNotEmpty) ...[
          if (question.multiSelect) ...[
            // multi_select: 复选框列表
            _buildMultiSelectOptions(question, colorScheme),
          ] else ...[
            // 单选: 选项按钮列表
            _buildSingleSelectOptions(question, colorScheme),
          ],
          const SizedBox(height: 8),
        ],
      ],
    );
  }

  /// 单选选项按钮
  Widget _buildSingleSelectOptions(
    AgentQuestionEvent question,
    ColorScheme colorScheme,
  ) {
    return Wrap(
      spacing: 6,
      runSpacing: 6,
      children: [
        for (final option in question.options)
          OutlinedButton(
            key: Key('agent-option-${option.hashCode}'),
            style: OutlinedButton.styleFrom(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(12),
              ),
              side: BorderSide(
                color: colorScheme.outlineVariant.withValues(alpha: 0.4),
              ),
              backgroundColor: Colors.white,
            ),
            onPressed: () => _handleAgentRespond(option),
            child: Text(
              option,
              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                    color: colorScheme.onSurface,
                  ),
            ),
          ),
      ],
    );
  }

  /// Multi-select 复选框列表
  Widget _buildMultiSelectOptions(
    AgentQuestionEvent question,
    ColorScheme colorScheme,
  ) {
    return Container(
      padding: const EdgeInsets.all(8),
      decoration: BoxDecoration(
        color: Colors.white.withValues(alpha: 0.82),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(
          color: colorScheme.outlineVariant.withValues(alpha: 0.14),
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          for (final option in question.options)
            _buildCheckboxOption(option, colorScheme),
          const SizedBox(height: 8),
          SizedBox(
            width: double.infinity,
            child: FilledButton(
              key: const Key('agent-multi-select-confirm'),
              style: FilledButton.styleFrom(
                minimumSize: const Size.fromHeight(36),
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(10),
                ),
                backgroundColor: const Color(0xFF1F5EFF),
              ),
              onPressed: _multiSelectChosen.isNotEmpty
                  ? () => _handleAgentRespond(
                        _multiSelectChosen.join(', '),
                      )
                  : null,
              child: const Text('确认选择'),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildCheckboxOption(String option, ColorScheme colorScheme) {
    final chosen = _multiSelectChosen.contains(option);
    return InkWell(
      onTap: () {
        setState(() {
          if (chosen) {
            _multiSelectChosen.remove(option);
          } else {
            _multiSelectChosen.add(option);
          }
        });
      },
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 4),
        child: Row(
          children: [
            SizedBox(
              width: 20,
              height: 20,
              child: Checkbox(
                value: chosen,
                onChanged: (v) {
                  setState(() {
                    if (v == true) {
                      _multiSelectChosen.add(option);
                    } else {
                      _multiSelectChosen.remove(option);
                    }
                  });
                },
              ),
            ),
            const SizedBox(width: 8),
            Expanded(
              child: Text(
                option,
                style: Theme.of(context).textTheme.bodySmall,
              ),
            ),
          ],
        ),
      ),
    );
  }

  /// Result：命令预览卡片 + 执行按钮
  Widget _buildResultView(ColorScheme colorScheme, bool connected) {
    final result = _agentResult;
    if (result == null) return const SizedBox.shrink();

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
          Row(
            children: [
              Icon(Icons.check_circle,
                  size: 16, color: colorScheme.primary),
              const SizedBox(width: 6),
              Expanded(
                child: Text(
                  result.summary,
                  style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                        fontWeight: FontWeight.w600,
                      ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          // 步骤列表
          for (final step in result.steps) ...[
            Container(
              margin: const EdgeInsets.only(bottom: 4),
              padding: const EdgeInsets.all(8),
              decoration: BoxDecoration(
                color: const Color(0xFFF5F7FA),
                borderRadius: BorderRadius.circular(8),
              ),
              child: Row(
                children: [
                  Text(
                    step.label,
                    style: Theme.of(context).textTheme.bodySmall?.copyWith(
                          fontWeight: FontWeight.w600,
                        ),
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      step.command,
                      style: Theme.of(context).textTheme.bodySmall?.copyWith(
                            fontFamily: 'monospace',
                            color: colorScheme.onSurfaceVariant,
                          ),
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                    ),
                  ),
                ],
              ),
            ),
          ],
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
              onPressed: connected && !_executing
                  ? _executeAgentResult
                  : null,
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

  /// Error：错误提示 + 重试/切换模式按钮
  Widget _buildErrorView(ColorScheme colorScheme) {
    final error = _agentError;
    final errorMsg =
        error?.message ?? '未知错误';

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _buildAssistantBubble(
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Icon(Icons.error_outline,
                  size: 16, color: colorScheme.error),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  errorMsg,
                  style: Theme.of(context).textTheme.bodySmall?.copyWith(
                        color: colorScheme.error,
                      ),
                ),
              ),
            ],
          ),
        ),
        const SizedBox(height: 10),
        Row(
          children: [
            Expanded(
              child: OutlinedButton(
                key: const Key('agent-retry'),
                style: OutlinedButton.styleFrom(
                  minimumSize: const Size.fromHeight(36),
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(10),
                  ),
                ),
                onPressed: _retryAgentSession,
                child: const Text('重试'),
              ),
            ),
            const SizedBox(width: 8),
            Expanded(
              child: FilledButton(
                key: const Key('agent-switch-fallback'),
                style: FilledButton.styleFrom(
                  minimumSize: const Size.fromHeight(36),
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(10),
                  ),
                  backgroundColor: const Color(0xFF1F5EFF),
                ),
                onPressed: _switchToFallbackMode,
                child: const Text('使用快速模式'),
              ),
            ),
          ],
        ),
      ],
    );
  }

  /// Planner 模式消息体（原始逻辑）
  Widget _buildPlannerBody(ColorScheme colorScheme, bool connected) {
    final hasPendingTurn = _pendingIntent != null;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (_turns.isEmpty && _pendingIntent == null && !_isFallbackMode)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 16, horizontal: 4),
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
    );
  }

  /// 底部输入栏
  Widget _buildInputBar(ColorScheme colorScheme) {
    final isAgentBusy = _agentState == AgentPanelState.exploring ||
        _agentState == AgentPanelState.asking;
    final canSend = !_executing && !_resolvingIntent && !isAgentBusy;

    return Container(
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
                    hintText: _agentState == AgentPanelState.asking
                        ? '输入回答...'
                        : '说目标，例如：进入日知项目',
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
                    if (_agentState == AgentPanelState.asking) {
                      final text = _intentController.text.trim();
                      if (text.isNotEmpty) {
                        _intentController.clear();
                        _handleAgentRespond(text);
                      }
                    } else if (canSend) {
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
              onPressed: canSend ? _handleResolveIntent : null,
              child: _resolvingIntent || isAgentBusy
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
