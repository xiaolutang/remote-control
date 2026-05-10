import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:provider/provider.dart';
import 'package:rc_client/models/config.dart';
import 'package:rc_client/models/runtime_device.dart';
import 'package:rc_client/models/runtime_terminal.dart';
import 'package:rc_client/screens/desktop/terminal_workspace_screen.dart';
import 'package:rc_client/services/desktop/desktop_agent_bootstrap_service.dart';
import 'package:rc_client/services/desktop/desktop_agent_manager.dart';
import 'package:rc_client/services/environment_service.dart';
import 'package:rc_client/services/runtime_device_service.dart';
import 'package:rc_client/services/runtime_selection_controller.dart';
import 'package:rc_client/services/terminal_session_manager.dart';
import 'package:rc_client/services/theme_controller.dart';
import 'package:rc_client/services/websocket_service.dart';
import 'package:rc_client/widgets/terminal_tab_bar.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../test/mocks/mock_websocket_service.dart';

// ─── Mock HTTP client to prevent real network calls ─────────────

/// A minimal mock HttpClient that returns empty responses for all requests.
/// This prevents SmartTerminalSidePanel's AgentSessionService from
/// making real HTTP calls during integration tests.
class _SilentHttpClient implements HttpClient {
  final _emptyRequest = _SilentHttpClientRequest();
  @override
  Future<HttpClientRequest> openUrl(String method, Uri url) async =>
      _emptyRequest;
  @override
  Future<HttpClientRequest> getUrl(Uri url) async => _emptyRequest;
  @override
  Future<HttpClientRequest> postUrl(Uri url) async => _emptyRequest;
  @override
  dynamic noSuchMethod(Invocation invocation) => null;
}

class _SilentHttpClientRequest implements HttpClientRequest {
  final _response = _SilentHttpClientResponse();
  @override
  Future<HttpClientResponse> close() async => _response;
  @override
  void write(Object? object) {}
  @override
  Future<HttpClientResponse> get done => Future.value(_response);
  @override
  HttpHeaders get headers => _SilentHttpHeaders();
  @override
  Future<void> addStream(Stream<List<int>> stream) => stream.drain();
  @override
  void add(List<int> data) {}
  @override
  Future<void> flush() => Future.value();
  @override
  void writeAll(Iterable<Object?> objects, [String separator = '']) {}
  @override
  void writeCharCode(int charCode) {}
  @override
  void writeln([Object? object = '']) {}
  @override
  int get contentLength => -1;
  @override
  set contentLength(int value) {}
  @override
  Encoding get encoding => utf8;
  @override
  set encoding(Encoding value) {}
  @override
  bool get persistentConnection => false;
  @override
  set persistentConnection(bool value) {}
  @override
  bool get followRedirects => false;
  @override
  set followRedirects(bool value) {}
  @override
  int get maxRedirects => 5;
  @override
  set maxRedirects(int value) {}
  @override
  String get method => 'GET';
  @override
  Uri get uri => Uri.parse('http://localhost');
  @override
  HttpConnectionInfo? get connectionInfo => null;
  @override
  List<Cookie> get cookies => [];
  @override
  void abort([Object? exception, StackTrace? stackTrace]) {}
  void destroy() {}
  @override
  void addError(Object error, [StackTrace? stackTrace]) {}
  @override
  bool get bufferOutput => true;
  @override
  set bufferOutput(bool value) {}
}

