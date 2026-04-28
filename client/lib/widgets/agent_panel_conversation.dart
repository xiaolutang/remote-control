// ignore_for_file: deprecated_member_use_from_same_package

part of 'smart_terminal_side_panel.dart';

/// 对话 UI 构建（历史对话、轮次编排、气泡布局）
mixin _PanelConversationMixin on _PanelStateFields {
  Widget _buildAgentBody(ColorScheme colorScheme, bool connected) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        // F110: 折叠式历史对话
        for (var i = 0; i < _agentHistory.length; i++) ...[
          _buildCollapsibleHistoryEntry(i, colorScheme),
          if (i < _agentHistory.length - 1) const SizedBox(height: 6),
        ],

        // F110: 历史/当前分界线
        if (_agentHistory.isNotEmpty && _agentIntent != null)
          _buildRoundDivider(colorScheme, _agentHistory.length),

        // F110: 追问衔接提示
        if (_agentHistory.isNotEmpty && _agentIntent != null)
          _buildContinuationHint(colorScheme),

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

  /// 从历史条目提取阶段摘要标签
  String _buildStageLabel(_AgentHistoryEntry entry) {
    final toolCount = entry.traces.length;
    final hasFollowUp = entry.answers.isNotEmpty;
    final result = entry.result;

    final resultLabel = result != null
        ? switch (result.responseType) {
            'message' => '回答了你的问题',
            'ai_prompt' => '生成了 AI Prompt',
            _ => result.steps.isNotEmpty
                ? '生成了 ${result.steps.length} 条命令'
                : '生成了命令',
          }
        : entry.error != null
            ? '出错了'
            : '已结束';

    final prefix = hasFollowUp
        ? '追问后'
        : toolCount > 0
            ? '探索了 $toolCount 步'
            : '';

    if (prefix.isEmpty) return resultLabel;
    return '$prefix → $resultLabel';
  }

  /// 折叠式历史轮次组件
  Widget _buildCollapsibleHistoryEntry(int index, ColorScheme colorScheme) {
    final entry = _agentHistory[index];
    final isExpanded = _expandedHistorySet.contains(index);
    final stageLabel = _buildStageLabel(entry);
    final roundLabel = '第 ${index + 1} 轮';

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        // 轮次标签
        Padding(
          padding: const EdgeInsets.only(bottom: 4),
          child: Text(
            roundLabel,
            style: Theme.of(context).textTheme.labelSmall?.copyWith(
                  color: colorScheme.onSurfaceVariant.withValues(alpha: 0.6),
                  fontSize: 10,
                ),
          ),
        ),
        // 折叠/展开的摘要行
        GestureDetector(
          onTap: () {
            setState(() {
              if (isExpanded) {
                _expandedHistorySet.remove(index);
              } else {
                _expandedHistorySet.add(index);
              }
            });
          },
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
            decoration: BoxDecoration(
              color: colorScheme.surfaceContainerLow,
              borderRadius: BorderRadius.circular(10),
              border: Border.all(
                color: colorScheme.outlineVariant.withValues(alpha: 0.12),
              ),
            ),
            child: Row(
              children: [
                Icon(
                  entry.error != null
                      ? Icons.error_outline
                      : Icons.chat_bubble_outline,
                  size: 14,
                  color: entry.error != null
                      ? colorScheme.error
                      : colorScheme.primary,
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        entry.intent,
                        style: Theme.of(context).textTheme.bodySmall?.copyWith(
                              fontWeight: FontWeight.w500,
                            ),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                      ),
                      const SizedBox(height: 2),
                      Text(
                        stageLabel,
                        style:
                            Theme.of(context).textTheme.labelSmall?.copyWith(
                                  color: colorScheme.onSurfaceVariant,
                                  fontSize: 10,
                                ),
                      ),
                    ],
                  ),
                ),
                const SizedBox(width: 4),
                AnimatedRotation(
                  turns: isExpanded ? 0.25 : 0,
                  duration: const Duration(milliseconds: 200),
                  child: Icon(
                    Icons.chevron_right,
                    size: 16,
                    color: colorScheme.onSurfaceVariant.withValues(alpha: 0.5),
                  ),
                ),
              ],
            ),
          ),
        ),
        // 展开内容
        if (isExpanded) ...[
          const SizedBox(height: 6),
          Padding(
            padding: const EdgeInsets.only(left: 8),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _buildUserBubble(
                  entry.intent,
                  historyIndex: index,
                  canEdit: true,
                ),
                const SizedBox(height: 8),
                ..._buildOrderedTurnEvents(
                  order: entry.turnEventOrder,
                  answers: entry.answers,
                  assistantMessages: entry.assistantMessages,
                  colorScheme: colorScheme,
                  historyIndex: index,
                ),
                if (entry.result != null)
                  _buildHistoryResultBubble(entry.result!, colorScheme)
                else if (entry.error != null)
                  _buildHistoryErrorBubble(entry.error!, colorScheme),
              ],
            ),
          ),
        ],
      ],
    );
  }

  /// 历史/当前轮次分界线
  Widget _buildRoundDivider(ColorScheme colorScheme, int roundIndex) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 8),
      child: Row(
        children: [
          Expanded(
            child: Container(
              height: 1,
              color: colorScheme.outlineVariant.withValues(alpha: 0.2),
            ),
          ),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 8),
            child: Text(
              '第 ${roundIndex + 1} 轮',
              style: Theme.of(context).textTheme.labelSmall?.copyWith(
                    color: colorScheme.onSurfaceVariant.withValues(alpha: 0.5),
                    fontSize: 10,
                  ),
            ),
          ),
          Expanded(
            child: Container(
              height: 1,
              color: colorScheme.outlineVariant.withValues(alpha: 0.2),
            ),
          ),
        ],
      ),
    );
  }

  /// 追问衔接提示
  Widget _buildContinuationHint(ColorScheme colorScheme) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 6),
      child: Row(
        children: [
          Icon(
            Icons.reply_rounded,
            size: 12,
            color: colorScheme.primary.withValues(alpha: 0.6),
          ),
          const SizedBox(width: 4),
          Text(
            '基于上轮结果继续',
            style: Theme.of(context).textTheme.labelSmall?.copyWith(
                  color: colorScheme.primary.withValues(alpha: 0.7),
                  fontSize: 10,
                ),
          ),
        ],
      ),
    );
  }

  /// 按 turnEventOrder 交错渲染 answers 和 assistantMessages
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

  /// 历史结果气泡
  Widget _buildHistoryResultBubble(
      AgentResultEvent result, ColorScheme colorScheme) {
    final rt = result.responseType;

    if (rt == 'message') {
      return _buildAssistantBubble(
        Text(
          result.summary,
          style: Theme.of(context).textTheme.bodyMedium,
        ),
      );
    }

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
              ),
            ],
          ],
        ),
      );
    }

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
}
