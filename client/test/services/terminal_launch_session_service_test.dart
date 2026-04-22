import 'package:flutter_test/flutter_test.dart';
import 'package:rc_client/models/terminal_launch_plan.dart';
import 'package:rc_client/services/terminal_launch_session_service.dart';
import 'package:rc_client/services/terminal_session_manager.dart';

import '../mocks/mock_websocket_service.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  group('TerminalLaunchSessionService', () {
    test('sends bootstrap input after terminal connected event', () async {
      final sessionManager = TerminalSessionManager();
      final service = MockWebSocketService(
        deviceId: 'dev-1',
        terminalId: 'term-1',
      );
      const launchService = TerminalLaunchSessionService(
        bootstrapInputDelay: Duration.zero,
      );

      launchService.ensureSession(
        sessionManager: sessionManager,
        deviceId: 'dev-1',
        terminalId: 'term-1',
        serviceFactory: () => service,
        plan: const TerminalLaunchPlan(
          tool: TerminalLaunchTool.codex,
          title: 'Codex',
          cwd: '~/project',
          command: '/bin/bash',
          entryStrategy: TerminalEntryStrategy.shellBootstrap,
          postCreateInput: 'codex\n',
          source: TerminalLaunchPlanSource.intent,
        ),
      );

      expect(service.sentMessages, isEmpty);

      service.simulateConnectedEvent();
      await Future<void>.delayed(const Duration(milliseconds: 10));

      expect(service.sentMessages, ['codex\n']);
    });

    test('does not send bootstrap input for direct exec plan', () async {
      final sessionManager = TerminalSessionManager();
      final service = MockWebSocketService(
        deviceId: 'dev-1',
        terminalId: 'term-1',
      );
      const launchService = TerminalLaunchSessionService(
        bootstrapInputDelay: Duration.zero,
      );

      launchService.ensureSession(
        sessionManager: sessionManager,
        deviceId: 'dev-1',
        terminalId: 'term-1',
        serviceFactory: () => service,
        plan: const TerminalLaunchPlan(
          tool: TerminalLaunchTool.shell,
          title: 'Shell',
          cwd: '~/project',
          command: '/bin/bash',
          entryStrategy: TerminalEntryStrategy.directExec,
          postCreateInput: '',
          source: TerminalLaunchPlanSource.recommended,
        ),
      );

      service.simulateConnectedEvent();
      await Future<void>.delayed(const Duration(milliseconds: 10));

      expect(service.sentMessages, isEmpty);
    });

    test('sends bootstrap immediately when service is already connected',
        () async {
      final sessionManager = TerminalSessionManager();
      final service = MockWebSocketService(
        deviceId: 'dev-1',
        terminalId: 'term-1',
      )..simulateConnect();
      const launchService = TerminalLaunchSessionService(
        bootstrapInputDelay: Duration.zero,
      );

      launchService.ensureSession(
        sessionManager: sessionManager,
        deviceId: 'dev-1',
        terminalId: 'term-1',
        serviceFactory: () => service,
        plan: const TerminalLaunchPlan(
          tool: TerminalLaunchTool.claudeCode,
          title: 'Claude',
          cwd: '~/project',
          command: '/bin/bash',
          entryStrategy: TerminalEntryStrategy.shellBootstrap,
          postCreateInput: 'claude\n',
          source: TerminalLaunchPlanSource.recommended,
        ),
      );
      await Future<void>.delayed(const Duration(milliseconds: 10));

      expect(service.sentMessages, ['claude\n']);
    });
  });
}