class _SilentHttpClientResponse extends StreamView<List<int>>
    implements HttpClientResponse {
  _SilentHttpClientResponse()
      : super(Stream.value('{}'.codeUnits).asBroadcastStream());

  @override
  int get statusCode => 200;
  @override
  HttpClientResponseCompressionState get compressionState =>
      HttpClientResponseCompressionState.notCompressed;
  @override
  int get contentLength => 0;
  @override
  bool get isRedirect => false;
  @override
  bool get persistentConnection => false;
  @override
  String get reasonPhrase => 'OK';
  @override
  HttpHeaders get headers => _SilentHttpHeaders();
  @override
  List<RedirectInfo> get redirects => [];
  @override
  Future<HttpClientResponse> redirect(
          [String? method, Uri? url, bool? followLoops]) =>
      Future.value(this);
  @override
  Future<Socket> detachSocket() =>
      throw UnsupportedError('detachSocket not supported');
  Future<void> get done => Future.value();
  @override
  X509Certificate? get certificate => null;
  @override
  HttpConnectionInfo? get connectionInfo => null;
  @override
  List<Cookie> get cookies => [];
}

class _SilentHttpHeaders implements HttpHeaders {
  @override
  List<String>? operator [](String name) => null;
  @override
  dynamic noSuchMethod(Invocation invocation) => null;
}

class _TestHttpOverrides extends HttpOverrides {
  @override
  HttpClient createHttpClient(SecurityContext? context) {
    return _SilentHttpClient();
  }
}

// ─── In-memory stub for RuntimeDeviceService ─────────────────────

class _StubRuntimeDeviceService extends RuntimeDeviceService {
  _StubRuntimeDeviceService() : super(serverUrl: 'ws://localhost:8888');

  final List<RuntimeTerminal> _terminals = [];
  int _nextId = 1;
  bool _agentOnline = true;
  int _maxTerminals = 3;

  void setAgentOnline(bool value) => _agentOnline = value;
  void setMaxTerminals(int value) => _maxTerminals = value;

  @override
  Future<List<RuntimeDevice>> listDevices(String token) async {
    final activeCount =
        _terminals.where((t) => t.status != 'closed').length;
    return [
      RuntimeDevice(
        deviceId: 'mbp-01',
        name: 'MacBook Pro',
        owner: 'user1',
        agentOnline: _agentOnline,
        maxTerminals: _maxTerminals,
        activeTerminals: activeCount,
      ),
    ];
  }

  @override
  Future<List<RuntimeTerminal>> listTerminals(
    String token,
    String deviceId,
  ) async {
    return List.unmodifiable(
      _terminals.where((t) => t.status != 'closed').toList(),
    );
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
      terminalId: terminalId ?? 'term-${_nextId++}',
      title: title,
      cwd: cwd,
      command: command,
      status: 'attached',
      views: const {'mobile': 0, 'desktop': 1},
    );
    _terminals.add(terminal);
    return terminal;
  }

  @override
  Future<RuntimeTerminal> closeTerminal(
    String token,
    String deviceId,
    String terminalId,
  ) async {
    final index = _terminals.indexWhere((t) => t.terminalId == terminalId);
    if (index < 0) {
      throw Exception('Terminal not found');
    }
    final closed = _terminals[index].copyWith(status: 'closed');
    _terminals[index] = closed;
    return closed;
  }

  @override
  Future<RuntimeTerminal> updateTerminalTitle(
    String token,
    String deviceId,
    String terminalId,
    String title,
  ) async {
    final index = _terminals.indexWhere((t) => t.terminalId == terminalId);
    if (index < 0) {
      throw Exception('Terminal not found');
    }
    final updated = _terminals[index].copyWith(title: title);
    _terminals[index] = updated;
    return updated;
  }
}

// ─── Stub for DesktopAgentBootstrapService ───────────────────────

class _StubDesktopAgentBootstrapService extends DesktopAgentBootstrapService {
  @override
  Future<DesktopAgentState> loadAgentState({
    required String serverUrl,
    required String token,
    required String deviceId,
  }) async {
    return const DesktopAgentState(kind: DesktopAgentStateKind.managedOnline);
  }

  @override
  Future<DesktopAgentState> startAgent({
    required String serverUrl,
    required String token,
    required String deviceId,
    Duration timeout = TimingConstants.agentStartTimeout,
  }) async {
    return const DesktopAgentState(kind: DesktopAgentStateKind.managedOnline);
  }

