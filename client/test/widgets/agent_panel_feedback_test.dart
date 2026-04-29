// ignore_for_file: deprecated_member_use_from_same_package, no_leading_underscores_for_local_identifiers, unused_element

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:rc_client/models/agent_conversation_projection.dart';
import 'package:rc_client/models/agent_session_event.dart';
import 'package:rc_client/models/runtime_device.dart';
import 'package:rc_client/models/runtime_terminal.dart';
import 'package:rc_client/services/agent_session_service.dart';
import 'package:rc_client/services/environment_service.dart';
import 'package:rc_client/services/runtime_device_service.dart';
import 'package:rc_client/services/runtime_selection_controller.dart';
import 'package:rc_client/services/usage_summary_service.dart';
import 'package:rc_client/services/websocket_service.dart';
import 'package:rc_client/widgets/smart_terminal_side_panel.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../mocks/mock_websocket_service.dart';

class _AgentFakeController extends RuntimeSelectionController {
  _AgentFakeController() : super(
          serverUrl: 'ws://localhost:8888',
          token: 'test-token',
          runtimeService: _TestRuntimeDeviceService(),
        );

  @override
  bool get isDesktopPlatform => true;

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
}

class _TestRuntimeDeviceService extends RuntimeDeviceService {
  _TestRuntimeDeviceService() : super(serverUrl: 'ws://localhost:8888');
}

class _FakeUsageSummaryService extends UsageSummaryService {
  _FakeUsageSummaryService() : super(serverUrl: 'ws://localhost:8888');

  @override
  Future<UsageSummaryData> fetchSummary({
    required String token,
    required String deviceId,
    String? terminalId,
  }) async => const UsageSummaryData.empty();
}

class _FakeAgentSessionService extends AgentSessionService {
  _FakeAgentSessionService({required this.events})
      : super(serverUrl: 'ws://localhost:8888');

  final List<AgentSessionEvent> events;

  @override
  Future<AgentConversationProjection> fetchConversation({
    required String deviceId,
    String? terminalId,
    required String token,
  }) async =>
      AgentConversationProjection.empty(
        deviceId: deviceId,
        terminalId: terminalId ?? 'term-1',
      );

  @override
  Stream<AgentSessionEvent> runSession({
    required String deviceId,
    String? terminalId,
    required String intent,
    required String token,
    String? conversationId,
    String? clientEventId,
    int? truncateAfterIndex,
  }) =>
      Stream<AgentSessionEvent>.fromIterable(events);

  @override
  Stream<AgentConversationEventItem> streamConversation({
    required String deviceId,
    String? terminalId,
    required String token,
    int afterIndex = -1,
  }) =>
      const Stream<AgentConversationEventItem>.empty();

  @override
  Future<bool> respond({
    required String deviceId,
    String? terminalId,
    required String sessionId,
    required String answer,
    required String token,
    String? questionId,
    String? clientEventId,
  }) async =>
      true;

  @override
  Future<bool> cancel({
    required String deviceId,
    String? terminalId,
    required String sessionId,
    required String token,
  }) async =>
      true;
}

