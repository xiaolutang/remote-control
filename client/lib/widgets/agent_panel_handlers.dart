// ignore_for_file: annotate_overrides

part of 'smart_terminal_side_panel.dart';

/// SSE 会话管理、Intent 提交、Agent 事件处理、取消/重试
mixin _PanelHandlersMixin on _PanelStateFields, ScrollToLatestMixin {
  void _handleIntentFocusChanged() {
    if (!mounted) return;
    // focus 变化影响 build 中的 keyboardInset 计算，必须 rebuild
    setState(() {});
    if (_intentFocusNode.hasFocus) _scheduleScrollToLatest();
  }

  AgentSessionService _agentSessionService(String serverUrl) {
    final builder = widget.agentSessionServiceBuilder;
    if (builder != null) return builder(serverUrl);
    return AgentSessionService(serverUrl: serverUrl);
  }

  UsageSummaryService _usageSummaryService(String serverUrl) {
    final builder = widget.usageSummaryServiceBuilder;
    if (builder != null) return builder(serverUrl);
    return UsageSummaryService(serverUrl: serverUrl);
  }

  void _scheduleScrollToLatest() {
    scheduleScrollToLatest(_scrollController);
  }

  /// 安全获取 Provider，不存在时返回 null（替代重复的 try-read-catch 模式）
  T? _tryGetController<T>() {
    try {
      return context.read<T>();
    } on ProviderNotFoundException {
      return null;
    }
  }

  String? _currentTerminalId() => _tryGetController<WebSocketService>()?.terminalId;

  // --- 投影加载 ---
  Future<void> _loadConversationProjection(
      {required String? deviceId, required String? terminalId}) async {
    final requestSerial = ++_projectionLoadSerial;
    if (deviceId == null ||
        deviceId.isEmpty ||
        terminalId == null ||
        terminalId.isEmpty) {
      if (!mounted || requestSerial != _projectionLoadSerial) return;
      setState(_resetPanelStateForScopeChange);
      return;
    }
    final controller = _tryGetController<RuntimeSelectionController>();
    if (controller == null) return;
    final service = _agentSessionService(controller.serverUrl);
    try {
      final projection = await service.fetchConversation(
          deviceId: deviceId, terminalId: terminalId, token: controller.token);
      if (!mounted || requestSerial != _projectionLoadSerial) return;
      setState(() {
        _resetPanelStateForScopeChange();
        _applyConversationProjection(projection);
      });
      _scheduleScrollToLatest();
      _startConversationStream(
          controller: controller, deviceId: deviceId, terminalId: terminalId);
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
            message: error.message);
      });
    }
  }

  // --- Conversation Stream ---

  void _startConversationStream(
      {required RuntimeSelectionController controller,
      required String deviceId,
      required String terminalId}) {
    if (_terminalConversationClosed) return;
    _conversationStreamSubscription?.cancel();
    final service = _agentSessionService(controller.serverUrl);
    final afterIndex = _nextConversationEventIndex - 1;
    _conversationStreamSubscription = service
        .streamConversationResilient(
            deviceId: deviceId,
            terminalId: terminalId,
            token: controller.token,
            afterIndex: afterIndex)
        .listen((event) {
      if (!mounted) return;
      setState(() {
        _applyConversationEventItem(event);
      });
      _scheduleScrollToLatest();
    }, onError: (Object error) {
      _conversationStreamSubscription = null;
    }, onDone: () {
      _conversationStreamSubscription = null;
    });
  }

  void _restartConversationStreamForCurrentScope() {
    final controller = _tryGetController<RuntimeSelectionController>();
    if (controller == null) return;
    final deviceId = controller.selectedDeviceId;
    final terminalId = _currentTerminalId();
    if (deviceId == null ||
        deviceId.isEmpty ||
        terminalId == null ||
        terminalId.isEmpty) return;
    _startConversationStream(
        controller: controller, deviceId: deviceId, terminalId: terminalId);
  }

  // --- Intent 提交 ---
  Future<void> _handleResolveIntent(
      {String? overrideIntent, int? truncateAfterIndex}) async {
    if (_terminalConversationClosed) return;
    final intent = (overrideIntent ?? _intentController.text).trim();
    if (intent.isEmpty) return;
    _intentController.clear();
    if (_agentIntent != null && _agentIntent!.isNotEmpty) {
      _archiveAgentTurn(result: _agentResult, error: _agentError);
    }
    final controller = _tryGetController<RuntimeSelectionController>();
    if (controller == null) {
      _presentAgentError(
          code: 'MISSING_CONTROLLER',
          message: '当前页面状态异常，无法启动智能交互，请联系开发者',
          intent: intent);
      return;
    }
    final deviceId = controller.selectedDeviceId;
    if (deviceId == null || deviceId.isEmpty) {
      _presentAgentError(
          code: 'DEVICE_NOT_SELECTED',
          message: '请先选择设备后再发起智能交互',
          intent: intent);
      return;
    }
    _startAgentSession(
        intent: intent,
        controller: controller,
        truncateAfterIndex: truncateAfterIndex);
  }

  // --- Agent SSE 会话 ---
  Future<void> _startAgentSession(
      {required String intent,
      required RuntimeSelectionController controller,
      int? truncateAfterIndex}) async {
    final deviceId = controller.selectedDeviceId!;
    final terminalId = _currentTerminalId();
    if (terminalId == null || terminalId.isEmpty) {
      _presentAgentError(
          code: 'TERMINAL_NOT_READY',
          message: '请先进入一个 terminal，再发起智能交互',
          intent: intent);
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
          truncateAfterIndex: truncateAfterIndex);
      _eventSubscription?.cancel();
      _eventSubscription = eventStream.listen((event) {
        if (!mounted) return;
        _handleAgentEvent(event, controller: controller);
      }, onError: (Object error) {
        if (!mounted) return;
        final message =
            error is AgentSessionException ? error.message : '智能交互启动失败，请联系开发者';
        _presentAgentError(
            code: error is AgentSessionException
                ? (error.code ?? 'AGENT_REQUEST_FAILED')
                : 'AGENT_REQUEST_FAILED',
            message: message,
            intent: intent);
      }, onDone: () {
        if (!mounted) return;
        final didReset = _pendingReset;
        if (didReset) {
          setState(() {
            _serverConversationEvents.clear();
            _agentHistory.clear();
            _expandedHistorySet.clear();
            _nextConversationEventIndex = 0;
            _pendingReset = false;
            _resetAgentRenderState(resetDraft: true);
          });
        }
        _eventSubscription = null;
        if ((_currentPhase == AgentPhase.exploring ||
                _currentPhase == AgentPhase.thinking ||
                _currentPhase == AgentPhase.analyzing ||
                _currentPhase == AgentPhase.responding) &&
            !didReset) {
          setState(() {
            _currentPhase = AgentPhase.error;
            _agentError = const AgentErrorEvent(
                code: 'STREAM_CLOSED', message: 'Agent 会话意外关闭');
          });
        }
        if (didReset) {
          _restartConversationStreamForCurrentScope();
        } else if (_conversationStreamSubscription == null) {
          _restartConversationStreamForCurrentScope();
        }
      });
    } catch (e) {
      if (!mounted) return;
      final message =
          e is AgentSessionException ? e.message : '智能交互启动失败，请联系开发者';
      _presentAgentError(
          code: e is AgentSessionException
              ? (e.code ?? 'AGENT_REQUEST_FAILED')
              : 'AGENT_REQUEST_FAILED',
          message: message,
          intent: intent);
    }
  }

  void _handleAgentEvent(AgentSessionEvent event,
      {required RuntimeSelectionController controller}) {
    switch (event) {
      case AgentSessionCreatedEvent created:
        setState(() {
          _activeSessionId = created.sessionId;
          final cid = created.conversationId?.trim();
          if (cid != null && cid.isNotEmpty) _agentConversationId = cid;
        });
      case PhaseChangeEvent phaseChange:
        setState(() {
          _currentPhase = _phaseFromEvent(phaseChange.phase.toUpperCase());
          _phaseDescription = (phaseChange.description != null &&
                  phaseChange.description!.isNotEmpty)
              ? phaseChange.description!
              : _defaultPhaseDescription(_currentPhase);
        });
        _scheduleScrollToLatest();
      case StreamingTextEvent streamingText:
        setState(() {
          _streamingTextBuffer.write(streamingText.textDelta);
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
          if (_currentPhase == AgentPhase.idle ||
              _currentPhase == AgentPhase.thinking) {
            _currentPhase = AgentPhase.exploring;
            _phaseDescription = '正在执行工具调用...';
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
          _agentResultEventId = result.eventId;
          _currentPhase = AgentPhase.result;
          _activeSessionId = null;
          if (_isCommandResult(result)) {
            _draft = _buildDraftFromAgentResult(result);
          }
          // Accumulate usage from result event (local immediate feedback)
          final usageMap = result.usage != null ? {
            'input_tokens': result.usage!.inputTokens,
            'output_tokens': result.usage!.outputTokens,
            'total_tokens': result.usage!.totalTokens,
            'requests': result.usage!.requests,
          } : null;
          _sessionUsageAccumulator.accumulate(usageMap);
        });
        if (_conversationStreamSubscription == null) {
          _restartConversationStreamForCurrentScope();
        }
        unawaited(_refreshUsageSummary(
            controller: controller, terminalId: _currentTerminalId()));
        _scheduleScrollToLatest();
      case AgentErrorEvent error:
        setState(() {
          _agentError = error;
          _currentPhase = AgentPhase.error;
          _activeSessionId = null;
          // Accumulate usage from error event (local immediate feedback)
          final errUsageMap = error.usage != null ? {
            'input_tokens': error.usage!.inputTokens,
            'output_tokens': error.usage!.outputTokens,
            'total_tokens': error.usage!.totalTokens,
            'requests': error.usage!.requests,
          } : null;
          _sessionUsageAccumulator.accumulate(errUsageMap);
        });
        unawaited(_refreshUsageSummary(
            controller: controller, terminalId: _currentTerminalId()));
        if (_conversationStreamSubscription == null) {
          _restartConversationStreamForCurrentScope();
        }
        _scheduleScrollToLatest();
    }
  }

  static AgentPhase _phaseFromEvent(String phaseName) => switch (phaseName) {
        'THINKING' => AgentPhase.thinking,
        'EXPLORING' || 'ACTING' => AgentPhase.exploring,
        'ANALYZING' => AgentPhase.analyzing,
        'RESPONDING' => AgentPhase.responding,
        'CONFIRMING' || 'ASK_USER' => AgentPhase.confirming,
        'RESULT' => AgentPhase.result,
        'ERROR' => AgentPhase.error,
        _ => AgentPhase.exploring,
      };

  static String _defaultPhaseDescription(AgentPhase phase) => switch (phase) {
        AgentPhase.idle => '',
        AgentPhase.thinking => '正在思考...',
        AgentPhase.exploring => '正在执行工具调用...',
        AgentPhase.analyzing => '正在分析结果...',
        AgentPhase.responding => '正在生成回复...',
        AgentPhase.confirming => '等待确认...',
        AgentPhase.result => '',
        AgentPhase.error => '',
      };

  void _archiveAgentTurn({AgentResultEvent? result, AgentErrorEvent? error}) {
    final intent = _agentIntent;
    if (intent == null || intent.isEmpty) return;
    _agentHistory.add(AgentHistoryEntry(
        intent: intent,
        traces: List.of(_traces),
        turnEventOrder: List.of(_turnEventOrder),
        assistantMessages: List.of(_assistantMessages),
        answers: List.of(_agentAnswers),
        result: result,
        error: error));
    _agentIntent = null;
  }

  void _presentAgentError(
      {required String code, required String message, String? intent}) {
    if (!mounted) return;
    setState(() {
      _currentPhase = AgentPhase.error;
      _agentError = AgentErrorEvent(code: code, message: message);
      _activeSessionId = null;
      _currentQuestion = null;
      if (intent != null && intent.isNotEmpty) _agentIntent = intent;
    });
    _scheduleScrollToLatest();
  }

  void _presentInjectionError(String message) {
    if (!mounted) return;
    setState(() {
      _executing = false;
      _currentPhase = AgentPhase.error;
      _agentError = AgentErrorEvent(code: 'INJECT_FAILED', message: message);
    });
    _scheduleScrollToLatest();
  }

  Future<void> _handleAgentRespond(String answer) async {
    if (_terminalConversationClosed ||
        _pendingReset ||
        _activeSessionId == null) return;
    final controller = _tryGetController<RuntimeSelectionController>();
    if (controller == null) return;
    final deviceId = controller.selectedDeviceId;
    if (deviceId == null) return;
    final terminalId = _currentTerminalId();
    if (terminalId == null || terminalId.isEmpty) return;
    final question = _currentQuestion;
    setState(() {
      if (question != null) {
        _agentAnswers.add(
            AgentAnswerEntry(question: question.question, answer: answer));
        _turnEventOrder.add(TurnEventType.answer);
      }
      _currentPhase = AgentPhase.exploring;
      _phaseDescription = '正在执行工具调用...';
      _currentQuestion = null;
    });
    try {
      await _agentSessionService(controller.serverUrl).respond(
          deviceId: deviceId,
          terminalId: terminalId,
          sessionId: _activeSessionId!,
          answer: answer,
          token: controller.token,
          questionId: question?.questionId);
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _agentError =
            AgentErrorEvent(code: 'RESPOND_FAILED', message: '回复失败：$e');
        _currentPhase = AgentPhase.error;
      });
    }
  }

  void _handleInputSubmit() {
    if (_terminalConversationClosed || _pendingReset) return;
    if (_currentPhase == AgentPhase.confirming) {
      final text = _intentController.text.trim();
      if (text.isEmpty) return;
      if (_activeSessionId == null) {
        setState(() {
          _currentPhase = AgentPhase.error;
          _agentError =
              AgentErrorEvent(code: 'SESSION_LOST', message: '会话已断开，请重新发送您的问题');
        });
        return;
      }
      _intentController.clear();
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

  Future<void> _executeAgentResult() async {
    if (_executing || !_isConnected) return;
    setState(() => _executing = true);
    final plan = _draft.toLaunchPlan();
    final input = plan.postCreateInput;
    var injectFailed = false;
    if (input.isNotEmpty) {
      try {
        await context.read<WebSocketService>().sendOrThrow(input);
      } catch (e) {
        injectFailed = true;
        final message = e is StateError ? '${e.message}' : e.toString();
        _presentInjectionError('命令注入失败：$message');
      }
    }
    if (!mounted) return;
    setState(() => _executing = false);
    if (!injectFailed) widget.onClose();
  }

  Future<void> _injectAiPrompt() async {
    if (_executing || !_isConnected) return;
    final result = _agentResult;
    if (result == null || result.aiPrompt.isEmpty) return;
    final service = context.read<WebSocketService>();
    setState(() => _executing = true);
    try {
      final prompt = result.aiPrompt;
      final multiline = prompt.contains('\n');
      if (multiline && !service.bracketedPasteModeEnabled) {
        if (!mounted) return;
        setState(() {
          _executing = false;
          _currentPhase = AgentPhase.error;
          _agentError = const AgentErrorEvent(
            code: 'BRACKETED_PASTE_UNAVAILABLE',
            message: '当前终端还没进入可安全注入多行 Prompt 的输入态，请先让 Claude Code 光标处于输入框后重试。',
          );
        });
        return;
      }
      AppLogger('AgentPanel').debug(
        'inject ai_prompt terminal=${service.terminalId} '
        'status=${service.status.name} '
        'canSend=${service.canSend} '
        'bracketedPaste=${service.bracketedPasteModeEnabled} '
        'closeCode=${service.lastCloseCode} '
        'closeReason=${service.lastCloseReason}',
      );
      final wrapped = multiline ? '\x1b[200~$prompt\x1b[201~' : prompt;
      await service.sendOrThrow('$wrapped\r');
    } catch (e) {
      final message = e is StateError ? '${e.message}' : e.toString();
      _presentInjectionError('Prompt 注入失败：$message');
      return;
    }
    if (!mounted) return;
    _archiveAgentTurn(result: result);
    setState(() {
      _executing = false;
      _resetAgentRenderState();
    });
    widget.onClose();
  }

  void _retryAgentSession() {
    final savedIntent = _agentIntent;
    if (_pendingReset) {
      _serverConversationEvents.clear();
      _agentHistory.clear();
      _expandedHistorySet.clear();
      _nextConversationEventIndex = 0;
      _resetAgentRenderState(resetDraft: true);
      _pendingReset = false;
    }
    if (savedIntent != null) {
      final controller = _tryGetController<RuntimeSelectionController>();
      if (controller == null) return;
      final truncateAfterIndex = _findTruncateAfterIndexForCurrentTurn();
      setState(() {
        _currentPhase = AgentPhase.idle;
        _phaseDescription = '';
        _agentError = null;
      });
      _startAgentSession(
          intent: savedIntent,
          controller: controller,
          truncateAfterIndex: truncateAfterIndex);
    }
  }

  int _findTruncateAfterIndexForCurrentTurn() {
    final cutPoint = _findUserIntentEventListIndex();
    if (cutPoint == null || cutPoint == 0) return -1;
    return _serverConversationEvents[cutPoint - 1].eventIndex;
  }

  int? _findUserIntentEventListIndex({int? historyIndex}) {
    if (historyIndex == null) {
      for (int i = _serverConversationEvents.length - 1; i >= 0; i--) {
        if (_serverConversationEvents[i].type == 'user_intent') return i;
      }
      return null;
    }
    int intentCount = 0;
    for (int i = 0; i < _serverConversationEvents.length; i++) {
      if (_serverConversationEvents[i].type != 'user_intent') continue;
      if (intentCount == historyIndex) return i;
      intentCount++;
    }
    return null;
  }

  Future<void> _cancelAgentSession() async {
    await _doCancelAgentNetwork();
    if (!mounted) return;
    setState(() {
      if (_agentIntent != null && _agentIntent!.isNotEmpty) {
        _agentHistory.add(AgentHistoryEntry(
            intent: _agentIntent!,
            traces: List.of(_traces),
            turnEventOrder: List.of(_turnEventOrder),
            assistantMessages: List.of(_assistantMessages),
            answers: List.of(_agentAnswers),
            error: const AgentErrorEvent(code: 'CANCELLED', message: '已取消')));
      }
      _currentPhase = AgentPhase.idle;
      _phaseDescription = '';
      _agentIntent = null;
      _activeSessionId = null;
    });
    _restartConversationStreamForCurrentScope();
  }

  Future<void> _doCancelAgentNetwork() async {
    _eventSubscription?.cancel();
    _eventSubscription = null;
    final sessionId = _activeSessionId;
    if (_pendingReset) {
      _serverConversationEvents.clear();
      _agentHistory.clear();
      _expandedHistorySet.clear();
      _nextConversationEventIndex = 0;
      _resetAgentRenderState(resetDraft: true);
      _pendingReset = false;
    }
    if (sessionId == null) return;
    final controller = _tryGetController<RuntimeSelectionController>();
    if (controller == null) return;
    final deviceId = controller.selectedDeviceId;
    if (deviceId == null) return;
    final terminalId = _currentTerminalId();
    if (terminalId == null || terminalId.isEmpty) return;
    try {
      await _agentSessionService(controller.serverUrl).cancel(
          deviceId: deviceId,
          terminalId: terminalId,
          sessionId: sessionId,
          token: controller.token);
    } catch (e) {
      // Expected: cancel is best-effort, failure must not block UI flow.
      AppLogger('AgentPanel').debug('cancel session network failed: $e');
    }
  }

  Future<void> _cancelAgentSessionSilent() => _doCancelAgentNetwork();

  // --- 定时任务创建 ---

  /// 创建定时任务：将 steps 的 command 用 \r 拼接为 text_content，
  /// 将 repeatType 字符串转为枚举，调用 ScheduledTaskService.create()。
  Future<void> _createScheduledTask() async {
    if (_scheduledTaskCreating) return; // 防重入
    final result = _agentResult;
    if (result == null || result.scheduleAt == null) return;

    final controller = _tryGetController<RuntimeSelectionController>();
    if (controller == null) {
      setState(() {
        _scheduledTaskError = '当前页面状态异常，无法创建定时任务';
      });
      return;
    }

    final terminalId = _currentTerminalId();
    if (terminalId == null || terminalId.isEmpty) {
      setState(() {
        _scheduledTaskError = '终端 ID 不可用，无法创建定时任务';
      });
      return;
    }

    final deviceId = controller.selectedDeviceId;
    if (deviceId == null || deviceId.isEmpty) {
      setState(() {
        _scheduledTaskError = '设备 ID 不可用，无法创建定时任务';
      });
      return;
    }

    // steps 为空则无法创建
    if (result.steps.isEmpty) {
      setState(() {
        _scheduledTaskError = '命令内容为空，无法创建定时任务';
      });
      return;
    }
    // steps 每步的 command 用 \r 拼接，确保末尾有 \r 以自动执行
    final joined = result.steps.map((s) => s.command).join('\r');
    final textContent = joined.endsWith('\r') ? joined : '$joined\r';

    // repeatType 字符串转枚举（非法值降级为 once）
    final repeatTypeEnum = ScheduledTaskRepeatType.fromString(result.repeatType);

    setState(() {
      _scheduledTaskCreating = true;
      _scheduledTaskError = null;
    });

    try {
      final service = ScheduledTaskService(serverUrl: controller.serverUrl);
      await service.create(
        token: controller.token,
        sessionId: deviceId,
        terminalId: terminalId,
        textContent: textContent,
        executeAt: result.scheduleAt!,
        repeatType: repeatTypeEnum,
      );

      if (!mounted) return;

      // 通知父组件刷新定时任务列表（父组件的 poller 会拉取最新数据）
      widget.onScheduledTaskCreated?.call();

      setState(() {
        _scheduledTaskCreating = false;
        _scheduledTaskError = null;
      });

      // 显示 SnackBar 提示
      if (context.mounted) {
        ScaffoldMessenger.of(context)
          ..clearSnackBars()
          ..showSnackBar(const SnackBar(
            content: Text('定时任务已创建'),
            duration: Duration(seconds: 2),
          ));
      }
    } on ScheduledTaskException catch (e) {
      if (!mounted) return;
      setState(() {
        _scheduledTaskCreating = false;
        _scheduledTaskError = e.message;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _scheduledTaskCreating = false;
        _scheduledTaskError = '创建失败：$e';
      });
    }
  }

  // --- 内联编辑处理 ---
  void _startInlineEdit(int? historyIndex, {int? answerIndex}) {
    if (_pendingReset) return;
    String originalText;
    if (answerIndex != null) {
      originalText = historyIndex != null
          ? _agentHistory[historyIndex].answers[answerIndex].answer
          : _agentAnswers[answerIndex].answer;
    } else {
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

  void _syncNextEventIndex() {
    _nextConversationEventIndex = _serverConversationEvents.isNotEmpty
        ? _serverConversationEvents.last.eventIndex + 1
        : 0;
  }

  int _computeTruncateAfter() => _serverConversationEvents.isNotEmpty
      ? _serverConversationEvents.last.eventIndex
      : -1;

  void _truncateConversationEvents(int? historyIndex) {
    final cutPoint = _findUserIntentEventListIndex(historyIndex: historyIndex);
    if (cutPoint == null) {
      _serverConversationEvents.clear();
      _nextConversationEventIndex = 0;
      return;
    }
    _serverConversationEvents.removeRange(
        cutPoint, _serverConversationEvents.length);
    _syncNextEventIndex();
  }

  Future<void> _submitInlineEdit({int? historyIndex}) async {
    if (_pendingReset) return;
    final newText = _editingController.text.trim();
    if (newText.isEmpty) return;
    final editingAnswer = _editingAnswerIndex;
    setState(() {
      _editingHistoryIndex = null;
      _editingAnswerIndex = null;
      _editingController.clear();
    });
    if (editingAnswer != null) {
      await _submitAnswerEdit(
          historyIndex: historyIndex,
          answerIndex: editingAnswer,
          newAnswer: newText);
    } else {
      await _submitIntentEdit(historyIndex: historyIndex, newText: newText);
    }
  }

  Future<void> _submitIntentEdit(
      {int? historyIndex, required String newText}) async {
    await _cancelAgentSessionSilent();
    final shouldArchiveCurrent = historyIndex == null &&
        _agentIntent != null &&
        _agentIntent!.isNotEmpty;
    if (shouldArchiveCurrent)
      _archiveAgentTurn(result: _agentResult, error: _agentError);
    setState(() {
      if (historyIndex != null)
        _agentHistory.removeRange(historyIndex, _agentHistory.length);
      _truncateConversationEvents(historyIndex);
      _resetAgentRenderState();
    });
    await _handleResolveIntent(
        overrideIntent: newText, truncateAfterIndex: _computeTruncateAfter());
  }

  Future<void> _submitAnswerEdit(
      {int? historyIndex,
      required int answerIndex,
      required String newAnswer}) async {
    await _cancelAgentSessionSilent();
    final isLive = historyIndex == null;
    final entry = isLive ? null : _agentHistory[historyIndex];
    final savedIntent = isLive ? _agentIntent : entry?.intent;
    setState(() {
      _truncateConversationEventsForAnswer(historyIndex, answerIndex);
      if (_serverConversationEvents.isNotEmpty) {
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
        var answersSeen = 0;
        var truncateAt = _turnEventOrder.length;
        for (var i = 0; i < _turnEventOrder.length; i++) {
          if (_turnEventOrder[i] == TurnEventType.answer) {
            if (answersSeen == answerIndex) {
              truncateAt = i;
              break;
            }
            answersSeen++;
          }
        }
        _turnEventOrder.removeRange(truncateAt, _turnEventOrder.length);
        var answerKeep = 0;
        var msgKeep = 0;
        for (final type in _turnEventOrder) {
          if (type == TurnEventType.answer) {
            answerKeep++;
          } else if (type == TurnEventType.assistantMessage) {
            msgKeep++;
          }
        }
        if (answerKeep < _agentAnswers.length)
          _agentAnswers.removeRange(answerKeep, _agentAnswers.length);
        if (msgKeep < _assistantMessages.length)
          _assistantMessages.removeRange(msgKeep, _assistantMessages.length);
        _currentPhase = AgentPhase.exploring;
        _phaseDescription = '正在执行工具调用...';
        _agentIntent = savedIntent;
        _traces.clear();
      }
      _currentQuestion = null;
      _agentResult = null;
      _agentError = null;
    });
    await _handleResolveIntent(
        overrideIntent: savedIntent!,
        truncateAfterIndex: _computeTruncateAfter());
  }

  void _truncateConversationEventsForAnswer(
      int? historyIndex, int answerIndex) {
    if (_serverConversationEvents.isEmpty) return;
    final intentListIndex =
        _findUserIntentEventListIndex(historyIndex: historyIndex);
    if (intentListIndex == null) {
      _serverConversationEvents.clear();
      _syncNextEventIndex();
      return;
    }
    int answerCount = 0;
    int cutPoint = _serverConversationEvents.length;
    for (int i = intentListIndex + 1;
        i < _serverConversationEvents.length;
        i++) {
      if (_serverConversationEvents[i].type == 'answer') {
        if (answerCount == answerIndex) {
          cutPoint = i;
          break;
        }
        answerCount++;
      }
    }
    _serverConversationEvents.removeRange(
        cutPoint, _serverConversationEvents.length);
    _syncNextEventIndex();
  }
}
