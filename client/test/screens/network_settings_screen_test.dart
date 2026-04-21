import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:rc_client/models/app_environment.dart';
import 'package:rc_client/screens/network_settings_screen.dart';
import 'package:rc_client/services/desktop_agent_manager.dart';
import 'package:rc_client/services/desktop_agent_supervisor.dart';
import 'package:rc_client/services/environment_service.dart';
import 'package:rc_client/services/environment_switch_coordinator.dart';
import 'package:rc_client/services/network_diagnostic_service.dart';
import 'package:rc_client/services/terminal_session_manager.dart';
import 'package:shared_preferences/shared_preferences.dart';

class _MobileFakeSupervisor extends DesktopAgentSupervisor {
  @override
  bool get supported => false;
}

class _FakeNetworkDiagnosticService extends NetworkDiagnosticService {
  int runCallCount = 0;
  String? lastServerUrl;

  @override
  Future<NetworkDiagnosticReport> run({
    required String serverUrl,
    String? username,
    String? password,
  }) async {
    runCallCount += 1;
    lastServerUrl = serverUrl;
    final httpUrl = serverUrl.replaceFirst('ws://', 'http://').replaceFirst(
          'wss://',
          'https://',
        );
    return NetworkDiagnosticReport(
      serverUrl: serverUrl,
      httpUrl: httpUrl,
      checks: [
        NetworkDiagnosticCheck(
          title: '连通性',
          success: true,
          detail: 'checked:$serverUrl',
        ),
      ],
    );
  }
}

class _FakeEnvironmentSwitchCoordinator extends EnvironmentSwitchCoordinator {
  int switchCallCount = 0;
  AppEnvironment? lastEnvironment;

  @override
  Future<void> switchEnvironment({
    required BuildContext context,
    required AppEnvironment newEnv,
    authServiceBuilder,
  }) async {
    switchCallCount += 1;
    lastEnvironment = newEnv;
    await EnvironmentService.instance.switchEnvironment(newEnv);
  }
}

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues({});
    EnvironmentService.setInstance(
      EnvironmentService(debugModeProvider: () => true),
    );
  });

  Future<void> setLargeViewport(WidgetTester tester) async {
    await tester.binding.setSurfaceSize(const Size(900, 1000));
    addTearDown(() => tester.binding.setSurfaceSize(null));
  }

  Widget wrapWithApp({
    required NetworkDiagnosticService diagnosticService,
    required EnvironmentSwitchCoordinator switchCoordinator,
  }) {
    return MultiProvider(
      providers: [
        ChangeNotifierProvider(create: (_) => TerminalSessionManager()),
        ChangeNotifierProvider(
          create: (_) =>
              DesktopAgentManager(supervisor: _MobileFakeSupervisor()),
        ),
      ],
      child: MaterialApp(
        home: NetworkSettingsScreen(
          diagnosticService: diagnosticService,
          switchCoordinator: switchCoordinator,
        ),
      ),
    );
  }

  testWidgets('auto runs diagnostics when page opens', (tester) async {
    final diagnosticService = _FakeNetworkDiagnosticService();

    await setLargeViewport(tester);
    await tester.pumpWidget(
      wrapWithApp(
        diagnosticService: diagnosticService,
        switchCoordinator: const EnvironmentSwitchCoordinator(),
      ),
    );
    await tester.pumpAndSettle();

    expect(diagnosticService.runCallCount, 1);
    expect(find.text('本地开发环境'), findsOneWidget);
    expect(find.text('网络连接'), findsOneWidget);
    expect(find.text('连接诊断'), findsOneWidget);
    expect(find.textContaining('checked:ws://localhost'), findsOneWidget);
  });

  testWidgets('switching environment reruns diagnostics automatically',
      (tester) async {
    final diagnosticService = _FakeNetworkDiagnosticService();
    final switchCoordinator = _FakeEnvironmentSwitchCoordinator();

    await setLargeViewport(tester);
    await tester.pumpWidget(
      wrapWithApp(
        diagnosticService: diagnosticService,
        switchCoordinator: switchCoordinator,
      ),
    );
    await tester.pumpAndSettle();

    expect(diagnosticService.runCallCount, 1);

    await tester.tap(find.text('线上'));
    await tester.pump();
    await tester.pumpAndSettle();

    expect(switchCoordinator.switchCallCount, 1);
    expect(switchCoordinator.lastEnvironment, AppEnvironment.production);
    expect(diagnosticService.runCallCount, 2);
    expect(find.text('线上正式环境'), findsOneWidget);
    expect(find.text('网络连接'), findsOneWidget);
  });

  testWidgets('does not show theme entry on network settings page',
      (tester) async {
    await setLargeViewport(tester);
    await tester.pumpWidget(
      wrapWithApp(
        diagnosticService: _FakeNetworkDiagnosticService(),
        switchCoordinator: const EnvironmentSwitchCoordinator(),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('主题外观'), findsNothing);
    expect(find.byIcon(Icons.palette_outlined), findsNothing);
    expect(find.text('网络设置'), findsOneWidget);
  });
}
