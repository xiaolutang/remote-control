import 'package:rc_client/models/command_sequence_draft.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:rc_client/models/assistant_plan.dart';
import 'package:rc_client/models/project_context_settings.dart';
import 'package:rc_client/models/runtime_device.dart';
import 'package:rc_client/models/runtime_terminal.dart';
import 'package:rc_client/models/terminal_launch_plan.dart';
import 'package:rc_client/screens/runtime_selection_screen.dart';
import 'package:rc_client/services/environment_service.dart';
import 'package:rc_client/services/planner_credentials_service.dart';
import 'package:rc_client/services/planner_provider.dart';
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
    this.resolveLaunchIntentHandler,
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
  MockWebSocketService? lastBuiltService;
  Map<String, dynamic>? lastExecutionReport;
  final int failCreateAttempts;
  final Future<PlannerResolutionResult> Function(String intent)?
      resolveLaunchIntentHandler;
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
  Future<void> initialize() async {}

  @override
  Future<void> loadDevices() async {}

  @override
  Future<void> selectDevice(String deviceId, {bool notify = true}) async {}

  @override
  Future<PlannerResolutionResult> resolveLaunchIntent(
    String intent, {
    String? conversationId,
    String? messageId,
    void Function(AssistantPlanProgressEvent event)? onProgress,
  }) async {
    final handler = resolveLaunchIntentHandler;
    if (handler != null) {
      return handler(intent);
    }
    return super.resolveLaunchIntent(
      intent,
      conversationId: conversationId,
      messageId: messageId,
      onProgress: onProgress,
    );
  }

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
    final service = MockWebSocketService(
      deviceId: selectedDeviceId,
      terminalId: terminal.terminalId,
    );
    lastBuiltService = service;
    return service;
  }

  @override
  Future<void> reportAssistantExecution({
    required CommandSequenceDraft draft,
    required String executionStatus,
    String? terminalId,
    String? failedStepId,
    String? outputSummary,
  }) async {
    lastExecutionReport = {
      'conversationId': draft.assistantConversationId,
      'messageId': draft.assistantMessageId,
      'executionStatus': executionStatus,
      'terminalId': terminalId,
      'failedStepId': failedStepId,
      'outputSummary': outputSummary,
    };
  }
}

class _FakeDesktopLocalController extends _FakeSelectionController {
  @override
  bool get isLocalDeviceSelected => true;
}

class _StreamingSelectionController extends _FakeSelectionController {
  _StreamingSelectionController({
    required this.result,
  });

  final PlannerResolutionResult result;

  @override
  Future<PlannerResolutionResult> resolveLaunchIntent(
    String intent, {
    String? conversationId,
    String? messageId,
    void Function(AssistantPlanProgressEvent event)? onProgress,
  }) async {
    onProgress?.call(
      const AssistantPlanProgressEvent(
        type: 'assistant_message',
        assistantMessage: AssistantMessage(
          type: 'assistant',
          text: '先读取项目上下文。',
        ),
      ),
    );
    onProgress?.call(
      const AssistantPlanProgressEvent(
        type: 'trace_item',
        traceItem: AssistantTraceItem(
          stage: 'context',
          title: '定位项目',
          status: 'completed',
          summary: '已找到 remote-control 对应目录',
        ),
      ),
    );
    await Future<void>.delayed(const Duration(milliseconds: 80));
    onProgress?.call(
      const AssistantPlanProgressEvent(
        type: 'trace_item',
        traceItem: AssistantTraceItem(
          stage: 'tool',
          title: '生成命令',
          status: 'running',
          summary: '正在拼接进入目录和启动 Claude 的步骤',
        ),
      ),
    );
    await Future<void>.delayed(const Duration(milliseconds: 80));
    return result;
  }
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

    expect(find.text('远程终端'), findsOneWidget);
    expect(find.byKey(const Key('device-mbp-01')), findsOneWidget);
    expect(find.text('Claude / ai_rules'), findsOneWidget);
    expect(find.text('连接'), findsOneWidget);
    expect(find.text('新建智能终端'), findsOneWidget);
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
    expect(find.text('远程终端'), findsNothing);
    expect(
      find.text('这台本机已经在线。直接说出你要进入哪个项目、用什么工具即可。'),
      findsOneWidget,
    );
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

