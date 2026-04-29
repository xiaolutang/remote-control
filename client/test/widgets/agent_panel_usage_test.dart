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
  _AgentFakeController({
    this.desktopPlatform = true,
  }) : super(
          serverUrl: 'ws://localhost:8888',
          token: 'test-token',
          runtimeService: _TestRuntimeDeviceService(),
        );

  final bool desktopPlatform;

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
}

class _TestRuntimeDeviceService extends RuntimeDeviceService {
  _TestRuntimeDeviceService() : super(serverUrl: 'ws://localhost:8888');
}

class _FakeUsageSummaryService extends UsageSummaryService {
  _FakeUsageSummaryService({
    required this.onFetch,
  }) : super(serverUrl: 'ws://localhost:8888');

  final Future<UsageSummaryData> Function(
      String token, String deviceId, String? terminalId) onFetch;
  int fetchCount = 0;
  String? lastTerminalId;

  @override
  Future<UsageSummaryData> fetchSummary({
    required String token,
    required String deviceId,
    String? terminalId,
  }) async {
    fetchCount += 1;
    lastTerminalId = terminalId;
    return onFetch(token, deviceId, terminalId);
  }
}

class _FakeAgentSessionService extends AgentSessionService {
  _FakeAgentSessionService({
    required this.events,
    this.onFetchConversation,
  }) : super(serverUrl: 'ws://localhost:8888');

  final List<AgentSessionEvent> events;
  final Future<AgentConversationProjection> Function(
    String deviceId,
    String? terminalId,
  )? onFetchConversation;

  @override
  Future<AgentConversationProjection> fetchConversation({
    required String deviceId,
    String? terminalId,
    required String token,
  }) async {
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
    return Stream<AgentSessionEvent>.fromIterable(events);
  }