Widget _buildTestApp({
  required RuntimeSelectionController controller,
  MockWebSocketService? wsService,
  AgentSessionServiceFactory? agentSessionServiceBuilder,
  FeedbackSubmitter? feedbackSubmitterOverride,
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
          agentSessionServiceBuilder: agentSessionServiceBuilder,
          usageSummaryServiceBuilder: (_) => _FakeUsageSummaryService(),
          feedbackSubmitterOverride: feedbackSubmitterOverride,
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

/// Helper: type intent and press send to trigger agent session
Future<void> _submitIntent(WidgetTester tester, String intent) async {
  await tester.enterText(
    find.byKey(const Key('side-panel-intent-input')),
    intent,
  );
  final button = tester.widget<FilledButton>(
    find.byKey(const Key('side-panel-send')),
  );
  button.onPressed?.call();
  await tester.pumpAndSettle();
}

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues({});
    EnvironmentService.setInstance(
      EnvironmentService(debugModeProvider: () => true),
    );
  });

  group('Agent Panel Feedback Buttons', () {
    testWidgets(
        'test_feedback_buttons_visible: result card shows feedback buttons',
        (tester) async {
      final controller = _AgentFakeController();
      final agentService = _FakeAgentSessionService(
        events: [
          const AgentSessionCreatedEvent(sessionId: 'session-1'),
          AgentResultEvent(
            summary: 'test result summary',
            steps: const [],
            provider: 'agent',
            source: 'recommended',
            needConfirm: false,
            aliases: const <String, String>{},
            responseType: 'message',
          ),
        ],
      );

      await tester.pumpWidget(_buildTestApp(
        controller: controller,
        agentSessionServiceBuilder: (_) => agentService,
      ));

      await _openSidePanel(tester);
      await _submitIntent(tester, 'test intent');

      // Result view should show feedback buttons
      expect(find.text('有帮助'), findsOneWidget);
      expect(find.text('需改进'), findsOneWidget);
    });

    testWidgets('test_feedback_submit: clicking submits to feedback API',
        (tester) async {
      final controller = _AgentFakeController();
      final agentService = _FakeAgentSessionService(
        events: [
          const AgentSessionCreatedEvent(sessionId: 'session-1'),
          AgentResultEvent(
            summary: 'test result',
            steps: const [],
            provider: 'agent',
            source: 'recommended',
            needConfirm: false,
            aliases: const <String, String>{},
            responseType: 'message',
          ),
        ],
      );

      bool feedbackCalled = false;
      String? capturedFeedbackType;
      String? capturedTerminalId;

      await tester.pumpWidget(_buildTestApp(
        controller: controller,
        agentSessionServiceBuilder: (_) => agentService,
        feedbackSubmitterOverride: ({
          required serverUrl,
          required token,
          required terminalId,
          resultEventId,
          required feedbackType,
          description,
        }) async {
          feedbackCalled = true;
          capturedFeedbackType = feedbackType;
          capturedTerminalId = terminalId;
          return true;
        },
      ));

      await _openSidePanel(tester);
      await _submitIntent(tester, 'test');

      // Tap "有帮助"
      await tester.tap(find.text('有帮助'));
      await tester.pumpAndSettle();

      expect(feedbackCalled, isTrue);
      expect(capturedFeedbackType, 'helpful');
      expect(capturedTerminalId, 'term-1');
    });

    testWidgets(
        'test_feedback_state_change: after submit buttons show feedback state',
        (tester) async {
      final controller = _AgentFakeController();
      final agentService = _FakeAgentSessionService(
        events: [
          const AgentSessionCreatedEvent(sessionId: 'session-1'),
          AgentResultEvent(
            summary: 'test state change',
            steps: const [],
            provider: 'agent',
            source: 'recommended',
            needConfirm: false,
            aliases: const <String, String>{},
            responseType: 'message',
          ),
        ],
      );

      await tester.pumpWidget(_buildTestApp(
        controller: controller,
        agentSessionServiceBuilder: (_) => agentService,
        feedbackSubmitterOverride: ({
          required serverUrl,
          required token,
          required terminalId,
          resultEventId,
          required feedbackType,
          description,
        }) async =>
            true,
      ));

      await _openSidePanel(tester);
      await _submitIntent(tester, 'test');

      // Before: buttons visible
      expect(find.text('有帮助'), findsOneWidget);

      // Tap "有帮助"
      await tester.tap(find.text('有帮助'));
      await tester.pumpAndSettle();

      // After: should show "已反馈" state
      expect(find.text('有帮助'), findsNothing);
      expect(find.textContaining('已反馈'), findsOneWidget);
    });

    testWidgets(
        'test_feedback_submit_failure: network failure shows error and allows retry',
        (tester) async {
      final controller = _AgentFakeController();
      final agentService = _FakeAgentSessionService(
        events: [
          const AgentSessionCreatedEvent(sessionId: 'session-1'),
          AgentResultEvent(
            summary: 'test failure',
            steps: const [],
            provider: 'agent',
            source: 'recommended',
            needConfirm: false,
            aliases: const <String, String>{},
            responseType: 'message',
          ),
        ],
      );

      int submitAttempts = 0;

      await tester.pumpWidget(_buildTestApp(
        controller: controller,
        agentSessionServiceBuilder: (_) => agentService,
        feedbackSubmitterOverride: ({
          required serverUrl,
          required token,
          required terminalId,
          resultEventId,
          required feedbackType,
          description,
        }) async {
          submitAttempts++;
          if (submitAttempts == 1) {
            throw Exception('Network error');
          }
          return true;
        },
      ));

      await _openSidePanel(tester);
      await _submitIntent(tester, 'test');

      // First attempt: will fail
      await tester.tap(find.text('有帮助'));
      await tester.pumpAndSettle();

      // Should show error message
      expect(find.text('反馈提交失败，请重试'), findsOneWidget);

      // Buttons should still be visible for retry
      expect(find.text('有帮助'), findsOneWidget);

      // Second attempt: will succeed
      await tester.tap(find.text('有帮助'));
      await tester.pumpAndSettle();

      // Now should show feedback state
      expect(find.textContaining('已反馈'), findsOneWidget);
    });

    testWidgets('test_error_view_feedback: error view has feedback button',
        (tester) async {
      final controller = _AgentFakeController();
      final agentService = _FakeAgentSessionService(
        events: [
          const AgentSessionCreatedEvent(sessionId: 'session-1'),
          const AgentErrorEvent(code: 'TEST_ERROR', message: 'test error msg'),
        ],
      );

      bool feedbackCalled = false;

      await tester.pumpWidget(_buildTestApp(
        controller: controller,
        agentSessionServiceBuilder: (_) => agentService,
        feedbackSubmitterOverride: ({
          required serverUrl,
          required token,
          required terminalId,
          resultEventId,
          required feedbackType,
          description,
        }) async {
          feedbackCalled = true;
          expect(feedbackType, 'error_report');
          return true;
        },
      ));

      await _openSidePanel(tester);
      await _submitIntent(tester, 'test');

      // Error view should show "报告问题" button
      expect(find.text('报告问题'), findsOneWidget);

      // Tap it
      await tester.tap(find.text('报告问题'));
      await tester.pumpAndSettle();

      expect(feedbackCalled, isTrue);
      // After feedback, should show feedback state
      expect(find.textContaining('已反馈'), findsOneWidget);
    });

    testWidgets(
        'test_feedback_duplicate: cannot submit feedback twice for same result',
        (tester) async {
      final controller = _AgentFakeController();
      final agentService = _FakeAgentSessionService(
        events: [
          const AgentSessionCreatedEvent(sessionId: 'session-1'),
          AgentResultEvent(
            summary: 'test duplicate',
            steps: const [],
            provider: 'agent',
            source: 'recommended',
            needConfirm: false,
            aliases: const <String, String>{},
            responseType: 'message',
          ),
        ],
      );

      int submitCount = 0;

      await tester.pumpWidget(_buildTestApp(
        controller: controller,
        agentSessionServiceBuilder: (_) => agentService,
        feedbackSubmitterOverride: ({
          required serverUrl,
          required token,
          required terminalId,
          resultEventId,
          required feedbackType,
          description,
        }) async {
          submitCount++;
          return true;
        },
      ));

      await _openSidePanel(tester);
      await _submitIntent(tester, 'test');

      // First submit
      await tester.tap(find.text('有帮助'));
      await tester.pumpAndSettle();

      expect(submitCount, 1);
      expect(find.textContaining('已反馈'), findsOneWidget);

      // Buttons should be gone, so no second submit possible
      expect(find.text('有帮助'), findsNothing);
      expect(find.text('需改进'), findsNothing);
    });
  });
}
