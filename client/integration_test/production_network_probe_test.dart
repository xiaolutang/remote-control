import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';

import '../test_support/production_probe.dart';

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  const bool runInHarness = bool.fromEnvironment(
    'RUN_PRODUCTION_NETWORK_PROBE_INTEGRATION',
    defaultValue: false,
  );
  const bool runRuntimeInHarness = bool.fromEnvironment(
    'RUN_PRODUCTION_RUNTIME_PROBE_INTEGRATION',
    defaultValue: false,
  );

  group('Production network e2e', () {
    final serverIp = (_readConfig(
      key: 'RC_TEST_SERVER_IP',
      fallback: '',
    )).trim();
    final username = (_readConfig(
      key: 'RC_TEST_USERNAME',
      fallback: 'prod_test',
    )).trim();
    final password = (_readConfig(
      key: 'RC_TEST_PASSWORD',
      fallback: 'test123456',
    )).trim();
    final runtimeDeviceId = (_readConfig(
      key: 'RC_TEST_RUNTIME_DEVICE_ID',
      fallback: '',
    )).trim();

    testWidgets(
      'validates deterministic ip+host health, login, and websocket auth',
      (_) async {
        expect(
          serverIp,
          isNotEmpty,
          reason: 'RC_TEST_SERVER_IP is required for production e2e. '
              'This test only gates the deterministic IP + Host path.',
        );

        final result = await runProductionProbe(
          ProductionProbeConfig(
            serverIp: serverIp,
            host: 'rc.xiaolutang.top',
            username: username,
            password: password,
          ),
          log: debugPrint,
        );

        expect(result.healthStatusCode, 200);
        expect(result.loginStatusCode, 200);
        expect(result.connectedMessage['type'], 'connected');
        expect(result.connectedMessage['view'], 'mobile');
        expect(result.connectedMessage['device_id'], isNotNull);
      },
      skip: !runInHarness,
    );

    testWidgets(
      'validates online runtime terminal create and cleanup when device is available',
      (_) async {
        expect(
          serverIp,
          isNotEmpty,
          reason: 'RC_TEST_SERVER_IP is required for production runtime e2e.',
        );

        final result = await runProductionProbe(
          ProductionProbeConfig(
            serverIp: serverIp,
            host: 'rc.xiaolutang.top',
            username: username,
            password: password,
            probeRuntimeTerminal: true,
            requireOnlineDevice: true,
            runtimeDeviceId: runtimeDeviceId.isEmpty ? null : runtimeDeviceId,
          ),
          log: debugPrint,
        );

        final runtime = result.runtimeTerminalResult;
        expect(runtime, isNotNull);
        expect(runtime!.executed, isTrue);
        expect(runtime.skipped, isFalse);
        expect(runtime.deviceId, isNotEmpty);
        expect(runtime.createdTerminalId, isNotEmpty);
        expect(runtime.closedStatus, 'closed');
      },
      skip: !runRuntimeInHarness,
    );
  });
}

String _readConfig({
  required String key,
  required String fallback,
}) {
  switch (key) {
    case 'RC_TEST_SERVER_IP':
      return const String.fromEnvironment(
        'RC_TEST_SERVER_IP',
        defaultValue: '',
      ).trim().isNotEmpty
          ? const String.fromEnvironment('RC_TEST_SERVER_IP')
          : (Platform.environment[key] ?? fallback);
    case 'RC_TEST_USERNAME':
      return const String.fromEnvironment(
        'RC_TEST_USERNAME',
        defaultValue: '',
      ).trim().isNotEmpty
          ? const String.fromEnvironment('RC_TEST_USERNAME')
          : (Platform.environment[key] ?? fallback);
    case 'RC_TEST_PASSWORD':
      return const String.fromEnvironment(
        'RC_TEST_PASSWORD',
        defaultValue: '',
      ).trim().isNotEmpty
          ? const String.fromEnvironment('RC_TEST_PASSWORD')
          : (Platform.environment[key] ?? fallback);
    case 'RC_TEST_RUNTIME_DEVICE_ID':
      return const String.fromEnvironment(
        'RC_TEST_RUNTIME_DEVICE_ID',
        defaultValue: '',
      ).trim().isNotEmpty
          ? const String.fromEnvironment('RC_TEST_RUNTIME_DEVICE_ID')
          : (Platform.environment[key] ?? fallback);
    default:
      return fallback;
  }
}
