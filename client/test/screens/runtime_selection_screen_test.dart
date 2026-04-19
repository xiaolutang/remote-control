import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
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

import '../mocks/mock_websocket_service.dart';

class _FakeSelectionController extends RuntimeSelectionController {
  _FakeSelectionController()
      : super(
          serverUrl: 'ws://localhost:8888',
          token: 'token',
          runtimeService: _TestRuntimeDeviceService(),
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
  List<RuntimeTerminal> get terminals => const [
        RuntimeTerminal(
          terminalId: 'term-1',
          title: 'Claude / ai_rules',
          cwd: './',
          command: '/bin/bash',
          status: 'detached',
          views: {'mobile': 0, 'desktop': 0},
        ),
      ];

  @override
  Future<void> initialize() async {}

  @override
  Future<void> loadDevices() async {}

  @override
  Future<void> selectDevice(String deviceId, {bool notify = true}) async {}

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

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues({});
    EnvironmentService.setInstance(
      EnvironmentService(debugModeProvider: () => true),
    );
  });

  testWidgets('shows devices and terminals in selection screen', (tester) async {
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

  testWidgets('shows local desktop title when local device is selected', (tester) async {
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

    final button = tester.widget<FilledButton>(find.widgetWithText(FilledButton, '连接'));
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
}
