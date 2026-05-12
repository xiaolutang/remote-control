// ignore_for_file: unused_element

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rc_client/models/runtime_device.dart';
import 'package:rc_client/models/runtime_terminal.dart';
import 'package:rc_client/screens/desktop/terminal_actions_mixin.dart';
import 'package:rc_client/screens/desktop/workspace_shortcut_intents.dart';

void main() {
  // ---------------------------------------------------------------------------
  // workspace_shortcut_intents.dart
  // ---------------------------------------------------------------------------
  group('SwitchTerminalIntent', () {
    test('stores index', () {
      const intent = SwitchTerminalIntent(2);
      expect(intent.index, 2);
    });

    test('equality by index', () {
      expect(const SwitchTerminalIntent(1), const SwitchTerminalIntent(1));
      expect(const SwitchTerminalIntent(0), isNot(equals(const SwitchTerminalIntent(1))));
    });
  });

  group('CloseCurrentTerminalIntent', () {
    test('can be constructed', () {
      const intent = CloseCurrentTerminalIntent();
      expect(intent, isA<CloseCurrentTerminalIntent>());
    });
  });

  group('SwitchTerminalAction', () {
    test('invokes callback with correct index', () {
      int? receivedIndex;
      final action = SwitchTerminalAction(onSwitch: (index) {
        receivedIndex = index;
      });
      action.invoke(const SwitchTerminalIntent(3));
      expect(receivedIndex, 3);
    });
  });

  group('CloseCurrentTerminalAction', () {
    test('invokes callback', () {
      var called = false;
      final action = CloseCurrentTerminalAction(onClose: () {
        called = true;
      });
      action.invoke(const CloseCurrentTerminalIntent());
      expect(called, isTrue);
    });
  });

  // ---------------------------------------------------------------------------
  // terminal_actions_mixin.dart - TabContextAction enum
  // ---------------------------------------------------------------------------
  group('TabContextAction', () {
    test('enum has rename and close values', () {
      expect(TabContextAction.values, hasLength(2));
      expect(TabContextAction.values, contains(TabContextAction.rename));
      expect(TabContextAction.values, contains(TabContextAction.close));
    });

    test('enum values are distinct', () {
      expect(TabContextAction.rename, isNot(equals(TabContextAction.close)));
    });
  });

  // ---------------------------------------------------------------------------
  // terminal_actions_mixin.dart - Pure logic tests (no widget tree required)
  // ---------------------------------------------------------------------------
  group('isCreateDisabled logic', () {
    test('disabled when device cannot create terminal (max reached)', () {
      final device = RuntimeDevice(
        deviceId: 'd1',
        name: 'Test',
        owner: 'user1',
        agentOnline: true,
        activeTerminals: 3,
        maxTerminals: 3,
      );
      // canCreateTerminal = agentOnline && activeTerminals < maxTerminals
      expect(device.canCreateTerminal, isFalse);
    });

    test('enabled when device can create and not at max', () {
      final device = RuntimeDevice(
        deviceId: 'd1',
        name: 'Test',
        owner: 'user1',
        agentOnline: true,
        activeTerminals: 0,
        maxTerminals: 3,
      );
      expect(device.canCreateTerminal, isTrue);
    });

    test('disabled when device is offline', () {
      final device = RuntimeDevice(
        deviceId: 'd1',
        name: 'Test',
        owner: 'user1',
        agentOnline: false,
        activeTerminals: 0,
        maxTerminals: 3,
      );
      expect(device.canCreateTerminal, isFalse);
    });
  });

  group('findTerminal logic', () {
    test('returns terminal when found', () {
      final terminals = [
        _makeTerminal('t1', 'Terminal 1'),
        _makeTerminal('t2', 'Terminal 2'),
      ];
      final result = terminals
          .where((t) => t.terminalId == 't2')
          .firstOrNull;
      expect(result, isNotNull);
      expect(result!.terminalId, 't2');
    });

    test('returns null when not found', () {
      final terminals = [
        _makeTerminal('t1', 'Terminal 1'),
      ];
      final result = terminals
          .where((t) => t.terminalId == 'nonexistent')
          .firstOrNull;
      expect(result, isNull);
    });

    test('returns null for empty list', () {
      const terminals = <RuntimeTerminal>[];
      final result = terminals
          .where((t) => t.terminalId == 'anything')
          .firstOrNull;
      expect(result, isNull);
    });
  });

  group('RuntimeTerminal status helpers', () {
    test('isClosed is true when status is closed', () {
      final terminal = _makeTerminalWithStatus('t1', 'closed');
      expect(terminal.isClosed, isTrue);
      expect(terminal.canAttach, isFalse);
      expect(terminal.canClose, isFalse);
    });

    test('isClosed is false when status is attached', () {
      final terminal = _makeTerminalWithStatus('t1', 'attached');
      expect(terminal.isClosed, isFalse);
      expect(terminal.canAttach, isTrue);
      expect(terminal.canClose, isTrue);
    });

    test('isClosed is false when status is pending', () {
      final terminal = _makeTerminalWithStatus('t1', 'pending');
      expect(terminal.isClosed, isFalse);
    });
  });
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

RuntimeTerminal _makeTerminal(String id, String title) {
  return RuntimeTerminal(
    terminalId: id,
    title: title,
    cwd: '~',
    command: '/bin/bash',
    status: 'attached',
    views: {},
  );
}

RuntimeTerminal _makeTerminalWithStatus(String id, String status) {
  return RuntimeTerminal(
    terminalId: id,
    title: 'Terminal',
    cwd: '~',
    command: '/bin/bash',
    status: status,
    views: {},
  );
}
