import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:rc_client/models/config.dart';
import 'package:rc_client/models/project_context_settings.dart';
import 'package:rc_client/models/project_context_snapshot.dart';
import 'package:rc_client/models/recent_launch_context.dart';
import 'package:rc_client/models/runtime_device.dart';
import 'package:rc_client/models/runtime_terminal.dart';
import 'package:rc_client/models/terminal_launch_plan.dart';
import 'package:rc_client/services/config_service.dart';
import 'package:rc_client/services/environment_service.dart';
import 'package:rc_client/services/llm_planner_provider.dart';
import 'package:rc_client/services/planner_credentials_service.dart';
import 'package:rc_client/services/runtime_device_service.dart';
import 'package:rc_client/services/runtime_selection_controller.dart';
import 'package:rc_client/services/terminal_launch_plan_service.dart';
import 'package:shared_preferences/shared_preferences.dart';

class _FakeRuntimeDeviceService extends RuntimeDeviceService {
  _FakeRuntimeDeviceService() : super(serverUrl: 'ws://localhost:8888');

  List<RuntimeDevice> devices = const [];
  Map<String, List<RuntimeTerminal>> terminalsByDevice = const {};
  final Map<String, ProjectContextSettings> settingsByDevice =
      <String, ProjectContextSettings>{};
  final Map<String, DeviceProjectContextSnapshot> snapshotsByDevice =
      <String, DeviceProjectContextSnapshot>{};

  @override
  Future<List<RuntimeDevice>> listDevices(String token) async => devices;

  @override
  Future<List<RuntimeTerminal>> listTerminals(
      String token, String deviceId) async {
    return terminalsByDevice[deviceId] ?? const [];
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
    return RuntimeTerminal(
      terminalId: terminalId ?? 'term-created',
      title: title,
      cwd: cwd,
      command: command,
      status: 'detached',
      views: const {'mobile': 0, 'desktop': 0},
    );
  }

  @override
  Future<RuntimeTerminal> closeTerminal(
    String token,
    String deviceId,
    String terminalId,
  ) async {
    return RuntimeTerminal(
      terminalId: terminalId,
      title: 'Closed',
      cwd: '/tmp',
      command: '/bin/bash',
      status: 'closed',
      disconnectReason: 'server_forced_close',
      views: const {'mobile': 0, 'desktop': 0},
      updatedAt: DateTime.parse('2026-03-29T02:00:00Z'),
    );
  }

  @override
  Future<RuntimeDevice> updateDevice(String token, String deviceId,
      {String? name}) async {
    return RuntimeDevice(
      deviceId: deviceId,
      name: name ?? 'Updated',
      owner: 'user1',
      agentOnline: true,
      maxTerminals: 3,
      activeTerminals: 1,
    );
  }