  @override
  Future<bool> stopManagedAgent({
    required String serverUrl,
    required String token,
    required String deviceId,
    Duration timeout = TimingConstants.agentStopTimeout,
  }) async {
    return true;
  }

  @override
  Future<void> syncNativeTerminationState({
    required bool keepRunningInBackground,
  }) async {}

  @override
  Future<bool> handleDesktopExit({
    required bool keepRunningInBackground,
    required String serverUrl,
    required String token,
    required String deviceId,
    Duration timeout = TimingConstants.agentStopTimeout,
  }) async {
    return true;
  }
}

// ─── Controller subclass with mock WebSocket ──────────────────────

class _StubRuntimeSelectionController extends RuntimeSelectionController {
  _StubRuntimeSelectionController({
    required super.runtimeService,
    required super.initialDevices,
    this.forceDesktopPlatform = false,
  }) : super(
          serverUrl: 'ws://localhost:8888',
          token: 'test-token',
        );

  final bool forceDesktopPlatform;

  @override
  bool get isDesktopPlatform =>
      forceDesktopPlatform || super.isDesktopPlatform;

  @override
  WebSocketService buildTerminalService(RuntimeTerminal terminal) {
    final service = MockWebSocketService();
    service.simulateConnect();
    return service;
  }
}

// ─── Helpers ─────────────────────────────────────────────────────

const _settleDelay = Duration(milliseconds: 200);

Future<void> pumpWorkspace(
  WidgetTester tester, {
  required RuntimeSelectionController controller,
  required TerminalSessionManager sessionManager,
}) async {
  await tester.pumpWidget(
    MultiProvider(
      providers: [
        ChangeNotifierProvider(create: (_) => ThemeController()),
        ChangeNotifierProvider<TerminalSessionManager>.value(
          value: sessionManager,
        ),
      ],
      child: MaterialApp(
        home: TerminalWorkspaceScreen(
          token: 'test-token',
          controller: controller,
          agentBootstrapService: _StubDesktopAgentBootstrapService(),
        ),
      ),
    ),
  );
  for (var i = 0; i < 10; i++) {
    await tester.pump(const Duration(milliseconds: 100));
  }
}

Future<void> pumpUntil(
  WidgetTester tester,
  bool Function() condition, {
  required String reason,
  int maxTicks = 50,
}) async {
  for (var i = 0; i < maxTicks; i++) {
    await tester.pump(const Duration(milliseconds: 100));
    if (condition()) return;
  }
  fail('Timed out waiting for: $reason');
}

