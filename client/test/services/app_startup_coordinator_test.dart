import 'package:flutter_test/flutter_test.dart';
import 'package:rc_client/models/config.dart';
import 'package:rc_client/models/runtime_device.dart';
import 'package:rc_client/models/runtime_terminal.dart';
import 'package:rc_client/services/app_startup_coordinator.dart';
import 'package:rc_client/services/auth_service.dart';
import 'package:rc_client/services/config_service.dart';
import 'package:rc_client/services/desktop/desktop_agent_manager.dart';
import 'package:rc_client/services/desktop/desktop_agent_supervisor.dart';
import 'package:rc_client/services/environment_service.dart';
import 'package:rc_client/services/runtime_device_service.dart';
import 'package:shared_preferences/shared_preferences.dart';

class _FakeAuthService extends AuthService {
  _FakeAuthService() : super(serverUrl: 'ws://localhost:8888');

  Map<String, String>? savedSession;
  Map<String, String>? savedCredentials;
  Object? savedSessionError;
  Object? savedCredentialsError;
  Object? loginError;
  Map<String, dynamic> loginResult = <String, dynamic>{
    'token': 'fresh-token',
    'session_id': 'fresh-session',
  };

  int getSavedSessionCallCount = 0;
  int getSavedCredentialsCallCount = 0;
  int loginCallCount = 0;

  @override
  Future<Map<String, String>?> getSavedSession({
    bool includeRefreshToken = false,
  }) async {
    getSavedSessionCallCount += 1;
    if (savedSessionError != null) {
      throw savedSessionError!;
    }
    return savedSession;
  }

  @override
  Future<Map<String, String>?> getSavedCredentials() async {
    getSavedCredentialsCallCount += 1;
    if (savedCredentialsError != null) {
      throw savedCredentialsError!;
    }
    return savedCredentials;
  }

  @override
  Future<Map<String, dynamic>> login(String username, String password) async {
    loginCallCount += 1;
    if (loginError != null) {
      throw loginError!;
    }
    return loginResult;
  }
}

class _FakeRuntimeDeviceService extends RuntimeDeviceService {
  _FakeRuntimeDeviceService() : super(serverUrl: 'ws://localhost:8888');

  Object? listDevicesError;
  int listDevicesErrorCount = 0;
  Object? listTerminalsError;
  int listTerminalsErrorCount = 0;
  List<RuntimeTerminal> terminals = const <RuntimeTerminal>[];
  List<RuntimeDevice> devices = const <RuntimeDevice>[
    RuntimeDevice(
      deviceId: 'device-1',
      name: 'mac',
      owner: 'test',
      agentOnline: true,
      maxTerminals: 3,
      activeTerminals: 0,
    ),
  ];

  int listDevicesCallCount = 0;
  int listTerminalsCallCount = 0;
  final List<String> closedTerminalIds = <String>[];

  @override
  Future<List<RuntimeDevice>> listDevices(String token) async {
    listDevicesCallCount += 1;
    if (listDevicesError != null && listDevicesErrorCount > 0) {
      listDevicesErrorCount -= 1;
      throw listDevicesError!;
    }
    return devices;
  }

  @override
  Future<List<RuntimeTerminal>> listTerminals(
      String token, String deviceId) async {
    listTerminalsCallCount += 1;
    if (listTerminalsError != null && listTerminalsErrorCount > 0) {
      listTerminalsErrorCount -= 1;
      throw listTerminalsError!;
    }
    return terminals;
  }

  @override
  Future<RuntimeTerminal> closeTerminal(
    String token,
    String deviceId,
    String terminalId,
  ) async {
    closedTerminalIds.add(terminalId);
    final terminal =
        terminals.firstWhere((item) => item.terminalId == terminalId);
    return terminal.copyWith(status: 'closed');
  }
}

class _FakeConfigService extends ConfigService {
  _FakeConfigService(this.config);

  final AppConfig config;

  @override
  Future<AppConfig> loadConfig() async => config;
}

class _FakeSupervisor extends DesktopAgentSupervisor {
  @override
  bool get supported => false;
}

class _FakeDesktopAgentManager extends DesktopAgentManager {
  _FakeDesktopAgentManager()
      : super(
          supervisor: _FakeSupervisor(),
        );

  int onAppStartCallCount = 0;
  String? lastToken;
  String? lastUsername;
  String? lastDeviceId;

