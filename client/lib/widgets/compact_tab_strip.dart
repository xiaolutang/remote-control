import 'package:flutter/material.dart';

import '../models/runtime_terminal.dart';
import 'terminal_create_button.dart';

/// Compact tab strip for mobile terminal switching.
///
/// Displays numbered tabs in a horizontal scrollable row, supporting
/// tap-to-switch, create (+) button, long-press context menu, and swipe
/// gestures to navigate between adjacent terminals.
///
/// Visual style aligns with desktop [TerminalTabBar]: selected tab uses
/// `primaryContainer` background with a bottom indicator line, rather than
/// a saturated pill shape.
///
/// Swipe detection uses [Listener] (raw pointer events) so it does not
/// compete with the inner [SingleChildScrollView] for horizontal drag.
/// A [ScrollNotification] guard suppresses swipe when the ScrollView
/// actually consumed the horizontal drag (overflow scrolling).
class CompactTabStrip extends StatefulWidget {
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

  @override
  State<CompactTabStrip> createState() => _CompactTabStripState();
}

class _CompactTabStripState extends State<CompactTabStrip> {
  Offset? _pointerDownPosition;
  int? _pointerDownTime;
  bool _scrollViewConsumed = false;

  static const int _swipeThresholdMs = 300;
  static const double _swipeMinVelocity = 0.5; // px/ms

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colorScheme = theme.colorScheme;

    return Listener(
      onPointerDown: _onPointerDown,
      onPointerUp: _onPointerUp,
      child: Container(
        height: 48,
        decoration: BoxDecoration(
          color: colorScheme.surfaceContainerHigh,
          border: Border(
            bottom: BorderSide(
              color: colorScheme.outlineVariant,
              width: 1,
            ),
          ),
        ),
        child: Row(
          children: [
            Expanded(
              child: NotificationListener<ScrollNotification>(
                onNotification: _onScrollNotification,
                child: SingleChildScrollView(
                  scrollDirection: Axis.horizontal,
                  child: Row(
                    children: [
                      for (var i = 0; i < widget.terminals.length; i++)
                        _buildCompactTab(
                          terminal: widget.terminals[i],
                          index: i,
                          isSelected: widget.terminals[i].terminalId ==
                              widget.selectedTerminalId,
                          colorScheme: colorScheme,
                          theme: theme,
                        ),
                    ],
                  ),
                ),
              ),
            ),
            _buildCreateButton(),
          ],
        ),
      ),
    );
  }

  /// Track when ScrollView consumes a drag — suppress swipe in that case.
  bool _onScrollNotification(ScrollNotification notification) {
    if (notification is ScrollUpdateNotification) {
      if (notification.dragDetails != null) {
        _scrollViewConsumed = true;
      }
    }
    return false;
  }

  void _onPointerDown(PointerDownEvent event) {
    _pointerDownPosition = event.position;
    _pointerDownTime = DateTime.now().millisecondsSinceEpoch;
    _scrollViewConsumed = false;
  }

  void _onPointerUp(PointerUpEvent event) {
    if (_pointerDownPosition == null || _pointerDownTime == null) return;

    // ScrollView consumed the horizontal drag — this is a scroll, not a swipe
    if (_scrollViewConsumed) {
      _pointerDownPosition = null;
      _pointerDownTime = null;
      return;
    }

    final upTime = DateTime.now().millisecondsSinceEpoch;
    final dt = upTime - _pointerDownTime!;
    if (dt <= 0 || dt > _swipeThresholdMs) {
      _pointerDownPosition = null;
      _pointerDownTime = null;
      return;
    }

    final dx = event.position.dx - _pointerDownPosition!.dx;
    final velocity = dx.abs() / dt; // px/ms
    _pointerDownPosition = null;
    _pointerDownTime = null;

    if (velocity < _swipeMinVelocity) return;

    final selectedIndex = widget.terminals.indexWhere(
      (t) => t.terminalId == widget.selectedTerminalId,
    );
    if (selectedIndex < 0) return;

    // Swipe left (negative dx) → next, right (positive dx) → previous
    final direction = dx < 0 ? 1 : -1;
    final neighbor = _findAttachableNeighbor(selectedIndex, direction);
    if (neighbor != null) {
      widget.onSwitch(widget.terminals[neighbor].terminalId);
    }
  }

  /// Find the index of the nearest attachable neighbor in [direction] (+1/-1).
  int? _findAttachableNeighbor(int startIndex, int direction) {
    int i;
    if (direction > 0) {
      for (i = startIndex + 1; i < widget.terminals.length; i++) {
        if (widget.terminals[i].canAttach) return i;
      }
    } else {
      for (i = startIndex - 1; i >= 0; i--) {
        if (widget.terminals[i].canAttach) return i;
      }
    }
    return null;
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
        ? colorScheme.primaryContainer
        : Colors.transparent;
    final fgColor = isSelected
        ? colorScheme.onPrimaryContainer
        : (canSwitch
            ? colorScheme.onSurface
            : colorScheme.onSurface.withValues(alpha: 0.38));
    final indicatorColor =
        isSelected ? colorScheme.primary : Colors.transparent;

    return InkWell(
      key: Key('compact-tab-${terminal.terminalId}'),
      onTap: canSwitch ? () => widget.onSwitch(terminal.terminalId) : null,
      child: GestureDetector(
        onLongPressStart: widget.onLongPress != null
            ? (details) => widget.onLongPress!(terminal.terminalId)
            : null,
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
          decoration: BoxDecoration(
            color: bgColor,
            border: Border(
              bottom: BorderSide(
                color: indicatorColor,
                width: isSelected ? 2.5 : 0,
              ),
            ),
          ),
          constraints: const BoxConstraints(minWidth: 72, maxWidth: 120),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(
                '${index + 1}',
                style: theme.textTheme.labelMedium?.copyWith(
                  color: fgColor,
                  fontWeight: FontWeight.w500,
                ),
              ),
              const SizedBox(width: 4),
              Flexible(
                child: Text(
                  terminal.title,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: theme.textTheme.labelMedium?.copyWith(
                    color: fgColor,
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildCreateButton() {
    return TerminalCreateButton(
      key: const Key('compact-tab-create'),
      onCreate: widget.onCreate,
      createDisabled: widget.createDisabled,
    );
  }
}
