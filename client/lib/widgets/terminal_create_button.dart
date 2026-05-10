import 'package:flutter/material.dart';

/// Shared create (+) button used by both [TerminalTabBar] and [CompactTabStrip].
class TerminalCreateButton extends StatelessWidget {
  const TerminalCreateButton({
    super.key,
    required this.onCreate,
    this.createDisabled = false,
  });

  final VoidCallback onCreate;
  final bool createDisabled;

  @override
  Widget build(BuildContext context) {
    final colorScheme = Theme.of(context).colorScheme;
    return SizedBox(
      width: 36,
      height: 36,
      child: IconButton(
        onPressed: createDisabled ? null : onCreate,
        icon: Icon(
          Icons.add,
          size: 18,
          color: createDisabled
              ? colorScheme.onSurface.withValues(alpha: 0.38)
              : colorScheme.onSurface,
        ),
        padding: EdgeInsets.zero,
        constraints: const BoxConstraints(minWidth: 36, minHeight: 36),
        tooltip: createDisabled ? '新建终端 (不可用)' : '新建终端',
      ),
    );
  }
}
