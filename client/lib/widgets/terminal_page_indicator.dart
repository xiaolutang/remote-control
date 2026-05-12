import 'package:flutter/material.dart';

import '../models/runtime_terminal.dart';
import 'terminal_create_button.dart';

/// Compact page indicator for mobile terminal switching.
///
/// Displays a compact `< 1/3 >` bar (32px height). Left/right arrows switch
/// between adjacent terminals. Tapping the center area opens a BottomSheet
/// with a terminal list and a create button. Long-pressing the center area
/// triggers a context menu callback.
///
/// When there are 0 terminals the widget renders nothing ([SizedBox.shrink]).
class TerminalPageIndicator extends StatelessWidget {
  const TerminalPageIndicator({
    super.key,
    required this.terminals,
    this.selectedTerminalId,
    required this.onSwitch,
    required this.onCreate,
    this.createDisabled = false,
    this.onContextMenu,
  });

  /// List of terminal sessions.
  final List<RuntimeTerminal> terminals;

  /// ID of the currently selected terminal, or null if none selected.
  final String? selectedTerminalId;

  /// Called when user switches to a different terminal.
  final ValueChanged<String> onSwitch;

  /// Called when user taps the create button.
  final VoidCallback onCreate;

  /// When true, the create button is disabled.
  final bool createDisabled;

  /// Called when user long-presses the center page indicator area.
  final void Function(String terminalId, Offset position)? onContextMenu;

  @override
  Widget build(BuildContext context) {
    // 0 terminals: render nothing
    if (terminals.isEmpty) return const SizedBox.shrink();

    final currentIndex =
        terminals.indexWhere((t) => t.terminalId == selectedTerminalId);
    final displayIndex = currentIndex < 0 ? 0 : currentIndex;

    final theme = Theme.of(context);
    final colorScheme = theme.colorScheme;

    return Container(
      height: 32,
      color: colorScheme.surfaceContainerHighest.withValues(alpha: 0.5),
      child: Row(
        children: [
          // Left arrow
          IconButton(
            key: const Key('page-indicator-left'),
            icon: Icon(Icons.chevron_left, size: 16),
            onPressed: displayIndex > 0
                ? () => onSwitch(terminals[displayIndex - 1].terminalId)
                : null,
            padding: EdgeInsets.zero,
            constraints: const BoxConstraints(minWidth: 32, minHeight: 32),
          ),
          // Center page indicator — expanded to fill space
          Expanded(
            child: GestureDetector(
              key: const Key('page-indicator-center'),
              onTap: () => _showTerminalList(context),
              onLongPressStart: currentIndex >= 0 && onContextMenu != null
                  ? (details) {
                      onContextMenu!(
                        terminals[displayIndex].terminalId,
                        details.globalPosition,
                      );
                    }
                  : null,
              child: Center(
                child: Text(
                  '${displayIndex + 1}/${terminals.length}',
                  key: const Key('page-indicator-label'),
                  style: theme.textTheme.labelMedium?.copyWith(
                    color: colorScheme.onSurface,
                    fontWeight: FontWeight.w500,
                  ),
                ),
              ),
            ),
          ),
          // Right arrow
          IconButton(
            key: const Key('page-indicator-right'),
            icon: Icon(Icons.chevron_right, size: 16),
            onPressed: displayIndex < terminals.length - 1
                ? () => onSwitch(terminals[displayIndex + 1].terminalId)
                : null,
            padding: EdgeInsets.zero,
            constraints: const BoxConstraints(minWidth: 32, minHeight: 32),
          ),
          // Context menu button (rename / close) — always visible
          if (onContextMenu != null)
            IconButton(
              key: const Key('page-indicator-more'),
              icon: Icon(Icons.more_horiz, size: 16),
              onPressed: currentIndex >= 0
                  ? () => onContextMenu!(
                        terminals[displayIndex].terminalId,
                        Offset.zero,
                      )
                  : null,
              padding: EdgeInsets.zero,
              constraints: const BoxConstraints(minWidth: 32, minHeight: 32),
            ),
          // Create button — always visible
          Padding(
            padding: const EdgeInsets.only(right: 4),
            child: TerminalCreateButton(
              key: const Key('page-indicator-create'),
              onCreate: onCreate,
              createDisabled: createDisabled,
            ),
          ),
        ],
      ),
    );
  }

  /// Opens a BottomSheet listing all terminals for quick switching.
  ///
  /// **Known limitation**: The BottomSheet captures a snapshot of [terminals]
  /// at the time it opens. Changes to the terminal list (rename, add, remove)
  /// while the sheet is visible will not be reflected. This is acceptable
  /// because the BottomSheet is short-lived (<5 seconds of user interaction);
  /// closing and reopening it will show the latest data.
  void _showTerminalList(BuildContext context) {
    showModalBottomSheet<void>(
      context: context,
      builder: (BuildContext sheetContext) {
        return SafeArea(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 12, 16, 8),
                child: Text(
                  '终端列表',
                  style: Theme.of(context).textTheme.titleSmall,
                ),
              ),
              const Divider(height: 1),
              ConstrainedBox(
                constraints: const BoxConstraints(maxHeight: 300),
                child: ListView.builder(
                  shrinkWrap: true,
                  itemCount: terminals.length,
                  itemBuilder: (BuildContext ctx, int index) {
                    final terminal = terminals[index];
                    final isSelected =
                        terminal.terminalId == selectedTerminalId;
                    return ListTile(
                      key: Key('bottom-sheet-terminal-${terminal.terminalId}'),
                      dense: true,
                      leading: Text(
                        '${index + 1}',
                        style: TextStyle(
                          fontWeight: isSelected
                              ? FontWeight.bold
                              : FontWeight.normal,
                        ),
                      ),
                      title: Text(
                        terminal.title,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                      ),
                      trailing: isSelected
                          ? Icon(Icons.check, size: 16)
                          : null,
                      onTap: () {
                        onSwitch(terminal.terminalId);
                        Navigator.of(sheetContext).pop();
                      },
                    );
                  },
                ),
              ),
              const Divider(height: 1),
              Padding(
                padding: const EdgeInsets.all(8),
                child: TerminalCreateButton(
                  key: const Key('bottom-sheet-create'),
                  onCreate: () {
                    Navigator.of(sheetContext).pop();
                    onCreate();
                  },
                  createDisabled: createDisabled,
                ),
              ),
            ],
          ),
        );
      },
    );
  }
}
