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

  // ── 工厂方法：消除 Ctrl / Esc 序列的重复构造 ──

  static TerminalShortcut _ctrl(String key) => TerminalShortcut(
        id: 'ctrl_$key',
        label: 'Ctrl+${key.toUpperCase()}',
        action: TerminalShortcutAction(
          type: TerminalShortcutActionType.sendControl,
          value: key,
        ),
      );

  static TerminalShortcut _esc(String id, String label, String seq) =>
      TerminalShortcut(
        id: id,
        label: label,
        action: TerminalShortcutAction(
          type: TerminalShortcutActionType.sendEscapeSequence,
          value: seq,
        ),
      );

  static final TerminalShortcutProfile claudeCode = TerminalShortcutProfile(
    id: claudeCodeId,
    shortcuts: [
      _esc('esc', 'Esc', '\x1b'),
      TerminalShortcut(
        id: 'tab',
        label: 'Tab',
        action: TerminalShortcutAction(
          type: TerminalShortcutActionType.sendText,
          value: '\t',
        ),
      ),
      _ctrl('c'),
      _ctrl('l'),
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
      _esc('left', '左移', '\x1b[D'),
      _esc('right', '右移', '\x1b[C'),
      TerminalShortcut(
        id: 'confirm',
        label: 'Enter',
        action: TerminalShortcutAction(
          type: TerminalShortcutActionType.sendText,
          value: '\r',
        ),
      ),
      // 终端控制键
      _ctrl('a'),
      _ctrl('d'),
      _ctrl('z'),
      _ctrl('u'),
      _ctrl('k'),
      _ctrl('w'),
      _ctrl('r'),
      // 光标移动键
      _esc('home', 'Home', '\x1b[H'),
      _esc('end', 'End', '\x1b[F'),
      _esc('page_up', 'PgUp', '\x1b[5~'),
      _esc('page_down', 'PgDn', '\x1b[6~'),
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
