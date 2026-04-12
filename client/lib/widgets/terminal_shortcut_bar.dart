import 'package:flutter/material.dart';

import '../models/shortcut_item.dart';

class TerminalShortcutBar extends StatelessWidget {
  const TerminalShortcutBar({
    super.key,
    required this.items,
    required this.onItemPressed,
    this.trailing,
  });

  final List<ShortcutItem> items;
  final ValueChanged<ShortcutItem> onItemPressed;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) {
    if (items.isEmpty && trailing == null) {
      return const SizedBox.shrink();
    }

    final colorScheme = Theme.of(context).colorScheme;
    final mediaQuery = MediaQuery.of(context);
    final bottomInset = mediaQuery.padding.bottom >
            mediaQuery.systemGestureInsets.bottom
        ? mediaQuery.padding.bottom
        : mediaQuery.systemGestureInsets.bottom;

    return Container(
      color: colorScheme.surfaceContainerHigh,
      child: Padding(
        padding: EdgeInsets.fromLTRB(8, 6, 8, 8 + bottomInset),
        child: Row(
          children: [
            Expanded(
              child: SingleChildScrollView(
                scrollDirection: Axis.horizontal,
                child: Row(
                  children: [
                    for (final item in items)
                      Padding(
                        padding: const EdgeInsets.symmetric(horizontal: 4),
                        child: OutlinedButton(
                          onPressed: () => onItemPressed(item),
                          style: OutlinedButton.styleFrom(
                            foregroundColor: colorScheme.onSurface,
                            backgroundColor: colorScheme.surface,
                            side: BorderSide(color: colorScheme.outlineVariant),
                          ),
                          child: Text(item.label),
                        ),
                      ),
                  ],
                ),
              ),
            ),
            if (trailing != null) ...[
              const SizedBox(width: 8),
              trailing!,
            ],
          ],
        ),
      ),
    );
  }
}
