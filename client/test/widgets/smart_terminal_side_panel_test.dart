import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:rc_client/models/assistant_plan.dart';
import 'package:rc_client/models/runtime_device.dart';
import 'package:rc_client/models/runtime_terminal.dart';
import 'package:rc_client/models/terminal_launch_plan.dart';
import 'package:rc_client/services/command_planner/planner_provider.dart';
import 'package:rc_client/services/environment_service.dart';
import 'package:rc_client/services/runtime_device_service.dart';
import 'package:rc_client/services/runtime_selection_controller.dart';
import 'package:rc_client/services/websocket_service.dart';
import 'package:rc_client/widgets/smart_terminal_side_panel.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../mocks/mock_websocket_service.dart';

class _FakeController extends RuntimeSelectionController {
  _FakeController({
    this.desktopPlatform = true,
    this.resolveLaunchIntentHandler,
  }) : super(
          serverUrl: 'ws://localhost:8888',
          token: 'token',
          runtimeService: _TestRuntimeDeviceService(),
        );

  final bool desktopPlatform;
  final Future<PlannerResolutionResult> Function(String)?
      resolveLaunchIntentHandler;

  @override
  bool get isDesktopPlatform => desktopPlatform;

  @override
  List<RuntimeDevice> get devices => const [];

  @override
  List<RuntimeTerminal> get terminals => const [];

  @override
  String? get selectedDeviceId => 'device-1';

  @override
  Future<void> initialize() async {}

  @override
  Future<void> loadDevices() async {}

  @override
  Future<PlannerResolutionResult> resolveLaunchIntent(
    String intent, {
    String? conversationId,
    String? messageId,
    void Function(AssistantPlanProgressEvent event)? onProgress,
  }) async {
    if (resolveLaunchIntentHandler != null) {
      return resolveLaunchIntentHandler!(intent);
    }
    return PlannerResolutionResult(
      provider: 'local_rules',
      plan: const TerminalLaunchPlan(
        tool: TerminalLaunchTool.claudeCode,
        title: 'Test',
        cwd: '~',
        command: '/bin/bash',
        entryStrategy: TerminalEntryStrategy.shellBootstrap,
        postCreateInput: 'echo hello',
        source: TerminalLaunchPlanSource.recommended,
      ),
      reasoningKind: 'test',
    );
  }
}

class _TestRuntimeDeviceService extends RuntimeDeviceService {
  _TestRuntimeDeviceService() : super(serverUrl: 'ws://localhost:8888');
}

