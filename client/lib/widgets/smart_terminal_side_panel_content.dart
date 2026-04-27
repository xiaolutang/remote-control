part of 'smart_terminal_side_panel.dart';

/// Agent 面板 Phase 驱动状态
enum AgentPhase {
  /// 空闲/初始状态
  idle,

  /// THINKING 阶段：正在思考
  thinking,

  /// EXPLORING 阶段：执行工具调用
  exploring,

  /// ANALYZING 阶段：分析结果
  analyzing,

  /// RESPONDING 阶段：流式文本输出
  responding,

  /// CONFIRMING 阶段：ask_user 等待确认
  confirming,

  /// RESULT 阶段：显示结果卡片
  result,

  /// 错误
  error,
}

/// 侧滑面板内部内容：会话消息流 + 意图输入框。
class _SmartTerminalSidePanelContent extends StatefulWidget {
  const _SmartTerminalSidePanelContent({
    required this.onClose,
    this.agentSessionServiceBuilder,
    this.usageSummaryServiceBuilder,
  });

  final VoidCallback onClose;
  final AgentSessionServiceFactory? agentSessionServiceBuilder;
  final UsageSummaryServiceFactory? usageSummaryServiceBuilder;

  @override
  State<_SmartTerminalSidePanelContent> createState() =>
      _SmartTerminalSidePanelContentState();
}

