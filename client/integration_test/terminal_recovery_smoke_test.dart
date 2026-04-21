import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:provider/provider.dart';
import 'package:rc_client/screens/terminal_screen.dart';
import 'package:rc_client/services/environment_service.dart';
import 'package:rc_client/services/terminal_session_manager.dart';
import 'package:rc_client/services/websocket_service.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:xterm/xterm.dart';

import '../test/mocks/mock_websocket_service.dart';
import '../third_party/xterm/test/_fixture/_fixture.dart';

const _settleDelay = Duration(milliseconds: 200);

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  group('Desktop terminal recovery smoke', () {
    late TerminalSessionManager sessionManager;
    late _RecoveryWebSocketService service;

    setUp(() {
      SharedPreferences.setMockInitialValues({});
      EnvironmentService.setInstance(
        EnvironmentService(debugModeProvider: () => true),
      );
      sessionManager = TerminalSessionManager();
      service = _RecoveryWebSocketService();
    });

    tearDown(() {
      service.dispose();
      sessionManager.dispose();
    });

    Future<Terminal> pumpScreen(WidgetTester tester) async {
      await tester.pumpWidget(
        MultiProvider(
          providers: [
            ChangeNotifierProvider<TerminalSessionManager>.value(
              value: sessionManager,
            ),
            ChangeNotifierProvider<WebSocketService>.value(value: service),
          ],
          child: const MaterialApp(
            home: TerminalScreen(platformOverride: TargetPlatform.macOS),
          ),
        ),
      );
      await tester.pump(_settleDelay);
      final terminal = sessionManager
          .getRendererAdapter(service.deviceId, service.terminalId!)
          ?.terminalForView;
      expect(terminal, isNotNull);
      return terminal!;
    }

    testWidgets('replays Claude slash-exit transcript to final shell prompt',
        (tester) async {
      final terminal = await pumpScreen(tester);

      service.simulateOutput(
        TestFixtures.claudeShellExitAfterSlashExitRealTranscript(),
      );
      await tester.pump(_settleDelay);

      expect(terminal.isUsingAltBuffer, isFalse);
      expect(terminal.buffer.currentLine.toString(), TestFixtures.shellPrompt);
      expect(_lastNonEmptyLine(terminal), TestFixtures.shellPrompt);
      expect(
        _lastNonEmptyLineIndex(terminal),
        terminal.buffer.absoluteCursorY,
      );
    });

    testWidgets(
        'ignores unsafe recovery snapshot and keeps restored shell prompt at bottom',
        (tester) async {
      final terminal = await pumpScreen(tester);

      terminal.write('bash-3.2\$ pwd\r\n/Users/tangxiaolu\r\nbash-3.2\$ claude');
      terminal.write('\x1b[?1049hClaude Code v2.1.76');
      expect(terminal.isUsingAltBuffer, isTrue);

      service.simulateConnectedEvent(rows: 24, cols: 80);
      service.simulateSnapshotChunk(
        '\x1b[?1049htruncated claude frame\x1b[?1049l',
        activeBuffer: TerminalBufferKind.main,
      );
      service.simulateOutput(
        '\x1b[?1049l'
        'Resume this session with:\r\n'
        'claude --resume 17078118-79f9-4f48-8ab8-e394e7b99e92\r\n'
        'bash-3.2\$ ',
      );
      service.simulateSnapshotComplete();
      await tester.pump(_settleDelay);

      final mainText = _terminalText(terminal.mainBuffer);
      expect(terminal.isUsingAltBuffer, isFalse);
      expect(mainText, contains('Resume this session with:'));
      expect(
        mainText,
        contains('claude --resume 17078118-79f9-4f48-8ab8-e394e7b99e92'),
      );
      expect(mainText, contains('bash-3.2\$ '));
      expect(mainText, isNot(contains('truncated claude frame')));
      expect(_lastNonEmptyLine(terminal), 'bash-3.2\$ ');
      expect(
        _lastNonEmptyLineIndex(terminal),
        terminal.buffer.absoluteCursorY,
      );
    });
  });
}

class _RecoveryWebSocketService extends MockWebSocketService {
  _RecoveryWebSocketService()
      : super(
          deviceId: 'device-1',
          terminalId: 'term-1',
          viewType: ViewType.desktop,
        );

  @override
  Future<bool> connect() async {
    connectCallCount++;
    simulateConnect();
    return true;
  }
}

String _terminalText(Buffer buffer) {
  final lines = <String>[];
  buffer.lines.forEach((line) {
    lines.add(line.toString());
  });
  return lines.join('\n');
}

String _lastNonEmptyLine(Terminal terminal) {
  for (var i = terminal.buffer.lines.length - 1; i >= 0; i--) {
    final text = terminal.buffer.lines[i].toString();
    if (text.trim().isNotEmpty) {
      return text;
    }
  }
  return '';
}

int _lastNonEmptyLineIndex(Terminal terminal) {
  for (var i = terminal.buffer.lines.length - 1; i >= 0; i--) {
    if (terminal.buffer.lines[i].toString().trim().isNotEmpty) {
      return i;
    }
  }
  return -1;
}
