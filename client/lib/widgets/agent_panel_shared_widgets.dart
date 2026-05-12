import 'package:flutter/material.dart';

import '../models/agent_session_event.dart';
import 'design_tokens.dart';

/// 阶段标签胶囊组件
class SidePanelStagePill extends StatelessWidget {
  const SidePanelStagePill({super.key, required this.stage});
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
      decoration: BoxDecoration(color: bg, borderRadius: BorderRadius.circular(999)),
      child: Text(label,
          style: Theme.of(context)
              .textTheme
              .labelSmall
              ?.copyWith(color: fg, fontWeight: FontWeight.w600, fontSize: 10)),
    );
  }
}

/// 闪烁光标动画组件
class BlinkingCursor extends StatefulWidget {
  const BlinkingCursor({super.key, required this.colorScheme});
  final ColorScheme colorScheme;

  @override
  State<BlinkingCursor> createState() => _BlinkingCursorState();
}

class _BlinkingCursorState extends State<BlinkingCursor>
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
  Widget build(BuildContext context) => AnimatedBuilder(
      animation: _controller,
      builder: (context, child) => Opacity(opacity: _controller.value, child: child),
      child: Container(
          width: 2,
          height: 14,
          decoration: BoxDecoration(
              color: widget.colorScheme.primary,
              borderRadius: BorderRadius.circular(1))));
}

/// 工具步骤卡片组件（可折叠结果详情）
class ToolStepCard extends StatefulWidget {
  const ToolStepCard({super.key, required this.step, required this.colorScheme});
  final ToolStepEvent step;
  final ColorScheme colorScheme;

  @override
  State<ToolStepCard> createState() => _ToolStepCardState();
}

class _ToolStepCardState extends State<ToolStepCard> {
  bool _expanded = false;

  @override
  Widget build(BuildContext context) {
    final step = widget.step;
    final colorScheme = widget.colorScheme;
    final Widget statusIcon = switch (step.status) {
      ToolStepStatus.running => SizedBox(
          width: 14,
          height: 14,
          child: CircularProgressIndicator(strokeWidth: 2, color: colorScheme.primary)),
      ToolStepStatus.done =>
        Icon(Icons.check_circle, size: 14, color: Colors.green),
      ToolStepStatus.error =>
        Icon(Icons.error, size: 14, color: colorScheme.error),
    };
    final hasResult =
        step.resultSummary != null && step.resultSummary!.isNotEmpty;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
      decoration: BoxDecoration(
          color: colorScheme.surfaceContainerLow,
          borderRadius: BorderRadius.circular(10),
          border: Border.all(color: subtleBorderColor(colorScheme))),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          statusIcon,
          const SizedBox(width: 8),
          Expanded(
              child: Text(step.toolName,
                  style: Theme.of(context)
                      .textTheme
                      .bodySmall
                      ?.copyWith(fontWeight: FontWeight.w600),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis)),
          if (hasResult)
            GestureDetector(
              onTap: () => setState(() => _expanded = !_expanded),
              child: Icon(
                  _expanded ? Icons.expand_less : Icons.expand_more,
                  size: 16,
                  color: colorScheme.onSurfaceVariant),
            ),
        ]),
        if (step.description.isNotEmpty) ...[
          const SizedBox(height: 4),
          Text(step.description,
              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                  color: colorScheme.onSurfaceVariant, height: 1.4),
              maxLines: 3,
              overflow: TextOverflow.ellipsis)
        ],
        if (hasResult && _expanded) ...[
          const SizedBox(height: 6),
          Container(
              width: double.infinity,
              padding:
                  const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
              decoration: BoxDecoration(
                  color: colorScheme.surfaceContainerHighest
                      .withValues(alpha: 0.5),
                  borderRadius: BorderRadius.circular(6)),
              child: Text(step.resultSummary!,
                  style: Theme.of(context).textTheme.bodySmall?.copyWith(
                      color:
                          colorScheme.onSurfaceVariant.withValues(alpha: 0.8),
                      height: 1.3)))
        ],
      ]),
    );
  }
}
