import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
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

import '../test/mocks/mock_websocket_service.dart';

class _SmokeRuntimeDeviceService extends RuntimeDeviceService {
  _SmokeRuntimeDeviceService() : super(serverUrl: 'ws://localhost:8888');

  final Map<String, ProjectContextSettings> settingsByDevice =
      <String, ProjectContextSettings>{};
  final Map<String, DeviceProjectContextSnapshot> snapshotsByDevice =
      <String, DeviceProjectContextSnapshot>{};

  @override
  Future<List<RuntimeDevice>> listDevices(String token) async {
    return const [
      RuntimeDevice(
        deviceId: 'mbp-01',
        name: 'MacBook Pro',
        owner: 'user1',
        agentOnline: true,
        maxTerminals: 3,
        activeTerminals: 0,
      ),
    ];
  }

  @override
  Future<List<RuntimeTerminal>> listTerminals(
    String token,
    String deviceId,
  ) async {
    return const [];
  }

  @override
  Future<ProjectContextSettings> getProjectContextSettings(
    String token,
    String deviceId,
  ) async {
    return settingsByDevice[deviceId] ??
        ProjectContextSettings(deviceId: deviceId);
  }

  @override
  Future<ProjectContextSettings> saveProjectContextSettings(
    String token,
    String deviceId,
    ProjectContextSettings settings,
  ) async {
    settingsByDevice[deviceId] = settings;
    snapshotsByDevice[deviceId] = DeviceProjectContextSnapshot(
      deviceId: deviceId,
      generatedAt: DateTime.parse('2026-04-22T20:20:00Z'),
      candidates: [
        for (final project in settings.pinnedProjects)
          ProjectContextCandidate(
            candidateId: 'cand-${project.cwd.hashCode}',
            deviceId: deviceId,
            label: project.label,
            cwd: project.cwd,
            source: 'pinned_project',
            toolHints: const ['claude_code', 'shell'],
            updatedAt: DateTime.parse('2026-04-22T20:20:00Z'),
          ),
      ],
    );
    return settings;
  }

  @override
  Future<DeviceProjectContextSnapshot> getProjectContextSnapshot(
    String token,
    String deviceId,
  ) async {
    return snapshotsByDevice[deviceId] ??
        DeviceProjectContextSnapshot(
          deviceId: deviceId,
          generatedAt: DateTime.parse('2026-04-22T20:00:00Z'),
        );
  }

  @override
  Future<DeviceProjectContextSnapshot> refreshProjectContextSnapshot(
    String token,
    String deviceId,
  ) async {
    return getProjectContextSnapshot(token, deviceId);
  }
}

class _SmokePlannerCredentialsService extends PlannerCredentialsService {
  _SmokePlannerCredentialsService();

  final Map<String, String> _values = <String, String>{};

  @override
  Future<String?> readApiKey(String deviceId) async => _values[deviceId];

  @override
  Future<void> saveApiKey(String deviceId, String value) async {
    _values[deviceId] = value;
  }
}

class _SmokeSelectionController extends RuntimeSelectionController {
  _SmokeSelectionController({
    required super.runtimeService,
  }) : super(
          serverUrl: 'ws://localhost:8888',
          token: 'token',
        );

  @override
  WebSocketService buildTerminalService(RuntimeTerminal terminal) {
    return MockWebSocketService();
  }
}

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  group('Project context settings smoke', () {
    late _SmokeRuntimeDeviceService runtimeService;

    setUp(() {
      SharedPreferences.setMockInitialValues(<String, Object>{});
      EnvironmentService.setInstance(
        EnvironmentService(debugModeProvider: () => true),
      );
      PlannerCredentialsService.shared = _SmokePlannerCredentialsService();
      runtimeService = _SmokeRuntimeDeviceService();
    });

    testWidgets(
        'can save pinned project from smart create and use it in recommendation',
        (tester) async {
      final controller =
          _SmokeSelectionController(runtimeService: runtimeService);

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

      expect(controller.recommendedLaunchPlans.first.cwd, '~');

      await controller.updateProjectContextSettings(
        ProjectContextSettings(
          deviceId: 'mbp-01',
          pinnedProjects: const [
            PinnedProject(
              label: 'remote-control',
              cwd: '/Users/demo/project/remote-control',
            ),
          ],
        ),
      );
      await tester.pumpAndSettle();

      expect(
        controller.recommendedLaunchPlans.first.cwd,
        '/Users/demo/project/remote-control',
      );
      expect(
        controller.recommendedLaunchPlans.first.tool,
        TerminalLaunchTool.claudeCode,
      );
      expect(
        runtimeService.settingsByDevice['mbp-01']!.pinnedProjects.single.label,
        'remote-control',
      );
    });
  });
}
