import 'package:flutter_test/flutter_test.dart';
import 'package:rc_client/models/runtime_device.dart';
import 'package:rc_client/services/app_startup_coordinator.dart';
import 'package:rc_client/services/auth_service.dart';
import 'package:rc_client/services/desktop_agent_manager.dart';
import 'package:rc_client/services/desktop_agent_supervisor.dart';
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

  @override
  Future<List<RuntimeDevice>> listDevices(String token) async {
    listDevicesCallCount += 1;
    if (listDevicesError != null) {
      throw listDevicesError!;
    }
    return devices;
  }
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
      ..listDevicesError = AuthException(AuthErrorCode.tokenInvalid, '认证信息无效');
    final agentManager = _FakeDesktopAgentManager();
    final coordinator = AppStartupCoordinator(
      serverUrl: 'ws://localhost:8888',
      authService: authService,
      runtimeService: runtimeService,
    );

    final result = await coordinator.restore(agentManager: agentManager);

    expect(result.destination, AppStartupDestination.workspace);
    expect(result.token, 'fresh-token');
    expect(authService.getSavedCredentialsCallCount, 1);
    expect(authService.loginCallCount, 1);
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
    );

    final result = await coordinator.restore(agentManager: agentManager);

    expect(result.destination, AppStartupDestination.workspace);
    expect(result.token, 'saved-token');
    expect(authService.getSavedCredentialsCallCount, 0);
    expect(agentManager.onAppStartCallCount, 1);
  });
}
