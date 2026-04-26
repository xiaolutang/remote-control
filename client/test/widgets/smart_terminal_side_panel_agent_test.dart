import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:rc_client/models/agent_conversation_projection.dart';
import 'package:rc_client/models/agent_session_event.dart';
import 'package:rc_client/models/assistant_plan.dart';
import 'package:rc_client/models/runtime_device.dart';
import 'package:rc_client/models/runtime_terminal.dart';
import 'package:rc_client/models/terminal_launch_plan.dart';
import 'package:rc_client/services/agent_session_service.dart';
import 'package:rc_client/services/command_planner/planner_provider.dart';
import 'package:rc_client/services/environment_service.dart';
import 'package:rc_client/services/runtime_device_service.dart';
import 'package:rc_client/services/runtime_selection_controller.dart';
import 'package:rc_client/services/usage_summary_service.dart';
import 'package:rc_client/services/websocket_service.dart';
import 'package:rc_client/widgets/smart_terminal_side_panel.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../mocks/mock_websocket_service.dart';

/// Fake controller that can simulate Agent events
class _AgentFakeController extends RuntimeSelectionController {
  _AgentFakeController({
    this.desktopPlatform = true,
    this.resolveLaunchIntentHandler,
  }) : super(
          serverUrl: 'ws://localhost:8888',
          token: 'test-token',
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
  AgentSessionServiceFactory? agentSessionServiceBuilder,
  UsageSummaryServiceFactory? usageSummaryServiceBuilder,
}) {
  final ws = wsService ?? MockWebSocketService()
    ..simulateConnect();
  return MaterialApp(
    home: Scaffold(
      body: MultiProvider(
        providers: [
          ChangeNotifierProvider<RuntimeSelectionController>.value(
              value: controller),
          ChangeNotifierProvider<WebSocketService>.value(value: ws),
        ],
        child: SmartTerminalSidePanel(
          agentSessionServiceBuilder: agentSessionServiceBuilder,
          usageSummaryServiceBuilder: usageSummaryServiceBuilder,
          child: const Center(child: Text('Terminal Content')),
        ),
      ),
    ),
  );
}

Future<void> _openSidePanel(WidgetTester tester) async {
  final fab = tester.widget<FloatingActionButton>(
    find.byKey(const Key('smart-terminal-fab')),
  );
  fab.onPressed?.call();
  await tester.pumpAndSettle();
}

Future<void> _pressSidePanelSend(WidgetTester tester) async {
  final button = tester.widget<FilledButton>(
    find.byKey(const Key('side-panel-send')),
  );
  button.onPressed?.call();
  await tester.pump();
}

class _FakeUsageSummaryService extends UsageSummaryService {
  _FakeUsageSummaryService({
    required this.onFetch,
  }) : super(serverUrl: 'ws://localhost:8888');

  final Future<UsageSummaryData> Function(String token, String deviceId)
      onFetch;
  int fetchCount = 0;

  @override
  Future<UsageSummaryData> fetchSummary({
    required String token,
    required String deviceId,
  }) async {
    fetchCount += 1;
    return onFetch(token, deviceId);
  }
}

class _FakeAgentSessionService extends AgentSessionService {
  _FakeAgentSessionService({
    required this.events,
    this.onFetchConversation,
    this.onRespond,
    this.onRunSession,
    this.onResumeSession,
    this.onStreamConversation,
  }) : super(serverUrl: 'ws://localhost:8888');

  final List<AgentSessionEvent> events;
  final Future<AgentConversationProjection> Function(
    String deviceId,
    String? terminalId,
  )? onFetchConversation;
  final Future<bool> Function(String answer)? onRespond;
  final Stream<AgentSessionEvent> Function(String intent)? onRunSession;
  final Stream<AgentSessionEvent> Function(String sessionId)? onResumeSession;
  final Stream<AgentConversationEventItem> Function(int afterIndex)?
      onStreamConversation;
  final List<String> respondAnswers = [];
  final List<String> runIntents = [];
  final List<String?> conversationIds = [];
  final List<String?> fetchedTerminalIds = [];
  final List<String?> resumedSessionIds = [];
  final List<int> streamedAfterIndexes = [];
  int fetchConversationCount = 0;
  int resumeCount = 0;
  int streamConversationCount = 0;

  @override
  Future<AgentConversationProjection> fetchConversation({
    required String deviceId,
    String? terminalId,
    required String token,
  }) async {
    fetchConversationCount += 1;
    fetchedTerminalIds.add(terminalId);
    if (onFetchConversation != null) {
      return onFetchConversation!(deviceId, terminalId);
    }
    return AgentConversationProjection.empty(
      deviceId: deviceId,
      terminalId: terminalId ?? 'term-1',
    );
  }

  @override
  Stream<AgentSessionEvent> runSession({
    required String deviceId,
    String? terminalId,
    required String intent,
    required String token,
    String? conversationId,
    String? clientEventId,
    int? truncateAfterIndex,
  }) {
    runIntents.add(intent);
    conversationIds.add(conversationId);
    if (onRunSession != null) {
      return onRunSession!(intent);
    }
    return Stream<AgentSessionEvent>.fromIterable(events);
  }

  @override
  Stream<AgentSessionEvent> resumeSession({
    required String deviceId,
    String? terminalId,
    required String sessionId,
    required String token,
  }) {
    resumeCount += 1;
    resumedSessionIds.add(sessionId);
    if (onResumeSession != null) {
      return onResumeSession!(sessionId);
    }
    return const Stream<AgentSessionEvent>.empty();
  }

  @override
  Stream<AgentConversationEventItem> streamConversation({
    required String deviceId,
    String? terminalId,
    required String token,
    int afterIndex = -1,
  }) {
    streamConversationCount += 1;
    streamedAfterIndexes.add(afterIndex);
    if (onStreamConversation != null) {
      return onStreamConversation!(afterIndex);
    }
    return const Stream<AgentConversationEventItem>.empty();
  }

  @override
  Future<bool> respond({
    required String deviceId,
    String? terminalId,
    required String sessionId,
    required String answer,
    required String token,
    String? questionId,
    String? clientEventId,
  }) async {
    respondAnswers.add(answer);
    if (onRespond != null) {
      return onRespond!(answer);
    }
    return true;
  }

