import 'package:flutter_test/flutter_test.dart';
import 'package:rc_client/models/claude_command_pack.dart';

void main() {
  group('ClaudeCommandPack', () {
    test('defaults contains all builtin Claude commands', () {
      final ids = ClaudeCommandPack.defaults.map((e) => e.id).toSet();

      expect(
        ids,
        containsAll([
          'claude_help',
          'claude_status',
          'claude_clear',
          'claude_compact',
          'claude_commit',
          'claude_model',
          'claude_fast',
          'claude_doctor',
          'claude_config',
        ]),
      );
      expect(ids.length, 9);
    });

    test('commands are ordered by ascending order', () {
      final orders = ClaudeCommandPack.defaults.map((e) => e.order).toList();
      final sorted = [...orders]..sort();
      expect(orders, sorted);
    });

    test('all commands have non-empty descriptions', () {
      for (final cmd in ClaudeCommandPack.defaults) {
        expect(cmd.description, isNotNull,
            reason: '${cmd.id} should have a description');
        expect(cmd.description!.isNotEmpty, isTrue,
            reason: '${cmd.id} description should not be empty');
      }
    });

    test('all commands use sendText action with trailing carriage return', () {
      for (final cmd in ClaudeCommandPack.defaults) {
        expect(cmd.action.toTerminalPayload(), endsWith('\r'),
            reason: '${cmd.id} action should end with \\r');
      }
    });

    test('cloneDefaults returns independent copies', () {
      final cloned = ClaudeCommandPack.cloneDefaults();

      expect(cloned.length, ClaudeCommandPack.defaults.length);
      for (var i = 0; i < cloned.length; i++) {
        expect(cloned[i].id, ClaudeCommandPack.defaults[i].id);
        expect(identical(cloned[i], ClaudeCommandPack.defaults[i]), isFalse);
      }
    });
  });
}
