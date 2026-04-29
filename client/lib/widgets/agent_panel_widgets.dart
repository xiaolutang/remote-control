// ignore_for_file: annotate_overrides, deprecated_member_use_from_same_package

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
            border: Border.all(color: colorScheme.outlineVariant.withValues(alpha: 0.15))),
          child: child)));
  }

  Widget _buildLoadingBubble(String text, ColorScheme colorScheme) {
    return _buildAssistantBubble(Row(mainAxisSize: MainAxisSize.min, children: [
      SizedBox(width: 14, height: 14, child: CircularProgressIndicator(strokeWidth: 2, color: colorScheme.primary)),
      const SizedBox(width: 10), Text(text, style: Theme.of(context).textTheme.bodySmall),
    ]));
  }

  Widget _buildBlinkingCursor(ColorScheme colorScheme) => _BlinkingCursor(colorScheme: colorScheme);
  Widget _buildToolStepCard(ToolStepEvent step, ColorScheme colorScheme) => _ToolStepCard(step: step, colorScheme: colorScheme);

  /// 可折叠 Agent Trace 列表
  Widget _buildAgentTraceExpansionTile(ColorScheme colorScheme) {
    return Container(decoration: BoxDecoration(color: colorScheme.surfaceContainerLow, borderRadius: BorderRadius.circular(12),
      border: Border.all(color: colorScheme.outlineVariant.withValues(alpha: 0.14))),
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

  Widget _buildAgentTraceItem(AgentTraceEvent trace, ColorScheme colorScheme) {
    return _buildAssistantBubble(Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Row(children: [_SidePanelStagePill(stage: 'tool'), const SizedBox(width: 8),
        Expanded(child: Text(trace.tool, style: Theme.of(context).textTheme.bodySmall?.copyWith(fontWeight: FontWeight.w600)))]),
      const SizedBox(height: 4),
      Text(trace.inputSummary, style: Theme.of(context).textTheme.bodySmall?.copyWith(color: colorScheme.onSurfaceVariant, height: 1.4)),
      if (trace.outputSummary.isNotEmpty) ...[const SizedBox(height: 2),
        Text(trace.outputSummary, style: Theme.of(context).textTheme.bodySmall?.copyWith(
            color: colorScheme.onSurfaceVariant.withValues(alpha: 0.7), height: 1.3),
          maxLines: 5, overflow: TextOverflow.ellipsis)],
    ]));
  }

  /// Usage Section: 底部固定的可展开/收起区域
  Widget _buildUsageSection(ColorScheme colorScheme) {
    final summary = _usageSummary;
    final totalTokens = summary?.user.totalTokens ?? 0;
    // 优先使用服务端 terminal scope 数据，fallback 到本地累加器
    final terminalScope = summary?.terminal;
    final currentTokens = terminalScope?.totalTokens ?? _sessionUsageAccumulator.totalTokens;
    final currentRequests = terminalScope?.totalRequests ?? _sessionUsageAccumulator.requests;
    final hasError = _usageSummaryError != null && summary == null;

    return Container(
      key: const Key('side-panel-usage-section'),
      decoration: BoxDecoration(
        color: colorScheme.surfaceContainerLow,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: colorScheme.outlineVariant.withValues(alpha: 0.14)),
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
                : Text('总消耗 $totalTokens · 当前对话 $currentTokens',
                    key: const Key('side-panel-usage-summary'),
                    style: Theme.of(context).textTheme.bodySmall?.copyWith(
                      color: colorScheme.onSurfaceVariant, fontWeight: FontWeight.w500))),
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
                const SizedBox(height: 2),
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

// --- 独立 Widget 组件 ---

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
    return Container(padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
      decoration: BoxDecoration(color: bg, borderRadius: BorderRadius.circular(999)),
      child: Text(label, style: Theme.of(context).textTheme.labelSmall?.copyWith(color: fg, fontWeight: FontWeight.w600, fontSize: 10)));
  }
}

class _BlinkingCursor extends StatefulWidget {
  const _BlinkingCursor({required this.colorScheme});
  final ColorScheme colorScheme;
  @override State<_BlinkingCursor> createState() => _BlinkingCursorState();
}

class _BlinkingCursorState extends State<_BlinkingCursor> with SingleTickerProviderStateMixin {
  late final AnimationController _controller;
  @override void initState() { super.initState(); _controller = AnimationController(vsync: this,
    duration: const Duration(milliseconds: 800), lowerBound: 0.15, upperBound: 1.0)..repeat(reverse: true); }
  @override void dispose() { _controller.dispose(); super.dispose(); }
  @override Widget build(BuildContext context) => AnimatedBuilder(animation: _controller,
    builder: (context, child) => Opacity(opacity: _controller.value, child: child),
    child: Container(width: 2, height: 14,
      decoration: BoxDecoration(color: widget.colorScheme.primary, borderRadius: BorderRadius.circular(1))));
}

class _ToolStepCard extends StatefulWidget {
  const _ToolStepCard({required this.step, required this.colorScheme});
  final ToolStepEvent step; final ColorScheme colorScheme;
  @override State<_ToolStepCard> createState() => _ToolStepCardState();
}

class _ToolStepCardState extends State<_ToolStepCard> {
  bool _expanded = false;
  @override Widget build(BuildContext context) {
    final step = widget.step; final colorScheme = widget.colorScheme;
    final Widget statusIcon = switch (step.status) {
      'running' => SizedBox(width: 14, height: 14, child: CircularProgressIndicator(strokeWidth: 2, color: colorScheme.primary)),
      'done' => Icon(Icons.check_circle, size: 14, color: Colors.green),
      'error' => Icon(Icons.error, size: 14, color: colorScheme.error),
      _ => Icon(Icons.build_outlined, size: 14, color: colorScheme.onSurfaceVariant),
    };
    final hasResult = step.resultSummary != null && step.resultSummary!.isNotEmpty;
    return Container(padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
      decoration: BoxDecoration(color: colorScheme.surfaceContainerLow, borderRadius: BorderRadius.circular(10),
        border: Border.all(color: colorScheme.outlineVariant.withValues(alpha: 0.12))),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [statusIcon, const SizedBox(width: 8),
          Expanded(child: Text(step.toolName, style: Theme.of(context).textTheme.bodySmall?.copyWith(fontWeight: FontWeight.w600),
            maxLines: 1, overflow: TextOverflow.ellipsis)),
          if (hasResult) GestureDetector(onTap: () => setState(() => _expanded = !_expanded),
            child: Icon(_expanded ? Icons.expand_less : Icons.expand_more, size: 16, color: colorScheme.onSurfaceVariant)),
        ]),
        if (step.description.isNotEmpty) ...[const SizedBox(height: 4),
          Text(step.description, style: Theme.of(context).textTheme.bodySmall?.copyWith(
              color: colorScheme.onSurfaceVariant, height: 1.4), maxLines: 3, overflow: TextOverflow.ellipsis)],
        if (hasResult && _expanded) ...[const SizedBox(height: 6),
          Container(width: double.infinity, padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
            decoration: BoxDecoration(color: colorScheme.surfaceContainerHighest.withValues(alpha: 0.5), borderRadius: BorderRadius.circular(6)),
            child: Text(step.resultSummary!, style: Theme.of(context).textTheme.bodySmall?.copyWith(
                color: colorScheme.onSurfaceVariant.withValues(alpha: 0.8), height: 1.3)))],
      ]));
  }
}
