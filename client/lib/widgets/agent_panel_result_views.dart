// ignore_for_file: annotate_overrides

part of 'smart_terminal_side_panel.dart';

/// 结果/进度/错误视图 UI
mixin _PanelResultViewsMixin on _PanelStateFields {
  Widget _buildProgressView(ColorScheme colorScheme) {
    final phaseLabel = switch (_currentPhase) {
      AgentPhase.thinking => '思考中',
      AgentPhase.analyzing => '分析中',
      _ => '执行中',
    };
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      _buildPhaseDescriptionIndicator(colorScheme),
      const SizedBox(height: 10),
      if (_toolSteps.isNotEmpty)
        for (final step in _toolSteps) ...[
          _buildToolStepCard(step, colorScheme),
          const SizedBox(height: 6)
        ],
      if (_traces.isNotEmpty && _toolSteps.isEmpty)
        _buildAgentTraceExpansionTile(colorScheme),
      if (_traces.isNotEmpty && _toolSteps.isEmpty) const SizedBox(height: 8),
      _buildLoadingBubble(
          _phaseDescription.isNotEmpty
              ? _phaseDescription
              : 'Agent 正在$phaseLabel...',
          colorScheme),
      const SizedBox(height: 10),
      Center(
          child: OutlinedButton(
              key: const Key('agent-cancel'),
              style: OutlinedButton.styleFrom(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
                  shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(10)),
                  side: BorderSide(
                      color:
                          colorScheme.outlineVariant.withValues(alpha: 0.4))),
              onPressed: _cancelAgentSession,
              child: Text('取消',
                  style: Theme.of(context)
                      .textTheme
                      .bodySmall
                      ?.copyWith(color: colorScheme.onSurfaceVariant)))),
    ]);
  }

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
                color: colorScheme.outlineVariant.withValues(alpha: 0.14))),
        child: Row(children: [
          SizedBox(
              width: 16,
              height: 16,
              child: CircularProgressIndicator(
                  strokeWidth: 2, color: colorScheme.primary)),
          const SizedBox(width: 10),
          Expanded(
              child: Text(description,
                  style: Theme.of(context).textTheme.bodySmall?.copyWith(
                      color: colorScheme.onSurfaceVariant,
                      fontWeight: FontWeight.w500),
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis)),
        ]));
  }

  Widget _buildRespondingView(ColorScheme colorScheme) {
    final text = _streamingTextBuffer.toString();
    if (text.isEmpty) return _buildLoadingBubble('正在生成回复...', colorScheme);
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Container(
            width: 28,
            height: 28,
            margin: const EdgeInsets.only(right: 8),
            decoration: BoxDecoration(
                color: colorScheme.primaryContainer,
                borderRadius: BorderRadius.circular(14)),
            child: Icon(Icons.smart_toy_outlined,
                size: 16, color: colorScheme.onPrimaryContainer)),
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
                        bottomRight: Radius.circular(4)),
                    border: Border.all(
                        color: colorScheme.outlineVariant
                            .withValues(alpha: 0.15))),
                child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      SelectableText(text,
                          style: Theme.of(context)
                              .textTheme
                              .bodyMedium
                              ?.copyWith(height: 1.5)),
                      if (_currentPhase == AgentPhase.responding)
                        Row(mainAxisSize: MainAxisSize.min, children: [
                          const SizedBox(width: 2),
                          _buildBlinkingCursor(colorScheme)
                        ]),
                    ]))),
      ]),
      if (_toolSteps.isNotEmpty) ...[
        const SizedBox(height: 10),
        for (final step in _toolSteps) ...[
          _buildToolStepCard(step, colorScheme),
          const SizedBox(height: 6)
        ]
      ],
    ]);
  }

  Widget _buildResultView(ColorScheme colorScheme, bool connected) {
    final result = _agentResult;
    if (result == null) {
      return const SizedBox.shrink();
    }
    final rt = result.responseType;
    final Widget resultWidget;
    if (rt == 'message') {
      resultWidget = _buildMessageResultView(result, colorScheme);
    } else if (rt == 'ai_prompt') {
      resultWidget = _buildAiPromptResultView(result, colorScheme, connected);
    } else {
      resultWidget = _buildCommandResultView(result, colorScheme, connected);
    }

    // 使用 result 的 hashCode 作为 eventId 的替代（SSE 事件没有独立 ID 字段）
    final resultKey = 'result_${result.summary.hashCode}';
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      resultWidget,
      const SizedBox(height: 8),
      _buildFeedbackButtons(
        colorScheme: colorScheme,
        feedbackKey: resultKey,
        resultEventId: resultKey,
      ),
    ]);
  }

  Widget _buildMessageResultView(
      AgentResultEvent result, ColorScheme colorScheme) {
    // 优先使用 streaming 文本：模型可能先流式输出了完整内容，再调用 deliver_result 传入短 summary
    // Phase 从 responding 切到 result 时 streaming 文本不再被渲染，这里回补
    final streamingText = _streamingTextBuffer.toString();
    final displayText = (streamingText.isNotEmpty &&
            streamingText.length > result.summary.length)
        ? streamingText
        : result.summary;
    return _buildAssistantBubble(
        Text(displayText, style: Theme.of(context).textTheme.bodyMedium));
  }

  Widget _buildAiPromptResultView(
      AgentResultEvent result, ColorScheme colorScheme, bool connected) {
    final service = Provider.of<WebSocketService?>(context);
    final multilinePrompt = result.aiPrompt.contains('\n');
    final bracketedPasteReady = service?.bracketedPasteModeEnabled ?? false;
    final canInjectPrompt = !multilinePrompt || bracketedPasteReady;
    return Container(
        width: double.infinity,
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
            color: colorScheme.surfaceContainerLow,
            borderRadius: BorderRadius.circular(16),
            border: Border.all(
                color: colorScheme.outlineVariant.withValues(alpha: 0.14))),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Icon(Icons.smart_toy_outlined,
                size: 16, color: colorScheme.primary),
            const SizedBox(width: 6),
            Expanded(
                child: Text(result.summary,
                    style: Theme.of(context)
                        .textTheme
                        .bodyMedium
                        ?.copyWith(fontWeight: FontWeight.w600)))
          ]),
          const SizedBox(height: 8),
          Container(
              width: double.infinity,
              padding: const EdgeInsets.all(10),
              decoration: BoxDecoration(
                  color: colorScheme.surfaceContainerHighest,
                  borderRadius: BorderRadius.circular(10),
                  border: Border.all(
                      color:
                          colorScheme.outlineVariant.withValues(alpha: 0.2))),
              child: Text(result.aiPrompt,
                  key: const Key('side-panel-ai-prompt-preview'),
                  style: Theme.of(context).textTheme.bodySmall?.copyWith(
                      fontFamily: 'monospace',
                      color: colorScheme.onSurfaceVariant),
                  maxLines: 8,
                  overflow: TextOverflow.ellipsis)),
          if (!connected) ...[
            const SizedBox(height: 6),
            Text('终端未连接，请先确认连接状态。',
                style: TextStyle(color: colorScheme.error, fontSize: 12))
          ],
          if (connected && multilinePrompt && !bracketedPasteReady) ...[
            const SizedBox(height: 6),
            Text(
              '当前终端未开启安全粘贴模式。请先让 Claude Code 光标处于输入框后再注入，避免污染后续输入。',
              key: const Key('side-panel-inject-warning'),
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
                          borderRadius: BorderRadius.circular(12)),
                      backgroundColor: colorScheme.primary),
                  onPressed: connected && !_executing && canInjectPrompt
                      ? _injectAiPrompt
                      : null,
                  child: _executing
                      ? SizedBox(
                          width: 16,
                          height: 16,
                          child: CircularProgressIndicator(
                              strokeWidth: 2, color: colorScheme.onPrimary))
                      : Text(canInjectPrompt ? '注入终端' : '等待输入态'))),
        ]));
  }

  Widget _buildCommandResultView(
      AgentResultEvent result, ColorScheme colorScheme, bool connected) {
    return Container(
        width: double.infinity,
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
            color: colorScheme.surfaceContainerLow,
            borderRadius: BorderRadius.circular(16),
            border: Border.all(
                color: colorScheme.outlineVariant.withValues(alpha: 0.14))),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Icon(Icons.check_circle, size: 16, color: colorScheme.primary),
            const SizedBox(width: 6),
            Expanded(
                child: Text(result.summary,
                    style: Theme.of(context)
                        .textTheme
                        .bodyMedium
                        ?.copyWith(fontWeight: FontWeight.w600)))
          ]),
          const SizedBox(height: 8),
          for (final step in result.steps)
            Container(
                margin: const EdgeInsets.only(bottom: 4),
                padding: const EdgeInsets.all(8),
                decoration: BoxDecoration(
                    color: colorScheme.surfaceContainerHighest,
                    borderRadius: BorderRadius.circular(8)),
                child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(step.label,
                          style: Theme.of(context)
                              .textTheme
                              .bodySmall
                              ?.copyWith(fontWeight: FontWeight.w600)),
                      const SizedBox(height: 2),
                      Text(step.command,
                          style: Theme.of(context)
                              .textTheme
                              .bodySmall
                              ?.copyWith(
                                  fontFamily: 'monospace',
                                  color: colorScheme.onSurfaceVariant)),
                    ])),
          if (!connected && result.steps.isNotEmpty) ...[
            const SizedBox(height: 6),
            Text('终端未连接，请先确认连接状态。',
                style: TextStyle(color: colorScheme.error, fontSize: 12))
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
                            borderRadius: BorderRadius.circular(12)),
                        backgroundColor: colorScheme.primary),
                    onPressed:
                        connected && !_executing ? _executeAgentResult : null,
                    child: _executing
                        ? SizedBox(
                            width: 16,
                            height: 16,
                            child: CircularProgressIndicator(
                                strokeWidth: 2, color: colorScheme.onPrimary))
                        : const Text('执行')))
          ],
        ]));
  }

  Widget _buildErrorView(ColorScheme colorScheme) {
    final errorMsg = _agentError?.message ?? '未知错误';
    final errorKey = 'error_${_agentError?.code.hashCode ?? 0}';
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      _buildAssistantBubble(
          Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Icon(Icons.error_outline, size: 16, color: colorScheme.error),
        const SizedBox(width: 8),
        Expanded(
            child: Text(errorMsg,
                style: Theme.of(context)
                    .textTheme
                    .bodySmall
                    ?.copyWith(color: colorScheme.error)))
      ])),
      const SizedBox(height: 10),
      Row(children: [
        Expanded(
            child: OutlinedButton(
                key: const Key('agent-retry'),
                style: OutlinedButton.styleFrom(
                    minimumSize: const Size.fromHeight(36),
                    shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(10))),
                onPressed: _retryAgentSession,
                child: const Text('重试')))
      ]),
      const SizedBox(height: 8),
      _buildFeedbackButtons(
        colorScheme: colorScheme,
        feedbackKey: errorKey,
        feedbackType: 'error_report',
        label: '报告问题',
      ),
    ]);
  }

  // --- 反馈按钮 ---

  Widget _buildFeedbackButtons({
    required ColorScheme colorScheme,
    required String feedbackKey,
    String? resultEventId,
    String feedbackType = 'helpful',
    String? label,
  }) {
    final hasFeedback = _feedbackStatus.containsKey(feedbackKey);
    final isSubmitting = _feedbackSubmittingKey == feedbackKey;
    final hasError = _feedbackErrorKey == feedbackKey;

    if (hasFeedback) {
      final chosen = _feedbackStatus[feedbackKey]!;
      final chosenLabel = switch (chosen) {
        'helpful' => '有帮助',
        'needs_improvement' => '需改进',
        'error_report' => '已报告',
        _ => chosen,
      };
      return Row(children: [
        Icon(Icons.check_circle_outline,
            size: 14, color: colorScheme.primary),
        const SizedBox(width: 4),
        Text('已反馈: $chosenLabel',
            style: Theme.of(context).textTheme.labelSmall?.copyWith(
                color: colorScheme.primary, fontWeight: FontWeight.w500)),
      ]);
    }

    // error 视图只需要一个按钮
    if (feedbackType == 'error_report') {
      return Row(children: [
        Expanded(
            child: OutlinedButton.icon(
                key: Key('feedback-$feedbackKey'),
                style: OutlinedButton.styleFrom(
                    padding: const EdgeInsets.symmetric(
                        horizontal: 10, vertical: 6),
                    shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(8)),
                    side: BorderSide(
                        color: hasError
                            ? colorScheme.error
                            : colorScheme.outlineVariant
                                .withValues(alpha: 0.4))),
                onPressed: isSubmitting
                    ? null
                    : () => _submitFeedback(
                          feedbackKey: feedbackKey,
                          feedbackType: 'error_report',
                          resultEventId: resultEventId,
                          description: _agentError?.message ?? '错误报告',
                        ),
                icon: isSubmitting
                    ? SizedBox(
                        width: 12,
                        height: 12,
                        child: CircularProgressIndicator(
                            strokeWidth: 1.5,
                            color: colorScheme.onSurfaceVariant))
                    : Icon(Icons.flag_outlined, size: 14),
                label: Text(label ?? '报告问题',
                    style: Theme.of(context).textTheme.labelSmall))),
        if (hasError) ...[
          const SizedBox(width: 6),
          Text('提交失败',
              style: Theme.of(context)
                  .textTheme
                  .labelSmall
                  ?.copyWith(color: colorScheme.error, fontSize: 10)),
        ],
      ]);
    }

    // result 视图两个按钮
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Row(children: [
        Expanded(
            child: OutlinedButton.icon(
                key: Key('feedback-helpful-$feedbackKey'),
                style: OutlinedButton.styleFrom(
                    padding:
                        const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
                    shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(8)),
                    side: BorderSide(
                        color: colorScheme.outlineVariant
                            .withValues(alpha: 0.4))),
                onPressed: isSubmitting
                    ? null
                    : () => _submitFeedback(
                          feedbackKey: feedbackKey,
                          feedbackType: 'helpful',
                          resultEventId: resultEventId,
                        ),
                icon: isSubmitting
                    ? SizedBox(
                        width: 12,
                        height: 12,
                        child: CircularProgressIndicator(
                            strokeWidth: 1.5,
                            color: colorScheme.onSurfaceVariant))
                    : const Icon(Icons.thumb_up_outlined, size: 14),
                label: Text('有帮助',
                    style: Theme.of(context).textTheme.labelSmall))),
        const SizedBox(width: 8),
        Expanded(
            child: OutlinedButton.icon(
                key: Key('feedback-needs_improvement-$feedbackKey'),
                style: OutlinedButton.styleFrom(
                    padding:
                        const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
                    shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(8)),
                    side: BorderSide(
                        color: colorScheme.outlineVariant
                            .withValues(alpha: 0.4))),
                onPressed: isSubmitting
                    ? null
                    : () => _submitFeedback(
                          feedbackKey: feedbackKey,
                          feedbackType: 'needs_improvement',
                          resultEventId: resultEventId,
                        ),
                icon: isSubmitting
                    ? SizedBox(
                        width: 12,
                        height: 12,
                        child: CircularProgressIndicator(
                            strokeWidth: 1.5,
                            color: colorScheme.onSurfaceVariant))
                    : const Icon(Icons.thumb_down_outlined, size: 14),
                label: Text('需改进',
                    style: Theme.of(context).textTheme.labelSmall))),
      ]),
      if (hasError) ...[
        const SizedBox(height: 4),
        Text('反馈提交失败，请重试',
            key: Key('feedback-error-$feedbackKey'),
            style: Theme.of(context)
                .textTheme
                .labelSmall
                ?.copyWith(color: colorScheme.error, fontSize: 10)),
      ],
    ]);
  }

  // --- Usage 统计处理 ---

  Future<void> _refreshUsageSummary({
    required RuntimeSelectionController controller,
    bool forceRefresh = true,
    String? terminalId,
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
        _usageSummaryError == null) return;
    final requestSerial = ++_usageRefreshSerial;
    setState(() {
      _usageSummaryLoading = true;
      if (_usageSummary == null || _usageSummaryDeviceId != deviceId)
        _usageSummary = const UsageSummaryData.empty();
    });
    try {
      final summary = await _usageSummaryService(controller.serverUrl)
          .fetchSummary(
              token: controller.token,
              deviceId: deviceId,
              terminalId: terminalId);
      if (!mounted || requestSerial != _usageRefreshSerial) return;
      setState(() {
        _usageSummary = summary;
        _usageSummaryDeviceId = deviceId;
        _usageSummaryError = null;
        _usageSummaryLoading = false;
      });
    } catch (_) {
      if (!mounted || requestSerial != _usageRefreshSerial) return;
      setState(() {
        _usageSummaryDeviceId = deviceId;
        _usageSummaryError = '统计暂不可用，稍会后自动重试';
        _usageSummaryLoading = false;
      });
    }
  }
}
