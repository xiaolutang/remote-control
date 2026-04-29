// ignore_for_file: annotate_overrides, deprecated_member_use_from_same_package, unused_element

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

// --- 内部模型 ---

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
  const _AgentAnswerEntry({required this.question, required this.answer});
  final String question;
  final String answer;
}

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

/// 面板 mixin 共享字段声明
mixin _PanelStateFields on State<_SmartTerminalSidePanelContent> {
  TextEditingController get _intentController;
  FocusNode get _intentFocusNode;
  ScrollController get _scrollController;
  TextEditingController get _editingController;
  CommandSequenceDraft get _draft;
  set _draft(CommandSequenceDraft v);
  bool get _executing;
  set _executing(bool v);
  AgentPhase get _currentPhase;
  set _currentPhase(AgentPhase v);
  String get _phaseDescription;
  set _phaseDescription(String v);
  List<AgentTraceEvent> get _traces;
  List<_TurnEventType> get _turnEventOrder;
  List<AgentAssistantMessageEvent> get _assistantMessages;
  StringBuffer get _streamingTextBuffer;
  List<ToolStepEvent> get _toolSteps;
  AgentQuestionEvent? get _currentQuestion;
  set _currentQuestion(AgentQuestionEvent? v);
  AgentResultEvent? get _agentResult;
  set _agentResult(AgentResultEvent? v);
  AgentErrorEvent? get _agentError;
  set _agentError(AgentErrorEvent? v);
  String? get _activeSessionId;
  set _activeSessionId(String? v);
  StreamSubscription<AgentSessionEvent>? get _eventSubscription;
  set _eventSubscription(StreamSubscription<AgentSessionEvent>? v);
  StreamSubscription<AgentConversationEventItem>? get _conversationStreamSubscription;
  set _conversationStreamSubscription(StreamSubscription<AgentConversationEventItem>? v);
  Set<String> get _multiSelectChosen;
  String? get _agentIntent;
  set _agentIntent(String? v);
  List<_AgentHistoryEntry> get _agentHistory;
  Set<int> get _expandedHistorySet;
  List<_AgentAnswerEntry> get _agentAnswers;
  List<AgentConversationEventItem> get _serverConversationEvents;
  String? get _agentConversationId;
  set _agentConversationId(String? v);
  String? get _loadedDeviceId;
  set _loadedDeviceId(String? v);
  String? get _loadedTerminalId;
  set _loadedTerminalId(String? v);
  String? get _loadedTerminalStatus;
  set _loadedTerminalStatus(String? v);
  int get _projectionLoadSerial;
  set _projectionLoadSerial(int v);
  int get _nextConversationEventIndex;
  set _nextConversationEventIndex(int v);
  bool get _pendingReset;
  set _pendingReset(bool v);
  bool get _terminalConversationClosed;
  set _terminalConversationClosed(bool v);
  String? get _terminalClosedReason;
  set _terminalClosedReason(String? v);
  int? get _editingHistoryIndex;
  set _editingHistoryIndex(int? v);
  int? get _editingAnswerIndex;
  set _editingAnswerIndex(int? v);
  UsageSummaryData? get _usageSummary;
  set _usageSummary(UsageSummaryData? v);
  String? get _usageSummaryDeviceId;
  set _usageSummaryDeviceId(String? v);
  String? get _usageSummaryError;
  set _usageSummaryError(String? v);
  bool get _usageSummaryLoading;
  set _usageSummaryLoading(bool v);
  bool get _usageExpanded;
  set _usageExpanded(bool v);
  int get _usageRefreshSerial;
  set _usageRefreshSerial(int v);
  SessionUsageAccumulator get _sessionUsageAccumulator;
  Map<String, String> get _feedbackStatus; // key: event_id or error key, value: feedback_type
  set _feedbackStatus(Map<String, String> v);
  String? get _feedbackSubmittingKey;
  set _feedbackSubmittingKey(String? v);
  String? get _feedbackErrorKey;
  set _feedbackErrorKey(String? v);

  // --- cross-mixin method stubs for feedback ---
  Future<bool> Function({
    required String serverUrl,
    required String token,
    required String terminalId,
    String? resultEventId,
    required String feedbackType,
    String? description,
  }) get _feedbackSubmitter;
  set _feedbackSubmitter(Future<bool> Function({
    required String serverUrl,
    required String token,
    required String terminalId,
    String? resultEventId,
    required String feedbackType,
    String? description,
  }) v);

  Future<bool> _submitFeedback({
    required String feedbackKey,
    required String feedbackType,
    String? resultEventId,
    String? description,
  });

  // --- derived getters (implemented in State class) ---
  bool get _isConnected;
  bool _isAgentActive();
  bool _isPhaseActive();

  // --- cross-mixin method stubs (implemented in functional mixins) ---

  // _PanelStateLogicMixin
  CommandSequenceDraft _defaultDraft();
  void _resetAgentRenderState({bool resetDraft = false});
  void _resetPanelStateForScopeChange();
  void _markTerminalConversationClosed(String message);
  void _applyConversationProjection(AgentConversationProjection projection);
  void _applyConversationEventItem(AgentConversationEventItem event);
  _AgentRenderState _deriveAgentRenderState(List<AgentConversationEventItem> events);
  CommandSequenceDraft _buildDraftFromAgentResult(AgentResultEvent result);
  bool _isCommandResult(AgentResultEvent result);

  // _PanelHandlersMixin
  AgentSessionService _agentSessionService(String serverUrl);
  UsageSummaryService _usageSummaryService(String serverUrl);
  void _scheduleScrollToLatest();
  String? _currentTerminalId();
  Future<void> _loadConversationProjection({required String? deviceId, required String? terminalId});
  void _startConversationStream({required RuntimeSelectionController controller, required String deviceId, required String terminalId});
  void _restartConversationStreamForCurrentScope();
  Future<void> _handleResolveIntent({String? overrideIntent, int? truncateAfterIndex});
  Future<void> _startAgentSession({required String intent, required RuntimeSelectionController controller, int? truncateAfterIndex});
  void _archiveAgentTurn({AgentResultEvent? result, AgentErrorEvent? error});
  void _presentAgentError({required String code, required String message, String? intent});
  Future<void> _handleAgentRespond(String answer);
  void _handleInputSubmit();
  Future<void> _executeAgentResult();
  Future<void> _injectAiPrompt();
  void _retryAgentSession();
  Future<void> _cancelAgentSession();
  Future<void> _cancelAgentSessionSilent();
  void _startInlineEdit(int? historyIndex, {int? answerIndex});
  void _cancelInlineEdit();
  Future<void> _submitInlineEdit({int? historyIndex});

  // _PanelWidgetsMixin
  Widget _buildAssistantBubble(Widget child);
  Widget _buildLoadingBubble(String text, ColorScheme colorScheme);
  Widget _buildBlinkingCursor(ColorScheme colorScheme);
  Widget _buildToolStepCard(ToolStepEvent step, ColorScheme colorScheme);
  Widget _buildAgentTraceExpansionTile(ColorScheme colorScheme);
  Widget _buildAgentTraceItem(AgentTraceEvent trace, ColorScheme colorScheme);
  Widget _buildUsageSection(ColorScheme colorScheme);

  // _PanelResultViewsMixin
  Widget _buildProgressView(ColorScheme colorScheme);
  Widget _buildRespondingView(ColorScheme colorScheme);
  Widget _buildResultView(ColorScheme colorScheme, bool connected);
  Widget _buildErrorView(ColorScheme colorScheme);
  Future<void> _refreshUsageSummary({required RuntimeSelectionController controller, bool forceRefresh = true, String? terminalId});

  // _PanelInputMixin
  Widget _buildInputBar(ColorScheme colorScheme);
  Widget _buildAskingView(ColorScheme colorScheme);
  Widget _buildUserBubble(String text, {int? historyIndex, bool canEdit = false, int? answerIndex, bool isLiveAnswer = false});
}

