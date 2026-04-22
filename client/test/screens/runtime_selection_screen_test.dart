import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:rc_client/models/project_context_settings.dart';
import 'package:rc_client/models/project_context_snapshot.dart';
import 'package:rc_client/models/runtime_device.dart';
import 'package:rc_client/models/runtime_terminal.dart';
import 'package:rc_client/models/terminal_launch_plan.dart';
import 'package:rc_client/screens/runtime_selection_screen.dart';
import 'package:rc_client/services/environment_service.dart';
import 'package:rc_client/services/planner_credentials_service.dart';
import 'package:rc_client/services/runtime_device_service.dart';
import 'package:rc_client/services/runtime_selection_controller.dart';
import 'package:rc_client/services/terminal_session_manager.dart';
import 'package:rc_client/services/theme_controller.dart';
import 'package:rc_client/services/websocket_service.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../helpers/account_menu_test_helper.dart';
import '../mocks/mock_websocket_service.dart';

class _FakeSelectionController extends RuntimeSelectionController {
  _FakeSelectionController({
    this.failCreateAttempts = 0,
    this.snapshot,
  }) : super(
          serverUrl: 'ws://localhost:8888',
          token: 'token',
          runtimeService: _TestRuntimeDeviceService(),
        );

  final List<RuntimeTerminal> _terminals = [
    const RuntimeTerminal(
      terminalId: 'term-1',
      title: 'Claude / ai_rules',
      cwd: './',
      command: '/bin/bash',
      status: 'detached',
      views: {'mobile': 0, 'desktop': 0},
    ),
  ];

  TerminalLaunchPlan? lastRememberedPlan;
  RuntimeTerminal? lastCreatedTerminal;
  final int failCreateAttempts;
  final DeviceProjectContextSnapshot? snapshot;
  int createAttemptCount = 0;
  String? _errorMessage;
  ProjectContextSettings settings = const ProjectContextSettings(
    deviceId: 'mbp-01',
  );

  @override
  List<RuntimeDevice> get devices => const [
        RuntimeDevice(
          deviceId: 'mbp-01',
          name: 'MacBook Pro',
          owner: 'user1',
          agentOnline: true,
          maxTerminals: 3,
          activeTerminals: 1,
        ),
      ];

  @override
  String? get selectedDeviceId => 'mbp-01';

  @override
  RuntimeDevice? get selectedDevice => devices.first;

  @override
  String? get errorMessage => _errorMessage;

  @override
  List<RuntimeTerminal> get terminals => List.unmodifiable(_terminals);

  @override
  DeviceProjectContextSnapshot? get projectContextSnapshot => snapshot;

  @override
  Future<void> initialize() async {}

  @override
  Future<void> loadDevices() async {}

  @override
  Future<void> selectDevice(String deviceId, {bool notify = true}) async {}

  @override
  Future<RuntimeTerminal?> createTerminal({
    required String title,
    required String cwd,
    required String command,
  }) async {
    createAttemptCount += 1;
    if (createAttemptCount <= failCreateAttempts) {
      _errorMessage = '模拟创建失败';
      notifyListeners();
      return null;
    }
    _errorMessage = null;
    final terminal = RuntimeTerminal(
      terminalId: 'term-created',
      title: title,
      cwd: cwd,
      command: command,
      status: 'detached',
      views: const {'mobile': 0, 'desktop': 0},
    );
    _terminals.add(terminal);
    lastCreatedTerminal = terminal;
    notifyListeners();
    return terminal;
  }

  @override
  Future<void> rememberSuccessfulLaunchPlan(TerminalLaunchPlan plan) async {
    lastRememberedPlan = plan;
  }

  @override
  Future<ProjectContextSettings?> loadProjectContextSettings({
    bool forceRefresh = false,
  }) async {
    return settings;
  }

  @override
  Future<ProjectContextSettings?> updateProjectContextSettings(
    ProjectContextSettings nextSettings,
  ) async {
    settings = nextSettings;
    notifyListeners();
    return settings;
  }

  @override
  WebSocketService buildTerminalService(RuntimeTerminal terminal) {
    return MockWebSocketService();
  }
}

class _FakeDesktopLocalController extends _FakeSelectionController {
  @override
  bool get isLocalDeviceSelected => true;
}

class _TestRuntimeDeviceService extends RuntimeDeviceService {
  _TestRuntimeDeviceService() : super(serverUrl: 'ws://localhost:8888');
}

class _FakePlannerCredentialsService extends PlannerCredentialsService {
  _FakePlannerCredentialsService();

