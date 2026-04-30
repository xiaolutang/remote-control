import 'dart:io';

import '../test_support/production_probe.dart';

Future<void> main(List<String> args) async {
  try {
    final config = _parseConfig(args);
    final result = await runProductionProbe(
      config,
      log: stdout.writeln,
    );

    stdout.writeln('production-network-e2e: PASS');
    stdout.writeln('  host: ${config.host}');
    stdout.writeln('  server_ip: ${config.serverIp}');
    stdout.writeln('  health_status: ${result.healthStatusCode}');
    stdout.writeln('  login_status: ${result.loginStatusCode}');
    stdout.writeln(
      '  connected_type: ${result.connectedMessage['type']}'
      ' session_id=${result.connectedMessage['session_id']}'
      ' device_id=${result.connectedMessage['device_id']}',
    );
    final runtime = result.runtimeTerminalResult;
    if (runtime != null) {
      if (runtime.skipped) {
        stdout.writeln(
          '  runtime_terminal_probe: skipped reason=${runtime.skipReason}',
        );
      } else {
        stdout.writeln(
          '  runtime_terminal_probe: executed'
          ' device_id=${runtime.deviceId}'
          ' device_name=${runtime.deviceName}'
          ' cwd=${runtime.candidateCwd}'
          ' terminal_id=${runtime.createdTerminalId}'
          ' created_status=${runtime.createdStatus}'
          ' input_probe_passed=${runtime.inputProbePassed}'
          ' closed_status=${runtime.closedStatus}',
        );
        if ((runtime.inputProbeEcho ?? '').isNotEmpty) {
          stdout.writeln(
            '  runtime_terminal_probe_echo: ${runtime.inputProbeEcho}',
          );
        }
      }
    }
    exitCode = 0;
  } catch (error, stackTrace) {
    stderr.writeln('production-network-e2e: FAIL');
    stderr.writeln('  error: $error');
    stderr.writeln(stackTrace);
    exitCode = 1;
  }
}

ProductionProbeConfig _parseConfig(List<String> args) {
  String? argValue(String name) {
    for (var index = 0; index < args.length; index++) {
      if (args[index] == name) {
        if (index + 1 >= args.length) {
          throw ArgumentError('Missing value for $name');
        }
        return args[index + 1];
      }
    }
    return null;
  }

  bool hasFlag(String name) => args.contains(name);

  if (hasFlag('--help') || hasFlag('-h')) {
    stdout.writeln('Usage: dart run tool/production_network_e2e.dart '
        '--server-ip YOUR_SERVER_IP '
        '--host YOUR_HOST '
        '[--username prod_test] '
        '[--password test123456] '
        '[--probe-runtime-terminal] '
        '[--require-online-device] '
        '[--runtime-device-id DEVICE_ID]');
    exit(0);
  }

  final serverIp = (argValue('--server-ip') ??
          Platform.environment['RC_TEST_SERVER_IP'] ??
          '')
      .trim();
  if (serverIp.isEmpty) {
    throw ArgumentError(
      'server ip is required. Use --server-ip or RC_TEST_SERVER_IP.',
    );
  }

  final host = (argValue('--host') ??
          Platform.environment['RC_TEST_HOST'] ??
          '')
      .trim();
  final username = (argValue('--username') ??
          Platform.environment['RC_TEST_USERNAME'] ??
          'prod_test')
      .trim();
  final password = (argValue('--password') ??
          Platform.environment['RC_TEST_PASSWORD'] ??
          'test123456')
      .trim();
  final runtimeDeviceId = (argValue('--runtime-device-id') ??
          Platform.environment['RC_TEST_RUNTIME_DEVICE_ID'] ??
          '')
      .trim();
  final probeRuntimeTerminal = hasFlag('--probe-runtime-terminal') ||
      Platform.environment['RC_TEST_PROBE_RUNTIME_TERMINAL'] == '1';
  final requireOnlineDevice = hasFlag('--require-online-device') ||
      Platform.environment['RC_TEST_REQUIRE_ONLINE_DEVICE'] == '1';

  return ProductionProbeConfig(
    serverIp: serverIp,
    host: host,
    username: username,
    password: password,
    probeRuntimeTerminal: probeRuntimeTerminal,
    requireOnlineDevice: requireOnlineDevice,
    runtimeDeviceId: runtimeDeviceId.isEmpty ? null : runtimeDeviceId,
  );
}
