import 'shortcut_item.dart';
import 'terminal_shortcut.dart';

class ClaudeCommandPack {
  const ClaudeCommandPack._();

  static const List<ShortcutItem> defaults = [
    ShortcutItem(
      id: 'claude_help',
      label: '/help',
      source: ShortcutItemSource.builtin,
      section: ShortcutItemSection.smart,
      action: TerminalShortcutAction(
        type: TerminalShortcutActionType.sendText,
        value: '/help\r',
      ),
      order: 10,
      scope: ShortcutItemScope.project,
    ),
    ShortcutItem(
      id: 'claude_status',
      label: '/status',
      source: ShortcutItemSource.builtin,
      section: ShortcutItemSection.smart,
      action: TerminalShortcutAction(
        type: TerminalShortcutActionType.sendText,
        value: '/status\r',
      ),
      order: 20,
      scope: ShortcutItemScope.project,
    ),
    ShortcutItem(
      id: 'claude_clear',
      label: '/clear',
      source: ShortcutItemSource.builtin,
      section: ShortcutItemSection.smart,
      action: TerminalShortcutAction(
        type: TerminalShortcutActionType.sendText,
        value: '/clear\r',
      ),
      order: 30,
      scope: ShortcutItemScope.project,
    ),
    ShortcutItem(
      id: 'claude_compact',
      label: '/compact',
      source: ShortcutItemSource.builtin,
      section: ShortcutItemSection.smart,
      action: TerminalShortcutAction(
        type: TerminalShortcutActionType.sendText,
        value: '/compact\r',
      ),
      order: 40,
      scope: ShortcutItemScope.project,
    ),
  ];

  static List<ShortcutItem> cloneDefaults() {
    return defaults.map((item) => item.copyWith()).toList(growable: false);
  }
}
