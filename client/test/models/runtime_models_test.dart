import 'package:flutter_test/flutter_test.dart';
import 'package:rc_client/models/runtime_device.dart';
import 'package:rc_client/models/runtime_terminal.dart';

void main() {
  test('runtime device exposes create capability', () {
    final online = RuntimeDevice.fromJson({
      'device_id': 'mbp-01',
      'name': 'MacBook Pro',
      'owner': 'user1',
      'agent_online': true,
      'max_terminals': 3,
      'active_terminals': 1,
    });
    final saturated = RuntimeDevice.fromJson({
      'device_id': 'mbp-02',
      'name': 'MacBook Air',
      'owner': 'user1',
      'agent_online': true,
      'max_terminals': 1,
      'active_terminals': 1,
    });

    expect(online.canCreateTerminal, isTrue);
    expect(saturated.canCreateTerminal, isFalse);
  });

  test('runtime terminal attachability follows status', () {
    final detached = RuntimeTerminal.fromJson({
      'terminal_id': 'term-1',
      'title': 'Claude',
      'cwd': '/tmp',
      'command': '/bin/bash',
      'status': 'detached',
      'views': {'mobile': 0, 'desktop': 0},
    });
    final closed = RuntimeTerminal.fromJson({
      'terminal_id': 'term-2',
      'title': 'Closed',
      'cwd': '/tmp',
      'command': '/bin/bash',
      'status': 'closed',
      'views': {'mobile': 0, 'desktop': 0},
    });

    expect(detached.canAttach, isTrue);
    expect(closed.canAttach, isFalse);
  });

  test('runtime terminal views handles non-int values', () {
    final terminal = RuntimeTerminal.fromJson({
      'terminal_id': 'term-1',
      'title': 'Test',
      'cwd': '/tmp',
      'command': '/bin/bash',
      'status': 'active',
      'views': {
        'mobile': 3,
        'desktop': 2.7, // double → toInt → 2
        'other': '5',   // string → readIntFromJson → 5
        'bad': true,     // bool → 0
      },
    });
    expect(terminal.views['mobile'], 3);
    expect(terminal.views['desktop'], 2);
    expect(terminal.views['other'], 5);
    expect(terminal.views['bad'], 0);
  });
}