  @override
  Future<void> onAppStart({
    required String serverUrl,
    required String token,
    required String username,
    required String deviceId,
  }) async {
    onAppStartCallCount += 1;
    lastToken = token;
    lastUsername = username;
    lastDeviceId = deviceId;
  }
}

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues({});
    EnvironmentService.setInstance(
      EnvironmentService(debugModeProvider: () => true),
    );
  });

  test(
      'session valid and password unavailable still restores workspace directly',
      () async {
    SharedPreferences.setMockInitialValues({
      'rc_username': 'testuser',
    });
    final authService = _FakeAuthService()
      ..savedSession = <String, String>{
        'token': 'saved-token',
        'session_id': 'saved-session',
      }
      ..savedCredentialsError = Exception('keychain unavailable');
    final runtimeService = _FakeRuntimeDeviceService();
    final agentManager = _FakeDesktopAgentManager();
    final coordinator = AppStartupCoordinator(
      serverUrl: 'ws://localhost:8888',
      authService: authService,
      runtimeService: runtimeService,
      configService: _FakeConfigService(const AppConfig()),
      isDesktopPlatform: true,
    );

    final result = await coordinator.restore(agentManager: agentManager);

    expect(result.destination, AppStartupDestination.workspace);
    expect(result.token, 'saved-token');
    expect(result.initialDevices, isNotEmpty);
    expect(authService.getSavedCredentialsCallCount, 0);
    expect(runtimeService.listDevicesCallCount, 1);
    expect(agentManager.onAppStartCallCount, 1);
    expect(agentManager.lastUsername, 'testuser');
  });

  test('invalid session falls back to password auto login', () async {
    SharedPreferences.setMockInitialValues({
      'rc_username': 'testuser',
    });
    final authService = _FakeAuthService()
      ..savedSession = <String, String>{
        'token': 'expired-token',
        'session_id': 'saved-session',
      }
      ..savedCredentials = <String, String>{
        'username': 'testuser',
        'password': 'testpass',
      }
      ..loginResult = <String, dynamic>{
        'token': 'fresh-token',
        'session_id': 'fresh-session',
      };
    final runtimeService = _FakeRuntimeDeviceService()
      ..listTerminalsError = AuthException(AuthErrorCode.tokenInvalid, '认证信息无效')
      ..listTerminalsErrorCount = 1
      ..terminals = const <RuntimeTerminal>[
        RuntimeTerminal(
          terminalId: 'term-recoverable',
          title: 'Claude',
          cwd: '~',
          command: '/bin/bash',
          status: 'detached',
          views: {'mobile': 0, 'desktop': 0},
        ),
      ];
    final agentManager = _FakeDesktopAgentManager();
    final coordinator = AppStartupCoordinator(
      serverUrl: 'ws://localhost:8888',
      authService: authService,
      runtimeService: runtimeService,
      configService: _FakeConfigService(const AppConfig()),
      isDesktopPlatform: true,
    );

    final result = await coordinator.restore(agentManager: agentManager);

    expect(result.destination, AppStartupDestination.workspace);
    expect(result.token, 'fresh-token');
    expect(result.initialDevices, isNotEmpty);
    expect(authService.getSavedCredentialsCallCount, 1);
    expect(authService.loginCallCount, 1);
    expect(runtimeService.listTerminalsCallCount, 2);
    expect(runtimeService.closedTerminalIds, <String>['term-recoverable']);
    expect(runtimeService.listDevicesCallCount, 1);
    expect(agentManager.onAppStartCallCount, 1);
    expect(agentManager.lastDeviceId, 'fresh-session');
  });

  test(
      'savedCredentials throwing does not block valid session restore when username exists',
      () async {
    SharedPreferences.setMockInitialValues({
      'rc_username': 'testuser',
    });
    final authService = _FakeAuthService()
      ..savedSession = <String, String>{
        'token': 'saved-token',
        'session_id': 'saved-session',
      }
      ..savedCredentialsError = StateError('keychain denied');
    final runtimeService = _FakeRuntimeDeviceService();
    final agentManager = _FakeDesktopAgentManager();
    final coordinator = AppStartupCoordinator(
      serverUrl: 'ws://localhost:8888',
      authService: authService,
      runtimeService: runtimeService,
      configService: _FakeConfigService(const AppConfig()),
      isDesktopPlatform: true,
    );

    final result = await coordinator.restore(agentManager: agentManager);

    expect(result.destination, AppStartupDestination.workspace);
    expect(result.token, 'saved-token');
    expect(authService.getSavedCredentialsCallCount, 0);
    expect(agentManager.onAppStartCallCount, 1);
  });

  test('desktop startup closes lingering terminals when background keep is off',
      () async {
    SharedPreferences.setMockInitialValues({
      'rc_username': 'testuser',
    });
    final authService = _FakeAuthService()
      ..savedSession = <String, String>{
        'token': 'saved-token',
        'session_id': 'saved-session',
      };
    final runtimeService = _FakeRuntimeDeviceService()
      ..terminals = const <RuntimeTerminal>[
        RuntimeTerminal(
          terminalId: 'term-detached',
          title: 'Claude',
          cwd: '~',
          command: '/bin/bash',
          status: 'detached',
          views: {'mobile': 0, 'desktop': 0},
        ),
        RuntimeTerminal(
          terminalId: 'term-live-elsewhere',
          title: 'Shared',
          cwd: '~',
          command: '/bin/bash',
          status: 'live',
          views: {'mobile': 0, 'desktop': 1},
        ),
      ];
    final agentManager = _FakeDesktopAgentManager();
    final coordinator = AppStartupCoordinator(
      serverUrl: 'ws://localhost:8888',
      authService: authService,
      runtimeService: runtimeService,
      configService: _FakeConfigService(const AppConfig()),
      isDesktopPlatform: true,
    );

    final result = await coordinator.restore(agentManager: agentManager);

    expect(result.destination, AppStartupDestination.workspace);
    expect(runtimeService.listTerminalsCallCount, 1);
    expect(runtimeService.closedTerminalIds,
        <String>['term-detached', 'term-live-elsewhere']);
    expect(runtimeService.listDevicesCallCount, 1);
  });
}
