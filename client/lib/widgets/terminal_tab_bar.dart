import 'package:flutter/material.dart';

import '../models/runtime_terminal.dart';

/// Desktop tab bar for switching between terminal sessions.
///
/// Displays horizontal scrollable tabs with a create (+) button.
/// Supports visual selection state, max terminal limit, and
/// context menu via long press or secondary (right) click.
class TerminalTabBar extends StatelessWidget {
  const TerminalTabBar({
    super.key,
    required this.terminals,
    required this.selectedTerminalId,
    required this.onSwitch,
    required this.onCreate,
    this.createDisabled = false,
    this.onContextMenu,
  });

  /// List of terminal sessions to display as tabs.
  final List<RuntimeTerminal> terminals;

  /// ID of the currently selected terminal, or null if none selected.
  final String? selectedTerminalId;

  /// Called when user taps a terminal tab.
  final ValueChanged<String> onSwitch;

  /// Called when user taps the create (+) button.
  final VoidCallback onCreate;

  /// When true, the create (+) button is disabled.
  /// The caller should derive this from the authoritative source
  /// (e.g. `RuntimeDevice.canCreateTerminal`), not from a local count.
  final bool createDisabled;

  /// Called when user triggers a context menu on a terminal tab.
  /// Triggered by long press (mobile) or secondary click (desktop).
  /// Provides the terminal ID and the tap position for menu placement.
  final void Function(String terminalId, Offset position)? onContextMenu;

  bool get _createDisabled => createDisabled;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colorScheme = theme.colorScheme;

    return Container(
      decoration: BoxDecoration(
        border: Border(
          bottom: BorderSide(
            color: colorScheme.outlineVariant,
            width: 1,
          ),
        ),
      ),
      constraints: const BoxConstraints(maxHeight: 42),
      child: Row(
        children: [
          Expanded(
            child: SingleChildScrollView(
              scrollDirection: Axis.horizontal,
              child: Row(
                children: [
                  for (final terminal in terminals)
                    _buildTab(
                      context: context,
                      terminal: terminal,
                      isSelected: terminal.terminalId == selectedTerminalId,
                      colorScheme: colorScheme,
                      theme: theme,
                    ),
                ],
              ),
            ),
          ),
          _buildCreateButton(colorScheme),
        ],
      ),
    );
  }

  Widget _buildTab({
    required BuildContext context,
    required RuntimeTerminal terminal,
    required bool isSelected,
    required ColorScheme colorScheme,
    required ThemeData theme,
  }) {
    final canSwitch = terminal.canAttach;
    final bgColor = isSelected
        ? colorScheme.primaryContainer
        : Colors.transparent;
    final fgColor = isSelected
        ? colorScheme.onPrimaryContainer
        : (canSwitch
            ? colorScheme.onSurface
            : colorScheme.onSurface.withValues(alpha: 0.38));
    final indicatorColor =
        isSelected ? colorScheme.primary : Colors.transparent;

    return Tooltip(
      message: terminal.title,
      child: InkWell(
        key: Key('tab-${terminal.terminalId}'),
        onTap: canSwitch ? () => onSwitch(terminal.terminalId) : null,
        child: GestureDetector(
          onLongPressStart: onContextMenu != null
              ? (details) {
                  onContextMenu!(
                    terminal.terminalId,
                    details.globalPosition,
                  );
                }
              : null,
          onSecondaryTapUp: onContextMenu != null
              ? (details) {
                  onContextMenu!(
                    terminal.terminalId,
                    details.globalPosition,
                  );
                }
              : null,
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
            decoration: BoxDecoration(
              color: bgColor,
              border: Border(
                bottom: BorderSide(
                  color: indicatorColor,
                  width: isSelected ? 2.5 : 0,
                ),
              ),
            ),
            constraints: const BoxConstraints(maxWidth: 180),
            child: Text(
              terminal.title,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: theme.textTheme.bodySmall?.copyWith(
                color: fgColor,
                fontWeight: isSelected ? FontWeight.w600 : FontWeight.normal,
              ),
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildCreateButton(ColorScheme colorScheme) {
    return SizedBox(
      key: const Key('tab-bar-create'),
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
}
