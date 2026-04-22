part of 'smart_terminal_create_dialog.dart';

class _SmartTerminalManualConfirm extends StatelessWidget {
  const _SmartTerminalManualConfirm({
    required this.accepted,
    required this.onChanged,
  });

  final bool accepted;
  final ValueChanged<bool>? onChanged;

  @override
  Widget build(BuildContext context) {
    final colorScheme = Theme.of(context).colorScheme;
    return InkWell(
      key: const Key('smart-create-confirm-manual'),
      borderRadius: BorderRadius.circular(18),
      onTap: onChanged == null ? null : () => onChanged!(!accepted),
      child: Container(
        width: double.infinity,
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          color: accepted
              ? const Color(0xFFEAF6EE)
              : colorScheme.tertiaryContainer.withValues(alpha: 0.56),
          borderRadius: BorderRadius.circular(18),
          border: Border.all(
            color: accepted
                ? const Color(0xFFB9DFC2)
                : colorScheme.outlineVariant.withValues(alpha: 0.28),
          ),
        ),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Checkbox(
              value: accepted,
              onChanged: onChanged == null
                  ? null
                  : (value) => onChanged!(value ?? false),
            ),
            const SizedBox(width: 8),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const SizedBox(height: 8),
                  Text(
                    '我已确认目录和命令步骤',
                    style: Theme.of(context).textTheme.titleSmall,
                  ),
                  const SizedBox(height: 4),
                  Text(
                    '涉及路径变更，需要你最后确认一次。',
                    style: Theme.of(context).textTheme.bodySmall?.copyWith(
                          color: colorScheme.onTertiaryContainer,
                        ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _SmartTerminalIntentComposer extends StatelessWidget {
  const _SmartTerminalIntentComposer({
    required this.controller,
    required this.focusNode,
    required this.creating,
    required this.resolvingIntent,
    required this.onResolveIntent,
  });

  final TextEditingController controller;
  final FocusNode focusNode;
  final bool creating;
  final bool resolvingIntent;
  final Future<void> Function() onResolveIntent;

  @override
  Widget build(BuildContext context) {
    final colorScheme = Theme.of(context).colorScheme;
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(16, 10, 12, 10),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(24),
        border: Border.all(
          color: colorScheme.outlineVariant.withValues(alpha: 0.3),
        ),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withValues(alpha: 0.025),
            blurRadius: 12,
            offset: const Offset(0, 4),
          ),
        ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.center,
            children: [
              Expanded(
                child: ConstrainedBox(
                  constraints: const BoxConstraints(minHeight: 52),
                  child: Center(
                    child: TextField(
                      key: const Key('smart-create-intent-input'),
                      controller: controller,
                      focusNode: focusNode,
                      autofocus: true,
                      textInputAction: TextInputAction.send,
                      textAlignVertical: TextAlignVertical.center,
                      decoration: const InputDecoration(
                        hintText: '说目标，例如：进入日知项目',
                        border: InputBorder.none,
                        isDense: true,
                        contentPadding: EdgeInsets.zero,
                      ),
                      minLines: 1,
                      maxLines: 4,
                      style: Theme.of(context).textTheme.bodyLarge,
                      onSubmitted: (_) {
                        if (!creating && !resolvingIntent) {
                          onResolveIntent();
                        }
                      },
                    ),
                  ),
                ),
              ),
              const SizedBox(width: 10),
              FilledButton(
                key: const Key('smart-create-generate'),
                style: FilledButton.styleFrom(
                  minimumSize: const Size(52, 52),
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(18),
                  ),
                  padding: EdgeInsets.zero,
                  backgroundColor: const Color(0xFF1F5EFF),
                ),
                onPressed: creating || resolvingIntent ? null : onResolveIntent,
                child: resolvingIntent
                    ? const _SmallLoadingSpinner(
                        size: 18,
                        color: Colors.white,
                      )
                    : const Icon(Icons.arrow_upward),
              ),
            ],
          ),
        ],
      ),
    );
  }
}