/// 状态管理 + 投影/事件应用逻辑
mixin _PanelStateLogicMixin on _PanelStateFields {
  CommandSequenceDraft _defaultDraft() {
    return CommandSequenceDraft.fromLaunchPlan(const TerminalLaunchPlan(
      tool: TerminalLaunchTool.claudeCode, title: 'Claude', cwd: '~',
      command: '/bin/bash', entryStrategy: TerminalEntryStrategy.shellBootstrap,
      postCreateInput: '', source: TerminalLaunchPlanSource.recommended,
    ));
  }

  void _resetAgentRenderState({bool resetDraft = false}) {
    _currentPhase = AgentPhase.idle;
    _phaseDescription = '';
    _traces.clear(); _turnEventOrder.clear(); _assistantMessages.clear();
    _streamingTextBuffer.clear(); _toolSteps.clear();
    _currentQuestion = null; _agentResult = null; _agentError = null;
    _activeSessionId = null; _multiSelectChosen.clear();
    _agentIntent = null; _agentAnswers.clear();
    _feedbackStatus = {};
    if (resetDraft) _draft = _defaultDraft();
  }

  void _resetPanelStateForScopeChange() {
    _eventSubscription?.cancel(); _eventSubscription = null;
    _conversationStreamSubscription?.cancel(); _conversationStreamSubscription = null;
    _pendingReset = false; _draft = _defaultDraft(); _executing = false;
    _resetAgentRenderState(); _agentHistory.clear(); _expandedHistorySet.clear();
    _serverConversationEvents.clear(); _agentConversationId = null;
    _nextConversationEventIndex = 0; _terminalConversationClosed = false;
    _terminalClosedReason = null; _editingHistoryIndex = null; _editingController.clear();
    _sessionUsageAccumulator.reset();
  }

  void _markTerminalConversationClosed(String message) {
    _eventSubscription?.cancel(); _eventSubscription = null;
    _conversationStreamSubscription?.cancel(); _conversationStreamSubscription = null;
    _pendingReset = false; _executing = false; _draft = _defaultDraft();
    _resetAgentRenderState(); _agentHistory.clear(); _expandedHistorySet.clear();
    _serverConversationEvents.clear(); _agentConversationId = null;
    _nextConversationEventIndex = 0; _terminalConversationClosed = true;
    _terminalClosedReason = message; _intentController.clear();
  }

  void _applyConversationProjection(AgentConversationProjection projection) {
    final renderState = _deriveAgentRenderState(projection.events);
    _serverConversationEvents..clear()..addAll(projection.events);
    _agentConversationId = projection.conversationId;
    _nextConversationEventIndex = projection.nextEventIndex;
    _terminalConversationClosed = false; _terminalClosedReason = null;
    _currentPhase = renderState.state; _phaseDescription = renderState.phaseDescription;
    _agentHistory.addAll(renderState.history); _traces.addAll(renderState.traces);
    _turnEventOrder.addAll(renderState.turnEventOrder);
    _assistantMessages.addAll(renderState.assistantMessages);
    _currentQuestion = renderState.currentQuestion; _agentResult = renderState.result;
    _agentError = renderState.error; _activeSessionId = projection.activeSessionId;
    _agentIntent = renderState.intent; _agentAnswers.addAll(renderState.answers);
    _streamingTextBuffer.clear(); _toolSteps.clear();
    if (_agentResult != null) _draft = _buildDraftFromAgentResult(_agentResult!);
  }

  void _applyConversationEventItem(AgentConversationEventItem event) {
    if (event.type == 'closed') {
      final reason = (event.payload['reason']?.toString() ?? 'terminal_closed').trim();
      _markTerminalConversationClosed('当前 terminal 已关闭，智能对话已结束。($reason)');
      return;
    }
    if (event.type == 'conversation_reset') {
      if (_eventSubscription != null) { _pendingReset = true; return; }
      _serverConversationEvents.clear(); _agentHistory.clear();
      _expandedHistorySet.clear(); _nextConversationEventIndex = 0;
      _resetAgentRenderState(resetDraft: true);
      return;
    }
    final existingIndex = _serverConversationEvents.indexWhere((item) => item.eventId == event.eventId);
    if (existingIndex >= 0) {
      _serverConversationEvents[existingIndex] = event;
    } else if (_serverConversationEvents.isEmpty || event.eventIndex > _serverConversationEvents.last.eventIndex) {
      _serverConversationEvents.add(event);
    } else {
      _serverConversationEvents.add(event);
      _serverConversationEvents.sort((l, r) => l.eventIndex.compareTo(r.eventIndex));
    }
    if (event.eventIndex + 1 > _nextConversationEventIndex) {
      _nextConversationEventIndex = event.eventIndex + 1;
    }
    final sseActive = _eventSubscription != null;
    if (sseActive) { _terminalConversationClosed = false; _terminalClosedReason = null; return; }
    if (event.type == 'trace') {
      _traces.add(AgentTraceEvent.fromJson(Map<String, dynamic>.from(event.payload)));
      _terminalConversationClosed = false; _terminalClosedReason = null;
      if (_currentPhase != AgentPhase.confirming) _currentPhase = AgentPhase.exploring;
      return;
    }
    if (event.type == 'assistant_message') {
      _assistantMessages.add(AgentAssistantMessageEvent.fromJson(Map<String, dynamic>.from(event.payload)));
      _turnEventOrder.add(_TurnEventType.assistantMessage);
      _terminalConversationClosed = false; _terminalClosedReason = null;
      if (_currentPhase == AgentPhase.idle) _currentPhase = AgentPhase.exploring;
      return;
    }
    final renderState = _deriveAgentRenderState(_serverConversationEvents);
    _terminalConversationClosed = false; _terminalClosedReason = null;
    _currentPhase = renderState.state; _phaseDescription = renderState.phaseDescription;
    _agentHistory..clear()..addAll(renderState.history);
    _traces..clear()..addAll(renderState.traces);
    _turnEventOrder..clear()..addAll(renderState.turnEventOrder);
    _assistantMessages..clear()..addAll(renderState.assistantMessages);
    _currentQuestion = renderState.currentQuestion; _agentResult = renderState.result;
    _agentError = renderState.error; _agentIntent = renderState.intent;
    _agentAnswers..clear()..addAll(renderState.answers);
    if (_activeSessionId == null &&
        (_currentPhase == AgentPhase.confirming || _currentPhase == AgentPhase.exploring ||
            _currentPhase == AgentPhase.thinking || _currentPhase == AgentPhase.analyzing)) {
      AgentConversationEventItem? eventWithSession;
      for (var i = _serverConversationEvents.length - 1; i >= 0; i--) {
        final e = _serverConversationEvents[i];
        if (e.sessionId != null && e.sessionId!.isNotEmpty) { eventWithSession = e; break; }
      }
      if (eventWithSession != null) _activeSessionId = eventWithSession.sessionId;
    }
    if (_agentResult != null) _draft = _buildDraftFromAgentResult(_agentResult!);
  }

  _AgentRenderState _deriveAgentRenderState(List<AgentConversationEventItem> events) {
    final history = <_AgentHistoryEntry>[];
    final traces = <AgentTraceEvent>[];
    final turnEventOrder = <_TurnEventType>[];
    final assistantMessages = <AgentAssistantMessageEvent>[];
    final answers = <_AgentAnswerEntry>[];
    String? activeIntent, lastQuestionText;
    AgentQuestionEvent? currentQuestion;
    AgentResultEvent? result;
    AgentErrorEvent? error;
    var state = AgentPhase.idle;
    var phaseDescription = '';
    void archiveCurrent({AgentResultEvent? archivedResult, AgentErrorEvent? archivedError}) {
      final intent = activeIntent?.trim();
      if (intent == null || intent.isEmpty) return;
      history.add(_AgentHistoryEntry(intent: intent, traces: List.of(traces),
          turnEventOrder: List.of(turnEventOrder), assistantMessages: List.of(assistantMessages),
          answers: List.of(answers), result: archivedResult, error: archivedError));
      activeIntent = null; traces.clear(); turnEventOrder.clear();
      assistantMessages.clear(); answers.clear(); currentQuestion = null; lastQuestionText = null;
    }
    for (final event in events) {
      switch (event.type) {
        case 'user_intent':
          archiveCurrent(archivedResult: result, archivedError: error);
          final text = (event.payload['text']?.toString() ?? '').trim();
          if (text.isEmpty) { state = AgentPhase.idle; break; }
          activeIntent = text; result = null; error = null;
          state = AgentPhase.thinking; phaseDescription = '正在分析你的意图...';
        case 'trace':
          traces.add(AgentTraceEvent.fromJson(Map<String, dynamic>.from(event.payload)));
          result = null; error = null; state = AgentPhase.exploring;
          phaseDescription = '正在执行工具调用...';
        case 'assistant_message':
          assistantMessages.add(AgentAssistantMessageEvent.fromJson(Map<String, dynamic>.from(event.payload)));
          turnEventOrder.add(_TurnEventType.assistantMessage);
          result = null; error = null; state = AgentPhase.responding;
        case 'question':
          currentQuestion = AgentQuestionEvent.fromJson({...Map<String, dynamic>.from(event.payload),
            if (event.questionId != null) 'question_id': event.questionId});
          lastQuestionText = currentQuestion?.question;
          result = null; error = null; state = AgentPhase.confirming;
          phaseDescription = currentQuestion?.question ?? '';
        case 'answer':
          final answer = (event.payload['text']?.toString() ?? '').trim();
          if (answer.isNotEmpty) {
            answers.add(_AgentAnswerEntry(question: lastQuestionText ?? '', answer: answer));
            turnEventOrder.add(_TurnEventType.answer);
          }
          currentQuestion = null; result = null; error = null;
          state = AgentPhase.exploring; phaseDescription = '正在执行工具调用...';
        case 'result':
          result = AgentResultEvent.fromJson(Map<String, dynamic>.from(event.payload));
          error = null; state = AgentPhase.result;
        case 'error':
          error = AgentErrorEvent.fromJson(Map<String, dynamic>.from(event.payload));
          result = null; state = AgentPhase.error;
      }
    }
    return _AgentRenderState(state: state, phaseDescription: phaseDescription, history: history,
        intent: activeIntent, traces: List.of(traces), turnEventOrder: List.of(turnEventOrder),
        assistantMessages: List.of(assistantMessages), answers: List.of(answers),
        currentQuestion: currentQuestion, result: result, error: error);
  }

  CommandSequenceDraft _buildDraftFromAgentResult(AgentResultEvent result) {
    final steps = result.steps.map((s) => CommandSequenceStep(
        id: s.id, label: s.label, command: s.command)).toList();
    return CommandSequenceDraft(summary: result.summary, provider: result.provider,
        tool: TerminalLaunchTool.custom, title: result.summary, cwd: '~',
        shellCommand: '/bin/bash', steps: List.unmodifiable(steps),
        source: TerminalLaunchPlanSource.intent, requiresManualConfirmation: result.needConfirm);
  }

  bool _isCommandResult(AgentResultEvent result) {
    final rt = result.responseType;
    return rt != 'message' && rt != 'ai_prompt';
  }

  /// 提交反馈到服务端
  Future<bool> _submitFeedback({
    required String feedbackKey,
    required String feedbackType,
    String? resultEventId,
    String? description,
  }) async {
    final key = feedbackKey;
    if (_feedbackStatus.containsKey(key)) return false; // 已反馈过

    RuntimeSelectionController? controller;
    try {
      controller = context.read<RuntimeSelectionController>();
    } on ProviderNotFoundException {
      return false;
    }

    final terminalId = _currentTerminalId();
    if (terminalId == null || terminalId.isEmpty) return false;

    setState(() {
      _feedbackSubmittingKey = key;
      _feedbackErrorKey = null;
    });

    try {
      final success = await _feedbackSubmitter(
        serverUrl: controller.serverUrl,
        token: controller.token,
        terminalId: terminalId,
        resultEventId: resultEventId,
        feedbackType: feedbackType,
        description: description,
      );

      if (!mounted) return false;

      if (success) {
        setState(() {
          final updated = Map<String, String>.from(_feedbackStatus);
          updated[key] = feedbackType;
          _feedbackStatus = updated;
          _feedbackSubmittingKey = null;
          _feedbackErrorKey = null;
        });
        return true;
      } else {
        setState(() {
          _feedbackSubmittingKey = null;
          _feedbackErrorKey = key;
        });
        return false;
      }
    } catch (_) {
      if (!mounted) return false;
      setState(() {
        _feedbackSubmittingKey = null;
        _feedbackErrorKey = key;
      });
      return false;
    }
  }
}
