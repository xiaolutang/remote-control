part of 'smart_terminal_side_panel.dart';

/// 输入区域 + 用户气泡 + 内联编辑 UI + 选项选择
mixin _PanelInputMixin on _PanelStateFields {
  Widget _buildInputBar(ColorScheme colorScheme) {
    final isExploring = _isPhaseActive();
    final isAwaitingAnswer = _currentPhase == AgentPhase.confirming;
    final isClosed = _terminalConversationClosed;
    final canSend = !isClosed && !_pendingReset && (isAwaitingAnswer ? !_executing : !_executing && !isExploring);
    return Container(padding: const EdgeInsets.fromLTRB(12, 8, 12, 14),
      decoration: BoxDecoration(color: colorScheme.surface,
        border: Border(top: BorderSide(color: colorScheme.outlineVariant.withValues(alpha: 0.14)))),
      child: Row(crossAxisAlignment: CrossAxisAlignment.center, children: [
        Expanded(child: ConstrainedBox(constraints: const BoxConstraints(minHeight: 44),
          child: Center(child: TextField(key: const Key('side-panel-intent-input'),
            controller: _intentController, focusNode: _intentFocusNode,
            enabled: !isClosed && !_pendingReset, textInputAction: TextInputAction.send,
            textAlignVertical: TextAlignVertical.center,
            decoration: InputDecoration(
              hintText: isClosed ? 'terminal 已关闭，无法继续智能交互'
                  : _currentPhase == AgentPhase.confirming ? '输入回答...' : '说目标，例如：进入日知项目',
              border: OutlineInputBorder(borderRadius: BorderRadius.circular(16), borderSide: BorderSide(color: colorScheme.outlineVariant.withValues(alpha: 0.3))),
              enabledBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(16), borderSide: BorderSide(color: colorScheme.outlineVariant.withValues(alpha: 0.3))),
              focusedBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(16), borderSide: BorderSide(color: colorScheme.primary)),
              isDense: true, contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10)),
            minLines: 1, maxLines: 3, style: Theme.of(context).textTheme.bodyMedium,
            onSubmitted: (_) { _handleInputSubmit(); })))),
        const SizedBox(width: 8),
        SizedBox(width: 44, height: 44, child: FilledButton(key: const Key('side-panel-send'),
          style: FilledButton.styleFrom(padding: EdgeInsets.zero,
            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)), backgroundColor: colorScheme.primary),
          onPressed: canSend ? _handleInputSubmit : null,
          child: isExploring ? SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2, color: colorScheme.onPrimary))
              : const Icon(Icons.arrow_upward, size: 18))),
      ]));
  }

  /// Asking：助手气泡 + 选项
  Widget _buildAskingView(ColorScheme colorScheme) {
    final question = _currentQuestion;
    if (question == null) return const SizedBox.shrink();
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      _buildAssistantBubble(Text(question.question, style: Theme.of(context).textTheme.bodyMedium)),
      const SizedBox(height: 10),
      if (question.options.isNotEmpty) ...[
        if (question.multiSelect) _buildMultiSelectOptions(question, colorScheme)
        else _buildSingleSelectOptions(question, colorScheme),
        const SizedBox(height: 8),
      ],
    ]);
  }

  Widget _buildSingleSelectOptions(AgentQuestionEvent question, ColorScheme colorScheme) {
    return Wrap(spacing: 6, runSpacing: 6, children: [
      for (final option in question.options) OutlinedButton(
        key: Key('agent-option-${option.hashCode}'),
        style: OutlinedButton.styleFrom(padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
          side: BorderSide(color: colorScheme.outlineVariant.withValues(alpha: 0.4)), backgroundColor: colorScheme.surface),
        onPressed: _pendingReset ? null : () => _handleAgentRespond(option),
        child: Text(option, style: Theme.of(context).textTheme.bodySmall?.copyWith(color: colorScheme.onSurface))),
    ]);
  }

  Widget _buildMultiSelectOptions(AgentQuestionEvent question, ColorScheme colorScheme) {
    return Container(padding: const EdgeInsets.all(8),
      decoration: BoxDecoration(color: colorScheme.surfaceContainerLow, borderRadius: BorderRadius.circular(12),
        border: Border.all(color: colorScheme.outlineVariant.withValues(alpha: 0.14))),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        for (final option in question.options) _buildCheckboxOption(option, colorScheme),
        const SizedBox(height: 8),
        SizedBox(width: double.infinity, child: FilledButton(key: const Key('agent-multi-select-confirm'),
          style: FilledButton.styleFrom(minimumSize: const Size.fromHeight(36),
            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)), backgroundColor: colorScheme.primary),
          onPressed: _multiSelectChosen.isNotEmpty && !_pendingReset ? () => _handleAgentRespond(_multiSelectChosen.join(', ')) : null,
          child: const Text('确认选择'))),
      ]));
  }

  Widget _buildCheckboxOption(String option, ColorScheme colorScheme) {
    final chosen = _multiSelectChosen.contains(option);
    return InkWell(onTap: _pendingReset ? null : () {
      setState(() { if (chosen) _multiSelectChosen.remove(option); else _multiSelectChosen.add(option); });
    }, child: Padding(padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(children: [
        SizedBox(width: 20, height: 20, child: Checkbox(value: chosen, onChanged: _pendingReset ? null : (v) {
          setState(() { if (v == true) _multiSelectChosen.add(option); else _multiSelectChosen.remove(option); });
        })),
        const SizedBox(width: 8), Expanded(child: Text(option, style: Theme.of(context).textTheme.bodySmall)),
      ])));
  }

  Widget _buildUserBubble(String text, {int? historyIndex, bool canEdit = false, int? answerIndex, bool isLiveAnswer = false}) {
    final colorScheme = Theme.of(context).colorScheme;
    final isEditing = canEdit && _editingHistoryIndex != null &&
        (isLiveAnswer ? _editingHistoryIndex == -1 : _editingHistoryIndex == (historyIndex ?? -1)) && _editingAnswerIndex == answerIndex;
    if (isEditing) return _buildInlineEditBubble(text, historyIndex: historyIndex, colorScheme: colorScheme);
    return Align(alignment: Alignment.centerRight,
      child: ConstrainedBox(constraints: const BoxConstraints(maxWidth: 280),
        child: GestureDetector(
          onTap: canEdit ? () => _startInlineEdit(historyIndex, answerIndex: answerIndex) : null,
          child: Container(padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
            decoration: BoxDecoration(color: colorScheme.primaryContainer,
              borderRadius: const BorderRadius.only(topLeft: Radius.circular(18), topRight: Radius.circular(18),
                  bottomLeft: Radius.circular(18), bottomRight: Radius.circular(4))),
            child: Row(mainAxisSize: MainAxisSize.min, children: [
              Flexible(child: Text(text, style: Theme.of(context).textTheme.bodyMedium)),
              if (canEdit) ...[const SizedBox(width: 6),
                Icon(Icons.edit_outlined, size: 14, color: Theme.of(context).colorScheme.onSurface.withValues(alpha: 0.4))],
            ])))));
  }

  Widget _buildInlineEditBubble(String originalText, {int? historyIndex, required ColorScheme colorScheme}) {
    return Align(alignment: Alignment.centerRight,
      child: ConstrainedBox(constraints: const BoxConstraints(maxWidth: 280),
        child: Container(padding: const EdgeInsets.all(10),
          decoration: BoxDecoration(color: colorScheme.primaryContainer,
            borderRadius: const BorderRadius.only(topLeft: Radius.circular(18), topRight: Radius.circular(18),
                bottomLeft: Radius.circular(18), bottomRight: Radius.circular(4)),
            border: Border.all(color: colorScheme.primary, width: 1.5)),
          child: Column(crossAxisAlignment: CrossAxisAlignment.end, mainAxisSize: MainAxisSize.min, children: [
            TextField(controller: _editingController, enabled: !_pendingReset, autofocus: true, maxLines: null,
              style: Theme.of(context).textTheme.bodyMedium,
              decoration: InputDecoration(isDense: true,
                contentPadding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
                border: OutlineInputBorder(borderRadius: BorderRadius.circular(8), borderSide: BorderSide(color: colorScheme.outline)),
                enabledBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(8), borderSide: BorderSide(color: colorScheme.outline)),
                focusedBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(8), borderSide: BorderSide(color: colorScheme.primary, width: 1.5)),
                filled: true, fillColor: colorScheme.surfaceContainerLow)),
            const SizedBox(height: 8),
            Row(mainAxisSize: MainAxisSize.min, children: [
              SizedBox(height: 30, child: TextButton(onPressed: _cancelInlineEdit,
                style: TextButton.styleFrom(padding: const EdgeInsets.symmetric(horizontal: 12), minimumSize: Size.zero),
                child: Text('取消', style: TextStyle(fontSize: 13, color: colorScheme.onSurface.withValues(alpha: 0.6))))),
              const SizedBox(width: 4),
              SizedBox(height: 30, child: FilledButton(
                onPressed: _pendingReset ? null : () => _submitInlineEdit(historyIndex: historyIndex),
                style: FilledButton.styleFrom(padding: const EdgeInsets.symmetric(horizontal: 12), minimumSize: Size.zero),
                child: const Text('发送', style: TextStyle(fontSize: 13)))),
            ]),
          ]))));
  }
}