  final Map<String, String> _values = <String, String>{};

  @override
  Future<String?> readApiKey(String deviceId) async => _values[deviceId];

  @override
  Future<void> saveApiKey(String deviceId, String value) async {
    _values[deviceId] = value;
  }

  @override
  Future<void> clearApiKey(String deviceId) async {
    _values.remove(deviceId);
  }
}

void main() {
  late PlannerCredentialsService originalPlannerCredentialsService;

  setUp(() {
    SharedPreferences.setMockInitialValues({});
    EnvironmentService.setInstance(
      EnvironmentService(debugModeProvider: () => true),
    );
    originalPlannerCredentialsService = PlannerCredentialsService.shared;
    PlannerCredentialsService.shared = _FakePlannerCredentialsService();
  });

  tearDown(() {
    PlannerCredentialsService.shared = originalPlannerCredentialsService;
  });

  Future<void> pumpRuntimeSelectionScreen(
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

  testWidgets('shows devices and terminals in selection screen',
      (tester) async {
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
            controller: _FakeSelectionController(),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('选择设备与终端'), findsOneWidget);
    expect(find.byKey(const Key('device-mbp-01')), findsOneWidget);
    expect(find.text('Claude / ai_rules'), findsOneWidget);
    expect(find.text('连接'), findsOneWidget);
    expect(find.text('可创建终端'), findsOneWidget);
  });

  testWidgets('shows local desktop title when local device is selected',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(1280, 900));
    addTearDown(() => tester.binding.setSurfaceSize(null));

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
            controller: _FakeDesktopLocalController(),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('本机终端'), findsOneWidget);
    expect(find.text('选择设备与终端'), findsNothing);
    expect(find.text('本机电脑在线，可直接创建并管理终端'), findsOneWidget);
  });

  testWidgets('shows connect action for available terminals', (tester) async {
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
            controller: _FakeSelectionController(),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    final button =
        tester.widget<FilledButton>(find.widgetWithText(FilledButton, '连接'));
    expect(button.onPressed, isNotNull);
  });

  testWidgets('shows close action for idle terminal', (tester) async {
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
            controller: _FakeSelectionController(),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('close-terminal-term-1')), findsOneWidget);
  });

  testWidgets('shows rename actions for device and terminal', (tester) async {
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
            controller: _FakeSelectionController(),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('edit-device-name')), findsOneWidget);
    expect(find.byKey(const Key('edit-terminal-term-1')), findsOneWidget);
  });

  testWidgets('device edit dialog only shows rename input', (tester) async {
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
            controller: _FakeSelectionController(),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('edit-device-name')));
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('rename-device-input')), findsOneWidget);
    expect(find.byKey(const Key('device-max-terminals-input')), findsNothing);
  });

  testWidgets('account menu exposes feedback and logout actions',
      (tester) async {
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
            controller: _FakeSelectionController(),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    await openAccountMenuAndExpectCommonEntries(tester);
  });

  testWidgets('create terminal dialog exposes smart entry actions',
      (tester) async {
    final controller = _FakeSelectionController();

    await pumpRuntimeSelectionScreen(tester, controller);

    await tester.tap(find.byKey(const Key('create-terminal')));
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('smart-create-intent-input')), findsOneWidget);
    expect(
      find.byKey(const Key('smart-create-recommend-claude_code')),
      findsOneWidget,
    );
    expect(
        find.byKey(const Key('smart-create-recommend-custom')), findsOneWidget);
  });

  testWidgets('smart create dialog can open and save project context settings',
      (tester) async {
    final controller = _FakeSelectionController();

    await pumpRuntimeSelectionScreen(tester, controller);

    await tester.tap(find.byKey(const Key('create-terminal')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('smart-create-project-settings')));
    await tester.pumpAndSettle();

    expect(find.byType(AlertDialog), findsOneWidget);
    await tester.enterText(
      find.byKey(const Key('project-settings-pinned-label')),
      'remote-control',
    );
    await tester.enterText(
      find.byKey(const Key('project-settings-pinned-cwd')),
      '/Users/demo/project/remote-control',
    );
    await tester.tap(find.byKey(const Key('project-settings-pinned-add')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('project-settings-save')));
    await tester.pumpAndSettle();

    expect(controller.settings.pinnedProjects.single.cwd,
        '/Users/demo/project/remote-control');
  });

  testWidgets('intent generation can create codex terminal and remember plan',
      (tester) async {
    final controller = _FakeSelectionController();

    await pumpRuntimeSelectionScreen(tester, controller);

    await tester.tap(find.byKey(const Key('create-terminal')));
    await tester.pumpAndSettle();
    await tester.enterText(
      find.byKey(const Key('smart-create-intent-input')),
      '进入 codex 修一下登录问题',
    );
    await tester.tap(find.byKey(const Key('smart-create-generate')));
    await tester.pumpAndSettle();

    expect(find.text('Codex'), findsWidgets);

    await tester.ensureVisible(find.byKey(const Key('smart-create-submit')));
    await tester.tap(find.byKey(const Key('smart-create-submit')));
    await tester.pumpAndSettle();

    expect(controller.lastCreatedTerminal, isNotNull);
    expect(controller.lastRememberedPlan?.tool, TerminalLaunchTool.codex);
    expect(
      controller.lastRememberedPlan?.entryStrategy,
      TerminalEntryStrategy.shellBootstrap,
    );
  });

  testWidgets(
      'smart create preview shows explanation metadata and supports candidate switch',
      (tester) async {
    final controller = _FakeSelectionController(
      snapshot: DeviceProjectContextSnapshot(
        deviceId: 'mbp-01',
        generatedAt: DateTime.parse('2026-04-22T12:00:00Z'),
        candidates: const [
          ProjectContextCandidate(
            candidateId: 'cand-1',
            deviceId: 'mbp-01',
            label: 'remote-control',
            cwd: '/Users/demo/project/remote-control',
            source: 'pinned_project',
          ),
          ProjectContextCandidate(
            candidateId: 'cand-2',
            deviceId: 'mbp-01',
            label: 'device-two',
            cwd: '/Users/demo/project/device-two',
            source: 'recent_terminal',
          ),
        ],
      ),
    );

    await pumpRuntimeSelectionScreen(tester, controller);

    await tester.tap(find.byKey(const Key('create-terminal')));
    await tester.pumpAndSettle();

    expect(
        find.byKey(const Key('smart-create-preview-source')), findsOneWidget);
    expect(
      find.byKey(const Key('smart-create-preview-provider')),
      findsOneWidget,
    );
    expect(
      find.byKey(const Key('smart-create-candidate-cand-2')),
      findsOneWidget,
    );

    await tester.ensureVisible(
      find.byKey(const Key('smart-create-candidate-cand-2')),
    );
    await tester.tap(find.byKey(const Key('smart-create-candidate-cand-2')));
    await tester.pumpAndSettle();

    expect(find.text('/Users/demo/project/device-two'), findsWidgets);
    expect(
      find.byKey(const Key('smart-create-preview-candidate')),
      findsOneWidget,
    );
    expect(
      find.byKey(const Key('smart-create-preview-user-edited')),
      findsOneWidget,
    );
  });

  testWidgets('custom advanced flow can create custom terminal',
      (tester) async {
    final controller = _FakeSelectionController();

    await pumpRuntimeSelectionScreen(tester, controller);

    await tester.tap(find.byKey(const Key('create-terminal')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('smart-create-recommend-custom')));
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.byKey(const Key('smart-create-title')));
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
    await tester.ensureVisible(find.byKey(const Key('smart-create-submit')));
    await tester.tap(find.byKey(const Key('smart-create-submit')));
    await tester.pumpAndSettle();

    expect(controller.lastCreatedTerminal?.title, 'Custom Runner');
    expect(controller.lastCreatedTerminal?.cwd, '/tmp/custom-project');
    expect(controller.lastCreatedTerminal?.command, '/bin/zsh');
    expect(controller.lastRememberedPlan?.tool, TerminalLaunchTool.custom);
  });

  testWidgets(
      'manual relative cwd override requires confirmation before create',
      (tester) async {
    final controller = _FakeSelectionController();

    await pumpRuntimeSelectionScreen(tester, controller);

    await tester.tap(find.byKey(const Key('create-terminal')));
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.byKey(const Key('smart-create-advanced')));
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
    expect(
      tester
          .widget<FilledButton>(find.byKey(const Key('smart-create-submit')))
          .onPressed,
      isNull,
    );

    await tester.ensureVisible(
      find.byKey(const Key('smart-create-confirm-manual')),
    );
    await tester.tap(find.byKey(const Key('smart-create-confirm-manual')));
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.byKey(const Key('smart-create-submit')));
    await tester.tap(find.byKey(const Key('smart-create-submit')));
    await tester.pumpAndSettle();

    expect(controller.lastCreatedTerminal?.cwd, 'project/app');
  });

  testWidgets('failed create keeps intent and allows retry', (tester) async {
    final controller = _FakeSelectionController(failCreateAttempts: 1);

    await pumpRuntimeSelectionScreen(tester, controller);

    await tester.tap(find.byKey(const Key('create-terminal')));
    await tester.pumpAndSettle();
    await tester.enterText(
      find.byKey(const Key('smart-create-intent-input')),
      '进入 codex 修一下登录问题',
    );
    await tester.tap(find.byKey(const Key('smart-create-generate')));
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.byKey(const Key('smart-create-submit')));
    await tester.tap(find.byKey(const Key('smart-create-submit')));
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('smart-create-intent-input')), findsOneWidget);
    expect(find.text('模拟创建失败'), findsWidgets);
    expect(
      tester
          .widget<TextField>(find.byKey(const Key('smart-create-intent-input')))
          .controller
          ?.text,
      '进入 codex 修一下登录问题',
    );

    await tester.ensureVisible(find.byKey(const Key('smart-create-submit')));
    await tester.tap(find.byKey(const Key('smart-create-submit')));
    await tester.pumpAndSettle();

    expect(controller.createAttemptCount, 2);
    expect(controller.lastCreatedTerminal, isNotNull);
    expect(controller.lastRememberedPlan?.tool, TerminalLaunchTool.codex);
  });

  testWidgets('mobile first-use smoke covers Claude, Codex and Shell paths',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(390, 844));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    final controller = _FakeSelectionController();

    await pumpRuntimeSelectionScreen(tester, controller);

    await tester.tap(find.byKey(const Key('create-terminal')));
    await tester.pumpAndSettle();
    await tester.tap(
      find.byKey(const Key('smart-create-recommend-claude_code')),
    );
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.byKey(const Key('smart-create-submit')));
    await tester.tap(find.byKey(const Key('smart-create-submit')));
    await tester.pumpAndSettle();

    expect(controller.lastRememberedPlan?.tool, TerminalLaunchTool.claudeCode);
    await tester.pageBack();
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('create-terminal')));
    await tester.pumpAndSettle();
    await tester.enterText(
      find.byKey(const Key('smart-create-intent-input')),
      '进入 codex 修一下登录问题',
    );
    await tester.tap(find.byKey(const Key('smart-create-generate')));
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.byKey(const Key('smart-create-submit')));
    await tester.tap(find.byKey(const Key('smart-create-submit')));
    await tester.pumpAndSettle();

    expect(controller.lastRememberedPlan?.tool, TerminalLaunchTool.codex);
    await tester.pageBack();
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('create-terminal')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('smart-create-recommend-shell')));
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.byKey(const Key('smart-create-submit')));
    await tester.tap(find.byKey(const Key('smart-create-submit')));
    await tester.pumpAndSettle();

    expect(controller.lastRememberedPlan?.tool, TerminalLaunchTool.shell);
  });

  testWidgets(
      'mobile first-use smoke covers candidate select, confirmation and custom fallback',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(390, 844));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    final controller = _FakeSelectionController(
      snapshot: DeviceProjectContextSnapshot(
        deviceId: 'mbp-01',
        generatedAt: DateTime.parse('2026-04-22T12:00:00Z'),
        candidates: const [
          ProjectContextCandidate(
            candidateId: 'cand-1',
            deviceId: 'mbp-01',
            label: 'remote-control',
            cwd: '/Users/demo/project/remote-control',
            source: 'pinned_project',
          ),
        ],
      ),
    );

    await pumpRuntimeSelectionScreen(tester, controller);

    await tester.tap(find.byKey(const Key('create-terminal')));
    await tester.pumpAndSettle();

    await tester.ensureVisible(
      find.byKey(const Key('smart-create-candidate-cand-1')),
    );
    await tester.tap(find.byKey(const Key('smart-create-candidate-cand-1')));
    await tester.pumpAndSettle();
    expect(find.text('/Users/demo/project/remote-control'), findsWidgets);

    await tester.enterText(
      find.byKey(const Key('smart-create-intent-input')),
      '进 claude 到 project/app 看下',
    );
    await tester.tap(find.byKey(const Key('smart-create-generate')));
    await tester.pumpAndSettle();
    expect(
      find.byKey(const Key('smart-create-confirm-manual')),
      findsOneWidget,
    );

    await tester.tap(find.byKey(const Key('smart-create-recommend-custom')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('smart-create-title')), findsOneWidget);
    expect(
      find.byKey(const Key('smart-create-preview-user-edited')),
      findsOneWidget,
    );
  });
}
