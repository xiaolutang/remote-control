import 'package:flutter_test/flutter_test.dart';
import 'package:rc_client/models/config.dart';
import 'package:rc_client/models/runtime_terminal.dart';
import 'package:rc_client/services/config_service.dart';
import 'package:rc_client/services/desktop_startup_terminal_cleanup_service.dart';
import 'package:rc_client/services/environment_service.dart';
import 'package:rc_client/services/runtime_device_service.dart';

class _FakeRuntimeDeviceService extends RuntimeDeviceService {
  _FakeRuntimeDeviceService() : super(serverUrl: 'ws://localhost:8888');

  List<RuntimeTerminal> terminals = const <RuntimeTerminal>[];
  int listTerminalsCallCount = 0;
  final List<String> closedTerminalIds = <String>[];
  final Set<String> failingTerminalIds = <String>{};

  @override
  Future<List<RuntimeTerminal>> listTerminals(
    String token,
    String deviceId,
  ) async {
    listTerminalsCallCount += 1;
    return terminals;
  }

  @override
  Future<RuntimeTerminal> closeTerminal(
    String token,
    String deviceId,
    String terminalId,
  ) async {
    if (failingTerminalIds.contains(terminalId)) {
      throw StateError('close failed: $terminalId');
    }
    closedTerminalIds.add(terminalId);
    return terminals
        .firstWhere((terminal) => terminal.terminalId == terminalId);
  }
}

class _FakeConfigService extends ConfigService {
  _FakeConfigService(this.config);

  final AppConfig config;

  @override
  Future<AppConfig> loadConfig() async => config;
}

void main() {
  setUp(() {
    EnvironmentService.setInstance(
      EnvironmentService(debugModeProvider: () => true),
    );
  });

  test('does nothing when desktop exit policy keeps agent in background',
      () async {
    final runtimeService = _FakeRuntimeDeviceService()
      ..terminals = const <RuntimeTerminal>[
        RuntimeTerminal(
          terminalId: 'term-1',
          title: 'Claude',
          cwd: '~',
          command: '/bin/bash',
          status: 'detached',
          views: {'desktop': 0},
        ),
      ];
    final service = DesktopStartupTerminalCleanupService(
      runtimeService: runtimeService,
      configService: _FakeConfigService(const AppConfig(
        desktopExitPolicy: DesktopExitPolicy.keepAgentRunningInBackground,
      )),
      isDesktopPlatform: true,
    );

    await service.cleanup(token: 'token', deviceId: 'device');

    expect(runtimeService.listTerminalsCallCount, 0);
    expect(runtimeService.closedTerminalIds, isEmpty);
  });

  test('closes every non-closed lingering terminal when stop-on-exit is active',
      () async {
    final runtimeService = _FakeRuntimeDeviceService()
      ..terminals = const <RuntimeTerminal>[
        RuntimeTerminal(
          terminalId: 'term-detached',
          title: 'Detached',
          cwd: '~',
          command: '/bin/bash',
          status: 'detached',
          views: {'desktop': 0},
        ),
        RuntimeTerminal(
          terminalId: 'term-live',
          title: 'Live elsewhere',
          cwd: '~',
          command: '/bin/bash',
          status: 'live',
          views: {'desktop': 1},
        ),
        RuntimeTerminal(
          terminalId: 'term-closed',
          title: 'Closed',
          cwd: '~',
          command: '/bin/bash',
          status: 'closed',
          views: {'desktop': 0},
        ),
      ];
    final service = DesktopStartupTerminalCleanupService(
      runtimeService: runtimeService,
      configService: _FakeConfigService(const AppConfig()),
      isDesktopPlatform: true,
    );

    await service.cleanup(token: 'token', deviceId: 'device');

    expect(runtimeService.listTerminalsCallCount, 1);
    expect(
      runtimeService.closedTerminalIds,
      <String>['term-detached', 'term-live'],
    );
  });

  test('cleanup swallows individual close failures', () async {
    final runtimeService = _FakeRuntimeDeviceService()
      ..terminals = const <RuntimeTerminal>[
        RuntimeTerminal(
          terminalId: 'term-fail',
          title: 'Fail',
          cwd: '~',
          command: '/bin/bash',
          status: 'detached',
          views: {'desktop': 0},
        ),
        RuntimeTerminal(
          terminalId: 'term-ok',
          title: 'OK',
          cwd: '~',
          command: '/bin/bash',
          status: 'detached',
          views: {'desktop': 0},
        ),
      ]
      ..failingTerminalIds.add('term-fail');
    final service = DesktopStartupTerminalCleanupService(
      runtimeService: runtimeService,
      configService: _FakeConfigService(const AppConfig()),
      isDesktopPlatform: true,
    );

    await service.cleanup(token: 'token', deviceId: 'device');

    expect(runtimeService.listTerminalsCallCount, 1);
    expect(runtimeService.closedTerminalIds, <String>['term-ok']);
  });
}
