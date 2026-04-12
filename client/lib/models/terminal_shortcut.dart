enum TerminalShortcutActionType {
  sendText,
  sendControl,
  sendEscapeSequence,
}

enum ClaudeNavigationMode {
  standard,
  application,
}

TerminalShortcutActionType _actionTypeFromName(String? name) {
  return TerminalShortcutActionType.values.byName(
    name ?? TerminalShortcutActionType.sendText.name,
  );
}

class TerminalShortcutAction {
  const TerminalShortcutAction({
    required this.type,
    required this.value,
  });

  final TerminalShortcutActionType type;
  final String value;

  String toTerminalPayload() {
    switch (type) {
      case TerminalShortcutActionType.sendText:
      case TerminalShortcutActionType.sendEscapeSequence:
        return value;
      case TerminalShortcutActionType.sendControl:
        if (value.isEmpty) return '';
        final normalized = value.toUpperCase().codeUnitAt(0);
        return String.fromCharCode(normalized & 0x1f);
    }
  }

  Map<String, dynamic> toJson() {
    return {
      'type': type.name,
      'value': value,
    };
  }

  factory TerminalShortcutAction.fromJson(Map<String, dynamic> json) {
    return TerminalShortcutAction(
      type: _actionTypeFromName(json['type'] as String?),
      value: json['value'] as String? ?? '',
    );
  }
}

class TerminalShortcut {
  const TerminalShortcut({
    required this.id,
    required this.label,
    required this.action,
  });

  final String id;
  final String label;
  final TerminalShortcutAction action;
}

class TerminalShortcutProfile {
  const TerminalShortcutProfile({
    required this.id,
    required this.shortcuts,
  });

  final String id;
  final List<TerminalShortcut> shortcuts;

  static const String claudeCodeId = 'claude_code';

  static const TerminalShortcutProfile claudeCode = TerminalShortcutProfile(
    id: claudeCodeId,
    shortcuts: [
      TerminalShortcut(
        id: 'esc',
        label: 'Esc',
        action: TerminalShortcutAction(
          type: TerminalShortcutActionType.sendEscapeSequence,
          value: '\x1b',
        ),
      ),
      TerminalShortcut(
        id: 'tab',
        label: 'Tab',
        action: TerminalShortcutAction(
          type: TerminalShortcutActionType.sendText,
          value: '\t',
        ),
      ),
      TerminalShortcut(
        id: 'ctrl_c',
        label: 'Ctrl+C',
        action: TerminalShortcutAction(
          type: TerminalShortcutActionType.sendControl,
          value: 'c',
        ),
      ),
      TerminalShortcut(
        id: 'ctrl_l',
        label: 'Ctrl+L',
        action: TerminalShortcutAction(
          type: TerminalShortcutActionType.sendControl,
          value: 'l',
        ),
      ),
      TerminalShortcut(
        id: 'prev_item',
        label: '上一项',
        action: _standardPrevAction,
      ),
      TerminalShortcut(
        id: 'next_item',
        label: '下一项',
        action: _standardNextAction,
      ),
      TerminalShortcut(
        id: 'left',
        label: '左移',
        action: TerminalShortcutAction(
          type: TerminalShortcutActionType.sendEscapeSequence,
          value: '\x1b[D',
        ),
      ),
      TerminalShortcut(
        id: 'right',
        label: '右移',
        action: TerminalShortcutAction(
          type: TerminalShortcutActionType.sendEscapeSequence,
          value: '\x1b[C',
        ),
      ),
      TerminalShortcut(
        id: 'confirm',
        label: 'Enter',
        action: TerminalShortcutAction(
          type: TerminalShortcutActionType.sendText,
          value: '\r',
        ),
      ),
    ],
  );

  static const TerminalShortcutAction _standardPrevAction =
      TerminalShortcutAction(
        type: TerminalShortcutActionType.sendEscapeSequence,
        value: '\x1b[A',
      );
  static const TerminalShortcutAction _standardNextAction =
      TerminalShortcutAction(
        type: TerminalShortcutActionType.sendEscapeSequence,
        value: '\x1b[B',
      );
  static const TerminalShortcutAction _applicationPrevAction =
      TerminalShortcutAction(
        type: TerminalShortcutActionType.sendEscapeSequence,
        value: '\x1bOA',
      );
  static const TerminalShortcutAction _applicationNextAction =
      TerminalShortcutAction(
        type: TerminalShortcutActionType.sendEscapeSequence,
        value: '\x1bOB',
      );

  static TerminalShortcutProfile fromId(String? id) {
    switch (id) {
      case claudeCodeId:
      default:
        return claudeCode;
    }
  }

  List<TerminalShortcut> shortcutsForNavigationMode(
    ClaudeNavigationMode mode,
  ) {
    if (id != claudeCodeId) return shortcuts;

    return shortcuts.map((shortcut) {
      if (shortcut.id == 'prev_item') {
        return TerminalShortcut(
          id: shortcut.id,
          label: shortcut.label,
          action: mode == ClaudeNavigationMode.application
              ? _applicationPrevAction
              : _standardPrevAction,
        );
      }
      if (shortcut.id == 'next_item') {
        return TerminalShortcut(
          id: shortcut.id,
          label: shortcut.label,
          action: mode == ClaudeNavigationMode.application
              ? _applicationNextAction
              : _standardNextAction,
        );
      }
      return shortcut;
    }).toList(growable: false);
  }
}
