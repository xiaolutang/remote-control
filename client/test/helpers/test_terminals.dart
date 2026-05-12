import 'package:rc_client/models/runtime_terminal.dart';

/// Creates a list of [count] mock terminals for testing.
///
/// Terminals have IDs `t0`, `t1`, ... and titles `Terminal 1`, `Terminal 2`, ...
List<RuntimeTerminal> createTestTerminals(int count) {
  return List.generate(
    count,
    (i) => RuntimeTerminal(
      terminalId: 't$i',
      title: 'Terminal ${i + 1}',
      cwd: '~',
      command: '/bin/bash',
      status: 'running',
      views: {},
    ),
  );
}
