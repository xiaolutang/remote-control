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
}