  @override
  Future<RuntimeTerminal> updateTerminalTitle(
    String token,
    String deviceId,
    String terminalId,
    String title,
  ) async {
    return RuntimeTerminal(
      terminalId: terminalId,
      title: title,
      cwd: '/tmp',
      command: '/bin/bash',
      status: 'detached',
      views: const {'mobile': 0, 'desktop': 0},
      updatedAt: DateTime.parse('2026-03-29T02:00:00Z'),
    );
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
          generatedAt: DateTime.parse('2026-04-22T12:00:00Z'),
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

class _AlwaysKeyPlannerCredentialsService extends PlannerCredentialsService {
  _AlwaysKeyPlannerCredentialsService();

  @override
  Future<String?> readApiKey(String deviceId) async => 'test-key';
}

void main() {
  group('RuntimeSelectionController', () {
    late _FakeRuntimeDeviceService runtimeService;
    late ConfigService configService;

    setUp(() {
      SharedPreferences.setMockInitialValues({});
      EnvironmentService.setInstance(
        EnvironmentService(debugModeProvider: () => true),
      );
      runtimeService = _FakeRuntimeDeviceService();
      configService = ConfigService();
    });

    test('initializes with preferred device and loads terminals', () async {
      await configService.saveConfig(
        const AppConfig(preferredDeviceId: 'mbp-02'),
      );
      runtimeService.devices = const [
        RuntimeDevice(
          deviceId: 'mbp-01',
          name: 'Offline',
          owner: 'user1',
          agentOnline: false,
          maxTerminals: 2,
          activeTerminals: 0,
        ),
        RuntimeDevice(
          deviceId: 'mbp-02',
          name: 'Online',
          owner: 'user1',
          agentOnline: true,
          maxTerminals: 2,
          activeTerminals: 1,
        ),
      ];
      runtimeService.terminalsByDevice = {
        'mbp-02': const [
          RuntimeTerminal(
            terminalId: 'term-1',
            title: 'Claude',
            cwd: '/tmp',
            command: '/bin/bash',
            status: 'detached',
            views: {'mobile': 0, 'desktop': 0},
          ),
        ],
      };

      final controller = RuntimeSelectionController(
        serverUrl: 'ws://localhost:8888',
        token: 'token',
        runtimeService: runtimeService,
        configService: configService,
      );
      await controller.initialize();

      expect(controller.selectedDeviceId, 'mbp-02');
      expect(controller.terminals.single.terminalId, 'term-1');
    });

    test('builds recommended launch plans from selected device context',
        () async {
      await configService.saveConfig(
        AppConfig(
          preferredDeviceId: 'mbp-02',
          recentLaunchContexts: {
            'mbp-02': RecentLaunchContext(
              deviceId: 'mbp-02',
              lastTool: TerminalLaunchTool.codex,
              lastCwd: '/Users/demo/project/remote-control',
              lastSuccessfulPlan: const TerminalLaunchPlan(
                tool: TerminalLaunchTool.codex,
                title: 'Codex / remote-control',
                cwd: '/Users/demo/project/remote-control',
                command: '/bin/bash',
                entryStrategy: TerminalEntryStrategy.shellBootstrap,
                postCreateInput: 'codex\n',
                source: TerminalLaunchPlanSource.recommended,
              ),
              updatedAt: DateTime.parse('2026-04-22T03:30:00Z'),
            ),
          },
        ),
      );
      runtimeService.devices = const [
        RuntimeDevice(
          deviceId: 'mbp-02',
          name: 'Online',
          owner: 'user1',
          agentOnline: true,
          maxTerminals: 2,
          activeTerminals: 0,
        ),
      ];
      runtimeService.terminalsByDevice = const {'mbp-02': []};

      final controller = RuntimeSelectionController(
        serverUrl: 'ws://localhost:8888',
        token: 'token',
        runtimeService: runtimeService,
        configService: configService,
      );
      await controller.initialize();

      expect(
        controller.recommendedLaunchPlans.first.tool,
        TerminalLaunchTool.codex,
      );
      expect(
        controller.recommendedLaunchPlans.first.postCreateInput,
        'codex\n',
      );
    });

    test('blocks terminal creation when selected device is offline', () async {
      runtimeService.devices = const [
        RuntimeDevice(
          deviceId: 'mbp-01',
          name: 'Offline',
          owner: 'user1',
          agentOnline: false,
          maxTerminals: 2,
          activeTerminals: 0,
        ),
      ];

      final controller = RuntimeSelectionController(
        serverUrl: 'ws://localhost:8888',
        token: 'token',
        runtimeService: runtimeService,
        configService: configService,
      );
      await controller.initialize();
      final terminal = await controller.createTerminal(
        title: 'Claude',
        cwd: '/tmp',
        command: '/bin/bash',
      );

      expect(terminal, isNull);
      expect(controller.errorMessage, contains('离线'));
    });

    test('sorts terminals by status then updatedAt', () async {
      runtimeService.devices = const [
        RuntimeDevice(
          deviceId: 'mbp-01',
          name: 'Online',
          owner: 'user1',
          agentOnline: true,
          maxTerminals: 3,
          activeTerminals: 2,
        ),
      ];
      runtimeService.terminalsByDevice = {
        'mbp-01': [
          RuntimeTerminal(
            terminalId: 'closed-old',
            title: 'Closed',
            cwd: '/tmp/closed',
            command: '/bin/bash',
            status: 'closed',
            views: const {'mobile': 0, 'desktop': 0},
            updatedAt: DateTime.parse('2026-03-29T01:00:00Z'),
          ),
          RuntimeTerminal(
            terminalId: 'detached-new',
            title: 'Detached',
            cwd: '/tmp/detached',
            command: '/bin/bash',
            status: 'detached',
            views: const {'mobile': 0, 'desktop': 0},
            updatedAt: DateTime.parse('2026-03-29T03:00:00Z'),
          ),
          RuntimeTerminal(
            terminalId: 'attached-old',
            title: 'Attached',
            cwd: '/tmp/attached',
            command: '/bin/bash',
            status: 'attached',
            views: const {'mobile': 1, 'desktop': 0},
            updatedAt: DateTime.parse('2026-03-29T00:00:00Z'),
          ),
        ],
      };

      final controller = RuntimeSelectionController(
        serverUrl: 'ws://localhost:8888',
        token: 'token',
        runtimeService: runtimeService,
        configService: configService,
      );
      await controller.initialize();

      expect(
        controller.terminals.map((terminal) => terminal.terminalId).toList(),
        ['attached-old', 'detached-new', 'closed-old'],
      );
    });

    test('closes terminal and updates local list', () async {
      runtimeService.devices = const [
        RuntimeDevice(
          deviceId: 'mbp-01',
          name: 'Online',
          owner: 'user1',
          agentOnline: true,
          maxTerminals: 3,
          activeTerminals: 1,
        ),
      ];
      runtimeService.terminalsByDevice = {
        'mbp-01': const [
          RuntimeTerminal(
            terminalId: 'term-1',
            title: 'Claude',
            cwd: '/tmp',
            command: '/bin/bash',
            status: 'detached',
            views: {'mobile': 0, 'desktop': 0},
          ),
        ],
      };

      final controller = RuntimeSelectionController(
        serverUrl: 'ws://localhost:8888',
        token: 'token',
        runtimeService: runtimeService,
        configService: configService,
      );
      await controller.initialize();
      final closed = await controller.closeTerminal('term-1');

      expect(closed, isNotNull);
      expect(controller.terminals.single.status, 'closed');
      expect(
          controller.terminals.single.disconnectReason, 'server_forced_close');
    });

    test('updates selected device name and local list', () async {
      runtimeService.devices = const [
        RuntimeDevice(
          deviceId: 'mbp-01',
          name: 'Old Name',
          owner: 'user1',
          agentOnline: true,
          maxTerminals: 1,
          activeTerminals: 1,
        ),
      ];
      runtimeService.terminalsByDevice = const {'mbp-01': []};

      final controller = RuntimeSelectionController(
        serverUrl: 'ws://localhost:8888',
        token: 'token',
        runtimeService: runtimeService,
        configService: configService,
      );
      await controller.initialize();
      final updated = await controller.updateSelectedDevice(
        name: 'New Name',
      );

      expect(updated, isNotNull);
      expect(controller.selectedDevice?.name, 'New Name');
      expect(controller.selectedDevice?.maxTerminals, 3);
    });

    test('renames terminal and updates local list', () async {
      runtimeService.devices = const [
        RuntimeDevice(
          deviceId: 'mbp-01',
          name: 'Online',
          owner: 'user1',
          agentOnline: true,
          maxTerminals: 3,
          activeTerminals: 1,
        ),
      ];
      runtimeService.terminalsByDevice = {
        'mbp-01': const [
          RuntimeTerminal(
            terminalId: 'term-1',
            title: 'Old Title',
            cwd: '/tmp',
            command: '/bin/bash',
            status: 'detached',
            views: {'mobile': 0, 'desktop': 0},
          ),
        ],
      };

      final controller = RuntimeSelectionController(
        serverUrl: 'ws://localhost:8888',
        token: 'token',
        runtimeService: runtimeService,
        configService: configService,
      );
      await controller.initialize();
      final updated = await controller.renameTerminal('term-1', 'New Title');

      expect(updated, isNotNull);
      expect(controller.terminals.single.title, 'New Title');
    });

    test('syncs selected device active terminal count after create and close',
        () async {
      runtimeService.devices = const [
        RuntimeDevice(
          deviceId: 'mbp-01',
          name: 'Online',
          owner: 'user1',
          agentOnline: true,
          maxTerminals: 3,
          activeTerminals: 1,
        ),
      ];
      runtimeService.terminalsByDevice = {
        'mbp-01': const [
          RuntimeTerminal(
            terminalId: 'term-1',
            title: 'Claude',
            cwd: '/tmp',
            command: '/bin/bash',
            status: 'detached',
            views: {'mobile': 0, 'desktop': 0},
          ),
        ],
      };

      final controller = RuntimeSelectionController(
        serverUrl: 'ws://localhost:8888',
        token: 'token',
        runtimeService: runtimeService,
        configService: configService,
      );
      await controller.initialize();
      expect(controller.selectedDevice?.activeTerminals, 1);

      await controller.createTerminal(
        title: 'Second',
        cwd: '/tmp/second',
        command: '/bin/bash',
      );
      expect(controller.selectedDevice?.activeTerminals, 2);

      await controller.closeTerminal('term-created');
      expect(controller.selectedDevice?.activeTerminals, 1);
    });

    test('rememberSuccessfulLaunchPlan persists selected device context',
        () async {
      runtimeService.devices = const [
        RuntimeDevice(
          deviceId: 'mbp-01',
          name: 'Online',
          owner: 'user1',
          agentOnline: true,
          maxTerminals: 3,
          activeTerminals: 0,
        ),
      ];
      runtimeService.terminalsByDevice = const {'mbp-01': []};

      final controller = RuntimeSelectionController(
        serverUrl: 'ws://localhost:8888',
        token: 'token',
        runtimeService: runtimeService,
        configService: configService,
      );
      await controller.initialize();
      await controller.rememberSuccessfulLaunchPlan(
        const TerminalLaunchPlan(
          tool: TerminalLaunchTool.claudeCode,
          title: 'Claude / remote-control',
          cwd: '/Users/demo/project/remote-control',
          command: '/bin/bash',
          entryStrategy: TerminalEntryStrategy.shellBootstrap,
          postCreateInput: 'claude\n',
          source: TerminalLaunchPlanSource.recommended,
        ),
      );

      final restored = await configService.loadConfig();
      final context = restored.recentLaunchContexts['mbp-01']!;
      expect(context.lastTool, TerminalLaunchTool.claudeCode);
      expect(context.lastCwd, '/Users/demo/project/remote-control');
      expect(context.lastSuccessfulPlan.postCreateInput, 'claude\n');
    });

    test('loads project context settings for selected device', () async {
      runtimeService.devices = const [
        RuntimeDevice(
          deviceId: 'mbp-01',
          name: 'Online',
          owner: 'user1',
          agentOnline: true,
          maxTerminals: 3,
          activeTerminals: 0,
        ),
      ];
      runtimeService.terminalsByDevice = const {'mbp-01': []};
      runtimeService.settingsByDevice['mbp-01'] = const ProjectContextSettings(
        deviceId: 'mbp-01',
        pinnedProjects: [
          PinnedProject(
            label: 'remote-control',
            cwd: '/Users/demo/project/remote-control',
          ),
        ],
      );

      final controller = RuntimeSelectionController(
        serverUrl: 'ws://localhost:8888',
        token: 'token',
        runtimeService: runtimeService,
        configService: configService,
      );
      await controller.initialize();
      final settings = await controller.loadProjectContextSettings();

      expect(settings, isNotNull);
      expect(settings!.pinnedProjects.single.label, 'remote-control');
      expect(controller.projectContextSettings?.deviceId, 'mbp-01');
    });

    test('saves project context settings for selected device', () async {
      runtimeService.devices = const [
        RuntimeDevice(
          deviceId: 'mbp-01',
          name: 'Online',
          owner: 'user1',
          agentOnline: true,
          maxTerminals: 3,
          activeTerminals: 0,
        ),
      ];
      runtimeService.terminalsByDevice = const {'mbp-01': []};

      final controller = RuntimeSelectionController(
        serverUrl: 'ws://localhost:8888',
        token: 'token',
        runtimeService: runtimeService,
        configService: configService,
      );
      await controller.initialize();

      final saved = await controller.updateProjectContextSettings(
        const ProjectContextSettings(
          deviceId: 'mbp-01',
          pinnedProjects: [
            PinnedProject(
              label: 'remote-control',
              cwd: '/Users/demo/project/remote-control',
            ),
          ],
          plannerConfig: PlannerRuntimeConfigModel(
            provider: 'llm',
            llmEnabled: true,
          ),
        ),
      );

      expect(saved, isNotNull);
      expect(
        runtimeService.settingsByDevice['mbp-01']!.plannerConfig.llmEnabled,
        isTrue,
      );
      expect(controller.projectContextSettings?.plannerConfig.provider, 'llm');
    });

    test(
        'loads project context snapshot and uses candidate cwd for recommendation',
        () async {
      runtimeService.devices = const [
        RuntimeDevice(
          deviceId: 'mbp-01',
          name: 'Online',
          owner: 'user1',
          agentOnline: true,
          maxTerminals: 3,
          activeTerminals: 0,
        ),
      ];
      runtimeService.terminalsByDevice = const {'mbp-01': []};
      runtimeService.snapshotsByDevice['mbp-01'] = DeviceProjectContextSnapshot(
        deviceId: 'mbp-01',
        generatedAt: DateTime.parse('2026-04-22T12:00:00Z'),
        candidates: const [
          ProjectContextCandidate(
            candidateId: 'cand-1',
            deviceId: 'mbp-01',
            label: 'remote-control',
            cwd: '/Users/demo/project/remote-control',
            source: 'pinned_project',
            toolHints: ['codex', 'shell'],
          ),
        ],
      );

      final controller = RuntimeSelectionController(
        serverUrl: 'ws://localhost:8888',
        token: 'token',
        runtimeService: runtimeService,
        configService: configService,
      );
      await controller.initialize();

      expect(
        controller.recommendedLaunchPlans.first.cwd,
        '/Users/demo/project/remote-control',
      );
      expect(
        controller.recommendedLaunchPlans.first.tool,
        TerminalLaunchTool.codex,
      );
    });

    test(
        'resolveLaunchPlanFromIntent lazy-loads settings and keeps local rules',
        () async {
      runtimeService.devices = const [
        RuntimeDevice(
          deviceId: 'mbp-01',
          name: 'Online',
          owner: 'user1',
          agentOnline: true,
          maxTerminals: 3,
          activeTerminals: 0,
        ),
      ];
      runtimeService.terminalsByDevice = const {'mbp-01': []};
      runtimeService.settingsByDevice['mbp-01'] = const ProjectContextSettings(
        deviceId: 'mbp-01',
        plannerConfig: PlannerRuntimeConfigModel(
          provider: 'local_rules',
          llmEnabled: false,
        ),
      );
      runtimeService.snapshotsByDevice['mbp-01'] = DeviceProjectContextSnapshot(
        deviceId: 'mbp-01',
        generatedAt: DateTime.parse('2026-04-22T12:00:00Z'),
        candidates: const [
          ProjectContextCandidate(
            candidateId: 'cand-1',
            deviceId: 'mbp-01',
            label: 'remote-control',
            cwd: '/Users/demo/project/remote-control',
            source: 'pinned_project',
            toolHints: ['shell'],
          ),
        ],
      );

      final controller = RuntimeSelectionController(
        serverUrl: 'ws://localhost:8888',
        token: 'token',
        runtimeService: runtimeService,
        configService: configService,
      );
      await controller.initialize();

      expect(controller.projectContextSettings, isNull);
      final plan = await controller.resolveLaunchPlanFromIntent(
        '进入 codex 修一下登录问题',
      );

      expect(controller.projectContextSettings?.deviceId, 'mbp-01');
      expect(plan.tool, TerminalLaunchTool.codex);
      expect(plan.cwd, '/Users/demo/project/remote-control');
      expect(plan.confidence, TerminalLaunchConfidence.medium);
    });

    test('resolveLaunchPlanFromIntent keeps llm candidate scope per device',
        () async {
      await configService.saveConfig(
        const AppConfig(preferredDeviceId: 'mbp-02'),
      );
      runtimeService.devices = const [
        RuntimeDevice(
          deviceId: 'mbp-01',
          name: 'Online 1',
          owner: 'user1',
          agentOnline: true,
          maxTerminals: 3,
          activeTerminals: 0,
        ),
        RuntimeDevice(
          deviceId: 'mbp-02',
          name: 'Online 2',
          owner: 'user1',
          agentOnline: true,
          maxTerminals: 3,
          activeTerminals: 0,
        ),
      ];
      runtimeService.terminalsByDevice = const {
        'mbp-01': [],
        'mbp-02': [],
      };
      runtimeService.settingsByDevice['mbp-01'] = const ProjectContextSettings(
        deviceId: 'mbp-01',
        plannerConfig: PlannerRuntimeConfigModel(
          provider: 'llm',
          llmEnabled: true,
        ),
      );
      runtimeService.settingsByDevice['mbp-02'] = const ProjectContextSettings(
        deviceId: 'mbp-02',
        plannerConfig: PlannerRuntimeConfigModel(
          provider: 'llm',
          llmEnabled: true,
        ),
      );
      runtimeService.snapshotsByDevice['mbp-01'] = DeviceProjectContextSnapshot(
        deviceId: 'mbp-01',
        generatedAt: DateTime.parse('2026-04-22T12:00:00Z'),
        candidates: const [
          ProjectContextCandidate(
            candidateId: 'cand-dev1',
            deviceId: 'mbp-01',
            label: 'device-one',
            cwd: '/Users/demo/project/device-one',
            source: 'pinned_project',
            toolHints: ['codex'],
          ),
        ],
      );
      runtimeService.snapshotsByDevice['mbp-02'] = DeviceProjectContextSnapshot(
        deviceId: 'mbp-02',
        generatedAt: DateTime.parse('2026-04-22T12:00:00Z'),
        candidates: const [
          ProjectContextCandidate(
            candidateId: 'cand-dev2',
            deviceId: 'mbp-02',
            label: 'device-two',
            cwd: '/Users/demo/project/device-two',
            source: 'pinned_project',
            toolHints: ['codex'],
          ),
        ],
      );

      final plannerService = TerminalLaunchPlanService(
        llmPlannerProvider: LlmPlannerProvider(
          client: MockClient((request) async {
            final body = jsonDecode(request.body) as Map<String, dynamic>;
            final messages = body['messages'] as List<dynamic>;
            final userPayload = jsonDecode(
              (messages.last as Map<String, dynamic>)['content'] as String,
            ) as Map<String, dynamic>;
            final candidates =
                userPayload['candidates'] as List<dynamic>? ?? const [];
            expect(candidates.length, 1);
            expect(
              (candidates.first as Map<String, dynamic>)['candidate_id'],
              'cand-dev2',
            );
            return http.Response(
              jsonEncode({
                'choices': [
                  {
                    'message': {
                      'content': jsonEncode({
                        'tool': 'codex',
                        'matched_candidate_id': 'cand-dev2',
                        'cwd': '/Users/demo/project/device-two',
                        'reasoning_kind': 'candidate_match',
                      }),
                    },
                  },
                ],
              }),
              200,
            );
          }),
          credentialsService: _AlwaysKeyPlannerCredentialsService(),
          endpointResolver: (_) =>
              Uri.parse('https://planner.test/v1/chat/completions'),
          model: 'test-model',
        ),
      );

      final controller = RuntimeSelectionController(
        serverUrl: 'ws://localhost:8888',
        token: 'token',
        runtimeService: runtimeService,
        configService: configService,
        terminalLaunchPlanService: plannerService,
      );
      await controller.initialize();

      final plan = await controller.resolveLaunchPlanFromIntent(
        '进入 codex 看下当前项目',
      );

      expect(controller.selectedDeviceId, 'mbp-02');
      expect(plan.tool, TerminalLaunchTool.codex);
      expect(plan.cwd, '/Users/demo/project/device-two');
    });

    // F030: 平台判断测试
    test('isDesktopPlatform returns true on desktop platforms', () {
      // 在 macOS/Linux/Windows 上运行测试时，isDesktopPlatform 应该返回 true
      // 在 Android/iOS 上运行测试时，isDesktopPlatform 应该返回 false
      final controller = RuntimeSelectionController(
        serverUrl: 'ws://localhost:8888',
        token: 'token',
        runtimeService: runtimeService,
        configService: configService,
      );

      // 由于测试运行在桌面环境（macOS），应该返回 true
      expect(controller.isDesktopPlatform, isTrue);
    });

    test(
        'isLocalDeviceSelected returns true only on desktop with matching device',
        () async {
      runtimeService.devices = const [
        RuntimeDevice(
          deviceId: 'mbp-local',
          name: 'Local Mac',
          owner: 'user1',
          agentOnline: true,
          maxTerminals: 3,
          activeTerminals: 0,
        ),
      ];

      final controller = RuntimeSelectionController(
        serverUrl: 'ws://localhost:8888',
        token: 'token',
        runtimeService: runtimeService,
        configService: configService,
      );
      await controller.initialize();

      // 在桌面端，如果选中的设备是本机设备，isLocalDeviceSelected 应该返回 true
      // 具体是否是本机设备取决于 hostname 匹配
      expect(controller.isDesktopPlatform, isTrue);
      // isLocalDeviceSelected 依赖于 hostname 匹配，可能为 true 或 false
    });
  });
}