class _SmartTerminalSidePanelContentState
    extends State<_SmartTerminalSidePanelContent> with WidgetsBindingObserver {
  late final TextEditingController _intentController;
  late final FocusNode _intentFocusNode;
  late final ScrollController _scrollController;

  // --- 面板状态 ---
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
  bool _executing = false;

  // --- Agent SSE 模式状态 ---
  AgentPhase _currentPhase = AgentPhase.idle;
  String _phaseDescription = ''; // 当前 phase 的描述文字
  final List<AgentTraceEvent> _traces = [];
  final List<_TurnEventType> _turnEventOrder = [];
  final List<AgentAssistantMessageEvent> _assistantMessages = [];
  final StringBuffer _streamingTextBuffer = StringBuffer(); // F108: streaming text
  final List<ToolStepEvent> _toolSteps = []; // F108: tool step 列表
  AgentQuestionEvent? _currentQuestion;
  AgentResultEvent? _agentResult;
  AgentErrorEvent? _agentError;
  String? _activeSessionId;
  StreamSubscription<AgentSessionEvent>? _eventSubscription;
  StreamSubscription<AgentConversationEventItem>?
      _conversationStreamSubscription;
  final Set<String> _multiSelectChosen = {};
  String? _agentIntent; // 当前 Agent 正在处理的意图
  final List<_AgentHistoryEntry> _agentHistory = []; // Agent 对话历史
  final List<_AgentAnswerEntry> _agentAnswers = []; // 当前 Agent 轮次内的问答
  final List<AgentConversationEventItem> _serverConversationEvents = [];
  String? _agentConversationId;
  String? _loadedDeviceId;
  String? _loadedTerminalId;
  String? _loadedTerminalStatus;
  int _projectionLoadSerial = 0;
  int _nextConversationEventIndex = 0;
  bool _pendingReset = false; // F093: SSE 活跃时收到 conversation_reset 的待处理标记
  bool _terminalConversationClosed = false;
  String? _terminalClosedReason;

  // --- 内联编辑状态 ---
  int? _editingHistoryIndex; // 正在编辑的历史条目索引 (null=无, -1=当前活跃意图)
  int? _editingAnswerIndex; // 正在编辑的问答回答索引 (null=编辑意图)
  late final TextEditingController _editingController;

  // --- SSE 重连已下沉到 AgentSessionService.streamConversationResilient ---
  UsageSummaryData? _usageSummary;
  String? _usageSummaryDeviceId;
  String? _usageSummaryError;
  bool _usageSummaryLoading = false;
  bool _usageToastVisible = false;
  int _usageRefreshSerial = 0;
  Timer? _usageToastTimer;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _intentController = TextEditingController();
    _intentFocusNode = FocusNode();
    _intentFocusNode.addListener(_handleIntentFocusChanged);
    _scrollController = ScrollController();
    _editingController = TextEditingController();
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
    _usageToastTimer?.cancel();
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
  }

  @override
  void didChangeMetrics() {
    if (_intentFocusNode.hasFocus) {
      _scheduleScrollToLatest();
    }
  }

  void _handleIntentFocusChanged() {
    if (!mounted) return;
    setState(() {});
    if (_intentFocusNode.hasFocus) {
      _scheduleScrollToLatest();
    }
  }

  bool get _isConnected {
    try {
      final service = context.read<WebSocketService>();
      return service.status == ConnectionStatus.connected;
    } on ProviderNotFoundException {
      return false;
    }
  }

  AgentSessionService _agentSessionService(String serverUrl) {
    final builder = widget.agentSessionServiceBuilder;
    if (builder != null) {
      return builder(serverUrl);
    }
    return AgentSessionService(serverUrl: serverUrl);
  }

  UsageSummaryService _usageSummaryService(String serverUrl) {
    final builder = widget.usageSummaryServiceBuilder;
    if (builder != null) {
      return builder(serverUrl);
    }
    return UsageSummaryService(serverUrl: serverUrl);
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

  CommandSequenceDraft _defaultDraft() {
    return CommandSequenceDraft.fromLaunchPlan(const TerminalLaunchPlan(
      tool: TerminalLaunchTool.claudeCode,
      title: 'Claude',
      cwd: '~',
      command: '/bin/bash',
      entryStrategy: TerminalEntryStrategy.shellBootstrap,
      postCreateInput: '',
      source: TerminalLaunchPlanSource.recommended,
    ));
  }

  void _resetAgentRenderState({bool resetDraft = false}) {
    _currentPhase = AgentPhase.idle;
    _phaseDescription = '';
    _traces.clear();
    _turnEventOrder.clear();
    _assistantMessages.clear();
    _streamingTextBuffer.clear();
    _toolSteps.clear();
    _currentQuestion = null;
    _agentResult = null;
    _agentError = null;
    _activeSessionId = null;
    _multiSelectChosen.clear();
    _agentIntent = null;
    _agentAnswers.clear();
    if (resetDraft) {
      _draft = _defaultDraft();
    }
  }

  void _resetPanelStateForScopeChange() {
    _eventSubscription?.cancel();
    _eventSubscription = null;
    _conversationStreamSubscription?.cancel();
    _conversationStreamSubscription = null;

    _pendingReset = false; // F093: scope 切换时清除 pendingReset 标记
    _draft = _defaultDraft();
    _executing = false;

    _resetAgentRenderState();
    _agentHistory.clear();
    _serverConversationEvents.clear();
    _agentConversationId = null;
    _nextConversationEventIndex = 0;
    _terminalConversationClosed = false;
    _terminalClosedReason = null;

    _editingHistoryIndex = null;
    _editingController.clear();
  }

  void _markTerminalConversationClosed(String message) {
    _eventSubscription?.cancel();
    _eventSubscription = null;
    _conversationStreamSubscription?.cancel();
    _conversationStreamSubscription = null;
    _pendingReset = false; // F093: terminal 关闭时清除 pendingReset 标记
    _executing = false;
    _draft = _defaultDraft();
    _resetAgentRenderState();
    _agentHistory.clear();
    _serverConversationEvents.clear();
    _agentConversationId = null;
    _nextConversationEventIndex = 0;
    _terminalConversationClosed = true;
    _terminalClosedReason = message;
    _intentController.clear();
  }

  Future<void> _loadConversationProjection({
    required String? deviceId,
    required String? terminalId,
  }) async {
    final requestSerial = ++_projectionLoadSerial;

    if (deviceId == null ||
        deviceId.isEmpty ||
        terminalId == null ||
        terminalId.isEmpty) {
      if (!mounted || requestSerial != _projectionLoadSerial) return;
      setState(_resetPanelStateForScopeChange);
      return;
    }

    RuntimeSelectionController? controller;
    try {
      controller = context.read<RuntimeSelectionController>();
    } on ProviderNotFoundException {
      return;
    }

    final service = _agentSessionService(controller.serverUrl);

    try {
      final projection = await service.fetchConversation(
        deviceId: deviceId,
        terminalId: terminalId,
        token: controller.token,
      );
      if (!mounted || requestSerial != _projectionLoadSerial) return;

      setState(() {
        _resetPanelStateForScopeChange();
        _applyConversationProjection(projection);
      });
      _scheduleScrollToLatest();

      // 始终使用 conversation stream 接收事件，不 resume agent session。
      // 原因：agent session 的 event_queue 是单消费者模式，
      // 如果两端同时订阅同一个 session，事件会被随机分配给某一端，
      // 导致另一端丢失事件（如 error），卡在 exploring 状态无法输入。
      // conversation stream 通过 DB 轮询 + pub/sub 广播，
      // 所有订阅者都能收到完整事件集。
      _startConversationStream(
        controller: controller,
        deviceId: deviceId,
        terminalId: terminalId,
      );
    } on AgentSessionException catch (error) {
      if (!mounted || requestSerial != _projectionLoadSerial) return;
      setState(() {
        _resetPanelStateForScopeChange();
        if (error.code == 'closed_terminal' || error.statusCode == 410) {
          _markTerminalConversationClosed('当前 terminal 已关闭，智能对话已结束。');
          return;
        }
        _currentPhase = AgentPhase.error;
        _agentError = AgentErrorEvent(
          code: error.code ?? 'PROJECTION_LOAD_FAILED',
          message: error.message,
        );
      });
    }
  }

  void _applyConversationProjection(AgentConversationProjection projection) {
    final renderState = _deriveAgentRenderState(projection.events);
    _serverConversationEvents
      ..clear()
      ..addAll(projection.events);
    _agentConversationId = projection.conversationId;
    _nextConversationEventIndex = projection.nextEventIndex;
    _terminalConversationClosed = false;
    _terminalClosedReason = null;
    _currentPhase = renderState.state;
    _phaseDescription = renderState.phaseDescription;
    _agentHistory.addAll(renderState.history);
    _traces.addAll(renderState.traces);
    _turnEventOrder.addAll(renderState.turnEventOrder);
    _assistantMessages.addAll(renderState.assistantMessages);
    _currentQuestion = renderState.currentQuestion;
    _agentResult = renderState.result;
    _agentError = renderState.error;
    _activeSessionId = projection.activeSessionId;
    _agentIntent = renderState.intent;
    _agentAnswers.addAll(renderState.answers);
    _streamingTextBuffer.clear();
    _toolSteps.clear();
    if (_agentResult != null) {
      _draft = _buildDraftFromAgentResult(_agentResult!);
    }
  }

  void _applyConversationEventItem(AgentConversationEventItem event) {
    if (event.type == 'closed') {
      final reason =
          (event.payload['reason']?.toString() ?? 'terminal_closed').trim();
      _markTerminalConversationClosed('当前 terminal 已关闭，智能对话已结束。($reason)');
      return;
    }

    // 服务端截断/重置通知：其他端编辑/重发时，全量清空本地渲染状态
    // 后续到达的事件会通过 _deriveAgentRenderState 重建完整状态
    if (event.type == 'conversation_reset') {
      // SSE 活跃时：记录 pendingReset 标记，SSE 结束后在 onDone 中统一清空。
      // 如果在这里清空，SSE 正在构建的新状态会被全部清除，导致页面消失。
      if (_eventSubscription != null) {
        _pendingReset = true;
        return;
      }
      _serverConversationEvents.clear();
      _agentHistory.clear();
      _nextConversationEventIndex = 0;
      _resetAgentRenderState(resetDraft: true);
      return;
    }

    final existingIndex = _serverConversationEvents.indexWhere(
      (item) => item.eventId == event.eventId,
    );
    if (existingIndex >= 0) {
      _serverConversationEvents[existingIndex] = event;
    } else if (_serverConversationEvents.isEmpty ||
        event.eventIndex > _serverConversationEvents.last.eventIndex) {
      // 绝大多数情况：事件按序到达，直接追加
      _serverConversationEvents.add(event);
    } else {
      // 异常乱序：插入后排序
      _serverConversationEvents.add(event);
      _serverConversationEvents.sort(
        (left, right) => left.eventIndex.compareTo(right.eventIndex),
      );
    }
    if (event.eventIndex + 1 > _nextConversationEventIndex) {
      _nextConversationEventIndex = event.eventIndex + 1;
    }

    // SSE 会话活跃时：conversation stream 仅追加事件到 _serverConversationEvents，
    // 不重建 UI 状态。UI 状态由 SSE handler (_handleAgentEvent) 实时维护。
    // SSE 结束后 onDone 会触发最终同步。
    final sseActive = _eventSubscription != null;
    if (sseActive) {
      _terminalConversationClosed = false;
      _terminalClosedReason = null;
      return;
    }

    // 热路径优化：trace/assistant_message 事件直接增量追加，避免全量重算
    if (event.type == 'trace') {
      _traces.add(AgentTraceEvent.fromJson(
        Map<String, dynamic>.from(event.payload),
      ));
      _terminalConversationClosed = false;
      _terminalClosedReason = null;
      if (_currentPhase != AgentPhase.confirming) {
        _currentPhase = AgentPhase.exploring;
      }
      return;
    }
    if (event.type == 'assistant_message') {
      _assistantMessages.add(AgentAssistantMessageEvent.fromJson(
        Map<String, dynamic>.from(event.payload),
      ));
      _turnEventOrder.add(_TurnEventType.assistantMessage);
      _terminalConversationClosed = false;
      _terminalClosedReason = null;
      // 仅从 idle 转到 exploring；confirming 状态保持不变（等待用户回答）
      if (_currentPhase == AgentPhase.idle) {
        _currentPhase = AgentPhase.exploring;
      }
      return;
    }

    // 状态变更事件：全量重算保证一致性
    final renderState = _deriveAgentRenderState(_serverConversationEvents);
    _terminalConversationClosed = false;
    _terminalClosedReason = null;
    _currentPhase = renderState.state;
    _phaseDescription = renderState.phaseDescription;
    _agentHistory
      ..clear()
      ..addAll(renderState.history);
    _traces
      ..clear()
      ..addAll(renderState.traces);
    _turnEventOrder
      ..clear()
      ..addAll(renderState.turnEventOrder);
    _assistantMessages
      ..clear()
      ..addAll(renderState.assistantMessages);
    _currentQuestion = renderState.currentQuestion;
    _agentResult = renderState.result;
    _agentError = renderState.error;
    _agentIntent = renderState.intent;
    _agentAnswers
      ..clear()
      ..addAll(renderState.answers);
    // conversation stream 重建时恢复 _activeSessionId：
    // 当状态为 asking/exploring 时，agent 会话可能仍在服务端存活，
    // 从最近的事件中提取 sessionId 以便用户能继续回答。
    if (_activeSessionId == null &&
        (_currentPhase == AgentPhase.confirming ||
            _currentPhase == AgentPhase.exploring ||
            _currentPhase == AgentPhase.thinking ||
            _currentPhase == AgentPhase.analyzing)) {
      AgentConversationEventItem? eventWithSession;
      for (var i = _serverConversationEvents.length - 1; i >= 0; i--) {
        final e = _serverConversationEvents[i];
        if (e.sessionId != null && e.sessionId!.isNotEmpty) {
          eventWithSession = e;
          break;
        }
      }
      if (eventWithSession != null) {
        _activeSessionId = eventWithSession.sessionId;
      }
    }
    if (_agentResult != null) {
      _draft = _buildDraftFromAgentResult(_agentResult!);
    }
  }

  void _startConversationStream({
    required RuntimeSelectionController controller,
    required String deviceId,
    required String terminalId,
  }) {
    if (_terminalConversationClosed) {
      return;
    }
    _conversationStreamSubscription?.cancel();
    final service = _agentSessionService(controller.serverUrl);
    final afterIndex = _nextConversationEventIndex - 1;
    // 使用弹性流：重连策略由 AgentSessionService 管理，Widget 不承载恢复逻辑
    _conversationStreamSubscription = service
        .streamConversationResilient(
      deviceId: deviceId,
      terminalId: terminalId,
      token: controller.token,
      afterIndex: afterIndex,
    )
        .listen(
      (event) {
        if (!mounted) return;
        setState(() {
          _applyConversationEventItem(event);
        });
        _scheduleScrollToLatest();
      },
      onError: (Object error) {
        _conversationStreamSubscription = null;
      },
      onDone: () {
        _conversationStreamSubscription = null;
      },
    );
  }

  void _restartConversationStreamForCurrentScope() {
    RuntimeSelectionController? controller;
    try {
      controller = context.read<RuntimeSelectionController>();
    } on ProviderNotFoundException {
      return;
    }
    final deviceId = controller.selectedDeviceId;
    final terminalId = _currentTerminalId();
    if (deviceId == null ||
        deviceId.isEmpty ||
        terminalId == null ||
        terminalId.isEmpty) {
      return;
    }
    _startConversationStream(
      controller: controller,
      deviceId: deviceId,
      terminalId: terminalId,
    );
  }

  _AgentRenderState _deriveAgentRenderState(
    List<AgentConversationEventItem> events,
  ) {
    final history = <_AgentHistoryEntry>[];
    final traces = <AgentTraceEvent>[];
    final turnEventOrder = <_TurnEventType>[];
    final assistantMessages = <AgentAssistantMessageEvent>[];
    final answers = <_AgentAnswerEntry>[];
    String? activeIntent;
    String? lastQuestionText;
    AgentQuestionEvent? currentQuestion;
    AgentResultEvent? result;
    AgentErrorEvent? error;
    var state = AgentPhase.idle;
    var phaseDescription = '';

    void archiveCurrent({
      AgentResultEvent? archivedResult,
      AgentErrorEvent? archivedError,
    }) {
      final intent = activeIntent?.trim();
      if (intent == null || intent.isEmpty) {
        return;
      }
      history.add(_AgentHistoryEntry(
        intent: intent,
        traces: List.of(traces),
        turnEventOrder: List.of(turnEventOrder),
        assistantMessages: List.of(assistantMessages),
        answers: List.of(answers),
        result: archivedResult,
        error: archivedError,
      ));
      activeIntent = null;
      traces.clear();
      turnEventOrder.clear();
      assistantMessages.clear();
      answers.clear();
      currentQuestion = null;
      lastQuestionText = null;
    }

    for (final event in events) {
      switch (event.type) {
        case 'user_intent':
          archiveCurrent(archivedResult: result, archivedError: error);
          final text = (event.payload['text']?.toString() ?? '').trim();
          if (text.isEmpty) {
            state = AgentPhase.idle;
            break;
          }
          activeIntent = text;
          result = null;
          error = null;
          state = AgentPhase.thinking;
          phaseDescription = '正在分析你的意图...';

        case 'trace':
          traces.add(AgentTraceEvent.fromJson(Map<String, dynamic>.from(
            event.payload,
          )));
          result = null;
          error = null;
          state = AgentPhase.exploring;
          phaseDescription = '正在执行工具调用...';

        case 'assistant_message':
          assistantMessages.add(AgentAssistantMessageEvent.fromJson(
            Map<String, dynamic>.from(event.payload),
          ));
          turnEventOrder.add(_TurnEventType.assistantMessage);
          result = null;
          error = null;
          state = AgentPhase.responding;

        case 'question':
          currentQuestion = AgentQuestionEvent.fromJson({
            ...Map<String, dynamic>.from(event.payload),
            if (event.questionId != null) 'question_id': event.questionId,
          });
          lastQuestionText = currentQuestion?.question;
          result = null;
          error = null;
          state = AgentPhase.confirming;
          phaseDescription = currentQuestion?.question ?? '';

        case 'answer':
          final answer = (event.payload['text']?.toString() ?? '').trim();
          if (answer.isNotEmpty) {
            answers.add(_AgentAnswerEntry(
              question: lastQuestionText ?? '',
              answer: answer,
            ));
            turnEventOrder.add(_TurnEventType.answer);
          }
          currentQuestion = null;
          result = null;
          error = null;
          state = AgentPhase.exploring;
          phaseDescription = '正在执行工具调用...';

        case 'result':
          result = AgentResultEvent.fromJson(
            Map<String, dynamic>.from(event.payload),
          );
          error = null;
          state = AgentPhase.result;

        case 'error':
          error = AgentErrorEvent.fromJson(
            Map<String, dynamic>.from(event.payload),
          );
          result = null;
          state = AgentPhase.error;
      }
    }

    return _AgentRenderState(
      state: state,
      phaseDescription: phaseDescription,
      history: history,
      intent: activeIntent,
      traces: List.of(traces),
      turnEventOrder: List.of(turnEventOrder),
      assistantMessages: List.of(assistantMessages),
      answers: List.of(answers),
      currentQuestion: currentQuestion,
      result: result,
      error: error,
    );
  }

  // ============================================================
  // Intent 提交入口：Agent SSE 模式
  // ============================================================

  Future<void> _handleResolveIntent({
    String? overrideIntent,
    int? truncateAfterIndex,
  }) async {
    if (_terminalConversationClosed) return;
    final intent = (overrideIntent ?? _intentController.text).trim();
    if (intent.isEmpty) return;

    _intentController.clear();

    // 如果当前有未归档的 Agent 轮次，先归档（无论状态）
    if (_agentIntent != null && _agentIntent!.isNotEmpty) {
      _archiveAgentTurn(
        result: _agentResult,
        error: _agentError,
      );
    }

    RuntimeSelectionController? controller;
    try {
      controller = context.read<RuntimeSelectionController>();
    } on ProviderNotFoundException {
      _presentAgentError(
        code: 'MISSING_CONTROLLER',
        message: '当前页面状态异常，无法启动智能交互，请联系开发者',
        intent: intent,
      );
      return;
    }

    final deviceId = controller.selectedDeviceId;
    if (deviceId == null || deviceId.isEmpty) {
      _presentAgentError(
        code: 'DEVICE_NOT_SELECTED',
        message: '请先选择设备后再发起智能交互',
        intent: intent,
      );
      return;
    }

    _startAgentSession(
      intent: intent,
      controller: controller,
      truncateAfterIndex: truncateAfterIndex,
    );
  }

  // ============================================================
  // Agent SSE 会话
  // ============================================================

  Future<void> _startAgentSession({
    required String intent,
    required RuntimeSelectionController controller,
    int? truncateAfterIndex,
  }) async {
    final deviceId = controller.selectedDeviceId!;
    final terminalId = _currentTerminalId();
    if (terminalId == null || terminalId.isEmpty) {
      _presentAgentError(
        code: 'TERMINAL_NOT_READY',
        message: '请先进入一个 terminal，再发起智能交互',
        intent: intent,
      );
      return;
    }
    final token = controller.token;
    final serverUrl = controller.serverUrl;

    setState(() {
      _currentPhase = AgentPhase.thinking;
      _phaseDescription = '正在分析你的意图...';
      _traces.clear();
      _turnEventOrder.clear();
      _assistantMessages.clear();
      _streamingTextBuffer.clear();
      _toolSteps.clear();
      _currentQuestion = null;
      _agentResult = null;
      _agentError = null;
      _multiSelectChosen.clear();
      _agentAnswers.clear();
      _agentIntent = intent;
      _activeSessionId = null;
    });
    _scheduleScrollToLatest();

    final service = _agentSessionService(serverUrl);

    try {
      final eventStream = service.runSession(
        deviceId: deviceId,
        terminalId: terminalId,
        intent: intent,
        token: token,
        conversationId: _agentConversationId,
        truncateAfterIndex: truncateAfterIndex,
      );

      // 不取消 conversation stream：保持 _serverConversationEvents 实时更新，
      // 避免 SSE 结束后的 conversation stream 重启间隙导致事件丢失。
      // SSE 活跃期间，conversation stream 仅追加事件到 _serverConversationEvents，
      // 不重建 UI 状态（由 _applyConversationEventItem 的 _eventSubscriptionActive 检查控制）。
      _eventSubscription?.cancel();
      _eventSubscription = eventStream.listen(
        (event) {
          if (!mounted) return;
          _handleAgentEvent(event, controller: controller);
        },
        onError: (Object error) {
          if (!mounted) return;
          final message = error is AgentSessionException
              ? error.message
              : '智能交互启动失败，请联系开发者';
          _presentAgentError(
            code: error is AgentSessionException
                ? (error.code ?? 'AGENT_REQUEST_FAILED')
                : 'AGENT_REQUEST_FAILED',
            message: message,
            intent: intent,
          );
        },
        onDone: () {
          // SSE 流关闭时清理状态，防止卡在 exploring
          if (!mounted) return;
          // F093: SSE 结束时检查 pendingReset，如果有待处理的 conversation_reset 则完整重置状态
          final didReset = _pendingReset;
          if (didReset) {
            setState(() {
              _serverConversationEvents.clear();
              _agentHistory.clear();
              _nextConversationEventIndex = 0;
              _pendingReset = false;
              _resetAgentRenderState(resetDraft: true);
            });
          }
          // SSE 结束：清空 _eventSubscription 使 conversation stream 恢复完整重建能力。
          _eventSubscription = null;
          // F093: pendingReset 导致的关闭是预期行为，不报 STREAM_CLOSED 错误
          if ((_currentPhase == AgentPhase.exploring ||
                  _currentPhase == AgentPhase.thinking ||
                  _currentPhase == AgentPhase.analyzing ||
                  _currentPhase == AgentPhase.responding) &&
              !didReset) {
            setState(() {
              _currentPhase = AgentPhase.error;
              _agentError = const AgentErrorEvent(
                code: 'STREAM_CLOSED',
                message: 'Agent 会话意外关闭',
              );
            });
          }
          // F093: pendingReset 清空了 _nextConversationEventIndex = 0，需要重启 conversation stream
          // 以确保从服务端获取完整的最新投影（resilient stream 内部 currentIndex 不会自动回退）
          if (didReset) {
            _restartConversationStreamForCurrentScope();
          } else if (_conversationStreamSubscription == null) {
            // conversation stream 之前因错误断开，尝试重启以保持连接
            _restartConversationStreamForCurrentScope();
          }
        },
      );
    } catch (e) {
      if (!mounted) return;
      final message =
          e is AgentSessionException ? e.message : '智能交互启动失败，请联系开发者';
      _presentAgentError(
        code: e is AgentSessionException
            ? (e.code ?? 'AGENT_REQUEST_FAILED')
            : 'AGENT_REQUEST_FAILED',
        message: message,
        intent: intent,
      );
    }
  }

  String? _currentTerminalId() {
    try {
      final service = context.read<WebSocketService>();
      return service.terminalId;
    } on ProviderNotFoundException {
      return null;
    }
  }

  void _handleAgentEvent(
    AgentSessionEvent event, {
    required RuntimeSelectionController controller,
  }) {
    switch (event) {
      case AgentSessionCreatedEvent created:
        setState(() {
          _activeSessionId = created.sessionId;
          final conversationId = created.conversationId?.trim();
          if (conversationId != null && conversationId.isNotEmpty) {
            _agentConversationId = conversationId;
          }
        });

      // --- F108: Phase 驱动事件 ---
      case PhaseChangeEvent phaseChange:
        setState(() {
          final phaseName = phaseChange.phase.toUpperCase();
          _currentPhase = _phaseFromEvent(phaseName);
          if (phaseChange.description != null &&
              phaseChange.description!.isNotEmpty) {
            _phaseDescription = phaseChange.description!;
          } else {
            _phaseDescription = _defaultPhaseDescription(_currentPhase);
          }
        });
        _scheduleScrollToLatest();

      case StreamingTextEvent streamingText:
        setState(() {
          _streamingTextBuffer.write(streamingText.textDelta);
          // 如果还没到 responding 阶段，自动推进
          if (_currentPhase != AgentPhase.responding &&
              _currentPhase != AgentPhase.result &&
              _currentPhase != AgentPhase.error &&
              _currentPhase != AgentPhase.confirming) {
            _currentPhase = AgentPhase.responding;
            _phaseDescription = '正在生成回复...';
          }
        });
        _scheduleScrollToLatest();

      case ToolStepEvent toolStep:
        setState(() {
          _toolSteps.add(toolStep);
          // 如果还没进入 exploring 阶段，自动推进
          if (_currentPhase == AgentPhase.idle ||
              _currentPhase == AgentPhase.thinking) {
            _currentPhase = AgentPhase.exploring;
            _phaseDescription = '正在执行工具调用...';
          }
        });
        _scheduleScrollToLatest();

      // --- 旧事件兼容（保留功能不退化）---

      case AgentTraceEvent trace:
        setState(() {
          _traces.add(trace);
          // 保持 exploring 状态（或者从 confirming 回到 exploring）
          if (_currentPhase == AgentPhase.idle ||
              _currentPhase == AgentPhase.confirming) {
            _currentPhase = AgentPhase.exploring;
            _phaseDescription = '正在执行工具调用...';
          }
        });
        _scheduleScrollToLatest();

      case AgentAssistantMessageEvent assistantMsg:
        setState(() {
          _assistantMessages.add(assistantMsg);
          _turnEventOrder.add(_TurnEventType.assistantMessage);
          // 仅从 idle 转到 responding
          if (_currentPhase == AgentPhase.idle) {
            _currentPhase = AgentPhase.responding;
            _phaseDescription = '正在生成回复...';
          }
        });
        _scheduleScrollToLatest();

      case AgentQuestionEvent question:
        setState(() {
          _currentQuestion = question;
          _currentPhase = AgentPhase.confirming;
          _phaseDescription = question.question;
          _multiSelectChosen.clear();
        });
        _scheduleScrollToLatest();

      case AgentResultEvent result:
        setState(() {
          _agentResult = result;
          _currentPhase = AgentPhase.result;
          _activeSessionId = null;
          // 仅 command 类型构建 CommandSequenceDraft
          if (_isCommandResult(result)) {
            _draft = _buildDraftFromAgentResult(result);
          }
        });
        // conversation stream 常驻，无需重启。
        // 仅在它意外断开时尝试恢复。
        if (_conversationStreamSubscription == null) {
          _restartConversationStreamForCurrentScope();
        }
        unawaited(_refreshUsageSummary(controller: controller));
        _scheduleScrollToLatest();

      case AgentErrorEvent error:
        setState(() {
          _agentError = error;
          _currentPhase = AgentPhase.error;
          _activeSessionId = null;
        });
        // conversation stream 常驻，无需重启。
        if (_conversationStreamSubscription == null) {
          _restartConversationStreamForCurrentScope();
        }
        _scheduleScrollToLatest();
    }
  }

  /// 从 PhaseChangeEvent.phase 字符串映射到 AgentPhase
  static AgentPhase _phaseFromEvent(String phaseName) {
    return switch (phaseName) {
      'THINKING' => AgentPhase.thinking,
      'EXPLORING' || 'ACTING' => AgentPhase.exploring,
      'ANALYZING' => AgentPhase.analyzing,
      'RESPONDING' => AgentPhase.responding,
      'CONFIRMING' || 'ASK_USER' => AgentPhase.confirming,
      'RESULT' => AgentPhase.result,
      'ERROR' => AgentPhase.error,
      _ => AgentPhase.exploring, // 未知 phase 降级为 exploring
    };
  }

  /// 返回默认 phase 描述
  static String _defaultPhaseDescription(AgentPhase phase) {
    return switch (phase) {
      AgentPhase.idle => '',
      AgentPhase.thinking => '正在思考...',
      AgentPhase.exploring => '正在执行工具调用...',
      AgentPhase.analyzing => '正在分析结果...',
      AgentPhase.responding => '正在生成回复...',
      AgentPhase.confirming => '等待确认...',
      AgentPhase.result => '',
      AgentPhase.error => '',
    };
  }

  /// 归档当前 Agent 对话轮次到历史列表
  void _archiveAgentTurn({
    AgentResultEvent? result,
    AgentErrorEvent? error,
  }) {
    final intent = _agentIntent;
    if (intent == null || intent.isEmpty) return;
    _agentHistory.add(_AgentHistoryEntry(
      intent: intent,
      traces: List.of(_traces),
      turnEventOrder: List.of(_turnEventOrder),
      assistantMessages: List.of(_assistantMessages),
      answers: List.of(_agentAnswers),
      result: result,
      error: error,
    ));
    _agentIntent = null;
  }

  void _presentAgentError({
    required String code,
    required String message,
    String? intent,
  }) {
    if (!mounted) return;
    setState(() {
      _currentPhase = AgentPhase.error;
      _agentError = AgentErrorEvent(code: code, message: message);
      _activeSessionId = null;
      _currentQuestion = null;
      if (intent != null && intent.isNotEmpty) {
        _agentIntent = intent;
      }
    });
    _scheduleScrollToLatest();
  }

  /// 判断 responseType 是否为 command 类型（含未知值降级）
  bool _isCommandResult(AgentResultEvent result) {
    final rt = result.responseType;
    return rt != 'message' && rt != 'ai_prompt';
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
    if (_terminalConversationClosed) return;
    if (_pendingReset) return; // F093: reset 待处理时拒绝 stale session respond
    if (_activeSessionId == null) return;

    RuntimeSelectionController? controller;
    try {
      controller = context.read<RuntimeSelectionController>();
    } on ProviderNotFoundException {
      return;
    }

    final deviceId = controller.selectedDeviceId;
    if (deviceId == null) return;
    final terminalId = _currentTerminalId();
    if (terminalId == null || terminalId.isEmpty) return;
    final question = _currentQuestion;

    setState(() {
      if (question != null) {
        _agentAnswers.add(_AgentAnswerEntry(
          question: question.question,
          answer: answer,
        ));
        _turnEventOrder.add(_TurnEventType.answer);
      }
      _currentPhase = AgentPhase.exploring;
      _phaseDescription = '正在执行工具调用...';
      _currentQuestion = null;
    });

    try {
      final service = _agentSessionService(controller.serverUrl);
      await service.respond(
        deviceId: deviceId,
        terminalId: terminalId,
        sessionId: _activeSessionId!,
        answer: answer,
        token: controller.token,
        questionId: question?.questionId,
      );
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _agentError = AgentErrorEvent(
          code: 'RESPOND_FAILED',
          message: '回复失败：$e',
        );
        _currentPhase = AgentPhase.error;
      });
    }
  }

  void _handleInputSubmit() {
    if (_terminalConversationClosed) {
      return;
    }
    if (_pendingReset) return; // F093: reset 待处理时拒绝 stale 操作
    if (_currentPhase == AgentPhase.confirming) {
      final text = _intentController.text.trim();
      if (text.isEmpty) return;
      // 如果 sessionId 丢失，恢复输入文字并提示错误，避免静默丢弃
      if (_activeSessionId == null) {
        setState(() {
          _currentPhase = AgentPhase.error;
          _agentError = AgentErrorEvent(
            code: 'SESSION_LOST',
            message: '会话已断开，请重新发送您的问题',
          );
        });
        return;
      }
      _intentController.clear();
      setState(() {});
      _handleAgentRespond(text);
      return;
    }
    if (_executing ||
        _currentPhase == AgentPhase.exploring ||
        _currentPhase == AgentPhase.thinking ||
        _currentPhase == AgentPhase.analyzing ||
        _currentPhase == AgentPhase.responding) {
      return;
    }
    _handleResolveIntent();
  }

  /// 执行 Agent 结果（注入命令到终端），send 完成后再关闭面板（不变量 #61）
  Future<void> _executeAgentResult() async {
    if (_executing || !_isConnected) return;
    setState(() => _executing = true);

    final plan = _draft.toLaunchPlan();
    final input = plan.postCreateInput;
    var injectFailed = false;
    if (input.isNotEmpty) {
      try {
        final service = context.read<WebSocketService>();
        await service.send(input);
      } catch (e) {
        injectFailed = true;
        if (!mounted) return;
        setState(() {
          _currentPhase = AgentPhase.error;
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

  /// 注入 ai_prompt 文本到终端 stdin，send 完成后再归档（不变量 #61）
  Future<void> _injectAiPrompt() async {
    if (_executing || !_isConnected) return;
    final result = _agentResult;
    if (result == null || result.aiPrompt.isEmpty) return;

    setState(() => _executing = true);

    try {
      final service = context.read<WebSocketService>();
      await service.send('${result.aiPrompt}\r');
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _currentPhase = AgentPhase.error;
        _agentError = AgentErrorEvent(
          code: 'INJECT_FAILED',
          message: 'Prompt 注入失败：$e',
        );
      });
      return;
    }

    if (!mounted) return;
    // 归档当前轮次并回到 idle（send 完成后执行）
    _archiveAgentTurn(result: result);
    setState(() {
      _executing = false;
      _currentPhase = AgentPhase.idle;
      _phaseDescription = '';
      _agentResult = null;
      _traces.clear();
      _turnEventOrder.clear();
      _assistantMessages.clear();
      _streamingTextBuffer.clear();
      _toolSteps.clear();
      _agentAnswers.clear();
      _currentQuestion = null;
    });
  }


  /// 重试 Agent 会话
  void _retryAgentSession() {
    // F093: 先保存 intent，因为 _resetAgentRenderState 会清空 _agentIntent
    final savedIntent = _agentIntent;
    // F093: 如果有 pendingReset，需要完整清空旧投影，不能基于旧事件列表计算截断索引
    if (_pendingReset) {
      _serverConversationEvents.clear();
      _agentHistory.clear();
      _nextConversationEventIndex = 0;
      _resetAgentRenderState(resetDraft: true);
      _pendingReset = false;
    }
    if (savedIntent != null) {
      RuntimeSelectionController? controller;
      try {
        controller = context.read<RuntimeSelectionController>();
      } on ProviderNotFoundException {
        return;
      }
      // 截断当前失败轮次的事件，避免重试后在其他设备上产生重复消息。
      final truncateAfterIndex = _findTruncateAfterIndexForCurrentTurn();
      setState(() {
        _currentPhase = AgentPhase.idle;
        _phaseDescription = '';
        _agentError = null;
      });
      _startAgentSession(
        intent: savedIntent,
        controller: controller,
        truncateAfterIndex: truncateAfterIndex,
      );
    }
  }

  /// 找到当前轮次起始 user_intent 的前一个事件索引，用于截断。
  /// 如果当前轮次是第一条，返回 -1。
  int _findTruncateAfterIndexForCurrentTurn() {
    final cutPoint = _findUserIntentEventListIndex();
    if (cutPoint == null || cutPoint == 0) return -1;
    return _serverConversationEvents[cutPoint - 1].eventIndex;
  }

  int? _findUserIntentEventListIndex({int? historyIndex}) {
    if (historyIndex == null) {
      for (int i = _serverConversationEvents.length - 1; i >= 0; i--) {
        if (_serverConversationEvents[i].type == 'user_intent') {
          return i;
        }
      }
      return null;
    }

    int intentCount = 0;
    for (int i = 0; i < _serverConversationEvents.length; i++) {
      if (_serverConversationEvents[i].type != 'user_intent') {
        continue;
      }
      if (intentCount == historyIndex) {
        return i;
      }
      intentCount++;
    }
    return null;
  }

  // ============================================================
  // UI 构建
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
      child: Stack(
        children: [
          AnimatedPadding(
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
              ],
            ),
          ),
          if (_usageToastVisible)
            Positioned(
              left: 12,
              right: 12,
              top: 68,
              child: _buildUsageToast(colorScheme),
            ),
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
          TextButton(
            key: const Key('side-panel-usage-button'),
            style: TextButton.styleFrom(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
              minimumSize: const Size(0, 36),
              tapTargetSize: MaterialTapTargetSize.shrinkWrap,
              foregroundColor: colorScheme.primary,
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(10),
              ),
              backgroundColor: colorScheme.primaryContainer,
            ),
            onPressed: _handleUsageButtonTap,
            child: Text(
              'Token 汇总',
              style: Theme.of(context).textTheme.labelLarge?.copyWith(
                    fontWeight: FontWeight.w600,
                    color: colorScheme.primary,
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

  bool _isAgentActive() {
    return _currentPhase != AgentPhase.idle;
  }

  Widget _buildAgentBody(ColorScheme colorScheme, bool connected) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        // 历史对话
        for (var i = 0; i < _agentHistory.length; i++) ...[
          () {
            final entry = _agentHistory[i];
            return Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _buildUserBubble(
                  entry.intent,
                  historyIndex: i,
                  canEdit: true,
                ),
                const SizedBox(height: 8),
                ..._buildOrderedTurnEvents(
                  order: entry.turnEventOrder,
                  answers: entry.answers,
                  assistantMessages: entry.assistantMessages,
                  colorScheme: colorScheme,
                  historyIndex: i,
                ),
                if (entry.result != null)
                  _buildHistoryResultBubble(entry.result!, colorScheme)
                else if (entry.error != null)
                  _buildHistoryErrorBubble(entry.error!, colorScheme),
                const SizedBox(height: 12),
              ],
            );
          }(),
        ],

        // 当前活跃意图气泡
        if (_agentIntent != null) ...[
          _buildUserBubble(
            _agentIntent!,
            canEdit: !_isPhaseActive() && !_pendingReset,
          ),
          const SizedBox(height: 8),
          ..._buildOrderedTurnEvents(
            order: _turnEventOrder,
            answers: _agentAnswers,
            assistantMessages: _assistantMessages,
            colorScheme: colorScheme,
            isLive: true,
          ),
        ],

        // Phase 驱动渲染分发
        switch (_currentPhase) {
          AgentPhase.thinking ||
          AgentPhase.exploring ||
          AgentPhase.analyzing =>
            _buildProgressView(colorScheme),
          AgentPhase.responding => _buildRespondingView(colorScheme),
          AgentPhase.confirming => _buildAskingView(colorScheme),
          AgentPhase.result => _buildResultView(colorScheme, connected),
          AgentPhase.error => _buildErrorView(colorScheme),
          _ => const SizedBox.shrink(),
        },
      ],
    );
  }

  /// 判断当前 phase 是否为活跃执行阶段（不可编辑意图）
  bool _isPhaseActive() {
    return _currentPhase == AgentPhase.thinking ||
        _currentPhase == AgentPhase.exploring ||
        _currentPhase == AgentPhase.analyzing ||
        _currentPhase == AgentPhase.responding;
  }

  /// 按 turnEventOrder 交错渲染 answers 和 assistantMessages，保持原始事件顺序
  List<Widget> _buildOrderedTurnEvents({
    required List<_TurnEventType> order,
    required List<_AgentAnswerEntry> answers,
    required List<AgentAssistantMessageEvent> assistantMessages,
    required ColorScheme colorScheme,
    int? historyIndex,
    bool isLive = false,
  }) {
    if (order.isEmpty) return const [];
    final widgets = <Widget>[];
    var answerIdx = 0;
    var msgIdx = 0;
    for (final type in order) {
      switch (type) {
        case _TurnEventType.answer:
          if (answerIdx < answers.length) {
            widgets.add(_buildAssistantBubble(
              Text(
                answers[answerIdx].question,
                style: Theme.of(context).textTheme.bodySmall,
              ),
            ));
            widgets.add(const SizedBox(height: 4));
            widgets.add(_buildUserBubble(
              answers[answerIdx].answer,
              canEdit: true,
              historyIndex: historyIndex,
              answerIndex: answerIdx,
              isLiveAnswer: isLive,
            ));
            widgets.add(const SizedBox(height: 6));
            answerIdx++;
          }
        case _TurnEventType.assistantMessage:
          if (msgIdx < assistantMessages.length) {
            widgets.add(_buildAssistantBubble(
              Text(
                assistantMessages[msgIdx].content,
                style: Theme.of(context).textTheme.bodyMedium,
              ),
            ));
            widgets.add(const SizedBox(height: 6));
            msgIdx++;
          }
      }
    }
    return widgets;
  }

  /// 历史结果气泡（不可执行，仅展示摘要，按 responseType 分支渲染）
  Widget _buildHistoryResultBubble(
      AgentResultEvent result, ColorScheme colorScheme) {
    final rt = result.responseType;

    // message 类型：直接显示文本气泡
    if (rt == 'message') {
      return _buildAssistantBubble(
        Text(
          result.summary,
          style: Theme.of(context).textTheme.bodyMedium,
        ),
      );
    }

    // ai_prompt 类型：显示 prompt 预览
    if (rt == 'ai_prompt') {
      return _buildAssistantBubble(
        Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(Icons.smart_toy_outlined,
                    size: 14, color: colorScheme.primary),
                const SizedBox(width: 6),
                Expanded(
                  child: Text(
                    result.summary,
                    style: Theme.of(context).textTheme.bodySmall?.copyWith(
                          fontWeight: FontWeight.w600,
                        ),
                    maxLines: 3,
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
              ],
            ),
            if (result.aiPrompt.isNotEmpty) ...[
              const SizedBox(height: 4),
              Text(
                result.aiPrompt,
                style: Theme.of(context).textTheme.labelSmall?.copyWith(
                      fontFamily: 'monospace',
                      color: colorScheme.onSurfaceVariant,
                    ),
                maxLines: 3,
                overflow: TextOverflow.ellipsis,
              ),
            ],
          ],
        ),
      );
    }

    // command 或未知类型：原有渲染
    return _buildAssistantBubble(
      Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(Icons.check_circle_outline,
                  size: 14, color: colorScheme.primary),
              const SizedBox(width: 6),
              Expanded(
                child: Text(
                  result.summary,
                  style: Theme.of(context).textTheme.bodySmall?.copyWith(
                        fontWeight: FontWeight.w600,
                      ),
                  maxLines: 3,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
            ],
          ),
          if (result.steps.isNotEmpty) ...[
            const SizedBox(height: 4),
            Text(
              '${result.steps.length} 个步骤',
              style: Theme.of(context).textTheme.labelSmall?.copyWith(
                    color: colorScheme.onSurfaceVariant,
                  ),
            ),
          ],
        ],
      ),
    );
  }

  /// 历史错误气泡
  Widget _buildHistoryErrorBubble(
      AgentErrorEvent error, ColorScheme colorScheme) {
    return _buildAssistantBubble(
      Row(
        children: [
          Icon(Icons.error_outline, size: 14, color: colorScheme.error),
          const SizedBox(width: 6),
          Expanded(
            child: Text(
              error.message,
              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                    color: colorScheme.error,
                  ),
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
            ),
          ),
        ],
      ),
    );
  }

  /// THINKING/EXPLORING/ANALYZING 阶段：phase 描述 + tool step 列表 + 加载指示 + 取消按钮
  Widget _buildProgressView(ColorScheme colorScheme) {
    final phaseLabel = switch (_currentPhase) {
      AgentPhase.thinking => '思考中',
      AgentPhase.analyzing => '分析中',
      _ => '执行中',
    };

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        // F109: Phase 描述指示器（带图标）
        _buildPhaseDescriptionIndicator(colorScheme),
        const SizedBox(height: 10),
        // F109: 新版 tool step 卡片列表（直接平铺，不用折叠）
        if (_toolSteps.isNotEmpty)
          for (final step in _toolSteps) ...[
            _buildToolStepCard(step, colorScheme),
            const SizedBox(height: 6),
          ],
        // 兼容旧版 traces
        if (_traces.isNotEmpty && _toolSteps.isEmpty)
          _buildAgentTraceExpansionTile(colorScheme),
        if (_traces.isNotEmpty && _toolSteps.isEmpty) const SizedBox(height: 8),
        _buildLoadingBubble(
          _phaseDescription.isNotEmpty
              ? _phaseDescription
              : 'Agent 正在$phaseLabel...',
          colorScheme,
        ),
        const SizedBox(height: 10),
        Center(
          child: OutlinedButton(
            key: const Key('agent-cancel'),
            style: OutlinedButton.styleFrom(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(10),
              ),
              side: BorderSide(
                color: colorScheme.outlineVariant.withValues(alpha: 0.4),
              ),
            ),
            onPressed: _cancelAgentSession,
            child: Text(
              '取消',
              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                    color: colorScheme.onSurfaceVariant,
                  ),
            ),
          ),
        ),
      ],
    );
  }

  /// F109: Phase 描述指示器 — 带图标和动画的描述行
  Widget _buildPhaseDescriptionIndicator(ColorScheme colorScheme) {
    final description = _phaseDescription.isNotEmpty
        ? _phaseDescription
        : switch (_currentPhase) {
            AgentPhase.thinking => '正在思考...',
            AgentPhase.exploring => '正在探索环境...',
            AgentPhase.analyzing => '正在分析...',
            _ => '处理中...',
          };

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      decoration: BoxDecoration(
        color: colorScheme.surfaceContainerLow,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(
          color: colorScheme.outlineVariant.withValues(alpha: 0.14),
        ),
      ),
      child: Row(
        children: [
          SizedBox(
            width: 16,
            height: 16,
            child: CircularProgressIndicator(
              strokeWidth: 2,
              color: colorScheme.primary,
            ),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              description,
              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                    color: colorScheme.onSurfaceVariant,
                    fontWeight: FontWeight.w500,
                  ),
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
            ),
          ),
        ],
      ),
    );
  }

  /// RESPONDING 阶段：流式文本输出区域（打字机效果 + 闪烁光标）
  Widget _buildRespondingView(ColorScheme colorScheme) {
    final text = _streamingTextBuffer.toString();
    if (text.isEmpty) {
      return _buildLoadingBubble('正在生成回复...', colorScheme);
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        // F109: 助手头像 + 流式文本气泡
        Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // 助手图标
            Container(
              width: 28,
              height: 28,
              margin: const EdgeInsets.only(right: 8),
              decoration: BoxDecoration(
                color: colorScheme.primaryContainer,
                borderRadius: BorderRadius.circular(14),
              ),
              child: Icon(
                Icons.smart_toy_outlined,
                size: 16,
                color: colorScheme.onPrimaryContainer,
              ),
            ),
            // 文本气泡
            Expanded(
              child: Container(
                padding:
                    const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
                decoration: BoxDecoration(
                  color: colorScheme.surfaceContainerLow,
                  borderRadius: const BorderRadius.only(
                    topLeft: Radius.circular(18),
                    topRight: Radius.circular(18),
                    bottomLeft: Radius.circular(18),
                    bottomRight: Radius.circular(4),
                  ),
                  border: Border.all(
                    color:
                        colorScheme.outlineVariant.withValues(alpha: 0.15),
                  ),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    SelectableText(
                      text,
                      style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                            height: 1.5,
                          ),
                    ),
                    // F109: 流式文本末尾闪烁光标
                    if (_currentPhase == AgentPhase.responding)
                      Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          const SizedBox(width: 2),
                          _buildBlinkingCursor(colorScheme),
                        ],
                      ),
                  ],
                ),
              ),
            ),
          ],
        ),
        // F109: RESPONDING 阶段也展示已完成的工具步骤卡片
        if (_toolSteps.isNotEmpty) ...[
          const SizedBox(height: 10),
          for (final step in _toolSteps) ...[
            _buildToolStepCard(step, colorScheme),
            const SizedBox(height: 6),
          ],
        ],
      ],
    );
  }

  /// F109: 闪烁光标指示器（使用 AnimatedOpacity 实现持续闪烁）
  Widget _buildBlinkingCursor(ColorScheme colorScheme) {
    return _BlinkingCursor(colorScheme: colorScheme);
  }

  /// F109: 工具步骤卡片 — 紧凑卡片，带状态图标、description 和可展开的 result_summary
  Widget _buildToolStepCard(ToolStepEvent step, ColorScheme colorScheme) {
    return _ToolStepCard(step: step, colorScheme: colorScheme);
  }

  /// 取消当前 Agent 会话
  Future<void> _cancelAgentSession() async {
    await _doCancelAgentNetwork();

    if (!mounted) return;
    setState(() {
      // 归档取消的轮次到历史
      if (_agentIntent != null && _agentIntent!.isNotEmpty) {
        _agentHistory.add(_AgentHistoryEntry(
          intent: _agentIntent!,
          traces: List.of(_traces),
          turnEventOrder: List.of(_turnEventOrder),
          assistantMessages: List.of(_assistantMessages),
          answers: List.of(_agentAnswers),
          error: const AgentErrorEvent(
            code: 'CANCELLED',
            message: '已取消',
          ),
        ));
      }
      _currentPhase = AgentPhase.idle;
      _phaseDescription = '';
      _agentIntent = null;
      _activeSessionId = null;
    });
    _restartConversationStreamForCurrentScope();
  }

  /// 网络层取消 Agent 会话（取消订阅 + 发送 cancel 请求）
  Future<void> _doCancelAgentNetwork() async {
    _eventSubscription?.cancel();
    _eventSubscription = null;
    // F093: 先保存 sessionId，因为 _resetAgentRenderState 会清空 _activeSessionId
    final sessionId = _activeSessionId;
    // F093: 取消时如果有 pendingReset，需要同步清空本地投影状态
    // 因为 cancel 后重启 conversation stream 时不会重新获取已被截断的旧事件
    if (_pendingReset) {
      _serverConversationEvents.clear();
      _agentHistory.clear();
      _nextConversationEventIndex = 0;
      _resetAgentRenderState(resetDraft: true);
      _pendingReset = false;
    }
    if (sessionId == null) return;
    RuntimeSelectionController? controller;
    try {
      controller = context.read<RuntimeSelectionController>();
    } on ProviderNotFoundException {
      return;
    }
    final deviceId = controller.selectedDeviceId;
    if (deviceId == null) return;
    final terminalId = _currentTerminalId();
    if (terminalId == null || terminalId.isEmpty) return;
    try {
      final service = _agentSessionService(controller.serverUrl);
      await service.cancel(
        deviceId: deviceId,
        terminalId: terminalId,
        sessionId: sessionId,
        token: controller.token,
      );
    } catch (_) {
      // 取消失败不阻塞 UI
    }
  }

  /// 可折叠 Agent Trace 列表
  Widget _buildAgentTraceExpansionTile(ColorScheme colorScheme) {
    return Container(
      decoration: BoxDecoration(
        color: colorScheme.surfaceContainerLow,
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
              maxLines: 5,
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
              backgroundColor: colorScheme.surface,
            ),
            onPressed: _pendingReset ? null : () => _handleAgentRespond(option),
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
        color: colorScheme.surfaceContainerLow,
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
                backgroundColor: colorScheme.primary,
              ),
              onPressed: _multiSelectChosen.isNotEmpty && !_pendingReset
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
      onTap: _pendingReset ? null : () {
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
                onChanged: _pendingReset ? null : (v) {
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

  /// Result：根据 responseType 分支渲染
  Widget _buildResultView(ColorScheme colorScheme, bool connected) {
    final result = _agentResult;
    if (result == null) return const SizedBox.shrink();

    final rt = result.responseType;
    if (rt == 'message') {
      return _buildMessageResultView(result, colorScheme);
    }
    if (rt == 'ai_prompt') {
      return _buildAiPromptResultView(result, colorScheme, connected);
    }
    // command 或未知类型，降级为 command 渲染
    return _buildCommandResultView(result, colorScheme, connected);
  }

  /// message 类型：直接显示文本气泡
  Widget _buildMessageResultView(
      AgentResultEvent result, ColorScheme colorScheme) {
    return _buildAssistantBubble(
      Text(
        result.summary,
        style: Theme.of(context).textTheme.bodyMedium,
      ),
    );
  }

  /// ai_prompt 类型：prompt 预览卡片 + 注入终端按钮
  Widget _buildAiPromptResultView(
      AgentResultEvent result, ColorScheme colorScheme, bool connected) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: colorScheme.surfaceContainerLow,
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
              Icon(Icons.smart_toy_outlined, size: 16, color: colorScheme.primary),
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
          // Prompt 预览文本
          Container(
            width: double.infinity,
            padding: const EdgeInsets.all(10),
            decoration: BoxDecoration(
              color: colorScheme.surfaceContainerHighest,
              borderRadius: BorderRadius.circular(10),
              border: Border.all(
                color: colorScheme.outlineVariant.withValues(alpha: 0.2),
              ),
            ),
            child: Text(
              result.aiPrompt,
              key: const Key('side-panel-ai-prompt-preview'),
              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                    fontFamily: 'monospace',
                    color: colorScheme.onSurfaceVariant,
                  ),
              maxLines: 8,
              overflow: TextOverflow.ellipsis,
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
              key: const Key('side-panel-inject-prompt'),
              style: FilledButton.styleFrom(
                minimumSize: const Size.fromHeight(40),
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(12),
                ),
                backgroundColor: colorScheme.primary,
              ),
              onPressed: connected && !_executing ? _injectAiPrompt : null,
              child: _executing
                  ? SizedBox(
                      width: 16,
                      height: 16,
                      child: CircularProgressIndicator(
                        strokeWidth: 2,
                        color: colorScheme.onPrimary,
                      ),
                    )
                  : const Text('注入终端'),
            ),
          ),
        ],
      ),
    );
  }

  /// command 类型：命令预览卡片 + 执行按钮（保持原有逻辑）
  Widget _buildCommandResultView(
      AgentResultEvent result, ColorScheme colorScheme, bool connected) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: colorScheme.surfaceContainerLow,
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
              Icon(Icons.check_circle, size: 16, color: colorScheme.primary),
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
                color: colorScheme.surfaceContainerHighest,
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
                      maxLines: 3,
                      overflow: TextOverflow.ellipsis,
                    ),
                  ),
                ],
              ),
            ),
          ],
          if (!connected && result.steps.isNotEmpty) ...[
            const SizedBox(height: 6),
            Text(
              '终端未连接，请先确认连接状态。',
              style: TextStyle(color: colorScheme.error, fontSize: 12),
            ),
          ],
          if (result.steps.isNotEmpty) ...[
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
                  backgroundColor: colorScheme.primary,
                ),
                onPressed:
                    connected && !_executing ? _executeAgentResult : null,
                child: _executing
                    ? SizedBox(
                        width: 16,
                        height: 16,
                        child: CircularProgressIndicator(
                          strokeWidth: 2,
                          color: colorScheme.onPrimary,
                        ),
                      )
                    : const Text('执行'),
              ),
            ),
          ],
        ],
      ),
    );
  }

  Widget _buildUsageToast(ColorScheme colorScheme) {
    final summary = _usageSummary ?? const UsageSummaryData.empty();
    return Container(
      key: const Key('side-panel-usage-toast'),
      padding: const EdgeInsets.fromLTRB(14, 14, 14, 12),
      decoration: BoxDecoration(
        color: colorScheme.surface,
        borderRadius: BorderRadius.circular(18),
        border: Border.all(
          color: colorScheme.outlineVariant.withValues(alpha: 0.2),
        ),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withValues(alpha: 0.1),
            blurRadius: 18,
            offset: const Offset(0, 10),
          ),
        ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(
                Icons.data_usage_outlined,
                size: 18,
                color: colorScheme.primary,
              ),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  'Token 汇总',
                  style: Theme.of(context).textTheme.titleSmall?.copyWith(
                        fontWeight: FontWeight.w700,
                      ),
                ),
              ),
              if (_usageSummaryLoading)
                SizedBox(
                  width: 14,
                  height: 14,
                  child: CircularProgressIndicator(
                    strokeWidth: 2,
                    color: colorScheme.primary,
                  ),
                ),
            ],
          ),
          if (_usageSummaryError != null) ...[
            const SizedBox(height: 8),
            Container(
              key: const Key('side-panel-usage-error'),
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
              decoration: BoxDecoration(
                color: colorScheme.errorContainer,
                borderRadius: BorderRadius.circular(12),
              ),
              child: Text(
                _usageSummaryError!,
                style: Theme.of(context).textTheme.bodySmall?.copyWith(
                      color: colorScheme.onErrorContainer,
                    ),
              ),
            ),
          ],
          const SizedBox(height: 10),
          _buildUsageSummarySection(
            label: '当前终端',
            scope: summary.device,
            colorScheme: colorScheme,
          ),
          const SizedBox(height: 8),
          _buildUsageSummarySection(
            label: '我的总计',
            scope: summary.user,
            colorScheme: colorScheme,
          ),
        ],
      ),
    );
  }

  Widget _buildUsageSummarySection({
    required String label,
    required UsageSummaryScope scope,
    required ColorScheme colorScheme,
  }) {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: colorScheme.surfaceContainerHighest,
        borderRadius: BorderRadius.circular(14),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            label,
            style: Theme.of(context).textTheme.labelLarge?.copyWith(
                  fontWeight: FontWeight.w700,
                  color: colorScheme.onSurfaceVariant,
                ),
          ),
          const SizedBox(height: 8),
          Row(
            children: [
              Expanded(
                child: Text(
                  '${scope.totalTokens}',
                  style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                        fontWeight: FontWeight.w700,
                      ),
                ),
              ),
              Text(
                '${scope.totalRequests} 次请求',
                style: Theme.of(context).textTheme.bodySmall?.copyWith(
                      color: colorScheme.onSurfaceVariant,
                    ),
              ),
            ],
          ),
          const SizedBox(height: 4),
          Text(
            '输入 ${scope.totalInputTokens}  输出 ${scope.totalOutputTokens}  会话 ${scope.totalSessions}',
            style: Theme.of(context).textTheme.bodySmall?.copyWith(
                  color: colorScheme.onSurfaceVariant,
                ),
          ),
          const SizedBox(height: 2),
          Text(
            scope.latestModelName.isNotEmpty ? scope.latestModelName : '暂无模型数据',
            style: Theme.of(context).textTheme.bodySmall?.copyWith(
                  fontWeight: FontWeight.w600,
                  color: colorScheme.onSurfaceVariant,
                ),
          ),
        ],
      ),
    );
  }

  void _showUsageToast() {
    _usageToastTimer?.cancel();
    setState(() {
      _usageToastVisible = true;
    });
    _usageToastTimer = Timer(const Duration(seconds: 3), () {
      if (!mounted) return;
      setState(() {
        _usageToastVisible = false;
      });
    });
  }

  Future<void> _handleUsageButtonTap() async {
    _showUsageToast();
    RuntimeSelectionController? controller;
    try {
      controller = context.read<RuntimeSelectionController>();
    } on ProviderNotFoundException {
      return;
    }
    await _refreshUsageSummary(controller: controller);
  }

  Future<void> _refreshUsageSummary({
    required RuntimeSelectionController controller,
    bool forceRefresh = true,
  }) async {
    final deviceId = controller.selectedDeviceId;
    if (deviceId == null || deviceId.isEmpty) {
      if (!mounted) return;
      setState(() {
        _usageSummary = const UsageSummaryData.empty();
        _usageSummaryDeviceId = null;
        _usageSummaryError = '请先选择设备';
        _usageSummaryLoading = false;
      });
      return;
    }
    if (!forceRefresh &&
        _usageSummary != null &&
        _usageSummaryDeviceId == deviceId &&
        _usageSummaryError == null) {
      return;
    }
    final requestSerial = ++_usageRefreshSerial;
    setState(() {
      _usageSummaryLoading = true;
      if (_usageSummary == null || _usageSummaryDeviceId != deviceId) {
        _usageSummary = const UsageSummaryData.empty();
      }
    });
    try {
      final summary = await _usageSummaryService(controller.serverUrl)
          .fetchSummary(token: controller.token, deviceId: deviceId);
      if (!mounted || requestSerial != _usageRefreshSerial) {
        return;
      }
      setState(() {
        _usageSummary = summary;
        _usageSummaryDeviceId = deviceId;
        _usageSummaryError = null;
        _usageSummaryLoading = false;
      });
    } catch (_) {
      if (!mounted || requestSerial != _usageRefreshSerial) {
        return;
      }
      setState(() {
        _usageSummaryDeviceId = deviceId;
        _usageSummaryError = '统计暂不可用，稍后会自动重试';
        _usageSummaryLoading = false;
      });
    }
  }

  /// Error：错误提示 + 重试/切换模式按钮
  Widget _buildErrorView(ColorScheme colorScheme) {
    final error = _agentError;
    final errorMsg = error?.message ?? '未知错误';

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _buildAssistantBubble(
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Icon(Icons.error_outline, size: 16, color: colorScheme.error),
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
          ],
        ),
      ],
    );
  }

  /// 初始状态提示（Agent 未启动时的欢迎文本）
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

  /// 底部输入栏
  Widget _buildInputBar(ColorScheme colorScheme) {
    final isExploring = _isPhaseActive();
    final isAwaitingAnswer = _currentPhase == AgentPhase.confirming;
    final isClosed = _terminalConversationClosed;
    final canSend = !isClosed && !_pendingReset &&
        (isAwaitingAnswer
            ? !_executing
            : !_executing && !isExploring);

    return Container(
      padding: const EdgeInsets.fromLTRB(12, 8, 12, 14),
      decoration: BoxDecoration(
        color: colorScheme.surface,
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
                  enabled: !isClosed && !_pendingReset,
                  textInputAction: TextInputAction.send,
                  textAlignVertical: TextAlignVertical.center,
                  decoration: InputDecoration(
                    hintText: isClosed
                        ? 'terminal 已关闭，无法继续智能交互'
                        : _currentPhase == AgentPhase.confirming
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
                    _handleInputSubmit();
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
                backgroundColor: colorScheme.primary,
              ),
              onPressed: canSend ? _handleInputSubmit : null,
              child: isExploring
                  ? SizedBox(
                      width: 16,
                      height: 16,
                      child: CircularProgressIndicator(
                        strokeWidth: 2,
                        color: colorScheme.onPrimary,
                      ),
                    )
                  : const Icon(Icons.arrow_upward, size: 18),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildUserBubble(
    String text, {
    int? historyIndex, // null=当前活跃意图, >=0=历史条目索引
    bool canEdit = false,
    int? answerIndex, // null=意图, >=0=问答回答索引
    bool isLiveAnswer = false, // 是否是当前活跃轮次的问答
  }) {
    final colorScheme = Theme.of(context).colorScheme;
    // 判断是否处于内联编辑模式
    final isEditing = canEdit &&
        _editingHistoryIndex != null &&
        (isLiveAnswer
            ? _editingHistoryIndex == -1
            : _editingHistoryIndex == (historyIndex ?? -1)) &&
        _editingAnswerIndex == answerIndex;

    if (isEditing) {
      return _buildInlineEditBubble(text, historyIndex: historyIndex, colorScheme: colorScheme);
    }

    return Align(
      alignment: Alignment.centerRight,
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 280),
        child: GestureDetector(
          onTap: canEdit ? () => _startInlineEdit(historyIndex, answerIndex: answerIndex) : null,
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
            decoration: BoxDecoration(
              color: colorScheme.primaryContainer,
              borderRadius: const BorderRadius.only(
                topLeft: Radius.circular(18),
                topRight: Radius.circular(18),
                bottomLeft: Radius.circular(18),
                bottomRight: Radius.circular(4),
              ),
            ),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Flexible(
                  child:
                      Text(text, style: Theme.of(context).textTheme.bodyMedium),
                ),
                if (canEdit) ...[
                  const SizedBox(width: 6),
                  Icon(Icons.edit_outlined,
                      size: 14,
                      color: Theme.of(context)
                          .colorScheme
                          .onSurface
                          .withValues(alpha: 0.4)),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }

  /// 内联编辑气泡：直接在消息位置显示输入框 + 取消/发送按钮
  Widget _buildInlineEditBubble(String originalText, {int? historyIndex, required ColorScheme colorScheme}) {

    return Align(
      alignment: Alignment.centerRight,
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 280),
        child: Container(
          padding: const EdgeInsets.all(10),
          decoration: BoxDecoration(
            color: colorScheme.primaryContainer,
            borderRadius: const BorderRadius.only(
              topLeft: Radius.circular(18),
              topRight: Radius.circular(18),
              bottomLeft: Radius.circular(18),
              bottomRight: Radius.circular(4),
            ),
            border: Border.all(color: colorScheme.primary, width: 1.5),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.end,
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(
                controller: _editingController,
                enabled: !_pendingReset, // F093: reset 待处理时禁用编辑
                autofocus: true,
                maxLines: null,
                style: Theme.of(context).textTheme.bodyMedium,
                decoration: InputDecoration(
                  isDense: true,
                  contentPadding:
                      const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
                  border: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(8),
                    borderSide: BorderSide(color: colorScheme.outline),
                  ),
                  enabledBorder: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(8),
                    borderSide: BorderSide(color: colorScheme.outline),
                  ),
                  focusedBorder: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(8),
                    borderSide:
                        BorderSide(color: colorScheme.primary, width: 1.5),
                  ),
                  filled: true,
                  fillColor: colorScheme.surfaceContainerLow,
                ),
              ),
              const SizedBox(height: 8),
              Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  SizedBox(
                    height: 30,
                    child: TextButton(
                      onPressed: _cancelInlineEdit,
                      style: TextButton.styleFrom(
                        padding: const EdgeInsets.symmetric(horizontal: 12),
                        minimumSize: Size.zero,
                      ),
                      child: Text('取消',
                          style: TextStyle(
                              fontSize: 13,
                              color: colorScheme.onSurface
                                  .withValues(alpha: 0.6))),
                    ),
                  ),
                  const SizedBox(width: 4),
                  SizedBox(
                    height: 30,
                    child: FilledButton(
                      onPressed: _pendingReset ? null : () =>
                          _submitInlineEdit(historyIndex: historyIndex),
                      style: FilledButton.styleFrom(
                        padding: const EdgeInsets.symmetric(horizontal: 12),
                        minimumSize: Size.zero,
                      ),
                      child: const Text('发送', style: TextStyle(fontSize: 13)),
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }

  void _startInlineEdit(int? historyIndex, {int? answerIndex}) {
    if (_pendingReset) return; // F093: reset 待处理时禁止编辑
    // 获取对应的原始文本
    String originalText;
    if (answerIndex != null) {
      // 编辑问答回答
      if (historyIndex != null) {
        originalText = _agentHistory[historyIndex].answers[answerIndex].answer;
      } else {
        originalText = _agentAnswers[answerIndex].answer;
      }
    } else {
      // 编辑意图
      originalText = historyIndex != null
          ? _agentHistory[historyIndex].intent
          : _agentIntent ?? '';
    }
    setState(() {
      _editingHistoryIndex = historyIndex ?? -1;
      _editingAnswerIndex = answerIndex;
      _editingController.text = originalText;
    });
  }

  void _cancelInlineEdit() {
    setState(() {
      _editingHistoryIndex = null;
      _editingAnswerIndex = null;
      _editingController.clear();
    });
  }

  /// 同步 [_nextConversationEventIndex] 到截断后的最新状态。
  void _syncNextEventIndex() {
    _nextConversationEventIndex = _serverConversationEvents.isNotEmpty
        ? _serverConversationEvents.last.eventIndex + 1
        : 0;
  }

  /// 计算 _serverConversationEvents 最后一条事件的 eventIndex，用于服务端截断。
  /// 返回 -1 表示全部清空。
  int _computeTruncateAfter() => _serverConversationEvents.isNotEmpty
      ? _serverConversationEvents.last.eventIndex
      : -1;

  /// 截断 [_serverConversationEvents] 中指定意图索引之后的所有事件。
  ///
  /// [historyIndex] 对应第 N 个 `user_intent` 事件，null 表示截断最后一个轮次。
  void _truncateConversationEvents(int? historyIndex) {
    final cutPoint = _findUserIntentEventListIndex(
      historyIndex: historyIndex,
    );
    if (cutPoint == null) {
      // 找不到对应 user_intent：防御性清空，保持与服务端一致
      _serverConversationEvents.clear();
      _nextConversationEventIndex = 0;
      return;
    }
    _serverConversationEvents.removeRange(
      cutPoint,
      _serverConversationEvents.length,
    );
    _syncNextEventIndex();
  }

  Future<void> _submitInlineEdit({int? historyIndex}) async {
    if (_pendingReset) return; // F093: reset 待处理时禁止提交编辑
    final newText = _editingController.text.trim();
    if (newText.isEmpty) return;

    final editingAnswer = _editingAnswerIndex;
    setState(() {
      _editingHistoryIndex = null;
      _editingAnswerIndex = null;
      _editingController.clear();
    });

    if (editingAnswer != null) {
      // 编辑问答回答：截断该回答之后的内容，用新回答继续 Agent 会话
      await _submitAnswerEdit(
        historyIndex: historyIndex,
        answerIndex: editingAnswer,
        newAnswer: newText,
      );
    } else {
      // 编辑意图：原有逻辑
      await _submitIntentEdit(historyIndex: historyIndex, newText: newText);
    }
  }

  /// 编辑意图：截断 + 重新 run
  Future<void> _submitIntentEdit({int? historyIndex, required String newText}) async {
    await _cancelAgentSessionSilent();

    // 归档当前活跃轮次（如果还没归档），避免丢失
    final shouldArchiveCurrent = historyIndex == null &&
        _agentIntent != null &&
        _agentIntent!.isNotEmpty;
    if (shouldArchiveCurrent) {
      _archiveAgentTurn(
        result: _agentResult,
        error: _agentError,
      );
    }

    setState(() {
      // 截断编辑点之后的所有历史（包括当前活跃意图）
      if (historyIndex != null) {
        _agentHistory.removeRange(historyIndex, _agentHistory.length);
      }

      // 截断 _serverConversationEvents 中编辑点之后的事件
      _truncateConversationEvents(historyIndex);

      // 清除当前活跃会话状态
      _resetAgentRenderState();
    });

    await _handleResolveIntent(
      overrideIntent: newText,
      truncateAfterIndex: _computeTruncateAfter(),
    );
  }

  /// 编辑问答回答：截断该回答之后的内容 + 用新回答 continue Agent
  Future<void> _submitAnswerEdit({
    int? historyIndex,
    required int answerIndex,
    required String newAnswer,
  }) async {
    await _cancelAgentSessionSilent();

    // 确定要操作的 history entry
    final isLive = historyIndex == null;
    final entry = isLive ? null : _agentHistory[historyIndex!];

    // 保留到 answerIndex 之前的问答，删掉之后的问答 + result + 后续 traces
    // 对于服务端事件，需要找到该 answer 对应的 question 事件之后截断
    // 在截断前保存 intent，用于空事件场景回退
    final savedIntent = isLive ? _agentIntent : entry!.intent;
    setState(() {
      // 先截断服务端事件
      _truncateConversationEventsForAnswer(historyIndex, answerIndex);

      if (_serverConversationEvents.isNotEmpty) {
        // 从截断后的服务端事件重建本地状态，保持 assistantMessages 与服务端一致
        final renderState = _deriveAgentRenderState(_serverConversationEvents);
        _agentHistory
          ..clear()
          ..addAll(renderState.history);
        _currentPhase = AgentPhase.exploring;
        _phaseDescription = '正在执行工具调用...';
        _agentIntent = renderState.intent ?? savedIntent;
        _traces
          ..clear()
          ..addAll(renderState.traces);
        _turnEventOrder
          ..clear()
          ..addAll(renderState.turnEventOrder);
        _assistantMessages
          ..clear()
          ..addAll(renderState.assistantMessages);
        _agentAnswers
          ..clear()
          ..addAll(renderState.answers);
      } else {
        // 纯 SSE 场景：服务端事件为空，手动截断本地状态
        // 根据 _turnEventOrder 找到截断点，保留截断点之前的 answers 和 assistantMessages
        var answersSeen = 0;
        var truncateAt = _turnEventOrder.length;
        for (var i = 0; i < _turnEventOrder.length; i++) {
          if (_turnEventOrder[i] == _TurnEventType.answer) {
            if (answersSeen == answerIndex) {
              truncateAt = i;
              break;
            }
            answersSeen++;
          }
        }
        _turnEventOrder.removeRange(truncateAt, _turnEventOrder.length);
        // 从截断后的 order 重建各列表的保留计数
        var answerKeep = 0;
        var msgKeep = 0;
        for (final type in _turnEventOrder) {
          if (type == _TurnEventType.answer) {
            answerKeep++;
          } else if (type == _TurnEventType.assistantMessage) {
            msgKeep++;
          }
        }
        if (answerKeep < _agentAnswers.length) {
          _agentAnswers.removeRange(answerKeep, _agentAnswers.length);
        }
        if (msgKeep < _assistantMessages.length) {
          _assistantMessages.removeRange(msgKeep, _assistantMessages.length);
        }
        _currentPhase = AgentPhase.exploring;
        _phaseDescription = '正在执行工具调用...';
        _agentIntent = savedIntent;
        _traces.clear();
      }
      _currentQuestion = null;
      _agentResult = null;
      _agentError = null;
    });

    // 重新 run 该意图
    await _handleResolveIntent(
      overrideIntent: savedIntent!,
      truncateAfterIndex: _computeTruncateAfter(),
    );
  }

  /// 截断服务端事件到指定问答之前（保留到 answerIndex 前一个 question 的事件）
  void _truncateConversationEventsForAnswer(int? historyIndex, int answerIndex) {
    if (_serverConversationEvents.isEmpty) return;

    // 找到对应的 user_intent 起始位置
    final intentListIndex = _findUserIntentEventListIndex(historyIndex: historyIndex);
    if (intentListIndex == null) {
      _serverConversationEvents.clear();
      _syncNextEventIndex();
      return;
    }

    // 从 intent 之后开始数 answer 事件（type='answer'）
    int answerCount = 0;
    int cutPoint = _serverConversationEvents.length;
    for (int i = intentListIndex + 1; i < _serverConversationEvents.length; i++) {
      if (_serverConversationEvents[i].type == 'answer') {
        if (answerCount == answerIndex) {
          cutPoint = i;
          break;
        }
        answerCount++;
      }
    }

    _serverConversationEvents.removeRange(cutPoint, _serverConversationEvents.length);
    _syncNextEventIndex();
  }

  /// 静默取消当前 Agent 会话（不归档、不设状态）
  Future<void> _cancelAgentSessionSilent() => _doCancelAgentNetwork();

  Widget _buildAssistantBubble(Widget child) {
    final colorScheme = Theme.of(context).colorScheme;
    return Align(
      alignment: Alignment.centerLeft,
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 340),
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
          decoration: BoxDecoration(
            color: colorScheme.surfaceContainerLow,
            borderRadius: const BorderRadius.only(
              topLeft: Radius.circular(18),
              topRight: Radius.circular(18),
              bottomLeft: Radius.circular(4),
              bottomRight: Radius.circular(18),
            ),
            border: Border.all(
              color: colorScheme.outlineVariant.withValues(alpha: 0.15),
            ),
          ),
          child: child,
        ),
      ),
    );
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
}

// --- 内部模型 ---

/// Agent 对话历史条目
class _AgentHistoryEntry {
  const _AgentHistoryEntry({
    required this.intent,
    required this.traces,
    required this.turnEventOrder,
    this.assistantMessages = const [],
    this.answers = const [],
    this.result,
    this.error,
  });

  final String intent;
  final List<AgentTraceEvent> traces;
  final List<_TurnEventType> turnEventOrder;
  final List<AgentAssistantMessageEvent> assistantMessages;
  final List<_AgentAnswerEntry> answers;
  final AgentResultEvent? result;
  final AgentErrorEvent? error;
}

class _AgentAnswerEntry {
  const _AgentAnswerEntry({
    required this.question,
    required this.answer,
  });

  final String question;
  final String answer;
}

/// 轮次内事件类型标记，用于保持 answers/assistantMessages 的交错渲染顺序
enum _TurnEventType { answer, assistantMessage }

class _AgentRenderState {
  const _AgentRenderState({
    required this.state,
    required this.history,
    required this.traces,
    required this.turnEventOrder,
    required this.assistantMessages,
    required this.answers,
    this.phaseDescription = '',
    this.intent,
    this.currentQuestion,
    this.result,
    this.error,
  });

  final AgentPhase state;
  final String phaseDescription;
  final List<_AgentHistoryEntry> history;
  final String? intent;
  final List<AgentTraceEvent> traces;
  final List<_TurnEventType> turnEventOrder;
  final List<AgentAssistantMessageEvent> assistantMessages;
  final List<_AgentAnswerEntry> answers;
  final AgentQuestionEvent? currentQuestion;
  final AgentResultEvent? result;
  final AgentErrorEvent? error;
}

class _SidePanelStagePill extends StatelessWidget {
  const _SidePanelStagePill({required this.stage});

  final String stage;

  @override
  Widget build(BuildContext context) {
    final colorScheme = Theme.of(context).colorScheme;
    final (label, bg, fg) = switch (stage) {
      'tool' || 'tools' => ('工具', colorScheme.primaryContainer, colorScheme.primary),
      'context' => ('上下文', colorScheme.tertiaryContainer, colorScheme.tertiary),
      'plan' || 'planner' => ('思考', colorScheme.secondaryContainer, colorScheme.secondary),
      'running' => ('执行中', colorScheme.secondaryContainer, colorScheme.secondary),
      'done' => ('完成', colorScheme.primaryContainer, colorScheme.primary),
      'error' => ('错误', colorScheme.errorContainer, colorScheme.error),
      _ => ('处理', colorScheme.surfaceContainerHighest, colorScheme.onSurfaceVariant),
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

/// F109: 闪烁光标组件 — 持续循环闪烁，不依赖父 setState
class _BlinkingCursor extends StatefulWidget {
  const _BlinkingCursor({required this.colorScheme});

  final ColorScheme colorScheme;

  @override
  State<_BlinkingCursor> createState() => _BlinkingCursorState();
}

class _BlinkingCursorState extends State<_BlinkingCursor>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 800),
      lowerBound: 0.15,
      upperBound: 1.0,
    )..repeat(reverse: true);
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: _controller,
      builder: (context, child) {
        return Opacity(
          opacity: _controller.value,
          child: child,
        );
      },
      child: Container(
        width: 2,
        height: 14,
        decoration: BoxDecoration(
          color: widget.colorScheme.primary,
          borderRadius: BorderRadius.circular(1),
        ),
      ),
    );
  }
}

/// F109: 工具步骤卡片 — 带状态图标、description 和可展开 result_summary
class _ToolStepCard extends StatefulWidget {
  const _ToolStepCard({required this.step, required this.colorScheme});

  final ToolStepEvent step;
  final ColorScheme colorScheme;

  @override
  State<_ToolStepCard> createState() => _ToolStepCardState();
}

class _ToolStepCardState extends State<_ToolStepCard> {
  bool _expanded = false;

  @override
  Widget build(BuildContext context) {
    final step = widget.step;
    final colorScheme = widget.colorScheme;

    // 状态图标
    final Widget statusIcon = switch (step.status) {
      'running' => SizedBox(
          width: 14,
          height: 14,
          child: CircularProgressIndicator(
            strokeWidth: 2,
            color: colorScheme.primary,
          ),
        ),
      'done' => Icon(Icons.check_circle, size: 14, color: Colors.green),
      'error' => Icon(Icons.error, size: 14, color: colorScheme.error),
      _ => Icon(Icons.build_outlined, size: 14, color: colorScheme.onSurfaceVariant),
    };

    final hasResult = step.resultSummary != null && step.resultSummary!.isNotEmpty;

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
      decoration: BoxDecoration(
        color: colorScheme.surfaceContainerLow,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(
          color: colorScheme.outlineVariant.withValues(alpha: 0.12),
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // 第一行：状态图标 + 工具名 + 展开按钮
          Row(
            children: [
              statusIcon,
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  step.toolName,
                  style: Theme.of(context).textTheme.bodySmall?.copyWith(
                        fontWeight: FontWeight.w600,
                      ),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
              if (hasResult)
                GestureDetector(
                  onTap: () => setState(() => _expanded = !_expanded),
                  child: Icon(
                    _expanded
                        ? Icons.expand_less
                        : Icons.expand_more,
                    size: 16,
                    color: colorScheme.onSurfaceVariant,
                  ),
                ),
            ],
          ),
          // 第二行：description
          if (step.description.isNotEmpty) ...[
            const SizedBox(height: 4),
            Text(
              step.description,
              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                    color: colorScheme.onSurfaceVariant,
                    height: 1.4,
                  ),
              maxLines: 3,
              overflow: TextOverflow.ellipsis,
            ),
          ],
          // 第三行：可展开的 result_summary
          if (hasResult && _expanded) ...[
            const SizedBox(height: 6),
            Container(
              width: double.infinity,
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
              decoration: BoxDecoration(
                color: colorScheme.surfaceContainerHighest
                    .withValues(alpha: 0.5),
                borderRadius: BorderRadius.circular(6),
              ),
              child: Text(
                step.resultSummary!,
                style: Theme.of(context).textTheme.bodySmall?.copyWith(
                      color: colorScheme.onSurfaceVariant.withValues(alpha: 0.8),
                      height: 1.3,
                    ),
              ),
            ),
          ],
        ],
      ),
    );
  }
}