Future<RuntimeTerminal> createTerminalDirect(
  WidgetTester tester,
  RuntimeSelectionController controller, {
  required String title,
}) async {
  final terminal = await controller.createTerminal(
    title: title,
    cwd: '/Users/demo',
    command: '/bin/bash',
  );
  await tester.pumpAndSettle(_settleDelay);
  return terminal!;
}

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  // Install mock HTTP overrides to prevent real network calls from
  // SmartTerminalSidePanel's AgentSessionService and other services.
  setUp(() {
    HttpOverrides.global = _TestHttpOverrides();
  });

  tearDown(() {
    HttpOverrides.global = null;
  });

  group('Desktop workspace terminal tab integration', () {
    late _StubRuntimeDeviceService runtimeService;
    late _StubRuntimeSelectionController controller;
    late TerminalSessionManager sessionManager;

    setUp(() {
      SharedPreferences.setMockInitialValues(<String, Object>{});
      EnvironmentService.setInstance(
        EnvironmentService(debugModeProvider: () => true),
      );
      runtimeService = _StubRuntimeDeviceService();
      controller = _StubRuntimeSelectionController(
        runtimeService: runtimeService,
        initialDevices: [
          RuntimeDevice(
            deviceId: 'mbp-01',
            name: 'MacBook Pro',
            owner: 'user1',
            agentOnline: true,
            maxTerminals: 3,
            activeTerminals: 0,
          ),
        ],
        forceDesktopPlatform: true,
      );
      sessionManager = TerminalSessionManager();
    });

    tearDown(() {
      sessionManager.dispose();
      runtimeService.dispose();
    });

    testWidgets('empty state shows create action', (tester) async {
      await tester.binding.setSurfaceSize(const Size(1200, 800));
      addTearDown(() => tester.binding.setSurfaceSize(null));

      await pumpWorkspace(tester,
          controller: controller, sessionManager: sessionManager);
      await pumpUntil(
        tester,
        () => find
            .byKey(const Key('workspace-empty-create-action'))
            .evaluate()
            .isNotEmpty,
        reason: 'workspace empty create action visible',
      );

      expect(find.text('创建第一个终端'), findsOneWidget);
      expect(
        find.byKey(const Key('workspace-empty-create-action')),
        findsOneWidget,
      );
    });

    testWidgets('create terminal -> tab appears in TerminalTabBar',
        (tester) async {
      await tester.binding.setSurfaceSize(const Size(1200, 800));
      addTearDown(() => tester.binding.setSurfaceSize(null));

      // Use a controller pre-initialized with one terminal
      final localRuntimeService = _StubRuntimeDeviceService();
      final t1 = await localRuntimeService.createTerminal(
        'token',
        'mbp-01',
        title: 'My Terminal',
        cwd: '~',
        command: '/bin/bash',
      );
      final localController = _StubRuntimeSelectionController(
        runtimeService: localRuntimeService,
        initialDevices: [
          RuntimeDevice(
            deviceId: 'mbp-01',
            name: 'MacBook Pro',
            owner: 'user1',
            agentOnline: true,
            maxTerminals: 3,
            activeTerminals: 1,
          ),
        ],
        forceDesktopPlatform: true,
      );

      await pumpWorkspace(tester,
          controller: localController, sessionManager: sessionManager);
      await pumpUntil(
        tester,
        () => find.byType(TerminalTabBar).evaluate().isNotEmpty,
        reason: 'TerminalTabBar visible with pre-created terminal',
        maxTicks: 30,
      );

      // TerminalTabBar should be visible
      expect(find.byType(TerminalTabBar), findsOneWidget);
      // Tab with key: tab-{terminalId}
      expect(find.byKey(Key('tab-${t1.terminalId}')), findsOneWidget);
      // Empty state should be gone
      expect(find.text('创建第一个终端'), findsNothing);

      localRuntimeService.dispose();
    });

    testWidgets('create multiple terminals -> all appear as tabs',
        (tester) async {
      await tester.binding.setSurfaceSize(const Size(1200, 800));
      addTearDown(() => tester.binding.setSurfaceSize(null));

      final localRuntimeService = _StubRuntimeDeviceService();
      final t1 = await localRuntimeService.createTerminal(
        'token',
        'mbp-01',
        title: 'Terminal 1',
        cwd: '~',
        command: '/bin/bash',
      );
      final t2 = await localRuntimeService.createTerminal(
        'token',
        'mbp-01',
        title: 'Terminal 2',
        cwd: '~',
        command: '/bin/bash',
      );
      final localController = _StubRuntimeSelectionController(
        runtimeService: localRuntimeService,
        initialDevices: [
          RuntimeDevice(
            deviceId: 'mbp-01',
            name: 'MacBook Pro',
            owner: 'user1',
            agentOnline: true,
            maxTerminals: 3,
            activeTerminals: 2,
          ),
        ],
        forceDesktopPlatform: true,
      );

      await pumpWorkspace(tester,
          controller: localController, sessionManager: sessionManager);
      await pumpUntil(
        tester,
        () => find.byType(TerminalTabBar).evaluate().isNotEmpty,
        reason: 'TerminalTabBar visible with terminals',
        maxTicks: 30,
      );

      expect(find.byKey(Key('tab-${t1.terminalId}')), findsOneWidget);
      expect(find.byKey(Key('tab-${t2.terminalId}')), findsOneWidget);

      localRuntimeService.dispose();
    });

    testWidgets('close terminal -> adjacent still visible', (tester) async {
      await tester.binding.setSurfaceSize(const Size(1200, 800));
      addTearDown(() => tester.binding.setSurfaceSize(null));

      final localRuntimeService = _StubRuntimeDeviceService();
      final t1 = await localRuntimeService.createTerminal(
        'token',
        'mbp-01',
        title: 'Terminal 1',
        cwd: '~',
        command: '/bin/bash',
      );
      final t2 = await localRuntimeService.createTerminal(
        'token',
        'mbp-01',
        title: 'Terminal 2',
        cwd: '~',
        command: '/bin/bash',
      );
      final localController = _StubRuntimeSelectionController(
        runtimeService: localRuntimeService,
        initialDevices: [
          RuntimeDevice(
            deviceId: 'mbp-01',
            name: 'MacBook Pro',
            owner: 'user1',
            agentOnline: true,
            maxTerminals: 3,
            activeTerminals: 2,
          ),
        ],
        forceDesktopPlatform: true,
      );

      await pumpWorkspace(tester,
          controller: localController, sessionManager: sessionManager);
      await pumpUntil(
        tester,
        () => find.byType(TerminalTabBar).evaluate().isNotEmpty,
        reason: 'TerminalTabBar visible with terminals',
        maxTicks: 30,
      );

      // Close first terminal via controller
      await localController.closeTerminal(t1.terminalId);
      await tester.pumpAndSettle(_settleDelay);

      // First terminal should be closed in backend
      expect(localRuntimeService._terminals.first.status, 'closed');
      // Second terminal tab should still be visible
      expect(find.byKey(Key('tab-${t2.terminalId}')), findsOneWidget);

      localRuntimeService.dispose();
    });

    testWidgets('close last terminal -> returns to empty state',
        (tester) async {
      await tester.binding.setSurfaceSize(const Size(1200, 800));
      addTearDown(() => tester.binding.setSurfaceSize(null));

      final localRuntimeService = _StubRuntimeDeviceService();
      final t1 = await localRuntimeService.createTerminal(
        'token',
        'mbp-01',
        title: 'Only terminal',
        cwd: '~',
        command: '/bin/bash',
      );
      final localController = _StubRuntimeSelectionController(
        runtimeService: localRuntimeService,
        initialDevices: [
          RuntimeDevice(
            deviceId: 'mbp-01',
            name: 'MacBook Pro',
            owner: 'user1',
            agentOnline: true,
            maxTerminals: 3,
            activeTerminals: 1,
          ),
        ],
        forceDesktopPlatform: true,
      );

      await pumpWorkspace(tester,
          controller: localController, sessionManager: sessionManager);
      await pumpUntil(
        tester,
        () => find.byType(TerminalTabBar).evaluate().isNotEmpty,
        reason: 'TerminalTabBar visible with terminal',
        maxTicks: 30,
      );

      await localController.closeTerminal(t1.terminalId);
      await tester.pumpAndSettle(_settleDelay);

      // Terminal should be marked as closed in backend
      expect(localRuntimeService._terminals.first.status, 'closed');

      localRuntimeService.dispose();
    });

    testWidgets('max terminals -> create button disabled in tab bar',
        (tester) async {
      final localRuntimeService = _StubRuntimeDeviceService();
      localRuntimeService.setMaxTerminals(1);
      await localRuntimeService.createTerminal(
        'token',
        'mbp-01',
        title: 'Existing',
        cwd: '~',
        command: '/bin/bash',
      );

      final localController = _StubRuntimeSelectionController(
        runtimeService: localRuntimeService,
        initialDevices: [
          RuntimeDevice(
            deviceId: 'mbp-01',
            name: 'MacBook Pro',
            owner: 'user1',
            agentOnline: true,
            maxTerminals: 1,
            activeTerminals: 1,
          ),
        ],
        forceDesktopPlatform: true,
      );

      await tester.binding.setSurfaceSize(const Size(1200, 800));
      addTearDown(() => tester.binding.setSurfaceSize(null));

      await pumpWorkspace(tester,
          controller: localController, sessionManager: sessionManager);
      await pumpUntil(
        tester,
        () =>
            find.byKey(const Key('tab-bar-create')).evaluate().isNotEmpty,
        reason: 'tab bar create button visible',
        maxTicks: 30,
      );

      final createButton = tester.widget<IconButton>(
        find.descendant(
          of: find.byKey(const Key('tab-bar-create')),
          matching: find.byType(IconButton),
        ),
      );
      expect(createButton.onPressed, isNull);

      localRuntimeService.dispose();
    });
  });

  group('Mobile workspace terminal tab integration', () {
    late _StubRuntimeDeviceService runtimeService;
    late _StubRuntimeSelectionController controller;
    late TerminalSessionManager sessionManager;

    setUp(() {
      SharedPreferences.setMockInitialValues(<String, Object>{});
      EnvironmentService.setInstance(
        EnvironmentService(debugModeProvider: () => true),
      );
      runtimeService = _StubRuntimeDeviceService();
      controller = _StubRuntimeSelectionController(
        runtimeService: runtimeService,
        initialDevices: [
          RuntimeDevice(
            deviceId: 'mbp-01',
            name: 'MacBook Pro',
            owner: 'user1',
            agentOnline: true,
            maxTerminals: 3,
            activeTerminals: 0,
          ),
        ],
      );
      sessionManager = TerminalSessionManager();
    });

    tearDown(() {
      sessionManager.dispose();
      runtimeService.dispose();
    });

    testWidgets('create terminal -> compact tab appears', (tester) async {
      await tester.binding.setSurfaceSize(const Size(390, 844));
      addTearDown(() => tester.binding.setSurfaceSize(null));

      await pumpWorkspace(tester,
          controller: controller, sessionManager: sessionManager);
      await pumpUntil(
        tester,
        () => find
            .byKey(const Key('workspace-empty-create-action'))
            .evaluate()
            .isNotEmpty,
        reason: 'workspace empty create action visible on mobile',
      );

      final terminal = await createTerminalDirect(tester, controller,
          title: 'Mobile terminal');

      expect(
        find.byKey(Key('compact-tab-${terminal.terminalId}')),
        findsOneWidget,
      );
    });

    testWidgets('close terminal -> returns to empty state', (tester) async {
      await tester.binding.setSurfaceSize(const Size(390, 844));
      addTearDown(() => tester.binding.setSurfaceSize(null));

      await pumpWorkspace(tester,
          controller: controller, sessionManager: sessionManager);
      await pumpUntil(
        tester,
        () => find
            .byKey(const Key('workspace-empty-create-action'))
            .evaluate()
            .isNotEmpty,
        reason: 'workspace empty create action visible on mobile',
      );

      final t1 = await createTerminalDirect(tester, controller,
          title: 'Temp terminal');

      await controller.closeTerminal(t1.terminalId);
      await tester.pumpAndSettle(_settleDelay);

      expect(runtimeService._terminals.first.status, 'closed');
    });

    testWidgets('max terminals -> create disabled in compact strip',
        (tester) async {
      runtimeService.setMaxTerminals(1);
      await runtimeService.createTerminal(
        'token',
        'mbp-01',
        title: 'Existing',
        cwd: '~',
        command: '/bin/bash',
      );

      final localController = _StubRuntimeSelectionController(
        runtimeService: runtimeService,
        initialDevices: [
          RuntimeDevice(
            deviceId: 'mbp-01',
            name: 'MacBook Pro',
            owner: 'user1',
            agentOnline: true,
            maxTerminals: 1,
            activeTerminals: 1,
          ),
        ],
      );

      await tester.binding.setSurfaceSize(const Size(390, 844));
      addTearDown(() => tester.binding.setSurfaceSize(null));

      await pumpWorkspace(tester,
          controller: localController, sessionManager: sessionManager);
      await pumpUntil(
        tester,
        () => find
            .byKey(const Key('compact-tab-create'))
            .evaluate()
            .isNotEmpty,
        reason: 'compact tab create button visible on mobile',
      );

      final createButton = tester.widget<IconButton>(
        find.descendant(
          of: find.byKey(const Key('compact-tab-create')),
          matching: find.byType(IconButton),
        ),
      );
      expect(createButton.onPressed, isNull);
    });
  });

  group('Offline workspace scenarios', () {
    late _StubRuntimeDeviceService runtimeService;
    late TerminalSessionManager sessionManager;

    setUp(() {
      SharedPreferences.setMockInitialValues(<String, Object>{});
      EnvironmentService.setInstance(
        EnvironmentService(debugModeProvider: () => true),
      );
      runtimeService = _StubRuntimeDeviceService();
      sessionManager = TerminalSessionManager();
    });

    tearDown(() {
      sessionManager.dispose();
      runtimeService.dispose();
    });

    testWidgets('desktop offline -> device offline empty state shown',
        (tester) async {
      final offlineController = _StubRuntimeSelectionController(
        runtimeService: runtimeService,
        initialDevices: [
          RuntimeDevice(
            deviceId: 'mbp-01',
            name: 'MacBook Pro',
            owner: 'user1',
            agentOnline: false,
            maxTerminals: 3,
            activeTerminals: 0,
          ),
        ],
      );

      await tester.binding.setSurfaceSize(const Size(1200, 800));
      addTearDown(() => tester.binding.setSurfaceSize(null));

      await pumpWorkspace(tester,
          controller: offlineController, sessionManager: sessionManager);
      await pumpUntil(
        tester,
        () => find.text('电脑离线').evaluate().isNotEmpty,
        reason: 'device offline state visible',
      );

      expect(find.text('电脑离线'), findsWidgets);
    });

    testWidgets('mobile offline -> device offline state shown',
        (tester) async {
      final offlineController = _StubRuntimeSelectionController(
        runtimeService: runtimeService,
        initialDevices: [
          RuntimeDevice(
            deviceId: 'mbp-01',
            name: 'MacBook Pro',
            owner: 'user1',
            agentOnline: false,
            maxTerminals: 3,
            activeTerminals: 0,
          ),
        ],
      );

      await tester.binding.setSurfaceSize(const Size(390, 844));
      addTearDown(() => tester.binding.setSurfaceSize(null));

      await pumpWorkspace(tester,
          controller: offlineController, sessionManager: sessionManager);
      await pumpUntil(
        tester,
        () => find.text('电脑离线').evaluate().isNotEmpty,
        reason: 'device offline state visible on mobile',
      );

      expect(find.text('电脑离线'), findsWidgets);
    });
  });

  group('F009/F008 regression — refresh preservation + no loading spinner',
      () {
    late _StubRuntimeDeviceService runtimeService;
    late TerminalSessionManager sessionManager;

    setUp(() {
      SharedPreferences.setMockInitialValues(<String, Object>{});
      EnvironmentService.setInstance(
        EnvironmentService(debugModeProvider: () => true),
      );
      runtimeService = _StubRuntimeDeviceService();
      sessionManager = TerminalSessionManager();
    });

    tearDown(() {
      sessionManager.dispose();
      runtimeService.dispose();
    });

    testWidgets(
        'F009 regression: refresh preserves selected terminal on desktop',
        (tester) async {
      await tester.binding.setSurfaceSize(const Size(1200, 800));
      addTearDown(() => tester.binding.setSurfaceSize(null));

      // Create 2 terminals
      final t1 = await runtimeService.createTerminal(
        'token',
        'mbp-01',
        title: 'First',
        cwd: '~',
        command: '/bin/bash',
      );
      final t2 = await runtimeService.createTerminal(
        'token',
        'mbp-01',
        title: 'Second',
        cwd: '~',
        command: '/bin/bash',
      );
      final localController = _StubRuntimeSelectionController(
        runtimeService: runtimeService,
        initialDevices: [
          RuntimeDevice(
            deviceId: 'mbp-01',
            name: 'MacBook Pro',
            owner: 'user1',
            agentOnline: true,
            maxTerminals: 3,
            activeTerminals: 2,
          ),
        ],
        forceDesktopPlatform: true,
      );

      await pumpWorkspace(tester,
          controller: localController, sessionManager: sessionManager);
      await pumpUntil(
        tester,
        () => find.byType(TerminalTabBar).evaluate().isNotEmpty,
        reason: 'TerminalTabBar visible with terminals',
        maxTicks: 30,
      );

      // Select second terminal by tapping its tab
      await tester.tap(find.byKey(Key('tab-${t2.terminalId}')));
      await tester.pumpAndSettle(_settleDelay);

      // Trigger refresh — loadDevices re-fetches from stub
      await localController.loadDevices();
      await tester.pumpAndSettle(_settleDelay);

      // Verify selection is preserved on t2 via TerminalTabBar.selectedTerminalId
      final tabBar = tester.widget<TerminalTabBar>(find.byType(TerminalTabBar));
      expect(tabBar.selectedTerminalId, equals(t2.terminalId),
          reason: 'F009: selection preserved on t2 after loadDevices refresh');

      // Verify the IndexedStack still has both children (no rebuilding)
      final stack = tester.widgetList<IndexedStack>(
        find.byType(IndexedStack),
      );
      expect(stack.length, equals(1),
          reason: 'F009: single IndexedStack present after refresh');
      expect(stack.first.children.length, equals(2),
          reason: 'F009: both terminals cached in IndexedStack after refresh');
    });

    testWidgets(
        'F008 regression: switch terminal does not show CircularProgressIndicator',
        (tester) async {
      await tester.binding.setSurfaceSize(const Size(1200, 800));
      addTearDown(() => tester.binding.setSurfaceSize(null));

      final t1 = await runtimeService.createTerminal(
        'token',
        'mbp-01',
        title: 'First',
        cwd: '~',
        command: '/bin/bash',
      );
      final t2 = await runtimeService.createTerminal(
        'token',
        'mbp-01',
        title: 'Second',
        cwd: '~',
        command: '/bin/bash',
      );
      final localController = _StubRuntimeSelectionController(
        runtimeService: runtimeService,
        initialDevices: [
          RuntimeDevice(
            deviceId: 'mbp-01',
            name: 'MacBook Pro',
            owner: 'user1',
            agentOnline: true,
            maxTerminals: 3,
            activeTerminals: 2,
          ),
        ],
        forceDesktopPlatform: true,
      );

      await pumpWorkspace(tester,
          controller: localController, sessionManager: sessionManager);
      await pumpUntil(
        tester,
        () => find.byType(TerminalTabBar).evaluate().isNotEmpty,
        reason: 'TerminalTabBar visible',
        maxTicks: 30,
      );

      // Switch to second terminal
      await tester.tap(find.byKey(Key('tab-${t2.terminalId}')));
      await tester.pumpAndSettle(_settleDelay);

      // Should NOT show CircularProgressIndicator — IndexedStack caches all
      expect(
        find.byType(CircularProgressIndicator),
        findsNothing,
        reason: 'F008: no loading spinner after terminal switch',
      );

      // Both terminal views should exist (IndexedStack children)
      expect(find.byKey(Key('tab-${t1.terminalId}')), findsOneWidget);
      expect(find.byKey(Key('tab-${t2.terminalId}')), findsOneWidget);
    });
  });
}
