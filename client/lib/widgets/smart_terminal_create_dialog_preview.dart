part of 'smart_terminal_create_dialog.dart';

class _TraceEventView extends StatelessWidget {
  const _TraceEventView({
    required this.item,
    this.fallbackReason,
  });

  final AssistantTraceItem item;
  final String? fallbackReason;

  @override
  Widget build(BuildContext context) {
    final colorScheme = Theme.of(context).colorScheme;
    final stageMeta = _traceStageMeta(item.stage, colorScheme);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          crossAxisAlignment: CrossAxisAlignment.center,
          children: [
            StatusPill(
              label: stageMeta.label,
              backgroundColor: stageMeta.background,
              textColor: stageMeta.foreground,
            ),
            const SizedBox(width: 10),
            Expanded(
              child: Text(
                item.title,
                style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                      fontWeight: FontWeight.w600,
                    ),
              ),
            ),
            _TraceStatusChip(status: item.status),
          ],
        ),
        const SizedBox(height: 8),
        Text(
          item.summary,
          style: Theme.of(context).textTheme.bodySmall?.copyWith(
                color: colorScheme.onSurfaceVariant,
                height: 1.45,
              ),
        ),
        if (fallbackReason != null)
          Padding(
            padding: const EdgeInsets.only(top: 8),
            child: Text(
              '兜底命令：$fallbackReason',
              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                    color: colorScheme.onSurfaceVariant,
                  ),
            ),
          ),
      ],
    );
  }
}

class _TraceStatusChip extends StatelessWidget {
  const _TraceStatusChip({
    required this.status,
  });

  final String status;

  @override
  Widget build(BuildContext context) {
    final colorScheme = Theme.of(context).colorScheme;
    final (background, text) = switch (status) {
      'completed' => (const Color(0xFFE6F6EC), const Color(0xFF1C7C45)),
      'running' => (const Color(0xFFE8F0FF), colorScheme.primary),
      'failed' => (colorScheme.errorContainer, colorScheme.error),
      _ => (const Color(0xFFF0F2F6), colorScheme.onSurfaceVariant),
    };
    return StatusPill(
      label: _statusLabel(status),
      backgroundColor: background,
      textColor: text,
    );
  }
}


class _ExecutionEventCard extends StatelessWidget {
  const _ExecutionEventCard({required this.event});

  final SmartTerminalExecutionEvent event;

  @override
  Widget build(BuildContext context) {
    final colorScheme = Theme.of(context).colorScheme;
    final (icon, color, label) = switch (event.status) {
      'success' => (Icons.check_circle_outline, Colors.green, '已完成'),
      'warning' => (Icons.info_outline, colorScheme.tertiary, '继续处理'),
      'error' => (Icons.error_outline, colorScheme.error, '失败'),
      _ => (Icons.sync, colorScheme.primary, '进行中'),
    };
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          crossAxisAlignment: CrossAxisAlignment.center,
          children: [
            Icon(icon, size: 16, color: color),
            const SizedBox(width: 8),
            Expanded(
              child: Text(
                event.title,
                style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                      fontWeight: FontWeight.w600,
                    ),
              ),
            ),
            _ExecutionStatusPill(
              label: label,
              color: color,
            ),
          ],
        ),
        const SizedBox(height: 6),
        Text(
          event.message,
          style: Theme.of(context).textTheme.bodySmall?.copyWith(
                color: colorScheme.onSurfaceVariant,
                height: 1.4,
              ),
        ),
      ],
    );
  }
}

class _CommandSequencePreview extends StatelessWidget {
  const _CommandSequencePreview({
    required this.draft,
    this.fallbackReason,
    required this.requiresManualConfirmation,
    required this.manualConfirmationAccepted,
    required this.onToggleManualConfirmation,
    required this.onSubmit,
    required this.creating,
    required this.submitEnabled,
  });

  final CommandSequenceDraft draft;
  final String? fallbackReason;
  final bool requiresManualConfirmation;
  final bool manualConfirmationAccepted;
  final ValueChanged<bool>? onToggleManualConfirmation;
  final Future<void> Function() onSubmit;
  final bool creating;
  final bool submitEnabled;

