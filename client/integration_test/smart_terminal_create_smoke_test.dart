import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:provider/provider.dart';
import 'package:rc_client/models/assistant_plan.dart';
import 'package:rc_client/models/command_sequence_draft.dart';
import 'package:rc_client/models/runtime_device.dart';
import 'package:rc_client/models/runtime_terminal.dart';
import 'package:rc_client/models/terminal_launch_plan.dart';
import 'package:rc_client/screens/runtime_selection_screen.dart';
import 'package:rc_client/services/environment_service.dart';
import 'package:rc_client/services/planner_provider.dart';
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
}

class _SmartCreateSmokeController extends RuntimeSelectionController {
  _SmartCreateSmokeController({
    required super.runtimeService,
  }) : super(
          serverUrl: 'ws://localhost:8888',
          token: 'token',
        );

  @override
  Future<PlannerResolutionResult> resolveLaunchIntent(
    String intent, {
    String? conversationId,
    String? messageId,
    void Function(AssistantPlanProgressEvent event)? onProgress,
  }) async {
    const sequence = CommandSequenceDraft(
      summary: '进入 remote-control 并启动 Claude',
      provider: 'smoke_test',
      tool: TerminalLaunchTool.claudeCode,
      title: 'Claude / remote-control',
      cwd: '/Users/demo/project/remote-control',
      shellCommand: '/bin/bash',
      steps: [
        CommandSequenceStep(
          id: 'step_1',
          label: '进入项目目录',
          command: 'cd /Users/demo/project/remote-control',
        ),
        CommandSequenceStep(
          id: 'step_2',
          label: '启动 Claude',
          command: 'claude',
        ),
      ],
      source: TerminalLaunchPlanSource.intent,
    );
    return PlannerResolutionResult(
      provider: 'smoke_test',
      plan: sequence.toLaunchPlan(),
      sequence: sequence,
      reasoningKind: 'smoke_test',
    );
  }

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

    Future<void> pumpUi(
      WidgetTester tester, {
      int frames = 2,
    }) async {
      for (var index = 0; index < frames; index++) {
        await tester.pump(const Duration(milliseconds: 100));
      }
    }

    Future<void> pumpUntil(
      WidgetTester tester,
      bool Function() condition, {
      required String reason,
      int maxTicks = 30,
    }) async {
      for (var index = 0; index < maxTicks; index++) {
        await tester.pump(const Duration(milliseconds: 100));
        if (condition()) {
          return;
        }
      }
      fail('Timed out waiting for $reason');
    }

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
      await pumpUi(tester);
    }

    testWidgets('mobile smoke exposes simplified create entry', (tester) async {
      await tester.binding.setSurfaceSize(const Size(390, 844));
      addTearDown(() => tester.binding.setSurfaceSize(null));

      final controller =
          _SmartCreateSmokeController(runtimeService: runtimeService);

      await pumpSmartCreateApp(tester, controller);

      await tester.tap(find.byKey(const Key('create-terminal')));
      await pumpUntil(
        tester,
        () => find
            .byKey(const Key('smart-create-generate'))
            .evaluate()
            .isNotEmpty,
        reason: 'smart create dialog',
      );

      expect(find.byKey(const Key('smart-create-generate')), findsOneWidget);
      expect(find.byKey(const Key('smart-create-quick-claude')), findsNothing);
      expect(find.byKey(const Key('smart-create-advanced')), findsNothing);
    });

    testWidgets('mobile smoke keeps input-only flow available', (tester) async {
      await tester.binding.setSurfaceSize(const Size(390, 844));
      addTearDown(() => tester.binding.setSurfaceSize(null));

      final controller =
          _SmartCreateSmokeController(runtimeService: runtimeService);

      await pumpSmartCreateApp(tester, controller);

      await tester.tap(find.byKey(const Key('create-terminal')));
      await pumpUntil(
        tester,
        () => find
            .byKey(const Key('smart-create-generate'))
            .evaluate()
            .isNotEmpty,
        reason: 'smart create dialog',
      );
      expect(find.byKey(const Key('smart-create-advanced')), findsNothing);
      await tester.enterText(
        find.byKey(const Key('smart-create-intent-input')),
        '进入 remote-control',
      );
      await tester.tap(find.byKey(const Key('smart-create-generate')));
      await pumpUntil(
        tester,
        () =>
            find.byKey(const Key('smart-create-submit')).evaluate().isNotEmpty,
        reason: 'submit action after intent generation',
      );
      await tester.ensureVisible(find.byKey(const Key('smart-create-submit')));
      await tester.tap(find.byKey(const Key('smart-create-submit')));
      await pumpUntil(
        tester,
        () => runtimeService.createdTerminals.isNotEmpty,
        reason: 'terminal creation result',
      );

      expect(runtimeService.createdTerminals.single.title, isNotEmpty);
      expect(runtimeService.createdTerminals.single.command, isNotEmpty);
    });
  });
}
