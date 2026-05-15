import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';

import '../models/runtime_terminal.dart';
import 'terminal_create_button.dart';

/// Desktop sidebar for switching between terminal sessions.
///
/// Displays a narrow vertical bar (48px collapsed) showing terminal icons.
/// On hover, expands to 160px to show terminal titles.
/// Supports selection, creation, and context menu via right-click.
class TerminalSidebar extends StatefulWidget {
  const TerminalSidebar({
    super.key,
    required this.terminals,
    this.selectedTerminalId,
    required this.onSwitch,
    required this.onCreate,
    this.createDisabled = false,
    this.onContextMenu,
  });

  /// List of terminal sessions to display in the sidebar.
  final List<RuntimeTerminal> terminals;

  /// ID of the currently selected terminal, or null if none selected.
  final String? selectedTerminalId;

  /// Called when user taps a terminal item.
  final ValueChanged<String> onSwitch;

  /// Called when user taps the create (+) button.
  final VoidCallback onCreate;

  /// When true, the create (+) button is disabled.
  final bool createDisabled;

  /// Called when user right-clicks a terminal item.
  /// Provides the terminal ID and the tap position for menu placement.
  final void Function(String terminalId, Offset position)? onContextMenu;

  @override
  State<TerminalSidebar> createState() => _TerminalSidebarState();
}

class _TerminalSidebarState extends State<TerminalSidebar> {
  static const double _collapsedWidth = 48.0;
  static const double _expandedWidth = 160.0;
  static const Duration _animationDuration = Duration(milliseconds: 200);

  bool _isHovered = false;

  void _onEnter(PointerEnterEvent _) {
    setState(() => _isHovered = true);
  }

  void _onExit(PointerExitEvent _) {
    setState(() => _isHovered = false);
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colorScheme = theme.colorScheme;

    return MouseRegion(
      onEnter: _onEnter,
      onExit: _onExit,
      child: AnimatedContainer(
        duration: _animationDuration,
        width: _isHovered ? _expandedWidth : _collapsedWidth,
        curve: Curves.easeInOut,
        decoration: BoxDecoration(
          color: colorScheme.surface,
          border: Border(
            right: BorderSide(
              color: colorScheme.outlineVariant,
              width: 1,
            ),
          ),
        ),
        child: Column(
          children: [
            Expanded(
              child: widget.terminals.isEmpty
                  ? const SizedBox.shrink()
                  : ListView.builder(
                      padding: EdgeInsets.zero,
                      itemCount: widget.terminals.length,
                      itemBuilder: (context, index) {
                        final terminal = widget.terminals[index];
                        final isSelected =
                            terminal.terminalId == widget.selectedTerminalId;
                        return _TerminalItem(
                          key: Key('sidebar-${terminal.terminalId}'),
                          terminal: terminal,
                          isSelected: isSelected,
                          isExpanded: _isHovered,
                          onSwitch: widget.onSwitch,
                          onContextMenu: widget.onContextMenu,
                        );
                      },
                    ),
            ),
            const Divider(height: 1),
            TerminalCreateButton(
              key: const Key('sidebar-create'),
              onCreate: widget.onCreate,
              createDisabled: widget.createDisabled,
            ),
          ],
        ),
      ),
    );
  }
}

class _TerminalItem extends StatelessWidget {
  const _TerminalItem({
    super.key,
    required this.terminal,
    required this.isSelected,
    required this.isExpanded,
    required this.onSwitch,
    this.onContextMenu,
  });

  final RuntimeTerminal terminal;
  final bool isSelected;
  final bool isExpanded;
  final ValueChanged<String> onSwitch;
  final void Function(String terminalId, Offset position)? onContextMenu;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colorScheme = theme.colorScheme;
    final canSwitch = terminal.canAttach;
    final fgColor = isSelected
        ? colorScheme.onSurface
        : (canSwitch
            ? colorScheme.onSurface.withValues(alpha: 0.6)
            : colorScheme.onSurface.withValues(alpha: 0.38));

    return Tooltip(
      message: terminal.title,
      child: GestureDetector(
        onSecondaryTapDown: onContextMenu != null
            ? (details) {
                onContextMenu!(
                  terminal.terminalId,
                  details.globalPosition,
                );
              }
            : null,
        child: InkWell(
          onTap: canSwitch ? () => onSwitch(terminal.terminalId) : null,
          child: Container(
            height: 42,
            decoration: BoxDecoration(
              color: isSelected
                  ? colorScheme.primaryContainer.withValues(alpha: 0.3)
                  : Colors.transparent,
            ),
            child: Row(
              children: [
                // Left selection indicator (3px)
                AnimatedContainer(
                  duration: const Duration(milliseconds: 200),
                  width: 3,
                  height: 20,
                  decoration: BoxDecoration(
                    color: isSelected ? colorScheme.primary : Colors.transparent,
                    borderRadius: BorderRadius.circular(1.5),
                  ),
                ),
                // Terminal icon
                SizedBox(
                  width: 44,
                  child: Icon(
                    Icons.terminal,
                    size: 18,
                    color: fgColor,
                  ),
                ),
                // Title text (only visible when expanded)
                if (isExpanded)
                  Expanded(
                    child: Text(
                      terminal.title,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: theme.textTheme.bodySmall?.copyWith(
                        color: fgColor,
                        fontWeight:
                            isSelected ? FontWeight.w600 : FontWeight.normal,
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
}
