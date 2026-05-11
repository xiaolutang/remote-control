// ignore_for_file: annotate_overrides

part of 'smart_terminal_side_panel.dart';

/// 共享子组件（气泡、光标、工具卡片、Trace 列表、Usage Section 等）
mixin _PanelWidgetsMixin on _PanelStateFields {
  Widget _buildAssistantBubble(Widget child) {
    final colorScheme = Theme.of(context).colorScheme;
    return Align(alignment: Alignment.centerLeft,
      child: ConstrainedBox(constraints: const BoxConstraints(maxWidth: 340),
        child: Container(padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
          decoration: BoxDecoration(color: colorScheme.surfaceContainerLow,
            borderRadius: const BorderRadius.only(topLeft: Radius.circular(18), topRight: Radius.circular(18),
                bottomLeft: Radius.circular(4), bottomRight: Radius.circular(18)),
            border: Border.all(color: subtleBorderColor(colorScheme))),
          child: child)));
  }

  Widget _buildLoadingBubble(String text, ColorScheme colorScheme) {
    return _buildAssistantBubble(Row(mainAxisSize: MainAxisSize.min, children: [
      SizedBox(width: 14, height: 14, child: CircularProgressIndicator(strokeWidth: 2, color: colorScheme.primary)),
      const SizedBox(width: 10), Text(text, style: Theme.of(context).textTheme.bodySmall),
    ]));
  }

  Widget _buildBlinkingCursor(ColorScheme colorScheme) => BlinkingCursor(colorScheme: colorScheme);
  Widget _buildToolStepCard(ToolStepEvent step, ColorScheme colorScheme) => ToolStepCard(step: step, colorScheme: colorScheme);

  /// 可折叠 Agent Trace 列表
  Widget _buildAgentTraceExpansionTile(ColorScheme colorScheme) {
    return Container(decoration: BoxDecoration(color: colorScheme.surfaceContainerLow, borderRadius: AppRadius.cardBorder,
      border: Border.all(color: subtleBorderColor(colorScheme))),
      child: ExpansionTile(key: const Key('agent-trace-expansion'), initiallyExpanded: false,
        tilePadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
        childrenPadding: const EdgeInsets.fromLTRB(12, 0, 12, 8), dense: true,
        title: Text('探索进度 (${_traces.length})',
          style: Theme.of(context).textTheme.bodySmall?.copyWith(color: colorScheme.onSurfaceVariant, fontWeight: FontWeight.w600)),
        children: [for (final trace in _traces) ...[
          _buildAgentTraceItem(trace, colorScheme),
          if (trace != _traces.last) const SizedBox(height: 6),
        ]]));
  }

  Widget _buildAgentTraceItem(ToolStepEvent trace, ColorScheme colorScheme) {
    return _buildAssistantBubble(Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Row(children: [SidePanelStagePill(stage: 'tool'), const SizedBox(width: 8),
        Expanded(child: Text(trace.toolName, style: Theme.of(context).textTheme.bodySmall?.copyWith(fontWeight: FontWeight.w600)))]),
      const SizedBox(height: 4),
      Text(trace.description, style: Theme.of(context).textTheme.bodySmall?.copyWith(color: colorScheme.onSurfaceVariant, height: 1.4)),
      if (trace.resultSummary != null && trace.resultSummary!.isNotEmpty) ...[const SizedBox(height: 2),
        Text(trace.resultSummary!, style: Theme.of(context).textTheme.bodySmall?.copyWith(
            color: colorScheme.onSurfaceVariant.withValues(alpha: 0.7), height: 1.3),
          maxLines: 5, overflow: TextOverflow.ellipsis)],
    ]));
  }

  /// Usage Section: 底部固定的可展开/收起区域
  Widget _buildUsageSection(ColorScheme colorScheme) {
    final summary = _usageSummary;
    final totalTokens = summary?.user.totalTokens ?? 0;
    // 使用服务端 terminal scope 数据，不 fallback 到本地累加器
    final terminalScope = summary?.terminal;
    final currentTokens = terminalScope?.totalTokens ?? 0;
    final currentRequests = terminalScope?.totalRequests ?? 0;
    final hasError = _usageSummaryError != null && summary == null;
    final isCurrentLoading = terminalScope == null && _usageSummaryLoading;
    final isCurrentUnavailable = terminalScope == null && !_usageSummaryLoading && summary != null;

    return Container(
      key: const Key('side-panel-usage-section'),
      decoration: BoxDecoration(
        color: colorScheme.surfaceContainerLow,
        borderRadius: AppRadius.cardBorder,
        border: Border.all(color: subtleBorderColor(colorScheme)),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        // 收起/展开摘要行
        GestureDetector(
          key: const Key('side-panel-usage-toggle'),
          onTap: () => setState(() => _usageExpanded = !_usageExpanded),
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
            child: Row(children: [
              Icon(Icons.data_usage_outlined, size: 16, color: colorScheme.primary),
              const SizedBox(width: 8),
              Expanded(child: hasError
                ? Text(_usageSummaryError ?? '加载失败', key: const Key('side-panel-usage-error'),
                    style: Theme.of(context).textTheme.bodySmall?.copyWith(color: colorScheme.error))
                : Builder(builder: (context) {
                    final currentLabel = isCurrentLoading
                        ? '加载中...'
                        : isCurrentUnavailable
                            ? '暂无数据'
                            : '$currentTokens';
                    return Text('总消耗 $totalTokens · 当前对话 $currentLabel',
                        key: const Key('side-panel-usage-summary'),
                        style: Theme.of(context).textTheme.bodySmall?.copyWith(
                          color: colorScheme.onSurfaceVariant, fontWeight: FontWeight.w500));
                  })),
              if (_usageSummaryLoading)
                SizedBox(width: 14, height: 14,
                  child: CircularProgressIndicator(strokeWidth: 2, color: colorScheme.primary)),
              const SizedBox(width: 4),
              AnimatedRotation(
                turns: _usageExpanded ? 0.25 : 0,
                duration: const Duration(milliseconds: 200),
                child: Icon(Icons.chevron_right, size: 16, color: colorScheme.onSurfaceVariant),
              ),
            ]),
          ),
        ),
        // 展开详情
        if (_usageExpanded) ...[
          const Divider(height: 1, indent: 12, endIndent: 12),
          Padding(padding: const EdgeInsets.fromLTRB(12, 8, 12, 10),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              // 总消耗段
              Text('总消耗', key: const Key('side-panel-usage-total-label'),
                style: Theme.of(context).textTheme.labelLarge?.copyWith(
                  fontWeight: FontWeight.w700, color: colorScheme.onSurfaceVariant)),
              const SizedBox(height: 4),
              if (summary != null) ...[
                _buildUsageStatRow('终端', summary.device.totalTokens, summary.device.totalRequests, colorScheme),
                const SizedBox(width: 2),
                _buildUsageStatRow('我的', summary.user.totalTokens, summary.user.totalRequests, colorScheme),
              ] else ...[
                Text(_usageSummaryError ?? '—',
                  style: Theme.of(context).textTheme.bodySmall?.copyWith(color: colorScheme.error)),
              ],
              const SizedBox(height: 10),
              // 当前对话段
              Text('当前对话', key: const Key('side-panel-usage-current-label'),
                style: Theme.of(context).textTheme.labelLarge?.copyWith(
                  fontWeight: FontWeight.w700, color: colorScheme.onSurfaceVariant)),
              const SizedBox(height: 4),
              if (isCurrentLoading)
                Text('加载中...', style: Theme.of(context).textTheme.bodySmall?.copyWith(color: colorScheme.onSurfaceVariant))
              else if (isCurrentUnavailable)
                Text('暂无数据', style: Theme.of(context).textTheme.bodySmall?.copyWith(color: colorScheme.onSurfaceVariant))
              else
                _buildUsageStatRow('对话', currentTokens, currentRequests, colorScheme),
            ]),
          ),
        ],
      ]),
    );
  }

  Widget _buildUsageStatRow(String label, int tokens, int requests, ColorScheme colorScheme) {
    return Row(children: [
      SizedBox(width: 40, child: Text(label, style: Theme.of(context).textTheme.bodySmall?.copyWith(
        color: colorScheme.onSurfaceVariant, fontWeight: FontWeight.w500))),
      Text('$tokens tokens', style: Theme.of(context).textTheme.bodySmall?.copyWith(
        fontWeight: FontWeight.w600, color: colorScheme.onSurface)),
      const SizedBox(width: 8),
      Text('$requests 次', style: Theme.of(context).textTheme.bodySmall?.copyWith(
        color: colorScheme.onSurfaceVariant)),
    ]);
  }

}
