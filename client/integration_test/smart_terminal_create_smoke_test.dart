import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:provider/provider.dart';
import 'package:rc_client/models/project_context_snapshot.dart';
import 'package:rc_client/models/runtime_device.dart';
import 'package:rc_client/models/runtime_terminal.dart';
import 'package:rc_client/screens/runtime_selection_screen.dart';
import 'package:rc_client/services/environment_service.dart';
import 'package:rc_client/services/runtime_device_service.dart';
import 'package:rc_client/services/runtime_selection_controller.dart';
import 'package:rc_client/services/terminal_session_manager.dart';
import 'package:rc_client/services/theme_controller.dart';
import 'package:rc_client/services/websocket_service.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../test/mocks/mock_websocket_service.dart';

class _SmartCreateSmokeRuntimeDeviceService extends RuntimeDeviceService {
  _SmartCreateSmokeRuntimeDeviceService()
      : super(serverUrl: 'ws://localhost:8888');

  final List<RuntimeTerminal> createdTerminals = <RuntimeTerminal>[];

  @override
  Future<List<RuntimeDevice>> listDevices(String token) async {
    return const [
      RuntimeDevice(
        deviceId: 'mbp-01',
        name: 'MacBook Pro',
        owner: 'user1',
        agentOnline: true,
        maxTerminals: 3,
        activeTerminals: 0,
      ),
    ];
  }

  @override
  Future<List<RuntimeTerminal>> listTerminals(
    String token,
    String deviceId,
  ) async {
    return const [];
  }

  @override
  Future<RuntimeTerminal> createTerminal(
    String token,
    String deviceId, {
    required String title,
    required String cwd,
    required String command,
    Map<String, String> env = const {},
    String? terminalId,
  }) async {
    final terminal = RuntimeTerminal(
      terminalId: terminalId ?? 'term-${createdTerminals.length + 1}',
      title: title,
      cwd: cwd,
      command: command,
      status: 'attached',
      views: const {'mobile': 0, 'desktop': 1},
    );
    createdTerminals.add(terminal);
    return terminal;
  }

  @override
  Future<DeviceProjectContextSnapshot> getProjectContextSnapshot(
    String token,
    String deviceId,
  ) async {
    return DeviceProjectContextSnapshot(
      deviceId: deviceId,
      generatedAt: DateTime.parse('2026-04-22T22:30:00Z'),
      candidates: const [
        ProjectContextCandidate(
          candidateId: 'cand-1',
          deviceId: 'mbp-01',
          label: 'remote-control',
          cwd: '/Users/demo/project/remote-control',
          source: 'pinned_project',
          toolHints: ['claude_code', 'shell'],
        ),
      ],
    );
  }

  @override
  Future<DeviceProjectContextSnapshot> refreshProjectContextSnapshot(
    String token,
    String deviceId,
  ) async {
    return getProjectContextSnapshot(token, deviceId);
  }
}

class _SmartCreateSmokeController extends RuntimeSelectionController {
  _SmartCreateSmokeController({
    required super.runtimeService,
  }) : super(
          serverUrl: 'ws://localhost:8888',
          token: 'token',
        );

  @override
  WebSocketService buildTerminalService(RuntimeTerminal terminal) {
    final service = MockWebSocketService();
    service.simulateConnect();
    return service;
  }
}

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  group('Smart terminal create smoke', () {
    late _SmartCreateSmokeRuntimeDeviceService runtimeService;

    setUp(() {
      SharedPreferences.setMockInitialValues(<String, Object>{});
      EnvironmentService.setInstance(
        EnvironmentService(debugModeProvider: () => true),
      );
      runtimeService = _SmartCreateSmokeRuntimeDeviceService();
    });

    Future<void> pumpSmartCreateApp(
      WidgetTester tester,
      RuntimeSelectionController controller,
    ) async {
      await tester.pumpWidget(
        MultiProvider(
          providers: [
            ChangeNotifierProvider(create: (_) => ThemeController()),
            ChangeNotifierProvider(create: (_) => TerminalSessionManager()),
          ],
          child: MaterialApp(
            home: RuntimeSelectionScreen(
              serverUrl: 'ws://localhost:8888',
              token: 'token',
              controller: controller,
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
    }

    testWidgets(
        'mobile smoke covers candidate preview and manual confirmation for relative cwd override',
        (tester) async {
      await tester.binding.setSurfaceSize(const Size(390, 844));
      addTearDown(() => tester.binding.setSurfaceSize(null));

      final controller =
          _SmartCreateSmokeController(runtimeService: runtimeService);

      await pumpSmartCreateApp(tester, controller);

      await tester.tap(find.byKey(const Key('create-terminal')));
      await tester.pumpAndSettle();

      expect(
        find.byKey(const Key('smart-create-preview-candidate')),
        findsOneWidget,
      );

      await tester
          .ensureVisible(find.byKey(const Key('smart-create-advanced')));
      await tester.tap(find.byKey(const Key('smart-create-advanced')));
      await tester.pumpAndSettle();
      await tester.enterText(
        find.byKey(const Key('smart-create-cwd')),
        'project/app',
      );
      await tester.pumpAndSettle();

      expect(
        find.byKey(const Key('smart-create-confirm-manual')),
        findsOneWidget,
      );

      await tester.ensureVisible(
        find.byKey(const Key('smart-create-confirm-manual')),
      );
      await tester.tap(find.byKey(const Key('smart-create-confirm-manual')));
      await tester.pumpAndSettle();
      await tester.ensureVisible(find.byKey(const Key('smart-create-submit')));
      await tester.tap(find.byKey(const Key('smart-create-submit')));
      await tester.pumpAndSettle();

      expect(runtimeService.createdTerminals.single.cwd, 'project/app');
    });

    testWidgets('mobile smoke keeps custom fallback available', (tester) async {
      await tester.binding.setSurfaceSize(const Size(390, 844));
      addTearDown(() => tester.binding.setSurfaceSize(null));

      final controller =
          _SmartCreateSmokeController(runtimeService: runtimeService);

      await pumpSmartCreateApp(tester, controller);

      await tester.tap(find.byKey(const Key('create-terminal')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('smart-create-recommend-custom')));
      await tester.pumpAndSettle();
      await tester.enterText(
        find.byKey(const Key('smart-create-title')),
        'Custom Runner',
      );
      await tester.enterText(
        find.byKey(const Key('smart-create-cwd')),
        '/tmp/custom-project',
      );
      await tester.enterText(
        find.byKey(const Key('smart-create-command')),
        '/bin/zsh',
      );
      await tester.pumpAndSettle();
      await tester.ensureVisible(find.byKey(const Key('smart-create-submit')));
      await tester.tap(find.byKey(const Key('smart-create-submit')));
      await tester.pumpAndSettle();

      expect(runtimeService.createdTerminals.single.title, 'Custom Runner');
      expect(runtimeService.createdTerminals.single.command, '/bin/zsh');
    });
  });
}