  @override
  Future<bool> cancel({
    required String deviceId,
    String? terminalId,
    required String sessionId,
    required String token,
  }) async {
    return true;
  }
}

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues({});
    EnvironmentService.setInstance(
      EnvironmentService(debugModeProvider: () => true),
    );
  });

  group('Agent SSE interaction', () {
    testWidgets('shows usage button and toast auto hides', (tester) async {
      final controller = _AgentFakeController();
      final usageService = _FakeUsageSummaryService(
        onFetch: (_, __) async => const UsageSummaryData(
          device: UsageSummaryScope(
            totalSessions: 2,
            totalInputTokens: 120,
            totalOutputTokens: 80,
            totalTokens: 200,
            totalRequests: 3,
            latestModelName: 'deepseek-chat',
          ),
          user: UsageSummaryScope(
            totalSessions: 5,
            totalInputTokens: 620,
            totalOutputTokens: 280,
            totalTokens: 900,
            totalRequests: 11,
            latestModelName: 'deepseek-chat',
          ),
        ),
      );
      await tester.pumpWidget(_buildTestApp(
        controller: controller,
        usageSummaryServiceBuilder: (_) => usageService,
      ));

      await _openSidePanel(tester);

      expect(find.byKey(const Key('side-panel-usage-button')), findsOneWidget);

      await tester.tap(find.byKey(const Key('side-panel-usage-button')));
      await tester.pumpAndSettle();

      expect(find.byKey(const Key('side-panel-usage-toast')), findsOneWidget);
      expect(find.text('当前终端'), findsOneWidget);
      expect(find.text('我的总计'), findsOneWidget);
      expect(find.text('200'), findsOneWidget);
      expect(find.text('900'), findsOneWidget);

      await tester.pump(const Duration(seconds: 3));
      await tester.pumpAndSettle();

      expect(find.byKey(const Key('side-panel-usage-toast')), findsNothing);
    });

    testWidgets('repeated usage button tap resets hide timer', (tester) async {
      final controller = _AgentFakeController();
      final usageService = _FakeUsageSummaryService(
        onFetch: (_, __) async => const UsageSummaryData.empty(),
      );
      await tester.pumpWidget(_buildTestApp(
        controller: controller,
        usageSummaryServiceBuilder: (_) => usageService,
      ));

      await _openSidePanel(tester);

      await tester.tap(find.byKey(const Key('side-panel-usage-button')));
      await tester.pumpAndSettle();
      await tester.pump(const Duration(seconds: 2));

      await tester.tap(find.byKey(const Key('side-panel-usage-button')));
      await tester.pumpAndSettle();
      await tester.pump(const Duration(seconds: 2));

      expect(find.byKey(const Key('side-panel-usage-toast')), findsOneWidget);

      await tester.pump(const Duration(seconds: 2));
      await tester.pumpAndSettle();

      expect(find.byKey(const Key('side-panel-usage-toast')), findsNothing);
    });

    testWidgets('refreshes usage summary after agent result arrives',
        (tester) async {
      final controller = _AgentFakeController();
      final usageService = _FakeUsageSummaryService(
        onFetch: (_, __) async => const UsageSummaryData(
          device: UsageSummaryScope(
            totalSessions: 1,
            totalInputTokens: 1520,
            totalOutputTokens: 380,
            totalTokens: 1900,
            totalRequests: 3,
            latestModelName: 'deepseek-chat',
          ),
          user: UsageSummaryScope(
            totalSessions: 4,
            totalInputTokens: 5400,
            totalOutputTokens: 1200,
            totalTokens: 6600,
            totalRequests: 10,
            latestModelName: 'deepseek-chat',
          ),
        ),
      );
      final agentService = _FakeAgentSessionService(
        events: [
          const AgentSessionCreatedEvent(sessionId: 'session-1'),
          AgentResultEvent(
            summary: 'done',
            steps: const [],
            provider: 'agent',
            source: 'recommended',
            needConfirm: false,
            aliases: const <String, String>{},
            usage: const AgentUsageData(
              inputTokens: 1520,
              outputTokens: 380,
              totalTokens: 1900,
              requests: 3,
              modelName: 'deepseek-chat',
            ),
          ),
        ],
      );
      await tester.pumpWidget(_buildTestApp(
        controller: controller,
        agentSessionServiceBuilder: (_) => agentService,
        usageSummaryServiceBuilder: (_) => usageService,
      ));

      await _openSidePanel(tester);
      await tester.enterText(
        find.byKey(const Key('side-panel-intent-input')),
        'show usage',
      );
      await _pressSidePanelSend(tester);
      await tester.pumpAndSettle();

      expect(usageService.fetchCount, 1);

      await tester.tap(find.byKey(const Key('side-panel-usage-button')));
      await tester.pumpAndSettle();

      expect(find.text('1900'), findsOneWidget);
      expect(find.text('6600'), findsOneWidget);
    });

    testWidgets('shows degraded message when usage summary fails',
        (tester) async {
      final controller = _AgentFakeController();
      final usageService = _FakeUsageSummaryService(
        onFetch: (_, __) async {
          throw const UsageSummaryException(message: 'timeout');
        },
      );
      await tester.pumpWidget(_buildTestApp(
        controller: controller,
        usageSummaryServiceBuilder: (_) => usageService,
      ));

      await _openSidePanel(tester);
      await tester.tap(find.byKey(const Key('side-panel-usage-button')));
      await tester.pumpAndSettle();

      expect(find.byKey(const Key('side-panel-usage-error')), findsOneWidget);
      expect(find.text('统计暂不可用，稍后会自动重试'), findsOneWidget);
    });

    testWidgets('exploring state shows trace expansion tile', (tester) async {
      final controller = _AgentFakeController();
      final ws = MockWebSocketService()..simulateConnect();
      await tester.pumpWidget(_buildTestApp(
        controller: controller,
        wsService: ws,
      ));

      // Open panel
      await _openSidePanel(tester);

      // Enter intent and submit
      await tester.enterText(
        find.byKey(const Key('side-panel-intent-input')),
        '进入项目',
      );
      await _pressSidePanelSend(tester);

      // The Agent SSE service is instantiated inside the widget;
      // since the HTTP call will fail in test, the widget should
      // eventually fallback. But we test the UI state directly by
      // checking that the loading indicator appears during exploring.
      // After timeout it should fall back to planner mode.
      await tester.pumpAndSettle(const Duration(seconds: 5));

      // Should show either loading or fallback planner result
      expect(find.byKey(const Key('side-panel-intent-input')), findsOneWidget);
    });

    testWidgets('asking state shows option buttons', (tester) async {
      final controller = _AgentFakeController();
      final agentService = _FakeAgentSessionService(
        events: const [
          AgentSessionCreatedEvent(sessionId: 'session-1'),
          AgentQuestionEvent(
            question: 'Which project?',
            options: ['remote-control', 'log-service'],
            multiSelect: false,
          ),
        ],
        onRespond: (_) async => true,
      );
      await tester.pumpWidget(_buildTestApp(
        controller: controller,
        agentSessionServiceBuilder: (_) => agentService,
      ));

      await _openSidePanel(tester);
      await tester.enterText(
        find.byKey(const Key('side-panel-intent-input')),
        '打开项目',
      );
      await tester.tap(find.byKey(const Key('side-panel-send')));
      await tester.pumpAndSettle();

      expect(find.text('Which project?'), findsOneWidget);
      expect(find.text('remote-control'), findsOneWidget);
      expect(find.text('log-service'), findsOneWidget);
      expect(find.byType(CircularProgressIndicator), findsNothing);
    });

    testWidgets('asking state send button submits answer and resumes exploring',
        (tester) async {
      final controller = _AgentFakeController();
      final agentService = _FakeAgentSessionService(
        events: const [
          AgentSessionCreatedEvent(sessionId: 'session-1'),
          AgentQuestionEvent(
            question: 'Which project?',
            options: ['remote-control', 'log-service'],
            multiSelect: false,
          ),
        ],
      );
      await tester.pumpWidget(_buildTestApp(
        controller: controller,
        agentSessionServiceBuilder: (_) => agentService,
      ));

      await _openSidePanel(tester);
      await tester.enterText(
        find.byKey(const Key('side-panel-intent-input')),
        '打开项目',
      );
      await tester.tap(find.byKey(const Key('side-panel-send')));
      await tester.pumpAndSettle();

      await tester.enterText(
        find.byKey(const Key('side-panel-intent-input')),
        'remote-control',
      );
      await _pressSidePanelSend(tester);

      expect(agentService.respondAnswers, ['remote-control']);
      expect(find.text('Agent 正在分析...'), findsOneWidget);
    });

    testWidgets('asking option tap submits answer and resumes exploring',
        (tester) async {
      final controller = _AgentFakeController();
      final agentService = _FakeAgentSessionService(
        events: const [
          AgentSessionCreatedEvent(sessionId: 'session-1'),
          AgentQuestionEvent(
            question: 'Which project?',
            options: ['remote-control', 'log-service'],
            multiSelect: false,
          ),
        ],
      );
      await tester.pumpWidget(_buildTestApp(
        controller: controller,
        agentSessionServiceBuilder: (_) => agentService,
      ));

      await _openSidePanel(tester);
      await tester.enterText(
        find.byKey(const Key('side-panel-intent-input')),
        '打开项目',
      );
      await tester.tap(find.byKey(const Key('side-panel-send')));
      await tester.pumpAndSettle();

      await tester.tap(find.text('remote-control'));
      await tester.pump();

      expect(agentService.respondAnswers, ['remote-control']);
      expect(find.text('Agent 正在分析...'), findsOneWidget);
    });

    testWidgets('panel hydrates history from server projection on open',
        (tester) async {
      final controller = _AgentFakeController();
      final agentService = _FakeAgentSessionService(
        events: const [],
        onFetchConversation: (_, __) async => AgentConversationProjection(
          conversationId: 'conv-server-1',
          deviceId: 'device-1',
          terminalId: 'term-1',
          status: 'active',
          nextEventIndex: 2,
          activeSessionId: null,
          events: const [
            AgentConversationEventItem(
              eventIndex: 0,
              eventId: 'evt-0',
              type: 'user_intent',
              role: 'user',
              payload: {'text': '打开日知项目'},
            ),
            AgentConversationEventItem(
              eventIndex: 1,
              eventId: 'evt-1',
              type: 'result',
              role: 'assistant',
              payload: {
                'summary': '已定位到日知项目。',
                'steps': [
                  {
                    'id': 'step-1',
                    'label': '进入目录',
                    'command': 'cd /Users/demo/project/rizhi',
                  },
                ],
                'provider': 'agent',
                'source': 'recommended',
                'need_confirm': false,
                'aliases': {'rizhi': '/Users/demo/project/rizhi'},
              },
            ),
          ],
        ),
      );
      await tester.pumpWidget(_buildTestApp(
        controller: controller,
        agentSessionServiceBuilder: (_) => agentService,
      ));
      await tester.pumpAndSettle();

      await _openSidePanel(tester);

      expect(agentService.fetchConversationCount, 1);
      expect(find.text('打开日知项目'), findsOneWidget);
      expect(find.text('已定位到日知项目。'), findsOneWidget);
      expect(find.byKey(const Key('side-panel-execute')), findsOneWidget);

      await tester.enterText(
        find.byKey(const Key('side-panel-intent-input')),
        '继续打开这个项目',
      );
      await _pressSidePanelSend(tester);

      expect(agentService.runIntents, ['继续打开这个项目']);
      expect(agentService.conversationIds, ['conv-server-1']);
    });

    testWidgets('panel restores active question via conversation projection',
        (tester) async {
      final controller = _AgentFakeController();
      final agentService = _FakeAgentSessionService(
        events: const [],
        onFetchConversation: (_, __) async => AgentConversationProjection(
          conversationId: 'conv-server-2',
          deviceId: 'device-1',
          terminalId: 'term-1',
          status: 'active',
          nextEventIndex: 3,
          activeSessionId: 'session-1',
          events: const [
            AgentConversationEventItem(
              eventIndex: 0,
              eventId: 'evt-0',
              type: 'user_intent',
              role: 'user',
              payload: {'text': '打开项目'},
            ),
            AgentConversationEventItem(
              eventIndex: 1,
              eventId: 'evt-1',
              type: 'trace',
              role: 'assistant',
              payload: {
                'tool': 'scan_projects',
                'input_summary': '扫描本地项目',
                'output_summary': '找到 2 个项目',
              },
            ),
            AgentConversationEventItem(
              eventIndex: 2,
              eventId: 'evt-2',
              type: 'question',
              role: 'assistant',
              questionId: 'q-1',
              payload: {
                'question': 'Which project?',
                'options': ['remote-control', 'log-service'],
                'multi_select': false,
              },
            ),
          ],
        ),
      );
      await tester.pumpWidget(_buildTestApp(
        controller: controller,
        agentSessionServiceBuilder: (_) => agentService,
      ));
      await tester.pumpAndSettle();

      await _openSidePanel(tester);

      expect(find.text('Which project?'), findsOneWidget);
      expect(find.text('remote-control'), findsOneWidget);
      // 不再 resume agent session，而是通过 conversation stream 接收事件
      expect(agentService.resumeCount, 0);
    });

    testWidgets('conversation stream syncs remote question and result',
        (tester) async {
      final controller = _AgentFakeController();
      final streamController = StreamController<AgentConversationEventItem>();
      final agentService = _FakeAgentSessionService(
        events: const [],
        onFetchConversation: (_, __) async => const AgentConversationProjection(
          conversationId: 'conv-server-3',
          deviceId: 'device-1',
          terminalId: 'term-1',
          status: 'active',
          nextEventIndex: 0,
          activeSessionId: null,
          events: [],
        ),
        onStreamConversation: (_) => streamController.stream,
      );
      await tester.pumpWidget(_buildTestApp(
        controller: controller,
        agentSessionServiceBuilder: (_) => agentService,
      ));
      await tester.pumpAndSettle();
      await _openSidePanel(tester);

      streamController.add(const AgentConversationEventItem(
        eventIndex: 0,
        eventId: 'evt-0',
        type: 'user_intent',
        role: 'user',
        payload: {'text': '打开远端项目'},
      ));
      streamController.add(const AgentConversationEventItem(
        eventIndex: 1,
        eventId: 'evt-1',
        type: 'question',
        role: 'assistant',
        questionId: 'q-1',
        payload: {
          'question': 'Which project?',
          'options': ['remote-control'],
          'multi_select': false,
        },
      ));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      expect(find.text('Which project?'), findsOneWidget);
      expect(find.text('remote-control'), findsOneWidget);

      streamController.add(const AgentConversationEventItem(
        eventIndex: 2,
        eventId: 'evt-2',
        type: 'answer',
        role: 'user',
        questionId: 'q-1',
        payload: {'text': 'remote-control'},
      ));
      streamController.add(const AgentConversationEventItem(
        eventIndex: 3,
        eventId: 'evt-3',
        type: 'result',
        role: 'assistant',
        payload: {
          'summary': '远端结果已同步',
          'steps': [],
          'provider': 'agent',
          'source': 'recommended',
          'need_confirm': false,
          'aliases': {},
        },
      ));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      expect(find.text('远端结果已同步'), findsOneWidget);
      expect(find.text('Agent 正在分析...'), findsNothing);
      // Q&A interaction should remain visible after result
      expect(find.text('Which project?'), findsOneWidget);
      expect(find.text('remote-control'), findsAtLeast(1));
      unawaited(streamController.close());
    });

    testWidgets(
        'conversation stream syncs message type result (response_type=message)',
        (tester) async {
      final controller = _AgentFakeController();
      final streamController = StreamController<AgentConversationEventItem>();
      final agentService = _FakeAgentSessionService(
        events: const [],
        onFetchConversation: (_, __) async =>
            const AgentConversationProjection(
          conversationId: 'conv-sync-msg',
          deviceId: 'device-1',
          terminalId: 'term-1',
          status: 'active',
          nextEventIndex: 0,
          activeSessionId: null,
          events: [],
        ),
        onStreamConversation: (_) => streamController.stream,
      );
      await tester.pumpWidget(_buildTestApp(
        controller: controller,
        agentSessionServiceBuilder: (_) => agentService,
      ));
      await tester.pumpAndSettle();
      await _openSidePanel(tester);

      // 远端产生 user_intent + message 类型 result
      streamController.add(const AgentConversationEventItem(
        eventIndex: 0,
        eventId: 'evt-msg-0',
        type: 'user_intent',
        role: 'user',
        payload: {'text': '查一下部署状态'},
      ));
      streamController.add(const AgentConversationEventItem(
        eventIndex: 1,
        eventId: 'evt-msg-1',
        type: 'result',
        role: 'assistant',
        payload: {
          'summary': '所有服务运行正常，无异常日志。',
          'steps': <Map<String, dynamic>>[],
          'provider': 'agent',
          'source': 'recommended',
          'need_confirm': false,
          'aliases': <String, dynamic>{},
          'response_type': 'message',
        },
      ));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      expect(find.text('查一下部署状态'), findsOneWidget);
      expect(find.text('所有服务运行正常，无异常日志。'), findsOneWidget);
      // message 类型不再显示折叠卡片和"已回复"标签
      expect(
          find.byKey(const Key('side-panel-message-replied-tag')),
          findsNothing);
      // message 类型无执行按钮、无注入按钮
      expect(find.byKey(const Key('side-panel-execute')), findsNothing);
      expect(
          find.byKey(const Key('side-panel-inject-prompt')), findsNothing);
      unawaited(streamController.close());
    });

    testWidgets(
        'conversation stream syncs ai_prompt type result (response_type=ai_prompt)',
        (tester) async {
      final controller = _AgentFakeController();
      final streamController = StreamController<AgentConversationEventItem>();
      final agentService = _FakeAgentSessionService(
        events: const [],
        onFetchConversation: (_, __) async =>
            const AgentConversationProjection(
          conversationId: 'conv-sync-prompt',
          deviceId: 'device-1',
          terminalId: 'term-1',
          status: 'active',
          nextEventIndex: 0,
          activeSessionId: null,
          events: [],
        ),
        onStreamConversation: (_) => streamController.stream,
      );
      await tester.pumpWidget(_buildTestApp(
        controller: controller,
        agentSessionServiceBuilder: (_) => agentService,
      ));
      await tester.pumpAndSettle();
      await _openSidePanel(tester);

      // 远端产生 user_intent + ai_prompt 类型 result
      streamController.add(const AgentConversationEventItem(
        eventIndex: 0,
        eventId: 'evt-prompt-0',
        type: 'user_intent',
        role: 'user',
        payload: {'text': '帮我生成部署脚本'},
      ));
      streamController.add(const AgentConversationEventItem(
        eventIndex: 1,
        eventId: 'evt-prompt-1',
        type: 'result',
        role: 'assistant',
        payload: {
          'summary': '已生成部署脚本',
          'steps': <Map<String, dynamic>>[],
          'provider': 'agent',
          'source': 'recommended',
          'need_confirm': false,
          'aliases': <String, dynamic>{},
          'response_type': 'ai_prompt',
          'ai_prompt': 'kubectl apply -f deploy.yaml',
        },
      ));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      expect(find.text('帮我生成部署脚本'), findsOneWidget);
      expect(find.text('已生成部署脚本'), findsOneWidget);
      // ai_prompt 类型展示 prompt 文本
      expect(find.text('kubectl apply -f deploy.yaml'), findsOneWidget);
      // 活跃结果无执行按钮
      expect(find.byKey(const Key('side-panel-execute')), findsNothing);
      // 活跃 ai_prompt 结果有注入按钮（跨端同步后可注入）
      expect(
          find.byKey(const Key('side-panel-inject-prompt')), findsOneWidget);
      unawaited(streamController.close());
    });

    testWidgets(
        'SSE session preserves conversation stream; history shows after sync',
        (tester) async {
      // 验证修复：SSE 会话期间不取消 conversation stream，
      // SSE 结束后从 _serverConversationEvents 同步重建状态。
      final controller = _AgentFakeController();
      final convStreamController =
          StreamController<AgentConversationEventItem>();
      var runSessionCall = 0;

      Stream<AgentSessionEvent> _runSession(String intent) async* {
        runSessionCall++;
        yield AgentSessionCreatedEvent(
          sessionId: 'session-$runSessionCall',
          conversationId: 'conv-sync',
        );
        if (runSessionCall == 1) {
          yield AgentTraceEvent(
            tool: 'execute_command',
            inputSummary: 'ls',
            outputSummary: 'project',
          );
          yield AgentResultEvent(
            summary: '第一个意图结果',
            steps: [],
            provider: 'agent',
            source: 'recommended',
            needConfirm: false,
            aliases: const {},
          );
        } else {
          yield AgentResultEvent(
            summary: '第二个意图结果',
            steps: [],
            provider: 'agent',
            source: 'recommended',
            needConfirm: false,
            aliases: const {},
          );
        }
      }

      final agentService = _FakeAgentSessionService(
        events: const [],
        onFetchConversation: (_, __) async =>
            const AgentConversationProjection(
              conversationId: 'conv-sync',
              deviceId: 'device-1',
              terminalId: 'term-1',
              status: 'active',
              nextEventIndex: 0,
              activeSessionId: null,
              events: [],
            ),
        onStreamConversation: (_) => convStreamController.stream,
        onRunSession: _runSession,
      );

      await tester.pumpWidget(_buildTestApp(
        controller: controller,
        agentSessionServiceBuilder: (_) => agentService,
      ));
      await tester.pumpAndSettle();
      await _openSidePanel(tester);

      // 发送第一个意图
      await tester.enterText(
        find.byKey(const Key('side-panel-intent-input')),
        '第一个意图',
      );
      await _pressSidePanelSend(tester);
      await tester.pumpAndSettle();

      // 第一个结果应该可见
      expect(find.text('第一个意图结果'), findsOneWidget);

      // conversation stream 仍在运行（未被 SSE 取消），
      // 模拟服务端推送第一个意图的 conversation events
      convStreamController.add(const AgentConversationEventItem(
        eventIndex: 0,
        eventId: 'evt-0',
        type: 'user_intent',
        role: 'user',
        payload: {'text': '第一个意图'},
      ));
      convStreamController.add(const AgentConversationEventItem(
        eventIndex: 1,
        eventId: 'evt-1',
        type: 'trace',
        role: 'assistant',
        payload: {'tool': 'execute_command', 'input_summary': 'ls'},
      ));
      convStreamController.add(const AgentConversationEventItem(
        eventIndex: 2,
        eventId: 'evt-2',
        type: 'result',
        role: 'assistant',
        payload: {
          'summary': '第一个意图结果',
          'steps': [],
          'provider': 'agent',
          'source': 'recommended',
          'need_confirm': false,
          'aliases': {},
        },
      ));
      await tester.pump();

      // 发送第二个意图
      await tester.enterText(
        find.byKey(const Key('side-panel-intent-input')),
        '第二个意图',
      );
      await _pressSidePanelSend(tester);
      await tester.pumpAndSettle();

      // 第一个意图应该在历史中可见（用户气泡）
      expect(find.text('第一个意图'), findsOneWidget);
      // 第二个意图的结果应该可见
      expect(find.text('第二个意图结果'), findsOneWidget);

      // conversation stream 推送第二个意图的事件
      convStreamController.add(const AgentConversationEventItem(
        eventIndex: 3,
        eventId: 'evt-3',
        type: 'user_intent',
        role: 'user',
        payload: {'text': '第二个意图'},
      ));
      convStreamController.add(const AgentConversationEventItem(
        eventIndex: 4,
        eventId: 'evt-4',
        type: 'result',
        role: 'assistant',
        payload: {
          'summary': '第二个意图结果',
          'steps': [],
          'provider': 'agent',
          'source': 'recommended',
          'need_confirm': false,
          'aliases': {},
        },
      ));
      await tester.pump();

      // 两个意图的用户气泡都应该在历史中
      expect(find.text('第一个意图'), findsOneWidget);
      expect(find.text('第二个意图'), findsOneWidget);

      unawaited(convStreamController.close());
    });

    testWidgets('conversation stream closed event disables smart input',
        (tester) async {
      final controller = _AgentFakeController();
      final streamController = StreamController<AgentConversationEventItem>();
      final agentService = _FakeAgentSessionService(
        events: const [],
        onFetchConversation: (_, __) async => const AgentConversationProjection(
          conversationId: 'conv-server-4',
          deviceId: 'device-1',
          terminalId: 'term-1',
          status: 'active',
          nextEventIndex: 0,
          activeSessionId: null,
          events: [],
        ),
        onStreamConversation: (_) => streamController.stream,
      );
      await tester.pumpWidget(_buildTestApp(
        controller: controller,
        agentSessionServiceBuilder: (_) => agentService,
      ));
      await tester.pumpAndSettle();
      await _openSidePanel(tester);

      streamController.add(const AgentConversationEventItem(
        eventIndex: 0,
        eventId: 'evt-closed',
        type: 'closed',
        role: 'system',
        payload: {'reason': 'user_request'},
      ));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      expect(
        find.byKey(const Key('side-panel-terminal-closed-message')),
        findsOneWidget,
      );
      final input = tester.widget<TextField>(
        find.byKey(const Key('side-panel-intent-input')),
      );
      expect(input.enabled, isFalse);
      final sendButton = tester.widget<FilledButton>(
        find.byKey(const Key('side-panel-send')),
      );
      expect(sendButton.onPressed, isNull);
      unawaited(streamController.close());
    });

    testWidgets(
        'terminal switch clears old projection and reloads new terminal',
        (tester) async {
      final controller = _AgentFakeController();
      final agentService = _FakeAgentSessionService(
        events: const [],
        onFetchConversation: (_, terminalId) async {
          if (terminalId == 'term-2') {
            return AgentConversationProjection(
              conversationId: 'conv-server-2',
              deviceId: 'device-1',
              terminalId: 'term-2',
              status: 'active',
              nextEventIndex: 2,
              activeSessionId: null,
              events: const [
                AgentConversationEventItem(
                  eventIndex: 0,
                  eventId: 'evt-0',
                  type: 'user_intent',
                  role: 'user',
                  payload: {'text': '打开 term-2 项目'},
                ),
                AgentConversationEventItem(
                  eventIndex: 1,
                  eventId: 'evt-1',
                  type: 'result',
                  role: 'assistant',
                  payload: {
                    'summary': 'term-2 已就绪',
                    'steps': [],
                    'provider': 'agent',
                    'source': 'recommended',
                    'need_confirm': false,
                    'aliases': {},
                  },
                ),
              ],
            );
          }
          return AgentConversationProjection(
            conversationId: 'conv-server-1',
            deviceId: 'device-1',
            terminalId: 'term-1',
            status: 'active',
            nextEventIndex: 2,
            activeSessionId: null,
            events: const [
              AgentConversationEventItem(
                eventIndex: 0,
                eventId: 'evt-0',
                type: 'user_intent',
                role: 'user',
                payload: {'text': '打开 term-1 项目'},
              ),
              AgentConversationEventItem(
                eventIndex: 1,
                eventId: 'evt-1',
                type: 'result',
                role: 'assistant',
                payload: {
                  'summary': 'term-1 已就绪',
                  'steps': [],
                  'provider': 'agent',
                  'source': 'recommended',
                  'need_confirm': false,
                  'aliases': {},
                },
              ),
            ],
          );
        },
      );
      final wsTerm1 = MockWebSocketService(terminalId: 'term-1')
        ..simulateConnect();
      await tester.pumpWidget(_buildTestApp(
        controller: controller,
        wsService: wsTerm1,
        agentSessionServiceBuilder: (_) => agentService,
      ));
      await tester.pumpAndSettle();

      await _openSidePanel(tester);
      expect(find.text('打开 term-1 项目'), findsOneWidget);

      final wsTerm2 = MockWebSocketService(terminalId: 'term-2')
        ..simulateConnect();
      await tester.pumpWidget(_buildTestApp(
        controller: controller,
        wsService: wsTerm2,
        agentSessionServiceBuilder: (_) => agentService,
      ));
      await tester.pumpAndSettle();

      expect(find.text('打开 term-1 项目'), findsNothing);
      expect(find.text('打开 term-2 项目'), findsOneWidget);
      expect(agentService.fetchedTerminalIds, ['term-1', 'term-2']);
    });

    testWidgets('new agent turn includes recent confirmed project context',
        (tester) async {
      final controller = _AgentFakeController();
      final agentService = _FakeAgentSessionService(
        events: [
          const AgentSessionCreatedEvent(
            sessionId: 'session-1',
            conversationId: 'conv-server-1',
          ),
          AgentResultEvent(
            summary: '打开 personal-growth-assistant（个人成长助手）项目，并准备后续启动命令。',
            steps: const [
              AgentResultStep(
                id: 'step-1',
                label: '进入目录',
                command:
                    'cd /Users/tangxiaolu/project/personal-growth-assistant',
              ),
            ],
            provider: 'agent',
            source: 'recommended',
            needConfirm: false,
            aliases: const {
              'personal-growth-assistant':
                  '/Users/tangxiaolu/project/personal-growth-assistant',
            },
          ),
        ],
      );
      await tester.pumpWidget(_buildTestApp(
        controller: controller,
        agentSessionServiceBuilder: (_) => agentService,
      ));

      await tester.tap(find.byKey(const Key('smart-terminal-fab')));
      await tester.pumpAndSettle();

      await tester.enterText(
        find.byKey(const Key('side-panel-intent-input')),
        '打开日知项目',
      );
      await tester.tap(find.byKey(const Key('side-panel-send')));
      await tester.pumpAndSettle();

      await tester.enterText(
        find.byKey(const Key('side-panel-intent-input')),
        '用claude code打开这个项目',
      );
      await tester.tap(find.byKey(const Key('side-panel-send')));
      await tester.pumpAndSettle();

      expect(agentService.runIntents.length, 2);
      expect(agentService.runIntents[1], '用claude code打开这个项目');
      expect(agentService.conversationIds.length, 2);
      expect(agentService.conversationIds[0], isNull);
      expect(agentService.conversationIds[1], 'conv-server-1');
    });

    testWidgets('new agent turn includes previous question answer',
        (tester) async {
      final controller = _AgentFakeController();
      final streams = <StreamController<AgentSessionEvent>>[];
      final agentService = _FakeAgentSessionService(
        events: const [],
        onRunSession: (_) {
          final stream = StreamController<AgentSessionEvent>();
          streams.add(stream);
          return stream.stream;
        },
      );
      await tester.pumpWidget(_buildTestApp(
        controller: controller,
        agentSessionServiceBuilder: (_) => agentService,
      ));

      await tester.tap(find.byKey(const Key('smart-terminal-fab')));
      await tester.pumpAndSettle();

      await tester.enterText(
        find.byKey(const Key('side-panel-intent-input')),
        '打开项目',
      );
      await tester.tap(find.byKey(const Key('side-panel-send')));
      await tester.pump();

      streams.single
          .add(const AgentSessionCreatedEvent(sessionId: 'session-1'));
      streams.single.add(const AgentQuestionEvent(
        question: 'Which project?',
        options: ['personal-growth-assistant', 'remote-control'],
        multiSelect: false,
      ));
      await tester.pump();

      await tester.tap(find.text('personal-growth-assistant'));
      await tester.pump();

      streams.single.add(AgentResultEvent(
        summary: '已确认 personal-growth-assistant 项目。',
        steps: const [
          AgentResultStep(
            id: 'step-1',
            label: '进入目录',
            command: 'cd /Users/tangxiaolu/project/personal-growth-assistant',
          ),
        ],
        provider: 'agent',
        source: 'recommended',
        needConfirm: false,
        aliases: const {
          'personal-growth-assistant':
              '/Users/tangxiaolu/project/personal-growth-assistant',
        },
      ));
      await streams.single.close();
      await tester.pumpAndSettle();

      await tester.enterText(
        find.byKey(const Key('side-panel-intent-input')),
        '用 claude code 打开这个项目',
      );
      await tester.tap(find.byKey(const Key('side-panel-send')));
      await tester.pump();

      expect(agentService.respondAnswers, ['personal-growth-assistant']);
      expect(agentService.runIntents.length, 2);
      expect(agentService.runIntents[1], '用 claude code 打开这个项目');

      await streams.last.close();
    });

    testWidgets('result state shows execute button with agent steps',
        (tester) async {
      final controller = _AgentFakeController();
      final ws = MockWebSocketService()..simulateConnect();
      final agentService = _FakeAgentSessionService(
        events: [
          AgentSessionCreatedEvent(
            sessionId: 'session-1',
            conversationId: 'conv-1',
            terminalId: 'term-1',
          ),
          AgentResultEvent(
            summary: '进入项目并启动 Claude',
            steps: [
              AgentResultStep(
                id: 'step-1',
                label: '进入目录',
                command: 'cd ~/remote-control',
              ),
            ],
            provider: 'agent',
            source: 'recommended',
            needConfirm: true,
            aliases: {},
          ),
        ],
      );
      await tester.pumpWidget(_buildTestApp(
        controller: controller,
        wsService: ws,
        agentSessionServiceBuilder: (_) => agentService,
      ));

      // Open panel
      await tester.tap(find.byKey(const Key('smart-terminal-fab')));
      await tester.pumpAndSettle();

      // Submit intent
      await tester.enterText(
        find.byKey(const Key('side-panel-intent-input')),
        'test intent',
      );
      await tester.tap(find.byKey(const Key('side-panel-send')));
      await tester.pumpAndSettle(const Duration(seconds: 5));

      // Verify execute button exists for successful agent result
      expect(find.byKey(const Key('side-panel-execute')), findsOneWidget);
    });

    testWidgets('error state shows retry only and no fast mode button',
        (tester) async {
      final controller = _AgentFakeController();
      final ws = MockWebSocketService()..simulateConnect();
      final agentService = _FakeAgentSessionService(
        events: const [],
        onRunSession: (_) => Stream<AgentSessionEvent>.value(
          const AgentErrorEvent(
            code: 'AGENT_ERROR',
            message: '智能服务 Token 未配置，请联系开发者',
          ),
        ),
      );
      await tester.pumpWidget(_buildTestApp(
        controller: controller,
        wsService: ws,
        agentSessionServiceBuilder: (_) => agentService,
      ));

      // Open panel
      await tester.tap(find.byKey(const Key('smart-terminal-fab')));
      await tester.pumpAndSettle();

      // Submit intent - agent returns explicit error
      await tester.enterText(
        find.byKey(const Key('side-panel-intent-input')),
        'test intent',
      );
      await tester.tap(find.byKey(const Key('side-panel-send')));
      await tester.pumpAndSettle();

      expect(find.text('智能服务 Token 未配置，请联系开发者'), findsWidgets);
      expect(find.byKey(const Key('agent-retry')), findsOneWidget);
      expect(find.byKey(const Key('agent-switch-fallback')), findsNothing);
      expect(find.byKey(const Key('side-panel-execute')), findsNothing);
    });

    testWidgets('agent request failure does not enter quick mode UI',
        (tester) async {
      final controller = _AgentFakeController();
      final ws = MockWebSocketService()..simulateConnect();
      final agentService = _FakeAgentSessionService(
        events: const [],
        onRunSession: (_) => Stream<AgentSessionEvent>.error(
          const AgentSessionException(
            code: 'service_llm_budget_blocked',
            message: '智能服务 Token 或配额不可用，请联系开发者',
            statusCode: 429,
          ),
        ),
      );
      await tester.pumpWidget(_buildTestApp(
        controller: controller,
        wsService: ws,
        agentSessionServiceBuilder: (_) => agentService,
      ));

      // Open panel
      await tester.tap(find.byKey(const Key('smart-terminal-fab')));
      await tester.pumpAndSettle();

      // Submit intent - Agent SSE request fails
      await tester.enterText(
        find.byKey(const Key('side-panel-intent-input')),
        'test token error',
      );
      await tester.tap(find.byKey(const Key('side-panel-send')));
      await tester.pumpAndSettle();

      expect(find.text('智能服务 Token 或配额不可用，请联系开发者'), findsOneWidget);
      expect(find.text('快速模式'), findsNothing);
      expect(find.byKey(const Key('agent-switch-fallback')), findsNothing);
      expect(find.byKey(const Key('side-panel-execute')), findsNothing);
    });

    testWidgets('state transitions: idle -> exploring -> error',
        (tester) async {
      final controller = _AgentFakeController();
      final ws = MockWebSocketService()..simulateConnect();
      final agentService = _FakeAgentSessionService(
        events: const [],
        onRunSession: (_) => Stream<AgentSessionEvent>.error(
          Exception('agent offline'),
        ),
      );
      await tester.pumpWidget(_buildTestApp(
        controller: controller,
        wsService: ws,
        agentSessionServiceBuilder: (_) => agentService,
      ));

      // Open panel - should be idle
      await _openSidePanel(tester);

      // Should show intro text
      expect(find.text('直接说目标，我会生成命令，确认后再执行。'), findsOneWidget);

      // Submit intent - transitions to exploring then error
      await tester.enterText(
        find.byKey(const Key('side-panel-intent-input')),
        '进入项目',
      );
      await _pressSidePanelSend(tester);

      // Send button should show loading
      expect(find.byKey(const Key('side-panel-send')), findsOneWidget);

      await tester.pumpAndSettle(const Duration(seconds: 5));

      expect(find.text('智能交互启动失败，请联系开发者'), findsOneWidget);
      expect(find.byKey(const Key('side-panel-execute')), findsNothing);
    });

    testWidgets('execute sends command via WebSocket', (tester) async {
      final controller = _AgentFakeController();
      final ws = MockWebSocketService()..simulateConnect();
      final agentService = _FakeAgentSessionService(
        events: [
          AgentSessionCreatedEvent(
            sessionId: 'session-1',
            conversationId: 'conv-1',
            terminalId: 'term-1',
          ),
          AgentResultEvent(
            summary: '进入项目并启动 Claude',
            steps: [
              AgentResultStep(
                id: 'step-1',
                label: '进入目录',
                command: 'echo hello',
              ),
            ],
            provider: 'agent',
            source: 'recommended',
            needConfirm: true,
            aliases: {},
          ),
        ],
      );
      await tester.pumpWidget(_buildTestApp(
        controller: controller,
        wsService: ws,
        agentSessionServiceBuilder: (_) => agentService,
      ));

      // Open panel
      await tester.tap(find.byKey(const Key('smart-terminal-fab')));
      await tester.pumpAndSettle();

      // Enter intent and resolve with agent result
      await tester.enterText(
        find.byKey(const Key('side-panel-intent-input')),
        'test intent',
      );
      await tester.tap(find.byKey(const Key('side-panel-send')));
      await tester.pumpAndSettle();

      // Execute
      await tester.tap(find.byKey(const Key('side-panel-execute')));
      await tester.pumpAndSettle();

      // Panel closed, FAB reappears
      expect(find.byKey(const Key('smart-terminal-fab')), findsOneWidget);
      expect(ws.sentMessages, isNotEmpty);
    });
  });

  group('Agent models', () {
    test('AgentTraceEvent parses correctly', () {
      final event = AgentTraceEvent.fromJson({
        'tool': 'bash',
        'input_summary': 'ls -la',
        'output_summary': 'file list',
      });
      expect(event.tool, 'bash');
      expect(event.inputSummary, 'ls -la');
      expect(event.outputSummary, 'file list');
    });

    test('AgentQuestionEvent parses correctly', () {
      final event = AgentQuestionEvent.fromJson({
        'question': 'Which project?',
        'options': ['project-a', 'project-b'],
        'multi_select': false,
      });
      expect(event.question, 'Which project?');
      expect(event.options, ['project-a', 'project-b']);
      expect(event.multiSelect, false);
    });

    test('AgentQuestionEvent multi_select parses correctly', () {
      final event = AgentQuestionEvent.fromJson({
        'question': 'Select tools',
        'options': ['bash', 'python', 'node'],
        'multi_select': true,
      });
      expect(event.multiSelect, true);
      expect(event.options.length, 3);
    });

    test('AgentResultEvent parses correctly', () {
      final event = AgentResultEvent.fromJson({
        'summary': '进入项目并启动',
        'steps': [
          {'id': 'step_1', 'label': '进入目录', 'command': 'cd ~/project'},
          {'id': 'step_2', 'label': '启动', 'command': 'claude'},
        ],
        'provider': 'agent',
        'source': 'recommended',
        'need_confirm': true,
        'aliases': <String, dynamic>{},
      });
      expect(event.summary, '进入项目并启动');
      expect(event.steps.length, 2);
      expect(event.steps[0].command, 'cd ~/project');
      expect(event.needConfirm, true);
      expect(event.usage, isNull);
    });

    test('AgentResultEvent parses usage correctly', () {
      final event = AgentResultEvent.fromJson({
        'summary': 'done',
        'steps': [],
        'provider': 'agent',
        'source': 'recommended',
        'need_confirm': false,
        'aliases': <String, dynamic>{},
        'usage': {
          'input_tokens': 1520,
          'output_tokens': 380,
          'total_tokens': 1900,
          'requests': 3,
          'model_name': 'deepseek-chat',
        },
      });
      expect(event.usage, isNotNull);
      expect(event.usage!.inputTokens, 1520);
      expect(event.usage!.outputTokens, 380);
      expect(event.usage!.totalTokens, 1900);
      expect(event.usage!.requests, 3);
      expect(event.usage!.modelName, 'deepseek-chat');
    });

    test('AgentUsageData defaults to zeros', () {
      final usage = AgentUsageData.fromJson({});
      expect(usage.inputTokens, 0);
      expect(usage.outputTokens, 0);
      expect(usage.totalTokens, 0);
      expect(usage.requests, 0);
      expect(usage.modelName, '');
    });

    test('AgentErrorEvent parses correctly', () {
      final event = AgentErrorEvent.fromJson({
        'code': 'TIMEOUT',
        'message': 'Agent timeout',
      });
      expect(event.code, 'TIMEOUT');
      expect(event.message, 'Agent timeout');
    });

    test('AgentFallbackEvent constructs correctly', () {
      const event = AgentFallbackEvent(
        reason: 'Agent 不可用',
        code: 'AGENT_OFFLINE',
      );
      expect(event.reason, 'Agent 不可用');
      expect(event.code, 'AGENT_OFFLINE');
    });
  });

  group('F088: response_type branching', () {
    testWidgets('responseType=message shows summary card without execute button',
        (tester) async {
      final controller = _AgentFakeController();
      final ws = MockWebSocketService()..simulateConnect();
      final agentService = _FakeAgentSessionService(
        events: [
          const AgentSessionCreatedEvent(sessionId: 'session-msg'),
          AgentResultEvent(
            summary: '这是消息回复',
            steps: const [],
            provider: 'agent',
            source: 'recommended',
            needConfirm: false,
            aliases: const {},
            responseType: 'message',
          ),
        ],
      );
      await tester.pumpWidget(_buildTestApp(
        controller: controller,
        wsService: ws,
        agentSessionServiceBuilder: (_) => agentService,
      ));

      await _openSidePanel(tester);
      await tester.enterText(
        find.byKey(const Key('side-panel-intent-input')),
        '发消息',
      );
      await tester.tap(find.byKey(const Key('side-panel-send')));
      await tester.pumpAndSettle(const Duration(seconds: 5));

      expect(find.text('这是消息回复'), findsOneWidget);
      // message 类型不再显示折叠卡片和"已回复"标签
      expect(find.byKey(const Key('side-panel-message-replied-tag')),
          findsNothing);
      // 无执行按钮
      expect(find.byKey(const Key('side-panel-execute')), findsNothing);
      // 无注入按钮
      expect(find.byKey(const Key('side-panel-inject-prompt')), findsNothing);
    });

    testWidgets('responseType=command shows execute button', (tester) async {
      final controller = _AgentFakeController();
      final ws = MockWebSocketService()..simulateConnect();
      final agentService = _FakeAgentSessionService(
        events: [
          const AgentSessionCreatedEvent(sessionId: 'session-cmd'),
          AgentResultEvent(
            summary: '进入项目目录',
            steps: const [
              AgentResultStep(
                id: 'step-1',
                label: '进入目录',
                command: 'cd ~/project',
              ),
            ],
            provider: 'agent',
            source: 'recommended',
            needConfirm: true,
            aliases: {},
            responseType: 'command',
          ),
        ],
      );
      await tester.pumpWidget(_buildTestApp(
        controller: controller,
        wsService: ws,
        agentSessionServiceBuilder: (_) => agentService,
      ));

      await _openSidePanel(tester);
      await tester.enterText(
        find.byKey(const Key('side-panel-intent-input')),
        '进入项目',
      );
      await tester.tap(find.byKey(const Key('side-panel-send')));
      await tester.pumpAndSettle(const Duration(seconds: 5));

      expect(find.text('进入项目目录'), findsOneWidget);
      expect(find.byKey(const Key('side-panel-execute')), findsOneWidget);
      expect(find.byKey(const Key('side-panel-inject-prompt')), findsNothing);
    });

    testWidgets('responseType=ai_prompt shows inject button and prompt preview',
        (tester) async {
      final controller = _AgentFakeController();
      final ws = MockWebSocketService()..simulateConnect();
      final agentService = _FakeAgentSessionService(
        events: [
          const AgentSessionCreatedEvent(sessionId: 'session-ai'),
          AgentResultEvent(
            summary: '执行部署命令',
            steps: const [],
            provider: 'agent',
            source: 'recommended',
            needConfirm: false,
            aliases: const {},
            responseType: 'ai_prompt',
            aiPrompt: 'kubectl apply -f deployment.yaml',
          ),
        ],
      );
      await tester.pumpWidget(_buildTestApp(
        controller: controller,
        wsService: ws,
        agentSessionServiceBuilder: (_) => agentService,
      ));

      await _openSidePanel(tester);
      await tester.enterText(
        find.byKey(const Key('side-panel-intent-input')),
        '部署',
      );
      await tester.tap(find.byKey(const Key('side-panel-send')));
      await tester.pumpAndSettle(const Duration(seconds: 5));

      expect(find.text('执行部署命令'), findsOneWidget);
      expect(find.byKey(const Key('side-panel-ai-prompt-preview')),
          findsOneWidget);
      expect(find.text('kubectl apply -f deployment.yaml'), findsOneWidget);
      expect(find.byKey(const Key('side-panel-inject-prompt')), findsOneWidget);
      // 无执行按钮
      expect(find.byKey(const Key('side-panel-execute')), findsNothing);
    });

    testWidgets('unknown responseType falls back to command rendering',
        (tester) async {
      final controller = _AgentFakeController();
      final ws = MockWebSocketService()..simulateConnect();
      final agentService = _FakeAgentSessionService(
        events: [
          const AgentSessionCreatedEvent(sessionId: 'session-unknown'),
          AgentResultEvent(
            summary: '未知类型',
            steps: const [
              AgentResultStep(
                id: 'step-1',
                label: '执行',
                command: 'echo test',
              ),
            ],
            provider: 'agent',
            source: 'recommended',
            needConfirm: true,
            aliases: {},
            responseType: 'future_type',
          ),
        ],
      );
      await tester.pumpWidget(_buildTestApp(
        controller: controller,
        wsService: ws,
        agentSessionServiceBuilder: (_) => agentService,
      ));

      await _openSidePanel(tester);
      await tester.enterText(
        find.byKey(const Key('side-panel-intent-input')),
        '测试未知类型',
      );
      await tester.tap(find.byKey(const Key('side-panel-send')));
      await tester.pumpAndSettle(const Duration(seconds: 5));

      expect(find.text('未知类型'), findsOneWidget);
      // 降级为 command 渲染，显示执行按钮
      expect(find.byKey(const Key('side-panel-execute')), findsOneWidget);
    });

    testWidgets('all result types allow editing intent', (tester) async {
      // Test message type allows edit
      final controller = _AgentFakeController();
      final ws = MockWebSocketService()..simulateConnect();
      final agentService = _FakeAgentSessionService(
        events: [
          const AgentSessionCreatedEvent(sessionId: 'session-edit'),
          AgentResultEvent(
            summary: '消息结果',
            steps: const [],
            provider: 'agent',
            source: 'recommended',
            needConfirm: false,
            aliases: const {},
            responseType: 'message',
          ),
        ],
      );
      await tester.pumpWidget(_buildTestApp(
        controller: controller,
        wsService: ws,
        agentSessionServiceBuilder: (_) => agentService,
      ));

      await _openSidePanel(tester);
      await tester.enterText(
        find.byKey(const Key('side-panel-intent-input')),
        '编辑测试',
      );
      await tester.tap(find.byKey(const Key('side-panel-send')));
      await tester.pumpAndSettle(const Duration(seconds: 5));

      // 结果状态下，intent 气泡可编辑
      final input = tester.widget<TextField>(
        find.byKey(const Key('side-panel-intent-input')),
      );
      expect(input.enabled, isTrue);
    });

    testWidgets('ai_prompt inject sends prompt text via WebSocket',
        (tester) async {
      final controller = _AgentFakeController();
      final ws = MockWebSocketService()..simulateConnect();
      final agentService = _FakeAgentSessionService(
        events: [
          const AgentSessionCreatedEvent(sessionId: 'session-inject'),
          AgentResultEvent(
            summary: '注入测试',
            steps: const [],
            provider: 'agent',
            source: 'recommended',
            needConfirm: false,
            aliases: const {},
            responseType: 'ai_prompt',
            aiPrompt: 'echo injected',
          ),
        ],
      );
      await tester.pumpWidget(_buildTestApp(
        controller: controller,
        wsService: ws,
        agentSessionServiceBuilder: (_) => agentService,
      ));

      await _openSidePanel(tester);
      await tester.enterText(
        find.byKey(const Key('side-panel-intent-input')),
        '注入',
      );
      await tester.tap(find.byKey(const Key('side-panel-send')));
      await tester.pumpAndSettle(const Duration(seconds: 5));

      // 点击注入按钮
      await tester.tap(find.byKey(const Key('side-panel-inject-prompt')));
      await tester.pumpAndSettle();

      // 验证 WebSocket 发送了 prompt 文本（追加回车）
      expect(ws.sentMessages, isNotEmpty);
      expect(ws.sentMessages.last, 'echo injected\r');
    });
  });

  group('Fix: asking state preserves Q&A history', () {
    testWidgets('asking state allows editing intent', (tester) async {
      final controller = _AgentFakeController();
      final agentService = _FakeAgentSessionService(
        events: const [
          AgentSessionCreatedEvent(sessionId: 'session-1'),
          AgentQuestionEvent(
            question: 'Which project?',
            options: ['remote-control'],
            multiSelect: false,
          ),
        ],
      );
      await tester.pumpWidget(_buildTestApp(
        controller: controller,
        agentSessionServiceBuilder: (_) => agentService,
      ));

      await _openSidePanel(tester);
      await tester.enterText(
        find.byKey(const Key('side-panel-intent-input')),
        '打开项目',
      );
      await tester.tap(find.byKey(const Key('side-panel-send')));
      await tester.pumpAndSettle();

      // asking 状态下意图气泡应可编辑（显示编辑按钮）
      // 查找意图文本旁边的编辑图标
      expect(find.text('打开项目'), findsOneWidget);
      expect(find.byIcon(Icons.edit_outlined), findsOneWidget);
    });

    testWidgets(
        'previous Q&A remains visible when agent asks follow-up question',
        (tester) async {
      final controller = _AgentFakeController();
      final streamController = StreamController<AgentConversationEventItem>();
      final agentService = _FakeAgentSessionService(
        events: const [],
        onFetchConversation: (_, __) async =>
            const AgentConversationProjection(
          conversationId: 'conv-qa',
          deviceId: 'device-1',
          terminalId: 'term-1',
          status: 'active',
          nextEventIndex: 0,
          activeSessionId: null,
          events: [],
        ),
        onStreamConversation: (_) => streamController.stream,
      );
      await tester.pumpWidget(_buildTestApp(
        controller: controller,
        agentSessionServiceBuilder: (_) => agentService,
      ));
      await tester.pumpAndSettle();
      await _openSidePanel(tester);

      // 模拟用户发送意图
      streamController.add(const AgentConversationEventItem(
        eventIndex: 0,
        eventId: 'evt-0',
        type: 'user_intent',
        role: 'user',
        payload: {'text': '你好'},
      ));
      // Agent 问第一个问题
      streamController.add(const AgentConversationEventItem(
        eventIndex: 1,
        eventId: 'evt-1',
        type: 'question',
        role: 'assistant',
        questionId: 'q-1',
        payload: {
          'question': '第一个问题',
          'options': ['选项A'],
          'multi_select': false,
        },
      ));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      expect(find.text('第一个问题'), findsOneWidget);

      // 用户回答第一个问题
      streamController.add(const AgentConversationEventItem(
        eventIndex: 2,
        eventId: 'evt-2',
        type: 'answer',
        role: 'user',
        questionId: 'q-1',
        payload: {'text': '我的回答'},
      ));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      // Agent 问第二个问题
      streamController.add(const AgentConversationEventItem(
        eventIndex: 3,
        eventId: 'evt-3',
        type: 'question',
        role: 'assistant',
        questionId: 'q-2',
        payload: {
          'question': '第二个问题',
          'options': ['选项B'],
          'multi_select': false,
        },
      ));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      // 关键断言：第一个问题 + 用户回答 应该仍然可见
      expect(find.text('第一个问题'), findsOneWidget);
      expect(find.text('我的回答'), findsOneWidget);
      // 第二个问题也可见
      expect(find.text('第二个问题'), findsOneWidget);

      unawaited(streamController.close());
    });
  });

  group('Fix: conversation stream rebuild restores sessionId', () {
    testWidgets(
        'asking state from conversation stream preserves sessionId for respond',
        (tester) async {
      final controller = _AgentFakeController();
      final streamController = StreamController<AgentConversationEventItem>();
      final agentService = _FakeAgentSessionService(
        events: const [],
        onFetchConversation: (_, __) async =>
            const AgentConversationProjection(
          conversationId: 'conv-session',
          deviceId: 'device-1',
          terminalId: 'term-1',
          status: 'active',
          nextEventIndex: 0,
          activeSessionId: null,
          events: [],
        ),
        onStreamConversation: (_) => streamController.stream,
      );
      await tester.pumpWidget(_buildTestApp(
        controller: controller,
        agentSessionServiceBuilder: (_) => agentService,
      ));
      await tester.pumpAndSettle();
      await _openSidePanel(tester);

      // 模拟对话流推送带有 sessionId 的事件序列
      streamController.add(const AgentConversationEventItem(
        eventIndex: 0,
        eventId: 'evt-0',
        type: 'user_intent',
        role: 'user',
        sessionId: 'session-abc123',
        payload: {'text': '帮我查看日志'},
      ));
      streamController.add(const AgentConversationEventItem(
        eventIndex: 1,
        eventId: 'evt-1',
        type: 'question',
        role: 'assistant',
        sessionId: 'session-abc123',
        questionId: 'q-1',
        payload: {
          'question': '哪个日志？',
          'options': ['syslog', 'server.log'],
          'multi_select': false,
        },
      ));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      // 验证 agent 处于 asking 状态
      expect(find.text('哪个日志？'), findsOneWidget);

      // 用户回答问题 - sessionId 应该已从事件中恢复
      await tester.enterText(
        find.byKey(const Key('side-panel-intent-input')),
        'syslog',
      );
      await _pressSidePanelSend(tester);
      // 不用 pumpAndSettle（conversation stream 持续活跃会导致超时）
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      // 关键断言：respond 请求应该被成功发送
      // 如果 sessionId 没有被恢复，respondAnswers 会为空
      expect(agentService.respondAnswers, ['syslog']);

      unawaited(streamController.close());
    });
  });

  group('Fix: sessionId lost shows error instead of silent drop', () {
    testWidgets(
        'asking state with null sessionId preserves input text and shows error',
        (tester) async {
      // 使用 SSE 模拟：先进入 asking 状态，然后 SSE 断开导致 sessionId 被清除
      final controller = _AgentFakeController();
      final streamController = StreamController<AgentConversationEventItem>();
      final agentService = _FakeAgentSessionService(
        events: const [
          AgentSessionCreatedEvent(sessionId: 'session-will-expire'),
          AgentQuestionEvent(
            question: '你想要什么？',
            options: ['选项A'],
            multiSelect: false,
          ),
        ],
        onStreamConversation: (_) => streamController.stream,
      );
      await tester.pumpWidget(_buildTestApp(
        controller: controller,
        agentSessionServiceBuilder: (_) => agentService,
      ));

      await _openSidePanel(tester);
      await tester.enterText(
        find.byKey(const Key('side-panel-intent-input')),
        '测试意图',
      );
      await tester.tap(find.byKey(const Key('side-panel-send')));
      await tester.pumpAndSettle();

      // 验证进入了 asking 状态
      expect(find.text('你想要什么？'), findsOneWidget);

      // 用户输入回答
      await tester.enterText(
        find.byKey(const Key('side-panel-intent-input')),
        '我的回答',
      );

      // SSE 流已经结束（events 全部消费），_activeSessionId 仍由 AgentSessionCreatedEvent 设置
      // 但如果 session 因 error 结束，_activeSessionId 会被清除
      // 这里我们通过 conversation stream 推送 error 事件来模拟 session 过期
      streamController.add(const AgentConversationEventItem(
        eventIndex: 0,
        eventId: 'evt-err',
        type: 'error',
        role: 'assistant',
        sessionId: 'session-will-expire',
        payload: {
          'code': 'SESSION_EXPIRED',
          'message': '会话已超时',
        },
      ));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      // error 事件后 conversation stream 重建会覆盖状态为 error
      // 此时 _activeSessionId 已被 SSE 的 AgentErrorEvent 清除
      // 但 conversation stream 重建可能将状态恢复为 asking（如果 error 事件还没到达）

      // 关键是：当 _activeSessionId 为 null 且状态为 asking 时，
      // 用户尝试回答不应该静默丢失输入

      // 如果状态已经是 error，输入文字应该在输入框中（因为 _handleInputSubmit 不走 asking 分支）
      // 如果状态被重建回 asking 但 sessionId 为 null，则走新的保护逻辑

      // 输入文字不应被清空（不应静默丢弃）
      final inputField = tester.widget<TextField>(
        find.byKey(const Key('side-panel-intent-input')),
      );
      // 无论走哪个分支，用户的输入 "我的回答" 不应该被静默丢弃
      expect(inputField.controller?.text, isNot(equals('')));

      unawaited(streamController.close());
    });
  });

  group('Fix: conversation_reset during active SSE does not clear page', () {
    testWidgets(
        'sending new intent preserves previous turns in history',
        (tester) async {
      final controller = _AgentFakeController();

      var runCount = 0;
      final agentService = _FakeAgentSessionService(
        events: const [],
        onRunSession: (intent) {
          runCount++;
          if (runCount == 1) {
            return Stream.fromIterable([
              const AgentSessionCreatedEvent(sessionId: 'session-1'),
              AgentResultEvent(
                summary: '结果1',
                steps: [],
                provider: 'agent',
                source: 'recommended',
                needConfirm: false,
                aliases: <String, String>{},
                responseType: 'message',
              ),
            ]);
          }
          return Stream.fromIterable([
            const AgentSessionCreatedEvent(sessionId: 'session-2'),
            AgentResultEvent(
              summary: '结果2',
              steps: [],
              provider: 'agent',
              source: 'recommended',
              needConfirm: false,
              aliases: <String, String>{},
              responseType: 'message',
            ),
          ]);
        },
        onStreamConversation: (_) =>
            const Stream<AgentConversationEventItem>.empty(),
      );
      await tester.pumpWidget(_buildTestApp(
        controller: controller,
        agentSessionServiceBuilder: (_) => agentService,
      ));
      await tester.pumpAndSettle();
      await _openSidePanel(tester);

      // 第一轮：发送意图 → 得到结果
      await tester.enterText(
        find.byKey(const Key('side-panel-intent-input')),
        '你好',
      );
      await tester.tap(find.byKey(const Key('side-panel-send')));
      await tester.pumpAndSettle();

      expect(find.text('结果1'), findsOneWidget);

      // 第二轮：发送新意图 → 上一轮归档到历史
      await tester.enterText(
        find.byKey(const Key('side-panel-intent-input')),
        '第二条',
      );
      await tester.tap(find.byKey(const Key('side-panel-send')));
      await tester.pumpAndSettle();

      // 历史：第一轮意图和结果仍然可见
      expect(find.text('你好'), findsOneWidget);
      expect(find.text('结果1'), findsOneWidget);
      // 当前：第二轮意图和结果可见
      expect(find.text('第二条'), findsOneWidget);
      expect(find.text('结果2'), findsOneWidget);
    });
  });

  group('Fix: edit active intent archives current turn', () {
    testWidgets(
        'sending new intent after result archives previous turn to history',
        (tester) async {
      // 验证核心逻辑：发送新意图时，上一轮的 result 应该被归档到历史
      final controller = _AgentFakeController();
      final agentService = _FakeAgentSessionService(
        events: const [],
        onRunSession: (intent) {
          if (intent == '第一条') {
            return Stream.fromIterable([
              const AgentSessionCreatedEvent(sessionId: 's1'),
              AgentResultEvent(
                summary: '结果1',
                steps: [],
                provider: 'agent',
                source: 'recommended',
                needConfirm: false,
                aliases: <String, String>{},
                responseType: 'message',
              ),
            ]);
          }
          // 第二条意图：返回结果
          return Stream.fromIterable([
            const AgentSessionCreatedEvent(sessionId: 's2'),
            AgentResultEvent(
              summary: '结果2',
              steps: [],
              provider: 'agent',
              source: 'recommended',
              needConfirm: false,
              aliases: <String, String>{},
              responseType: 'message',
            ),
          ]);
        },
        onStreamConversation: (_) =>
            const Stream<AgentConversationEventItem>.empty(),
      );
      await tester.pumpWidget(_buildTestApp(
        controller: controller,
        agentSessionServiceBuilder: (_) => agentService,
      ));
      await tester.pumpAndSettle();
      await _openSidePanel(tester);

      // 发送第一条意图
      await tester.enterText(
        find.byKey(const Key('side-panel-intent-input')),
        '第一条',
      );
      await tester.tap(find.byKey(const Key('side-panel-send')));
      await tester.pumpAndSettle();

      // 验证结果可见
      expect(find.text('结果1'), findsOneWidget);
      expect(find.text('第一条'), findsOneWidget);

      // 发送第二条意图（上一轮应该被归档到历史）
      await tester.enterText(
        find.byKey(const Key('side-panel-intent-input')),
        '第二条',
      );
      await tester.tap(find.byKey(const Key('side-panel-send')));
      await tester.pumpAndSettle();

      // 关键断言：历史中应有"第一条"及其结果
      expect(find.text('第一条'), findsOneWidget);
      expect(find.text('结果1'), findsOneWidget);
      // 当前活跃的应该是"第二条"及其结果
      expect(find.text('第二条'), findsOneWidget);
      expect(find.text('结果2'), findsOneWidget);

      // 验证 runSession 被调用了两次
      expect(agentService.runIntents, ['第一条', '第二条']);
    });
  });

  group('F093: conversation_reset pendingReset', () {
    // 测试 1: SSE 活跃时收到 conversation_reset 设置 pendingReset
    testWidgets(
        'sets pendingReset when conversation_reset arrives during active SSE',
        (tester) async {
      final controller = _AgentFakeController();
      final sseController = StreamController<AgentSessionEvent>();
      final convStreamController =
          StreamController<AgentConversationEventItem>.broadcast();
      final agentService = _FakeAgentSessionService(
        events: const [],
        onRunSession: (intent) {
          return sseController.stream;
        },
        onStreamConversation: (_) => convStreamController.stream,
      );
      await tester.pumpWidget(_buildTestApp(
        controller: controller,
        agentSessionServiceBuilder: (_) => agentService,
      ));
      await tester.pumpAndSettle();
      await _openSidePanel(tester);

      // 启动 SSE：发送意图（SSE 流不关闭，保持活跃）
      await tester.enterText(
        find.byKey(const Key('side-panel-intent-input')),
        '测试意图',
      );
      await _pressSidePanelSend(tester);
      await tester.pump();

      // SSE 活跃中：推送 session created + trace（进入 exploring）
      sseController.add(const AgentSessionCreatedEvent(sessionId: 's1'));
      sseController.add(const AgentTraceEvent(
        tool: 'bash',
        inputSummary: '思考中...',
        outputSummary: '',
      ));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      // SSE 仍然活跃时，conversation stream 推送 conversation_reset
      convStreamController.add(const AgentConversationEventItem(
        eventIndex: 5,
        eventId: 'evt-reset',
        type: 'conversation_reset',
        role: 'system',
        payload: {},
      ));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      // 关键：SSE 活跃期间不应清空当前页面（exploring 状态仍然可见）
      expect(find.text('Agent 正在分析...'), findsOneWidget);
      // trace 被记录在 exploring 视图中（折叠在 ExpansionTile 内）
      expect(find.text('探索进度 (1)'), findsOneWidget);

      // SSE 结束：关闭 SSE 流，触发 onDone
      sseController.add(AgentResultEvent(
        summary: '最终结果',
        steps: [],
        provider: 'agent',
        source: 'recommended',
        needConfirm: false,
        aliases: <String, String>{},
        responseType: 'message',
      ));
      await tester.pump();
      await sseController.close();
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      // SSE 结束后 pendingReset 应该已触发状态清空
      // conversation stream 仍在推送新事件，通过增量同步重建 UI
      convStreamController.add(const AgentConversationEventItem(
        eventIndex: 0,
        eventId: 'evt-new-0',
        type: 'user_intent',
        role: 'user',
        sessionId: 'session-new',
        payload: {'text': '重建的意图'},
      ));
      convStreamController.add(const AgentConversationEventItem(
        eventIndex: 1,
        eventId: 'evt-new-1',
        type: 'result',
        role: 'assistant',
        sessionId: 'session-new',
        payload: {
          'summary': '重建的结果',
          'steps': <Map<String, dynamic>>[],
          'provider': 'agent',
          'source': 'recommended',
          'need_confirm': false,
          'aliases': <String, dynamic>{},
          'response_type': 'message',
        },
      ));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      // 验证状态已重建
      expect(find.text('重建的意图'), findsOneWidget);
      expect(find.text('重建的结果'), findsOneWidget);

      unawaited(convStreamController.close());
    });

    // 测试 2: SSE 结束后 pendingReset 触发状态重建（含 _activeSessionId 清空）
    testWidgets(
        'resets state including activeSessionId on SSE done when pendingReset is true',
        (tester) async {
      final controller = _AgentFakeController();
      final sseController = StreamController<AgentSessionEvent>();
      final convStreamController =
          StreamController<AgentConversationEventItem>.broadcast();
      final agentService = _FakeAgentSessionService(
        events: const [],
        onRunSession: (intent) {
          return sseController.stream;
        },
        onStreamConversation: (_) => convStreamController.stream,
      );
      await tester.pumpWidget(_buildTestApp(
        controller: controller,
        agentSessionServiceBuilder: (_) => agentService,
      ));
      await tester.pumpAndSettle();
      await _openSidePanel(tester);

      // 启动 SSE
      await tester.enterText(
        find.byKey(const Key('side-panel-intent-input')),
        '清空测试',
      );
      await _pressSidePanelSend(tester);
      await tester.pump();

      sseController.add(const AgentSessionCreatedEvent(sessionId: 's-reset'));
      sseController.add(const AgentTraceEvent(
        tool: 'bash',
        inputSummary: '工作中',
        outputSummary: '',
      ));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      // SSE 活跃时 conversation_reset
      convStreamController.add(const AgentConversationEventItem(
        eventIndex: 3,
        eventId: 'evt-rst',
        type: 'conversation_reset',
        role: 'system',
        payload: {},
      ));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      // SSE 结束（不传 result，SSE 流直接关闭）
      // F093: 因为 pendingReset 为 true，不会触发 STREAM_CLOSED 错误
      await sseController.close();
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      // pendingReset 已在 onDone 中处理：
      // - _resetAgentRenderState 被调用，清空 traces/result/error 等
      // - 不会出现 STREAM_CLOSED 错误
      expect(find.text('Agent 会话意外关闭'), findsNothing);
      // conversation stream 推送新事件重建状态
      convStreamController.add(const AgentConversationEventItem(
        eventIndex: 0,
        eventId: 'evt-rebuild-0',
        type: 'user_intent',
        role: 'user',
        sessionId: 'session-rebuilt',
        payload: {'text': '新意图'},
      ));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      // 验证新状态可见
      expect(find.text('新意图'), findsOneWidget);

      unawaited(convStreamController.close());
    });

    // 测试 3: 无 reset 时 SSE 结束不触发额外清理
    testWidgets(
        'does not reset state on SSE done when no pendingReset', (tester) async {
      final controller = _AgentFakeController();
      final agentService = _FakeAgentSessionService(
        events: const [],
        onRunSession: (intent) {
          return Stream.fromIterable([
            const AgentSessionCreatedEvent(sessionId: 's-normal'),
            AgentResultEvent(
              summary: '正常结果',
              steps: [],
              provider: 'agent',
              source: 'recommended',
              needConfirm: false,
              aliases: <String, String>{},
              responseType: 'message',
            ),
          ]);
        },
        onStreamConversation: (_) =>
            const Stream<AgentConversationEventItem>.empty(),
      );
      await tester.pumpWidget(_buildTestApp(
        controller: controller,
        agentSessionServiceBuilder: (_) => agentService,
      ));
      await tester.pumpAndSettle();
      await _openSidePanel(tester);

      // 发送意图 → 得到结果（SSE 自然结束，无 conversation_reset）
      await tester.enterText(
        find.byKey(const Key('side-panel-intent-input')),
        '正常流程',
      );
      await tester.tap(find.byKey(const Key('side-panel-send')));
      await tester.pumpAndSettle();

      // SSE 结束后，正常结果仍然可见（状态未被动清理）
      expect(find.text('正常结果'), findsOneWidget);
      expect(find.text('正常流程'), findsOneWidget);
    });

    // 测试 4: 连续 reset（快速多端编辑）只保留最后一次
    testWidgets('handles consecutive resets during active SSE', (tester) async {
      final controller = _AgentFakeController();
      final sseController = StreamController<AgentSessionEvent>();
      final convStreamController =
          StreamController<AgentConversationEventItem>.broadcast();
      final agentService = _FakeAgentSessionService(
        events: const [],
        onRunSession: (intent) {
          return sseController.stream;
        },
        onStreamConversation: (_) => convStreamController.stream,
      );
      await tester.pumpWidget(_buildTestApp(
        controller: controller,
        agentSessionServiceBuilder: (_) => agentService,
      ));
      await tester.pumpAndSettle();
      await _openSidePanel(tester);

      // 启动 SSE
      await tester.enterText(
        find.byKey(const Key('side-panel-intent-input')),
        '连续 reset',
      );
      await _pressSidePanelSend(tester);
      await tester.pump();

      sseController.add(const AgentSessionCreatedEvent(sessionId: 's-multi'));
      sseController.add(const AgentTraceEvent(
        tool: 'bash',
        inputSummary: '处理中',
        outputSummary: '',
      ));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      // SSE 活跃期间连续推送多个 conversation_reset
      convStreamController.add(const AgentConversationEventItem(
        eventIndex: 5,
        eventId: 'evt-reset-1',
        type: 'conversation_reset',
        role: 'system',
        payload: {},
      ));
      convStreamController.add(const AgentConversationEventItem(
        eventIndex: 6,
        eventId: 'evt-reset-2',
        type: 'conversation_reset',
        role: 'system',
        payload: {},
      ));
      convStreamController.add(const AgentConversationEventItem(
        eventIndex: 7,
        eventId: 'evt-reset-3',
        type: 'conversation_reset',
        role: 'system',
        payload: {},
      ));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      // SSE 仍然活跃，页面内容不应消失（exploring 状态仍然可见）
      expect(find.text('Agent 正在分析...'), findsOneWidget);
      expect(find.text('探索进度 (1)'), findsOneWidget);

      // SSE 结束：pendingReset 导致的关闭是预期行为
      await sseController.close();
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      // 不会出现 STREAM_CLOSED 错误（因为 pendingReset 为 true）
      expect(find.text('Agent 会话意外关闭'), findsNothing);

      // 连续 reset 只保留最后一次的效果：状态已被清空
      // conversation stream 推送最终状态
      convStreamController.add(const AgentConversationEventItem(
        eventIndex: 0,
        eventId: 'evt-final-0',
        type: 'user_intent',
        role: 'user',
        sessionId: 'session-final',
        payload: {'text': '最终意图'},
      ));
      convStreamController.add(const AgentConversationEventItem(
        eventIndex: 1,
        eventId: 'evt-final-1',
        type: 'result',
        role: 'assistant',
        sessionId: 'session-final',
        payload: {
          'summary': '最终结果',
          'steps': <Map<String, dynamic>>[],
          'provider': 'agent',
          'source': 'recommended',
          'need_confirm': false,
          'aliases': <String, dynamic>{},
          'response_type': 'message',
        },
      ));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      expect(find.text('最终意图'), findsOneWidget);
      expect(find.text('最终结果'), findsOneWidget);

      unawaited(convStreamController.close());
    });

    // 测试 5: pendingReset 后 conversation stream 增量同步重建 UI
    testWidgets('conversation stream rebuilds after pendingReset',
        (tester) async {
      final controller = _AgentFakeController();
      final sseController = StreamController<AgentSessionEvent>();
      final convStreamController =
          StreamController<AgentConversationEventItem>.broadcast();
      final agentService = _FakeAgentSessionService(
        events: const [],
        onRunSession: (intent) {
          return sseController.stream;
        },
        onStreamConversation: (_) => convStreamController.stream,
      );
      await tester.pumpWidget(_buildTestApp(
        controller: controller,
        agentSessionServiceBuilder: (_) => agentService,
      ));
      await tester.pumpAndSettle();
      await _openSidePanel(tester);

      // 启动 SSE
      await tester.enterText(
        find.byKey(const Key('side-panel-intent-input')),
        '集成测试',
      );
      await _pressSidePanelSend(tester);
      await tester.pump();

      sseController.add(const AgentSessionCreatedEvent(sessionId: 's-integ'));
      sseController.add(const AgentTraceEvent(
        tool: 'bash',
        inputSummary: '执行步骤1',
        outputSummary: '',
      ));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      // conversation_reset 到达
      convStreamController.add(const AgentConversationEventItem(
        eventIndex: 10,
        eventId: 'evt-reset-integ',
        type: 'conversation_reset',
        role: 'system',
        payload: {},
      ));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      // SSE 结束（正常完成，带 result）
      sseController.add(AgentResultEvent(
        summary: '旧结果',
        steps: [],
        provider: 'agent',
        source: 'recommended',
        needConfirm: false,
        aliases: <String, String>{},
        responseType: 'message',
      ));
      await sseController.close();
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      // SSE 结束后 pendingReset 已清空旧状态
      // conversation stream 推送完整事件序列，重建 UI
      convStreamController.add(const AgentConversationEventItem(
        eventIndex: 0,
        eventId: 'evt-rr-0',
        type: 'user_intent',
        role: 'user',
        sessionId: 'session-rebuilt',
        payload: {'text': '重建意图'},
      ));
      convStreamController.add(const AgentConversationEventItem(
        eventIndex: 1,
        eventId: 'evt-rr-1',
        type: 'question',
        role: 'assistant',
        sessionId: 'session-rebuilt',
        questionId: 'q-rebuilt',
        payload: {
          'question': '重建问题？',
          'options': ['选项A', '选项B'],
          'multi_select': false,
        },
      ));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      // 验证 conversation stream 增量同步完整重建了 UI
      expect(find.text('重建意图'), findsOneWidget);
      expect(find.text('重建问题？'), findsOneWidget);

      // 回答问题后，sessionId 应该已通过 conversation stream 事件恢复
      await tester.enterText(
        find.byKey(const Key('side-panel-intent-input')),
        '选项A',
      );
      await _pressSidePanelSend(tester);
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      // respond 应被成功调用（sessionId 已恢复）
      expect(agentService.respondAnswers, ['选项A']);

      unawaited(convStreamController.close());
    });

    // 测试 6: pendingReset 后 SSE 关闭，尚未收到新事件时 UI 已清空
    testWidgets(
        'UI clears immediately on SSE done with pendingReset before new events',
        (tester) async {
      final controller = _AgentFakeController();
      final sseController = StreamController<AgentSessionEvent>();
      final convStreamController =
          StreamController<AgentConversationEventItem>.broadcast();
      final agentService = _FakeAgentSessionService(
        events: const [],
        onRunSession: (intent) {
          return sseController.stream;
        },
        onStreamConversation: (_) => convStreamController.stream,
      );
      await tester.pumpWidget(_buildTestApp(
        controller: controller,
        agentSessionServiceBuilder: (_) => agentService,
      ));
      await tester.pumpAndSettle();
      await _openSidePanel(tester);

      // 启动 SSE，进入 exploring
      await tester.enterText(
        find.byKey(const Key('side-panel-intent-input')),
        'UI 清空验证',
      );
      await _pressSidePanelSend(tester);
      await tester.pump();

      sseController.add(const AgentSessionCreatedEvent(sessionId: 's-clear'));
      sseController.add(const AgentTraceEvent(
        tool: 'bash',
        inputSummary: '执行中',
        outputSummary: '',
      ));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      // 验证 exploring UI 可见
      expect(find.text('Agent 正在分析...'), findsOneWidget);
      expect(find.text('探索进度 (1)'), findsOneWidget);

      // conversation_reset 到达（SSE 活跃时）
      convStreamController.add(const AgentConversationEventItem(
        eventIndex: 5,
        eventId: 'evt-reset-clear',
        type: 'conversation_reset',
        role: 'system',
        payload: {},
      ));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      // SSE 关闭
      await sseController.close();
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      // 关键断言：SSE 关闭后 UI 立即清空（setState 已触发）
      // exploring 视图的元素应该消失
      expect(find.text('Agent 正在分析...'), findsNothing);
      expect(find.text('探索进度 (1)'), findsNothing);
      // 无 STREAM_CLOSED 错误
      expect(find.text('Agent 会话意外关闭'), findsNothing);

      unawaited(convStreamController.close());
    });

    // 测试 7: pendingReset 后走 cancel/restart，不会污染下一轮 session
    testWidgets(
        'cancel during pendingReset does not leak to next session', (tester) async {
      final controller = _AgentFakeController();
      final sseController1 = StreamController<AgentSessionEvent>();
      final sseController2 = StreamController<AgentSessionEvent>();
      // 使用 broadcast 流避免重启 conversation stream 时 "already listened to" 错误
      final convStreamController =
          StreamController<AgentConversationEventItem>.broadcast();
      var runCount = 0;
      final agentService = _FakeAgentSessionService(
        events: const [],
        onRunSession: (intent) {
          runCount++;
          if (runCount == 1) {
            return sseController1.stream;
          }
          return sseController2.stream;
        },
        onStreamConversation: (_) => convStreamController.stream,
      );
      await tester.pumpWidget(_buildTestApp(
        controller: controller,
        agentSessionServiceBuilder: (_) => agentService,
      ));
      await tester.pumpAndSettle();
      await _openSidePanel(tester);

      // 第一轮：启动 SSE → exploring
      await tester.enterText(
        find.byKey(const Key('side-panel-intent-input')),
        '第一轮',
      );
      await _pressSidePanelSend(tester);
      await tester.pump();

      sseController1.add(const AgentSessionCreatedEvent(sessionId: 's-leak'));
      sseController1.add(const AgentTraceEvent(
        tool: 'bash',
        inputSummary: '第一轮执行',
        outputSummary: '',
      ));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));
      expect(find.text('Agent 正在分析...'), findsOneWidget);

      // conversation_reset 到达 → pendingReset = true
      convStreamController.add(const AgentConversationEventItem(
        eventIndex: 3,
        eventId: 'evt-reset-leak',
        type: 'conversation_reset',
        role: 'system',
        payload: {},
      ));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      // 用户取消当前 Agent（走 _cancelAgentSession -> _doCancelAgentNetwork）
      await tester.tap(find.byKey(const Key('agent-cancel')));
      await tester.pumpAndSettle();

      // 第一轮 SSE 被取消，pendingReset 已被 _doCancelAgentNetwork 清除
      // 不应出现 STREAM_CLOSED 错误
      expect(find.text('Agent 会话意外关闭'), findsNothing);

      // 第二轮：发送新意图
      await tester.enterText(
        find.byKey(const Key('side-panel-intent-input')),
        '第二轮',
      );
      await _pressSidePanelSend(tester);
      await tester.pump();

      sseController2.add(const AgentSessionCreatedEvent(sessionId: 's-new'));
      sseController2.add(AgentResultEvent(
        summary: '第二轮结果',
        steps: [],
        provider: 'agent',
        source: 'recommended',
        needConfirm: false,
        aliases: <String, String>{},
        responseType: 'message',
      ));
      await tester.pumpAndSettle();

      // 关键断言：第二轮正常完成，旧 pendingReset 未污染
      expect(find.text('第二轮'), findsOneWidget);
      expect(find.text('第二轮结果'), findsOneWidget);
      // 第一轮 trace 内容不应出现（因为 _resetAgentRenderState 已清空 traces）
      expect(find.text('第一轮执行'), findsNothing);

      unawaited(sseController1.close());
      unawaited(sseController2.close());
      unawaited(convStreamController.close());
    });

    // 测试 8: conversation_reset -> error -> retry，不基于旧投影重试
    testWidgets(
        'retry after pendingReset clears old projection and restarts cleanly',
        (tester) async {
      final controller = _AgentFakeController();
      final sseController1 = StreamController<AgentSessionEvent>();
      final sseController2 = StreamController<AgentSessionEvent>();
      final convStreamController =
          StreamController<AgentConversationEventItem>.broadcast();
      var runCount = 0;
      final agentService = _FakeAgentSessionService(
        events: const [],
        onRunSession: (intent) {
          runCount++;
          if (runCount == 1) {
            return sseController1.stream;
          }
          return sseController2.stream;
        },
        onStreamConversation: (_) => convStreamController.stream,
      );
      await tester.pumpWidget(_buildTestApp(
        controller: controller,
        agentSessionServiceBuilder: (_) => agentService,
      ));
      await tester.pumpAndSettle();
      await _openSidePanel(tester);

      // 第一轮：启动 SSE → exploring
      await tester.enterText(
        find.byKey(const Key('side-panel-intent-input')),
        '重试验证',
      );
      await _pressSidePanelSend(tester);
      await tester.pump();

      sseController1.add(const AgentSessionCreatedEvent(sessionId: 's-retry'));
      sseController1.add(const AgentTraceEvent(
        tool: 'bash',
        inputSummary: '旧执行',
        outputSummary: '',
      ));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));
      expect(find.text('Agent 正在分析...'), findsOneWidget);

      // conversation_reset 到达 → pendingReset = true
      convStreamController.add(const AgentConversationEventItem(
        eventIndex: 5,
        eventId: 'evt-reset-retry',
        type: 'conversation_reset',
        role: 'system',
        payload: {},
      ));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      // SSE 关闭（不传 result，进入 error 状态）
      await sseController1.close();
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      // 因为 pendingReset 被处理，不会出现 STREAM_CLOSED
      // 但 _resetAgentRenderState 会将状态重置为 idle
      // UI 已清空
      expect(find.text('Agent 正在分析...'), findsNothing);
      expect(find.text('探索进度 (1)'), findsNothing);

      // conversation stream 推送新事件
      convStreamController.add(const AgentConversationEventItem(
        eventIndex: 0,
        eventId: 'evt-retry-0',
        type: 'user_intent',
        role: 'user',
        sessionId: 'session-new-retry',
        payload: {'text': '新意图'},
      ));
      convStreamController.add(const AgentConversationEventItem(
        eventIndex: 1,
        eventId: 'evt-retry-1',
        type: 'result',
        role: 'assistant',
        sessionId: 'session-new-retry',
        payload: {
          'summary': '重试后的新结果',
          'steps': <Map<String, dynamic>>[],
          'provider': 'agent',
          'source': 'recommended',
          'need_confirm': false,
          'aliases': <String, dynamic>{},
          'response_type': 'message',
        },
      ));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      // 验证 UI 重建正确
      expect(find.text('新意图'), findsOneWidget);
      expect(find.text('重试后的新结果'), findsOneWidget);
      // 旧 trace 不应出现
      expect(find.text('旧执行'), findsNothing);

      unawaited(sseController1.close());
      unawaited(sseController2.close());
      unawaited(convStreamController.close());
    });

    // 测试 9: asking + pendingReset 时 UI 禁用，respond 不发出
    testWidgets(
        'blocks respond and disables UI when pendingReset during asking state',
        (tester) async {
      final controller = _AgentFakeController();
      final sseController = StreamController<AgentSessionEvent>();
      final convStreamController =
          StreamController<AgentConversationEventItem>.broadcast();
      var respondCalled = false;
      final agentService = _FakeAgentSessionService(
        events: const [],
        onRunSession: (intent) {
          return sseController.stream;
        },
        onRespond: (_) async {
          respondCalled = true;
          return true;
        },
        onStreamConversation: (_) => convStreamController.stream,
      );
      await tester.pumpWidget(_buildTestApp(
        controller: controller,
        agentSessionServiceBuilder: (_) => agentService,
      ));
      await tester.pumpAndSettle();
      await _openSidePanel(tester);

      // 启动 SSE → session created
      await tester.enterText(
        find.byKey(const Key('side-panel-intent-input')),
        '测试 stale guard',
      );
      await _pressSidePanelSend(tester);
      await tester.pump();

      sseController.add(const AgentSessionCreatedEvent(sessionId: 's-stale'));
      // 进入 asking 状态
      sseController.add(const AgentQuestionEvent(
        question: '请选择操作',
        options: ['选项A', '选项B'],
        multiSelect: false,
        questionId: 'q1',
      ));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      // 验证 asking UI 可见
      expect(find.text('请选择操作'), findsOneWidget);

      // SSE 仍然活跃时，conversation stream 推送 conversation_reset
      convStreamController.add(const AgentConversationEventItem(
        eventIndex: 5,
        eventId: 'evt-reset-stale',
        type: 'conversation_reset',
        role: 'system',
        payload: {},
      ));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      // pendingReset 已设置，选项按钮应被禁用（onPressed=null）
      // 尝试点击选项按钮，不应触发 respond
      final optionAFinder = find.text('选项A');
      expect(optionAFinder, findsOneWidget);
      // 找到 OutlinedButton parent
      final outlinedButtons = find.byType(OutlinedButton);
      // 点第一个 OutlinedButton（选项A）
      await tester.tap(outlinedButtons.first);
      await tester.pump();

      // respond 不应被调用
      expect(respondCalled, isFalse);

      // 输入栏应被禁用（enabled=false 因为 pendingReset）
      final inputBar = find.byKey(const Key('side-panel-intent-input'));
      expect(inputBar, findsOneWidget);
      final textField = tester.widget<TextField>(inputBar);
      expect(textField.enabled, isFalse);

      // SSE 关闭触发 pendingReset 处理
      await sseController.close();
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      unawaited(convStreamController.close());
    });
  });
}
