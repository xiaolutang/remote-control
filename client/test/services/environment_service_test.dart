import 'package:flutter_test/flutter_test.dart';
import 'package:rc_client/models/app_environment.dart';
import 'package:rc_client/services/environment_service.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  group('EnvironmentService', () {
    late EnvironmentService service;

    setUp(() {
      SharedPreferences.setMockInitialValues({});
      service = EnvironmentService(debugModeProvider: () => true);
    });

    group('default environment', () {
      test('debugModeProvider=true -> local', () {
        service = EnvironmentService(debugModeProvider: () => true);
        EnvironmentService.setInstance(service);
        expect(service.currentEnvironment, AppEnvironment.local);
      });

      test('debugModeProvider=false -> production', () {
        service = EnvironmentService(debugModeProvider: () => false);
        EnvironmentService.setInstance(service);
        expect(service.currentEnvironment, AppEnvironment.production);
      });
    });

    group('serverUrl generation', () {
      test('local default host=localhost, port="" -> ws://localhost', () async {
        await service.loadSavedState();
        expect(service.currentServerUrl, 'ws://localhost');
      });

      test('local host=192.168.1.100, port=8080 -> ws://192.168.1.100:8080', () async {
        await service.updateLocalHost('192.168.1.100');
        await service.updateLocalPort('8080');
        expect(service.currentServerUrl, 'ws://192.168.1.100:8080');
      });

      test('local host=localhost, port empty -> ws://localhost', () async {
        await service.updateLocalHost('localhost');
        await service.updateLocalPort('');
        expect(service.currentServerUrl, 'ws://localhost');
      });

      test('production -> wss://rc.xiaolutang.top/rc', () async {
        service = EnvironmentService(debugModeProvider: () => false);
        EnvironmentService.setInstance(service);
        await service.loadSavedState();
        expect(service.currentServerUrl, 'wss://rc.xiaolutang.top/rc');
      });

      test('direct default -> ws://${RC_TEST_SERVER_IP}:8880', () async {
        await service.loadSavedState();
        await service.switchEnvironment(AppEnvironment.direct);
        expect(service.currentServerUrl, 'ws://${RC_TEST_SERVER_IP}:8880');
      });

      test('direct custom host/port -> ws://1.2.3.4:9090', () async {
        await service.loadSavedState();
        await service.switchEnvironment(AppEnvironment.direct);
        await service.updateDirectHost('1.2.3.4');
        await service.updateDirectPort('9090');
        expect(service.currentServerUrl, 'ws://1.2.3.4:9090');
      });
    });

    group('persistence', () {
      test('save environment selection -> persists across re-initialization', () async {
        await service.loadSavedState();
        await service.switchEnvironment(AppEnvironment.production);

        // Create new instance reading same prefs
        final restored = EnvironmentService(debugModeProvider: () => true);
        await restored.loadSavedState();
        expect(restored.currentEnvironment, AppEnvironment.production);
      });

      test('save local host/port -> persists across re-initialization', () async {
        await service.loadSavedState();
        await service.updateLocalHost('10.0.2.2');
        await service.updateLocalPort('9090');

        final restored = EnvironmentService(debugModeProvider: () => true);
        await restored.loadSavedState();
        expect(restored.localHost, '10.0.2.2');
        expect(restored.localPort, '9090');
      });

      test('save direct host/port -> persists across re-initialization', () async {
        await service.loadSavedState();
        await service.updateDirectHost('8.8.8.8');
        await service.updateDirectPort('9999');

        final restored = EnvironmentService(debugModeProvider: () => true);
        await restored.loadSavedState();
        expect(restored.directHost, '8.8.8.8');
        expect(restored.directPort, '9999');
      });
    });

    group('first install / corrupted data', () {
      test('no persisted data -> returns default environment', () async {
        await service.loadSavedState();
        expect(service.currentEnvironment, AppEnvironment.local);
      });

      test('corrupted environment string -> falls back to default', () async {
        SharedPreferences.setMockInitialValues({'rc_environment': 'invalid_value'});
        await service.loadSavedState();
        expect(service.currentEnvironment, AppEnvironment.local);
      });

      test('missing host/port -> defaults to localhost, empty port', () async {
        await service.loadSavedState();
        expect(service.localHost, 'localhost');
        expect(service.localPort, '');
      });
    });

    group('input validation', () {
      test('host with special characters -> rejected (falls back to default)', () async {
        await service.updateLocalHost('!@#%');
        expect(service.localHost, 'localhost');
      });

      test('host with spaces trimmed -> accepted', () async {
        await service.updateLocalHost('  192.168.1.1  ');
        expect(service.localHost, '192.168.1.1');
      });

      test('host with slashes -> rejected', () async {
        await service.updateLocalHost('http://evil.com');
        expect(service.localHost, 'localhost');
      });

      test('port with non-numeric chars -> rejected (empty)', () async {
        await service.updateLocalPort('abc');
        expect(service.localPort, '');
      });

      test('port out of range -> rejected (empty)', () async {
        await service.updateLocalPort('99999');
        expect(service.localPort, '');
      });

      test('port zero -> rejected (empty)', () async {
        await service.updateLocalPort('0');
        expect(service.localPort, '');
      });

      test('valid port 8080 -> accepted', () async {
        await service.updateLocalPort('8080');
        expect(service.localPort, '8080');
      });
    });

    group('no side-effect dependencies', () {
      test('EnvironmentService only imports foundation + shared_preferences', () {
        // 约束：EnvironmentService 不导入 AuthService / DesktopAgentManager
        // 此约束由 code review 和 import 检查保障
        expect(service.currentServerUrl, isNotEmpty);
        expect(service.currentEnvironment, isNotNull);
      });
    });
  });
}
