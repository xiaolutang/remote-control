import 'package:flutter_test/flutter_test.dart';
import 'package:rc_client/models/terminal_shortcut.dart';

void main() {
  group('TerminalShortcutProfile', () {
    test('returns claude_code profile in stable order', () {
      final profile = TerminalShortcutProfile.fromId('claude_code');

      expect(profile.id, TerminalShortcutProfile.claudeCodeId);
      expect(
        profile.shortcuts.map((shortcut) => shortcut.id).toList(),
        [
          'esc',
          'tab',
          'ctrl_c',
          'ctrl_l',
          'prev_item',
          'next_item',
          'left',
          'right',
          'confirm',
        ],
      );
    });

    test('uses Claude navigation semantics for user-facing labels', () {
      final profile = TerminalShortcutProfile.fromId('claude_code');
      final labels = profile.shortcuts.map((shortcut) => shortcut.label).toList();

      expect(labels, containsAll(['上一项', '下一项', 'Enter']));
      expect(labels, isNot(contains('Up')));
      expect(labels, isNot(contains('Down')));
      expect(labels, isNot(contains('确认')));
    });

    test('supports swappable Claude navigation mappings without changing labels',
        () {
      final profile = TerminalShortcutProfile.fromId('claude_code');
      final standard = profile.shortcutsForNavigationMode(
        ClaudeNavigationMode.standard,
      );
      final application = profile.shortcutsForNavigationMode(
        ClaudeNavigationMode.application,
      );

      expect(
        standard.firstWhere((shortcut) => shortcut.id == 'prev_item').label,
        '上一项',
      );
      expect(
        application.firstWhere((shortcut) => shortcut.id == 'prev_item').label,
        '上一项',
      );
      expect(
        standard.firstWhere((shortcut) => shortcut.id == 'prev_item').action.value,
        '\x1b[A',
      );
      expect(
        application.firstWhere((shortcut) => shortcut.id == 'prev_item').action.value,
        '\x1bOA',
      );
    });

    test('falls back to claude_code profile for unknown ids', () {
      final profile = TerminalShortcutProfile.fromId('unknown');

      expect(profile.id, TerminalShortcutProfile.claudeCodeId);
      expect(profile.shortcuts, isNotEmpty);
    });
  });

  group('TerminalShortcutAction', () {
    test('maps control shortcuts to control characters', () {
      const ctrlC = TerminalShortcutAction(
        type: TerminalShortcutActionType.sendControl,
        value: 'c',
      );
      const ctrlL = TerminalShortcutAction(
        type: TerminalShortcutActionType.sendControl,
        value: 'l',
      );

      expect(ctrlC.toTerminalPayload(), '\x03');
      expect(ctrlL.toTerminalPayload(), '\x0c');
    });

    test('keeps escape sequences unchanged', () {
      const action = TerminalShortcutAction(
        type: TerminalShortcutActionType.sendEscapeSequence,
        value: '\x1b[A',
      );

      expect(action.toTerminalPayload(), '\x1b[A');
    });

    test('returns empty payload for empty control value', () {
      const action = TerminalShortcutAction(
        type: TerminalShortcutActionType.sendControl,
        value: '',
      );

      expect(action.toTerminalPayload(), isEmpty);
    });
  });
}