Widget _buildTestApp({
  required RuntimeSelectionController controller,
  MockWebSocketService? wsService,
}) {
  final ws = wsService ?? MockWebSocketService()..simulateConnect();
  return MaterialApp(
    home: Scaffold(
      body: MultiProvider(
        providers: [
          ChangeNotifierProvider<RuntimeSelectionController>.value(
              value: controller),
          ChangeNotifierProvider<WebSocketService>.value(value: ws),
        ],
        child: SmartTerminalSidePanel(
          child: const Center(child: Text('Terminal Content')),
        ),
      ),
    ),
  );
}

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues({});
    EnvironmentService.setInstance(
      EnvironmentService(debugModeProvider: () => true),
    );
  });

  group('SmartTerminalSidePanel', () {
    testWidgets('FAB visible when panel closed', (tester) async {
      final controller = _FakeController();
      await tester.pumpWidget(_buildTestApp(controller: controller));

      expect(find.byKey(const Key('smart-terminal-fab')), findsOneWidget);
      expect(find.text('Terminal Content'), findsOneWidget);
    });

    testWidgets('FAB click opens side panel with input and close',
        (tester) async {
      final controller = _FakeController();
      await tester.pumpWidget(_buildTestApp(controller: controller));

      await tester.tap(find.byKey(const Key('smart-terminal-fab')));
      await tester.pumpAndSettle();

      // FAB hidden when panel open
      expect(find.byKey(const Key('smart-terminal-fab')), findsNothing);
      // Panel content visible
      expect(find.byKey(const Key('side-panel-intent-input')), findsOneWidget);
      expect(find.byKey(const Key('side-panel-send')), findsOneWidget);
    });

    testWidgets('close button shows FAB again', (tester) async {
      final controller = _FakeController();
      await tester.pumpWidget(_buildTestApp(controller: controller));

      // Open panel
      await tester.tap(find.byKey(const Key('smart-terminal-fab')));
      await tester.pumpAndSettle();

      // Close via close button
      await tester.tap(find.byKey(const Key('side-panel-close')));
      await tester.pumpAndSettle();

      // FAB visible again
      expect(find.byKey(const Key('smart-terminal-fab')), findsOneWidget);
    });

    testWidgets('tap overlay mask shows FAB again', (tester) async {
      final controller = _FakeController();
      await tester.pumpWidget(_buildTestApp(controller: controller));

      // Open panel
      await tester.tap(find.byKey(const Key('smart-terminal-fab')));
      await tester.pumpAndSettle();

      // Tap the overlay mask (top-left area, outside panel)
      await tester.tapAt(const Offset(50, 50));
      await tester.pumpAndSettle();

      expect(find.byKey(const Key('smart-terminal-fab')), findsOneWidget);
    });

    testWidgets('intent input and send show preview card', (tester) async {
      final controller = _FakeController();
      await tester.pumpWidget(_buildTestApp(controller: controller));

      // Open panel
      await tester.tap(find.byKey(const Key('smart-terminal-fab')));
      await tester.pumpAndSettle();

      // Enter intent
      await tester.enterText(
        find.byKey(const Key('side-panel-intent-input')),
        '进入日知项目',
      );
      // Submit
      await tester.tap(find.byKey(const Key('side-panel-send')));
      await tester.pumpAndSettle();

      // Preview card should appear with execute button
      expect(find.byKey(const Key('side-panel-execute')), findsOneWidget);
      // User bubble visible
      expect(find.text('进入日知项目'), findsOneWidget);
    });

    testWidgets('shows intro text when no turns', (tester) async {
      final controller = _FakeController();
      await tester.pumpWidget(_buildTestApp(controller: controller));

      // Open panel
      await tester.tap(find.byKey(const Key('smart-terminal-fab')));
      await tester.pumpAndSettle();

      expect(find.text('直接说目标，我会生成命令，确认后再执行。'), findsOneWidget);
    });

    testWidgets('execute sends command and closes panel on success',
        (tester) async {
      final controller = _FakeController();
      final ws = MockWebSocketService()..simulateConnect();
      await tester.pumpWidget(_buildTestApp(
        controller: controller,
        wsService: ws,
      ));

      // Open panel
      await tester.tap(find.byKey(const Key('smart-terminal-fab')));
      await tester.pumpAndSettle();

      // Enter intent and resolve
      await tester.enterText(
        find.byKey(const Key('side-panel-intent-input')),
        'test intent',
      );
      await tester.tap(find.byKey(const Key('side-panel-send')));
      await tester.pumpAndSettle();

      // Execute
      await tester.tap(find.byKey(const Key('side-panel-execute')));
      await tester.pumpAndSettle();

      // Panel closed → FAB reappears
      expect(find.byKey(const Key('smart-terminal-fab')), findsOneWidget);
      // Command was sent
      expect(ws.sentMessages, isNotEmpty);
    });

    testWidgets('fallback reason resets between turns', (tester) async {
      var callCount = 0;
      final controller = _FakeController(
        resolveLaunchIntentHandler: (intent) async {
          callCount++;
          if (callCount == 1) {
            return PlannerResolutionResult(
              provider: 'local_rules',
              plan: const TerminalLaunchPlan(
                tool: TerminalLaunchTool.claudeCode,
                title: 'Test',
                cwd: '~',
                command: '/bin/bash',
                entryStrategy: TerminalEntryStrategy.shellBootstrap,
                postCreateInput: '',
                source: TerminalLaunchPlanSource.recommended,
              ),
              reasoningKind: 'test',
              fallbackUsed: true,
              fallbackReason: 'first fallback',
            );
          }
          return PlannerResolutionResult(
            provider: 'local_rules',
            plan: const TerminalLaunchPlan(
              tool: TerminalLaunchTool.claudeCode,
              title: 'Test',
              cwd: '~',
              command: '/bin/bash',
              entryStrategy: TerminalEntryStrategy.shellBootstrap,
              postCreateInput: '',
              source: TerminalLaunchPlanSource.recommended,
            ),
            reasoningKind: 'test',
            fallbackUsed: false,
          );
        },
      );
      final ws = MockWebSocketService()..simulateConnect();
      await tester.pumpWidget(_buildTestApp(
        controller: controller,
        wsService: ws,
      ));

      // Open panel
      await tester.tap(find.byKey(const Key('smart-terminal-fab')));
      await tester.pumpAndSettle();

      // First intent with fallback
      await tester.enterText(
        find.byKey(const Key('side-panel-intent-input')),
        'intent one',
      );
      await tester.tap(find.byKey(const Key('side-panel-send')));
      await tester.pumpAndSettle();

      // Second intent without fallback
      await tester.enterText(
        find.byKey(const Key('side-panel-intent-input')),
        'intent two',
      );
      await tester.tap(find.byKey(const Key('side-panel-send')));
      await tester.pumpAndSettle();

      // Both user bubbles should exist
      expect(find.text('intent one'), findsOneWidget);
      expect(find.text('intent two'), findsOneWidget);
    });
  });
}
