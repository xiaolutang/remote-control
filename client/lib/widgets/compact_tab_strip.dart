import 'package:flutter/material.dart';

import '../models/runtime_terminal.dart';

/// Compact tab strip for mobile terminal switching.
///
/// Displays numbered tabs in a horizontal row, supporting tap-to-switch,
/// create (+) button, long-press context menu, and swipe gestures to
/// navigate between adjacent terminals.
///
/// Each tab expands equally to fill available space. Titles are truncated
/// with ellipsis when the available width per tab is narrow (e.g. many
/// terminals). Swipe-to-switch is handled at the strip level via a fling
/// gesture recognizer that does not compete with any scroll view.
class CompactTabStrip extends StatelessWidget {
  const CompactTabStrip({
    super.key,
    required this.terminals,
    required this.selectedTerminalId,
    required this.onSwitch,
    required this.onCreate,
    this.createDisabled = false,
    this.onLongPress,
  });

  /// List of terminal sessions to display as tabs.
  final List<RuntimeTerminal> terminals;

  /// ID of the currently selected terminal, or null if none selected.
  final String? selectedTerminalId;

  /// Called when user taps a terminal tab.
  final ValueChanged<String> onSwitch;

  /// Called when user taps the create (+) button.
  final VoidCallback onCreate;

  /// Called when user long-presses a terminal tab.
  final ValueChanged<String>? onLongPress;

  /// When true, the create (+) button is disabled.
  /// The caller should derive this from the authoritative source
  /// (e.g. `RuntimeDevice.canCreateTerminal`), not from a local count.
  final bool createDisabled;

  bool get _createDisabled => createDisabled;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colorScheme = theme.colorScheme;

    return GestureDetector(
      onHorizontalDragEnd: (details) => _handleSwipe(details),
      child: Container(
        height: 44,
        color: colorScheme.surfaceContainerHigh,
        child: Row(
          children: [
            for (var i = 0; i < terminals.length; i++)
              Expanded(
                child: _buildCompactTab(
                  terminal: terminals[i],
                  index: i,
                  isSelected: terminals[i].terminalId == selectedTerminalId,
                  colorScheme: colorScheme,
                  theme: theme,
                ),
              ),
            _buildCreateButton(colorScheme),
          ],
        ),
      ),
    );
  }

  Widget _buildCompactTab({
    required RuntimeTerminal terminal,
    required int index,
    required bool isSelected,
    required ColorScheme colorScheme,
    required ThemeData theme,
  }) {
    final canSwitch = terminal.canAttach;
    final bgColor = isSelected
        ? colorScheme.primary
        : Colors.transparent;
    final fgColor = isSelected
        ? colorScheme.onPrimary
        : (canSwitch
            ? colorScheme.onSurface
            : colorScheme.onSurface.withValues(alpha: 0.38));

    return InkWell(
      key: Key('compact-tab-${terminal.terminalId}'),
      onTap: canSwitch ? () => onSwitch(terminal.terminalId) : null,
      child: GestureDetector(
        onLongPressStart: onLongPress != null
            ? (details) => onLongPress!(terminal.terminalId)
            : null,
        child: DecoratedBox(
          decoration: BoxDecoration(
            color: bgColor,
            borderRadius: BorderRadius.circular(16),
          ),
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Text(
                  '${index + 1}',
                  style: theme.textTheme.labelMedium?.copyWith(
                    color: fgColor,
                    fontWeight: FontWeight.w700,
                  ),
                ),
                const SizedBox(width: 4),
                Flexible(
                  child: Text(
                    terminal.title,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: theme.textTheme.labelSmall?.copyWith(
                      color: fgColor,
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildCreateButton(ColorScheme colorScheme) {
    return SizedBox(
      key: const Key('compact-tab-create'),
      width: 36,
      height: 36,
      child: IconButton(
        onPressed: _createDisabled ? null : onCreate,
        icon: Icon(
          Icons.add,
          size: 18,
          color: _createDisabled
              ? colorScheme.onSurface.withValues(alpha: 0.38)
              : colorScheme.onSurface,
        ),
        padding: EdgeInsets.zero,
        constraints: const BoxConstraints(minWidth: 36, minHeight: 36),
        tooltip: _createDisabled ? '新建终端 (不可用)' : '新建终端',
      ),
    );
  }

  void _handleSwipe(DragEndDetails details) {
    final velocity = details.primaryVelocity ?? 0;
    if (velocity.abs() < 200) return; // ignore weak swipes

    final selectedIndex = terminals.indexWhere(
      (t) => t.terminalId == selectedTerminalId,
    );
    if (selectedIndex < 0) return;

    // Find the next/previous attachable terminal, skipping closed ones.
    // Swipe left (negative velocity) → next terminal
    // Swipe right (positive velocity) → previous terminal
    if (velocity < 0) {
      for (var i = selectedIndex + 1; i < terminals.length; i++) {
        if (terminals[i].canAttach) {
          onSwitch(terminals[i].terminalId);
          return;
        }
      }
    } else if (velocity > 0) {
      for (var i = selectedIndex - 1; i >= 0; i--) {
        if (terminals[i].canAttach) {
          onSwitch(terminals[i].terminalId);
          return;
        }
      }
    }
  }
}