  @override
  Widget build(BuildContext context) {
    final colorScheme = Theme.of(context).colorScheme;
    final summary = draft.summary.trim().isEmpty ? '准备执行命令' : draft.summary;
    final cautionText = requiresManualConfirmation
        ? '请先确认目录和命令步骤，再继续创建。'
        : fallbackReason != null
            ? '这是一组兜底命令，建议先看一眼再执行。'
            : null;
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: Colors.white.withValues(alpha: 0.82),
        borderRadius: BorderRadius.circular(20),
        border: Border.all(
          color: colorScheme.outlineVariant.withValues(alpha: 0.14),
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            summary,
            key: const Key('smart-create-preview-summary'),
            style: Theme.of(context).textTheme.titleSmall?.copyWith(
                  fontWeight: FontWeight.w600,
                ),
          ),
          const SizedBox(height: 6),
          Text(
            '确认后执行。',
            key: const Key('smart-create-preview-info'),
            style: Theme.of(context).textTheme.bodySmall?.copyWith(
                  color: colorScheme.onSurfaceVariant,
                ),
          ),
          const SizedBox(height: 8),
          Text(
            '目录 · ${draft.cwd}    步骤 · ${draft.steps.length}',
            style: Theme.of(context).textTheme.bodySmall?.copyWith(
                  color: colorScheme.onSurfaceVariant,
                ),
          ),
          if (cautionText != null) ...[
            const SizedBox(height: 8),
            Text(
              cautionText,
              key: const Key('smart-create-preview-warning'),
              style: TextStyle(color: colorScheme.error),
            ),
          ],
          if (requiresManualConfirmation) ...[
            const SizedBox(height: 10),
            _SmartTerminalManualConfirm(
              accepted: manualConfirmationAccepted,
              onChanged: onToggleManualConfirmation,
            ),
          ],
          const SizedBox(height: 10),
          SizedBox(
            width: double.infinity,
            child: FilledButton(
              key: const Key('smart-create-submit'),
              style: FilledButton.styleFrom(
                minimumSize: const Size.fromHeight(44),
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(16),
                ),
              ),
              onPressed: submitEnabled ? onSubmit : null,
              child:
                  creating ? const _SmallLoadingSpinner() : const Text('创建并执行'),
            ),
          ),
        ],
      ),
    );
  }
}

class _ExecutionStatusPill extends StatelessWidget {
  const _ExecutionStatusPill({
    required this.label,
    required this.color,
  });

  final String label;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return StatusPill(
      label: label,
      backgroundColor: color.withValues(alpha: 0.12),
      textColor: color,
    );
  }
}

_TraceStageMeta _traceStageMeta(String stage, ColorScheme colorScheme) {
  switch (stage) {
    case 'tool':
    case 'tools':
      return _TraceStageMeta(
        label: '工具调用',
        background: const Color(0xFFEAF2FF),
        foreground: colorScheme.primary,
      );
    case 'context':
      return _TraceStageMeta(
        label: '上下文读取',
        background: const Color(0xFFF4EFE6),
        foreground: const Color(0xFF8B5E2B),
      );
    case 'plan':
    case 'planner':
      return _TraceStageMeta(
        label: '思考过程',
        background: const Color(0xFFF2EEFF),
        foreground: const Color(0xFF6852C8),
      );
    default:
      return _TraceStageMeta(
        label: '处理中',
        background: const Color(0xFFEFF3F8),
        foreground: colorScheme.onSurfaceVariant,
      );
  }
}

String _statusLabel(String status) {
  switch (status) {
    case 'completed':
      return '已完成';
    case 'running':
      return '进行中';
    case 'failed':
      return '失败';
    default:
      return '待处理';
  }
}

class _TraceStageMeta {
  const _TraceStageMeta({
    required this.label,
    required this.background,
    required this.foreground,
  });

  final String label;
  final Color background;
  final Color foreground;
}
