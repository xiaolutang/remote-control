// ignore_for_file: deprecated_member_use_from_same_package

part of 'smart_terminal_side_panel.dart';

/// 侧滑面板内部内容：会话消息流 + 意图输入框。
class _SmartTerminalSidePanelContent extends StatefulWidget {
  const _SmartTerminalSidePanelContent({
    required this.onClose,
    this.agentSessionServiceBuilder,
    this.usageSummaryServiceBuilder,
    this.feedbackSubmitterOverride,
  });

  final VoidCallback onClose;
  final AgentSessionServiceFactory? agentSessionServiceBuilder;
  final UsageSummaryServiceFactory? usageSummaryServiceBuilder;
  final FeedbackSubmitter? feedbackSubmitterOverride;

  @override
  State<_SmartTerminalSidePanelContent> createState() =>
      _SmartTerminalSidePanelContentState();
}

class _SmartTerminalSidePanelContentState
    extends State<_SmartTerminalSidePanelContent>
    with
        WidgetsBindingObserver,
        ScrollToLatestMixin,
        _PanelStateFields,
        _PanelStateLogicMixin,
        _PanelHandlersMixin,
        _PanelConversationMixin,
        _PanelResultViewsMixin,
        _PanelInputMixin,
        _PanelWidgetsMixin {
  @override
  late final TextEditingController _intentController;
  @override
  late final FocusNode _intentFocusNode;
  @override
  late final ScrollController _scrollController;

  // --- 面板状态 ---
  @override
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
  @override
  bool _executing = false;

  // --- Agent SSE 模式状态 ---
  @override
  AgentPhase _currentPhase = AgentPhase.idle;
  @override
  String _phaseDescription = ''; // 当前 phase 的描述文字
  @override
  final List<AgentTraceEvent> _traces = [];
  @override
  final List<_TurnEventType> _turnEventOrder = [];
  @override
  final List<AgentAssistantMessageEvent> _assistantMessages = [];
  @override
  final StringBuffer _streamingTextBuffer = StringBuffer(); // F108: streaming text
  @override
  final List<ToolStepEvent> _toolSteps = []; // F108: tool step 列表
  @override
  AgentQuestionEvent? _currentQuestion;
  @override
  AgentResultEvent? _agentResult;
  @override
  AgentErrorEvent? _agentError;
  @override
  String? _activeSessionId;
  @override
  StreamSubscription<AgentSessionEvent>? _eventSubscription;
  @override
  StreamSubscription<AgentConversationEventItem>?
      _conversationStreamSubscription;
  @override
  final Set<String> _multiSelectChosen = {};
  @override
  String? _agentIntent; // 当前 Agent 正在处理的意图
  @override
  final List<_AgentHistoryEntry> _agentHistory = []; // Agent 对话历史
  @override
  final Set<int> _expandedHistorySet = {}; // F110: 展开的历史轮次索引
  @override
  final List<_AgentAnswerEntry> _agentAnswers = []; // 当前 Agent 轮次内的问答
  @override
  final List<AgentConversationEventItem> _serverConversationEvents = [];
  @override
  String? _agentConversationId;
  @override
  String? _loadedDeviceId;
  @override
  String? _loadedTerminalId;
  @override
  String? _loadedTerminalStatus;
  @override
  int _projectionLoadSerial = 0;
  @override
  int _nextConversationEventIndex = 0;
  @override
  bool _pendingReset = false; // F093: SSE 活跃时收到 conversation_reset 的待处理标记
  @override
  bool _terminalConversationClosed = false;
  @override
  String? _terminalClosedReason;

  // --- 内联编辑状态 ---
  @override
  int? _editingHistoryIndex; // 正在编辑的历史条目索引 (null=无, -1=当前活跃意图)
  @override
  int? _editingAnswerIndex; // 正在编辑的问答回答索引 (null=编辑意图)
  @override
  late final TextEditingController _editingController;

  // --- SSE 重连已下沉到 AgentSessionService.streamConversationResilient ---
  @override
  UsageSummaryData? _usageSummary;
  @override
  String? _usageSummaryDeviceId;
  @override
  String? _usageSummaryError;
  @override
  bool _usageSummaryLoading = false;
  @override
  bool _usageExpanded = false;
  @override
  int _usageRefreshSerial = 0;
  @override
  final SessionUsageAccumulator _sessionUsageAccumulator = SessionUsageAccumulator();
  @override
  Map<String, String> _feedbackStatus = {}; // event_id/error_key -> feedback_type
  @override
  String? _feedbackSubmittingKey;
  @override
  String? _feedbackErrorKey;
  @override
  late Future<bool> Function({
    required String serverUrl,
    required String token,
    required String terminalId,
    String? resultEventId,
    required String feedbackType,
    String? description,
  }) _feedbackSubmitter;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _intentController = TextEditingController();
    _intentFocusNode = FocusNode();
    _intentFocusNode.addListener(_handleIntentFocusChanged);
    _scrollController = ScrollController();
    _editingController = TextEditingController();
    _feedbackSubmitter = widget.feedbackSubmitterOverride ?? _defaultFeedbackSubmitter;
  }

  /// 默认反馈提交实现（真实 HTTP 请求）
  Future<bool> _defaultFeedbackSubmitter({
    required String serverUrl,
    required String token,
    required String terminalId,
    String? resultEventId,
    required String feedbackType,
    String? description,
  }) async {
    final httpUrl = serverUrlToHttpBase(serverUrl);
    final payload = <String, dynamic>{
      'session_id': '',
      'category': 'other',
      'description': description ?? feedbackType,
      'terminal_id': terminalId,
      'feedback_type': feedbackType,
    };
    if (resultEventId != null) {
      payload['result_event_id'] = resultEventId;
    }
    try {
      final client = HttpClientFactory.create();
      final response = await client.post(
        Uri.parse('$httpUrl/api/feedback'),
        headers: {
          'Content-Type': 'application/json',
          'Authorization': 'Bearer $token',
        },
        body: jsonEncode(payload),
      );
      return response.statusCode == 200;
    } catch (_) {
      return false;
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _eventSubscription?.cancel();
    _conversationStreamSubscription?.cancel();
    _intentFocusNode.removeListener(_handleIntentFocusChanged);
    _intentController.dispose();
    _intentFocusNode.dispose();
    _scrollController.dispose();
    _editingController.dispose();
    super.dispose();
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final controller = Provider.of<RuntimeSelectionController?>(context);
    final service = Provider.of<WebSocketService?>(context);
    final deviceId = controller?.selectedDeviceId;
    final terminalId = service?.terminalId;
    final terminalStatus = service?.terminalStatus;
    if (terminalStatus == 'closed' && terminalStatus != _loadedTerminalStatus) {
      _loadedTerminalStatus = terminalStatus;
      if (mounted) {
        setState(() {
          _markTerminalConversationClosed('当前 terminal 已关闭，智能对话已结束。');
        });
      }
      return;
    }
    if (deviceId == _loadedDeviceId &&
        terminalId == _loadedTerminalId &&
        terminalStatus == _loadedTerminalStatus) {
      return;
    }
    _loadedDeviceId = deviceId;
    _loadedTerminalId = terminalId;
    _loadedTerminalStatus = terminalStatus;
    unawaited(
      _loadConversationProjection(
        deviceId: deviceId,
        terminalId: terminalId,
      ),
    );
    // Auto-refresh usage summary when scope changes
    if (deviceId != null && deviceId.isNotEmpty) {
      try {
        final controller = context.read<RuntimeSelectionController>();
        unawaited(_refreshUsageSummary(
            controller: controller,
            forceRefresh: false,
            terminalId: terminalId));
      } on ProviderNotFoundException {
        // ignore
      }
    }
  }

  @override
  void didChangeMetrics() {
    if (_intentFocusNode.hasFocus) {
      _scheduleScrollToLatest();
    }
  }

  @override
  bool get _isConnected {
    try {
      final service = context.read<WebSocketService>();
      return service.status == ConnectionStatus.connected;
    } on ProviderNotFoundException {
      return false;
    }
  }

  @override
  bool _isAgentActive() {
    return _currentPhase != AgentPhase.idle;
  }

  @override
  bool _isPhaseActive() {
    return _currentPhase == AgentPhase.thinking ||
        _currentPhase == AgentPhase.exploring ||
        _currentPhase == AgentPhase.analyzing ||
        _currentPhase == AgentPhase.responding;
  }

  // ============================================================
  // UI 构建 — 主 build() 框架 + 布局编排
  // ============================================================

  @override
  Widget build(BuildContext context) {
    final colorScheme = Theme.of(context).colorScheme;
    final connected = _isConnected;
    final compactLayout = MediaQuery.sizeOf(context).width < 600;
    final keyboardInset = compactLayout && _intentFocusNode.hasFocus
        ? resolveMobileBottomInset(MediaQuery.of(context), keyboardOnly: true)
        : 0.0;

    return Container(
      decoration: BoxDecoration(
        color: colorScheme.surface,
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
      child: AnimatedPadding(
            duration: const Duration(milliseconds: 220),
            curve: Curves.easeOutCubic,
            padding: EdgeInsets.only(bottom: keyboardInset),
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

                // 底部 usage 区域
                if (!_terminalConversationClosed)
                  Padding(
                    padding: const EdgeInsets.fromLTRB(12, 4, 12, 8),
                    child: _buildUsageSection(colorScheme),
                  ),
              ],
            ),
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
          if (_terminalConversationClosed)
            Container(
              margin: const EdgeInsets.only(right: 8),
              padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
              decoration: BoxDecoration(
                color: colorScheme.errorContainer,
                borderRadius: BorderRadius.circular(999),
              ),
              child: Text(
                '已关闭',
                style: Theme.of(context).textTheme.labelSmall?.copyWith(
                      color: colorScheme.onErrorContainer,
                      fontWeight: FontWeight.w600,
                      fontSize: 10,
                    ),
              ),
            ),
          const SizedBox(width: 4),
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
    if (_terminalConversationClosed) {
      return _buildClosedView(colorScheme);
    }
    // Agent 模式（活跃或已归档历史）：按 agentState 分发
    if (_isAgentActive() || _agentHistory.isNotEmpty) {
      return _buildAgentBody(colorScheme, connected);
    }

    // 初始状态（Agent 未启动）：显示欢迎提示
    return _buildIdleHint(colorScheme);
  }

  Widget _buildClosedView(ColorScheme colorScheme) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _buildAssistantBubble(
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Icon(Icons.lock_clock_outlined,
                  size: 16, color: colorScheme.error),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  _terminalClosedReason ?? '当前 terminal 已关闭，智能对话已结束。',
                  key: const Key('side-panel-terminal-closed-message'),
                  style: Theme.of(context).textTheme.bodySmall?.copyWith(
                        color: colorScheme.error,
                      ),
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }

  Widget _buildIdleHint(ColorScheme colorScheme) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 16, horizontal: 4),
      child: Text(
        '直接说目标，我会生成命令，确认后再执行。',
        style: Theme.of(context).textTheme.bodySmall?.copyWith(
              color: colorScheme.onSurfaceVariant.withValues(alpha: 0.82),
            ),
      ),
    );
  }
}