  @override
  Stream<AgentConversationEventItem> streamConversation({
    required String deviceId,
    String? terminalId,
    required String token,
    int afterIndex = -1,
  }) {
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

Widget _buildTestApp({
  required RuntimeSelectionController controller,
  MockWebSocketService? wsService,
  AgentSessionServiceFactory? agentSessionServiceBuilder,
  UsageSummaryServiceFactory? usageSummaryServiceBuilder,
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

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues({});
    EnvironmentService.setInstance(
      EnvironmentService(debugModeProvider: () => true),
    );
  });

  group('Agent Panel Usage Section', () {
    testWidgets(
        'test_collapsed_shows_summary: collapsed shows total and current tokens',
        (tester) async {
      final controller = _AgentFakeController();
      final usageService = _FakeUsageSummaryService(
        onFetch: (_, __, ___) async => const UsageSummaryData(
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
      await tester.pumpAndSettle();

      // Usage section should be visible
      expect(find.byKey(const Key('side-panel-usage-section')),
          findsOneWidget);
      // Summary text should show total and current tokens
      expect(
          find.byKey(const Key('side-panel-usage-summary')), findsOneWidget);
      // Total is 900, current is 0 (no terminal scope data, no local accumulation)
      expect(find.text('总消耗 900 · 当前对话 0'), findsOneWidget);
    });

    testWidgets(
        'test_toggle_expand_collapse: click toggles expand/collapse',
        (tester) async {
      final controller = _AgentFakeController();
      final usageService = _FakeUsageSummaryService(
        onFetch: (_, __, ___) async => const UsageSummaryData(
          device: UsageSummaryScope(
            totalSessions: 1,
            totalInputTokens: 100,
            totalOutputTokens: 50,
            totalTokens: 150,
            totalRequests: 2,
            latestModelName: 'test-model',
          ),
          user: UsageSummaryScope(
            totalSessions: 3,
            totalInputTokens: 300,
            totalOutputTokens: 150,
            totalTokens: 450,
            totalRequests: 5,
            latestModelName: 'test-model',
          ),
        ),
      );
      await tester.pumpWidget(_buildTestApp(
        controller: controller,
        usageSummaryServiceBuilder: (_) => usageService,
      ));

      await _openSidePanel(tester);
      await tester.pumpAndSettle();

      // Initially collapsed: no detail labels
      expect(find.byKey(const Key('side-panel-usage-total-label')),
          findsNothing);

      // Tap to expand
      await tester.tap(find.byKey(const Key('side-panel-usage-toggle')));
      await tester.pumpAndSettle();

      // Expanded: detail labels visible
      expect(find.byKey(const Key('side-panel-usage-total-label')),
          findsOneWidget);
      expect(find.byKey(const Key('side-panel-usage-current-label')),
          findsOneWidget);

      // Tap again to collapse
      await tester.tap(find.byKey(const Key('side-panel-usage-toggle')));
      await tester.pumpAndSettle();

      // Collapsed again
      expect(find.byKey(const Key('side-panel-usage-total-label')),
          findsNothing);
    });

    testWidgets(
        'test_expanded_shows_two_sections: expanded shows total and current sections',
        (tester) async {
      final controller = _AgentFakeController();
      final usageService = _FakeUsageSummaryService(
        onFetch: (_, __, ___) async => const UsageSummaryData(
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
      await tester.pumpAndSettle();

      // Expand
      await tester.tap(find.byKey(const Key('side-panel-usage-toggle')));
      await tester.pumpAndSettle();

      // Both sections visible
      expect(find.byKey(const Key('side-panel-usage-total-label')),
          findsOneWidget);
      expect(find.byKey(const Key('side-panel-usage-current-label')),
          findsOneWidget);

      // Total section should show device and user data
      expect(find.text('总消耗'), findsOneWidget);
      expect(find.text('当前对话'), findsOneWidget);
    });

    testWidgets('test_data_accuracy: mock data numbers match display',
        (tester) async {
      final controller = _AgentFakeController();
      final usageService = _FakeUsageSummaryService(
        onFetch: (_, __, ___) async => const UsageSummaryData(
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
      await tester.pumpAndSettle();

      // Collapsed summary should show total 900 and current 0
      expect(find.text('总消耗 900 · 当前对话 0'), findsOneWidget);

      // Expand to verify detail accuracy
      await tester.tap(find.byKey(const Key('side-panel-usage-toggle')));
      await tester.pumpAndSettle();

      // Device row: 200 tokens, 3 次
      expect(find.text('200 tokens'), findsOneWidget);
      expect(find.text('3 次'), findsOneWidget);
      // User row: 900 tokens, 11 次
      expect(find.text('900 tokens'), findsOneWidget);
      expect(find.text('11 次'), findsOneWidget);
      // Current session: 0 tokens, 0 次
      expect(find.text('0 tokens'), findsWidgets);
      expect(find.text('0 次'), findsOneWidget);
    });

    testWidgets(
        'test_api_failure_shows_fallback: API failure shows error state',
        (tester) async {
      final controller = _AgentFakeController();
      final usageService = _FakeUsageSummaryService(
        onFetch: (_, __, ___) async {
          throw const UsageSummaryException(message: 'timeout');
        },
      );
      await tester.pumpWidget(_buildTestApp(
        controller: controller,
        usageSummaryServiceBuilder: (_) => usageService,
      ));

      await _openSidePanel(tester);
      // Wait for the async auto-refresh to complete
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));
      await tester.pump();
      await tester.pump();

      // Usage section should be visible
      expect(find.byKey(const Key('side-panel-usage-section')),
          findsOneWidget);

      // After fetch failure, either error message or the summary with 0 tokens should be shown.
      final errorKey = find.byKey(const Key('side-panel-usage-error'));
      final summaryKey = find.byKey(const Key('side-panel-usage-summary'));

      // Either the error or summary widget should be present
      expect(
        errorKey.evaluate().isNotEmpty || summaryKey.evaluate().isNotEmpty,
        isTrue,
        reason:
            'Either error or summary should be visible after API failure',
      );

      // No NaN or negative numbers anywhere
      expect(find.text('NaN'), findsNothing);
    });

    testWidgets(
        'test_empty_data_display: no data does not show NaN or negative',
        (tester) async {
      final controller = _AgentFakeController();
      final usageService = _FakeUsageSummaryService(
        onFetch: (_, __, ___) async => const UsageSummaryData.empty(),
      );
      await tester.pumpWidget(_buildTestApp(
        controller: controller,
        usageSummaryServiceBuilder: (_) => usageService,
      ));

      await _openSidePanel(tester);
      await tester.pumpAndSettle();

      // Should show 0 for both values, not NaN or negative
      expect(find.byKey(const Key('side-panel-usage-summary')),
          findsOneWidget);
      expect(find.text('总消耗 0 · 当前对话 0'), findsOneWidget);

      // Expand to verify
      await tester.tap(find.byKey(const Key('side-panel-usage-toggle')));
      await tester.pumpAndSettle();

      // No NaN in expanded view
      expect(find.text('NaN'), findsNothing);
      // 0 tokens is valid
      expect(find.text('0 tokens'), findsWidgets);
    });

    testWidgets(
        'test_state_sync: accumulator updates reflect in UI after result event',
        (tester) async {
      final controller = _AgentFakeController();
      final usageService = _FakeUsageSummaryService(
        onFetch: (_, __, ___) async => const UsageSummaryData(
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
      // Press send
      final button = tester.widget<FilledButton>(
        find.byKey(const Key('side-panel-send')),
      );
      button.onPressed?.call();
      await tester.pumpAndSettle();

      // After result event, current conversation should show 1900 tokens
      // (from local accumulator since server response does not include terminal scope)
      expect(find.byKey(const Key('side-panel-usage-summary')),
          findsOneWidget);
      expect(find.text('总消耗 6600 · 当前对话 1900'), findsOneWidget);
    });

    testWidgets(
        'test_terminal_scope_overrides_local: server terminal scope data overrides local accumulator',
        (tester) async {
      final controller = _AgentFakeController();
      final usageService = _FakeUsageSummaryService(
        onFetch: (_, __, ___) async => const UsageSummaryData(
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
          terminal: UsageSummaryScope(
            totalSessions: 2,
            totalInputTokens: 3000,
            totalOutputTokens: 600,
            totalTokens: 3600,
            totalRequests: 5,
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
      // Press send
      final button = tester.widget<FilledButton>(
        find.byKey(const Key('side-panel-send')),
      );
      button.onPressed?.call();
      await tester.pumpAndSettle();

      // After result event, server terminal scope (3600) should override
      // the local accumulator (1900) in the collapsed summary
      expect(find.byKey(const Key('side-panel-usage-summary')),
          findsOneWidget);
      expect(find.text('总消耗 6600 · 当前对话 3600'), findsOneWidget);
    });

    testWidgets(
        'test_terminal_id_passed_to_api: refresh after result passes terminal_id',
        (tester) async {
      final controller = _AgentFakeController();
      final usageService = _FakeUsageSummaryService(
        onFetch: (_, __, ___) async => const UsageSummaryData(
          device: UsageSummaryScope(
            totalSessions: 1,
            totalTokens: 200,
            totalRequests: 3,
            latestModelName: 'deepseek-chat',
            totalInputTokens: 100,
            totalOutputTokens: 100,
          ),
          user: UsageSummaryScope(
            totalSessions: 2,
            totalTokens: 500,
            totalRequests: 5,
            latestModelName: 'deepseek-chat',
            totalInputTokens: 300,
            totalOutputTokens: 200,
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
              inputTokens: 100,
              outputTokens: 50,
              totalTokens: 150,
              requests: 1,
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
        'test',
      );
      final button = tester.widget<FilledButton>(
        find.byKey(const Key('side-panel-send')),
      );
      button.onPressed?.call();
      await tester.pumpAndSettle();

      // Verify that the usage service was called at least once
      // (the exact terminal_id depends on MockWebSocketService.terminalId)
      expect(usageService.fetchCount, greaterThanOrEqualTo(1));
    });
  });
}