  testWidgets('create terminal dialog exposes command sequence actions',
      (tester) async {
    final controller = _FakeSelectionController();

    await pumpRuntimeSelectionScreen(tester, controller);

    await tester.tap(find.byKey(const Key('create-terminal')));
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('smart-create-intent-input')), findsOneWidget);
    expect(find.byKey(const Key('smart-create-generate')), findsOneWidget);
    expect(find.byKey(const Key('smart-create-quick-claude')), findsNothing);
    expect(find.byKey(const Key('smart-create-advanced')), findsNothing);
    expect(find.byKey(const Key('smart-create-preview-summary')), findsNothing);
  });

  testWidgets('smart create dialog shows first-use guide only once',
      (tester) async {
    SharedPreferences.setMockInitialValues({});
    final controller = _FakeSelectionController();

    await pumpRuntimeSelectionScreen(tester, controller);

    await tester.tap(find.byKey(const Key('create-terminal')));
    await tester.pumpAndSettle();

    expect(
        find.byKey(const Key('smart-create-first-use-hint')), findsOneWidget);

    await tester.tap(find.byKey(const Key('smart-create-cancel')));
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('create-terminal')));
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('smart-create-first-use-hint')), findsNothing);
  });

  testWidgets('smart create dialog hides first-use guide when already seen',
      (tester) async {
    SharedPreferences.setMockInitialValues({
      'smart_terminal_create_first_use_guide_seen_v2': true,
    });
    final controller = _FakeSelectionController();

    await pumpRuntimeSelectionScreen(tester, controller);

    await tester.tap(find.byKey(const Key('create-terminal')));
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('smart-create-first-use-hint')), findsNothing);
  });

  testWidgets('smart create first-use hint hides when user starts typing',
      (tester) async {
    SharedPreferences.setMockInitialValues({});
    final controller = _FakeSelectionController();

    await pumpRuntimeSelectionScreen(tester, controller);

    await tester.tap(find.byKey(const Key('create-terminal')));
    await tester.pumpAndSettle();

    expect(
        find.byKey(const Key('smart-create-first-use-hint')), findsOneWidget);

    await tester.enterText(
      find.byKey(const Key('smart-create-intent-input')),
      '进入日知项目',
    );
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('smart-create-first-use-hint')), findsNothing);
  });

  testWidgets('intent generation creates claude plan and remembers shell steps',
      (tester) async {
    final controller = _FakeSelectionController();

    await pumpRuntimeSelectionScreen(tester, controller);

    await tester.tap(find.byKey(const Key('create-terminal')));
    await tester.pumpAndSettle();
    await tester.enterText(
      find.byKey(const Key('smart-create-intent-input')),
      '进入 codex 修一下登录问题',
    );
    await tester.ensureVisible(find.byKey(const Key('smart-create-generate')));
    await tester.tap(find.byKey(const Key('smart-create-generate')));
    await tester.pumpAndSettle();

    expect(
        find.byKey(const Key('smart-create-preview-summary')), findsOneWidget);

    await tester.ensureVisible(find.byKey(const Key('smart-create-submit')));
    await tester.tap(find.byKey(const Key('smart-create-submit')));
    await tester.pumpAndSettle();

    expect(controller.lastCreatedTerminal, isNotNull);
    expect(controller.lastRememberedPlan?.tool, TerminalLaunchTool.claudeCode);
    expect(
      controller.lastRememberedPlan?.entryStrategy,
      TerminalEntryStrategy.shellBootstrap,
    );
    expect(controller.lastRememberedPlan?.postCreateInput, contains('claude'));
  });

  testWidgets('real intent "我想进入日知项目" generates rizhi command draft',
      (tester) async {
    final controller = _FakeSelectionController(
      resolveLaunchIntentHandler: (intent) async {
        expect(intent, '我想进入日知项目');
        return PlannerResolutionResult(
          provider: 'service_llm',
          plan: const TerminalLaunchPlan(
            tool: TerminalLaunchTool.claudeCode,
            title: 'Claude / 日知',
            cwd: '/Users/demo/project/rizhi',
            command: '/bin/bash',
            entryStrategy: TerminalEntryStrategy.shellBootstrap,
            postCreateInput: 'set -e\ncd /Users/demo/project/rizhi\nclaude\n',
            source: TerminalLaunchPlanSource.intent,
          ),
          sequence: const CommandSequenceDraft(
            summary: '进入日知项目并启动 Claude',
            provider: 'service_llm',
            tool: TerminalLaunchTool.claudeCode,
            title: 'Claude / 日知',
            cwd: '/Users/demo/project/rizhi',
            shellCommand: '/bin/bash',
            steps: [
              CommandSequenceStep(
                id: 'step_1',
                label: '进入项目目录',
                command: 'cd /Users/demo/project/rizhi',
              ),
              CommandSequenceStep(
                id: 'step_2',
                label: '启动 Claude',
                command: 'claude',
              ),
            ],
            source: TerminalLaunchPlanSource.intent,
            assistantConversationId: 'assistant-mbp-01',
            assistantMessageId: 'msg-rizhi-001',
          ),
          reasoningKind: 'service_llm',
        );
      },
    );

    await pumpRuntimeSelectionScreen(tester, controller);

    await tester.tap(find.byKey(const Key('create-terminal')));
    await tester.pumpAndSettle();
    await tester.enterText(
      find.byKey(const Key('smart-create-intent-input')),
      '我想进入日知项目',
    );
    await tester.ensureVisible(find.byKey(const Key('smart-create-generate')));
    await tester.tap(find.byKey(const Key('smart-create-generate')));
    await tester.pumpAndSettle();

    expect(find.text('进入日知项目并启动 Claude'), findsOneWidget);
    expect(
        find.byKey(const Key('smart-create-preview-summary')), findsOneWidget);

    await tester.ensureVisible(find.byKey(const Key('smart-create-submit')));
    await tester.tap(find.byKey(const Key('smart-create-submit')));
    await tester.pumpAndSettle();

    expect(controller.lastCreatedTerminal, isNotNull);
    expect(controller.lastCreatedTerminal?.cwd, '/Users/demo/project/rizhi');
    expect(controller.lastRememberedPlan?.cwd, '/Users/demo/project/rizhi');
    expect(controller.lastRememberedPlan?.postCreateInput, contains('claude'));
  });

  testWidgets(
      'assistant-backed create reports execution after bootstrap dispatch',
      (tester) async {
    final controller = _FakeSelectionController(
      resolveLaunchIntentHandler: (_) async => PlannerResolutionResult(
        provider: 'service_llm',
        plan: const TerminalLaunchPlan(
          tool: TerminalLaunchTool.claudeCode,
          title: 'Claude / remote-control',
          cwd: '/Users/demo/project/remote-control',
          command: '/bin/bash',
          entryStrategy: TerminalEntryStrategy.shellBootstrap,
          postCreateInput:
              'set -e\ncd /Users/demo/project/remote-control\nclaude\n',
          source: TerminalLaunchPlanSource.intent,
        ),
        sequence: const CommandSequenceDraft(
          summary: '进入 remote-control 并启动 Claude',
          provider: 'service_llm',
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
          assistantConversationId: 'assistant-mbp-01',
          assistantMessageId: 'msg-001',
        ),
        reasoningKind: 'service_llm',
      ),
    );

    await pumpRuntimeSelectionScreen(tester, controller);

    await tester.tap(find.byKey(const Key('create-terminal')));
    await tester.pumpAndSettle();
    await tester.enterText(
      find.byKey(const Key('smart-create-intent-input')),
      '进入 remote-control 修一下登录问题',
    );
    await tester.ensureVisible(find.byKey(const Key('smart-create-generate')));
    await tester.tap(find.byKey(const Key('smart-create-generate')));
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.byKey(const Key('smart-create-submit')));
    await tester.tap(find.byKey(const Key('smart-create-submit')));
    await tester.pumpAndSettle();

    expect(controller.lastBuiltService, isNotNull);
    controller.lastBuiltService!.simulateConnectedEvent();
    await tester.pump(const Duration(milliseconds: 300));
    await tester.pumpAndSettle();

    expect(controller.lastExecutionReport, isNotNull);
    expect(
        controller.lastExecutionReport!['conversationId'], 'assistant-mbp-01');
    expect(controller.lastExecutionReport!['executionStatus'], 'succeeded');
    expect(controller.lastExecutionReport!['terminalId'], 'term-created');
  });

  testWidgets(
      'smart create preview shows only user-facing command content after intent generation',
      (tester) async {
    final controller = _FakeSelectionController();

    await pumpRuntimeSelectionScreen(tester, controller);

    await tester.tap(find.byKey(const Key('create-terminal')));
    await tester.pumpAndSettle();
    await tester.enterText(
      find.byKey(const Key('smart-create-intent-input')),
      '进入 remote-control 项目修一下登录问题',
    );
    await tester.ensureVisible(find.byKey(const Key('smart-create-generate')));
    await tester.tap(find.byKey(const Key('smart-create-generate')));
    await tester.pumpAndSettle();

    expect(
        find.byKey(const Key('smart-create-preview-summary')), findsOneWidget);
    expect(
      find.byKey(const Key('smart-create-preview-info')),
      findsOneWidget,
    );
    expect(find.byKey(const Key('smart-create-preview-step-0')), findsNothing);
    expect(
      find.byKey(const Key('smart-create-preview-source')),
      findsNothing,
    );
    expect(
      find.byKey(const Key('smart-create-preview-provider')),
      findsNothing,
    );
    expect(
      find.byKey(const Key('smart-create-preview-reasoning')),
      findsNothing,
    );
    expect(
      find.byKey(const Key('smart-create-preview-command')),
      findsNothing,
    );
  });

  testWidgets('smart create streams thinking and tool events as chat items',
      (tester) async {
    final controller = _StreamingSelectionController(
      result: PlannerResolutionResult(
        provider: 'service_llm',
        plan: const TerminalLaunchPlan(
          tool: TerminalLaunchTool.claudeCode,
          title: 'Claude / remote-control',
          cwd: '/Users/demo/project/remote-control',
          command: '/bin/bash',
          entryStrategy: TerminalEntryStrategy.shellBootstrap,
          postCreateInput:
              'set -e\ncd /Users/demo/project/remote-control\nclaude\n',
          source: TerminalLaunchPlanSource.intent,
        ),
        sequence: const CommandSequenceDraft(
          summary: '进入 remote-control 并启动 Claude',
          provider: 'service_llm',
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
        ),
        reasoningKind: 'service_llm',
      ),
    );

    await pumpRuntimeSelectionScreen(tester, controller);

    await tester.tap(find.byKey(const Key('create-terminal')));
    await tester.pumpAndSettle();
    await tester.enterText(
      find.byKey(const Key('smart-create-intent-input')),
      '进入 remote-control',
    );
    await tester.tap(find.byKey(const Key('smart-create-generate')));
    await tester.pump();

    expect(find.text('先读取项目上下文。'), findsOneWidget);
    expect(find.text('定位项目'), findsOneWidget);
    expect(find.text('上下文读取'), findsOneWidget);

    await tester.pump(const Duration(milliseconds: 120));
    expect(find.text('生成命令'), findsOneWidget);
    expect(find.text('工具调用'), findsOneWidget);

    await tester.pumpAndSettle();
    expect(
        find.byKey(const Key('smart-create-preview-summary')), findsOneWidget);
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
    await tester.ensureVisible(find.byKey(const Key('smart-create-generate')));
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
      '',
    );

    await tester.ensureVisible(find.byKey(const Key('smart-create-submit')));
    await tester.tap(find.byKey(const Key('smart-create-submit')));
    await tester.pumpAndSettle();

    expect(controller.createAttemptCount, 2);
    expect(controller.lastCreatedTerminal, isNotNull);
    expect(controller.lastRememberedPlan?.tool, TerminalLaunchTool.claudeCode);
  });

  testWidgets(
      'fallback planner result still allows manual create with same-shell claude sequence',
      (tester) async {
    final fallbackSequence = CommandSequenceDraft(
      summary: '定位项目后启动 Claude',
      provider: 'local_rules',
      tool: TerminalLaunchTool.claudeCode,
      title: 'Claude / remote-control',
      cwd: '~',
      shellCommand: '/bin/bash',
      steps: const [
        CommandSequenceStep(
          id: 'step_1',
          label: '确认当前目录',
          command: 'pwd',
        ),
        CommandSequenceStep(
          id: 'step_2',
          label: '查找目标项目',
          command: 'find ~/project -maxdepth 2 -name remote-control',
        ),
        CommandSequenceStep(
          id: 'step_3',
          label: '进入目标项目',
          command: 'cd /Users/demo/project/remote-control',
        ),
        CommandSequenceStep(
          id: 'step_4',
          label: '启动 Claude',
          command: 'claude',
        ),
      ],
      source: TerminalLaunchPlanSource.intent,
      confidence: TerminalLaunchConfidence.medium,
    );
    final controller = _FakeSelectionController(
      resolveLaunchIntentHandler: (_) async => PlannerResolutionResult(
        provider: 'local_rules',
        plan: fallbackSequence.toLaunchPlan(),
        sequence: fallbackSequence,
        reasoningKind: 'fallback',
        fallbackUsed: true,
        fallbackReason: 'claude_cli_unavailable',
      ),
    );

    await pumpRuntimeSelectionScreen(tester, controller);

    await tester.tap(find.byKey(const Key('create-terminal')));
    await tester.pumpAndSettle();
    await tester.enterText(
      find.byKey(const Key('smart-create-intent-input')),
      '进入 remote-control 修一下登录问题',
    );
    await tester.ensureVisible(find.byKey(const Key('smart-create-generate')));
    await tester.tap(find.byKey(const Key('smart-create-generate')));
    await tester.pumpAndSettle();

    expect(
      find.byKey(const Key('smart-create-preview-warning')),
      findsOneWidget,
    );
    expect(find.text('这是一组兜底命令，建议先看一眼再执行。'), findsOneWidget);
    expect(
        find.byKey(const Key('smart-create-preview-summary')), findsOneWidget);

    await tester.ensureVisible(find.byKey(const Key('smart-create-submit')));
    await tester.tap(find.byKey(const Key('smart-create-submit')));
    await tester.pumpAndSettle();

    expect(controller.lastCreatedTerminal?.title, 'Claude / remote-control');
    expect(controller.lastRememberedPlan?.tool, TerminalLaunchTool.claudeCode);
    expect(controller.lastRememberedPlan?.entryStrategy,
        TerminalEntryStrategy.shellBootstrap);
    expect(
      controller.lastRememberedPlan?.postCreateInput,
      'set -e\npwd\nfind ~/project -maxdepth 2 -name remote-control\ncd /Users/demo/project/remote-control\nclaude\n',
    );
  });

  testWidgets('mobile first-use smoke covers intent path', (tester) async {
    await tester.binding.setSurfaceSize(const Size(390, 844));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    final controller = _FakeSelectionController();

    await pumpRuntimeSelectionScreen(tester, controller);

    await tester.tap(find.byKey(const Key('create-terminal')));
    await tester.pumpAndSettle();
    await tester.enterText(
      find.byKey(const Key('smart-create-intent-input')),
      '进入 codex 修一下登录问题',
    );
    await tester.ensureVisible(find.byKey(const Key('smart-create-generate')));
    await tester.tap(find.byKey(const Key('smart-create-generate')));
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.byKey(const Key('smart-create-submit')));
    await tester.tap(find.byKey(const Key('smart-create-submit')));
    await tester.pumpAndSettle();

    expect(controller.lastRememberedPlan?.tool, TerminalLaunchTool.claudeCode);
  });

  testWidgets(
      'mobile smart create dialog adapts actions and supports manual confirmation',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(390, 844));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    final controller = _FakeSelectionController();

    await pumpRuntimeSelectionScreen(tester, controller);

    await tester.tap(find.byKey(const Key('create-terminal')));
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('smart-create-generate')), findsOneWidget);
    expect(find.byKey(const Key('smart-create-quick-claude')), findsNothing);
    expect(find.byKey(const Key('smart-create-advanced')), findsNothing);

    await tester.enterText(
      find.byKey(const Key('smart-create-intent-input')),
      '进 claude 到 project/app 看下',
    );
    await tester.ensureVisible(find.byKey(const Key('smart-create-generate')));
    await tester.tap(find.byKey(const Key('smart-create-generate')));
    await tester.pumpAndSettle();
    expect(
      find.byKey(const Key('smart-create-confirm-manual')),
      findsOneWidget,
    );
    expect(
        find.byKey(const Key('smart-create-preview-warning')), findsOneWidget);
  });
}
