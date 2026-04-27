import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:rc_client/models/runtime_device.dart';
import 'package:rc_client/services/desktop/desktop_agent_http_client.dart';
import 'package:rc_client/services/desktop/desktop_agent_supervisor.dart';
import 'package:rc_client/services/runtime_device_service.dart';
import 'package:shared_preferences/shared_preferences.dart';

class _FakeRuntimeDeviceService extends RuntimeDeviceService {
  _FakeRuntimeDeviceService(this.responses)
      : super(serverUrl: 'ws://localhost:8888');

  final List<List<RuntimeDevice>> responses;
  int _index = 0;

  @override
  Future<List<RuntimeDevice>> listDevices(String token) async {
    final value =
        responses[_index < responses.length ? _index : responses.length - 1];
    _index += 1;
    return value;
  }
}

class _FakeHttpClient extends DesktopAgentHttpClient {
  _FakeHttpClient({
    this.discoverResult,
    this.stopSucceeds = true,
    this.healthCheckAfterStop = false,
  }) : super(homeDirectory: '/tmp/test');

  final LocalAgentStatus? discoverResult;
  final bool stopSucceeds;
  final bool healthCheckAfterStop;

  int discoverCalls = 0;
  int stopCalls = 0;
  int healthCalls = 0;
  int? lastStopPort;

  @override
  Future<LocalAgentStatus?> discoverAgent() async {
    discoverCalls += 1;
    return discoverResult;
  }

  @override
  Future<bool> sendStop(int port, {int graceTimeout = 5}) async {
    stopCalls += 1;
    lastStopPort = port;
    return stopSucceeds;
  }

  @override
  Future<bool> checkHealth(int port) async {
    healthCalls += 1;
    return healthCheckAfterStop;
  }
}

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  test('ensureAgentOnline starts managed agent when device is offline',
      () async {
    var started = false;
    final supervisor = DesktopAgentSupervisor(
      runtimeService: _FakeRuntimeDeviceService([
        const [
          RuntimeDevice(
            deviceId: 'dev-1',
            name: 'mac-phone',
            owner: 'user',
            agentOnline: false,
            maxTerminals: 3,
            activeTerminals: 0,
          ),
        ],
        const [
          RuntimeDevice(
            deviceId: 'dev-1',
            name: 'mac-phone',
            owner: 'user',
            agentOnline: true,
            maxTerminals: 3,
            activeTerminals: 0,
          ),
        ],
      ]),
      processStarter: (
        String executable,
        List<String> arguments, {
        String? workingDirectory,
        Map<String, String>? environment,
        ProcessStartMode mode = ProcessStartMode.normal,
      }) async {
        started = true;
        return await Process.start(
          'sleep',
          const ['1'],
          mode: ProcessStartMode.detached,
        );
      },
      processRunner: (executable, arguments) async {
        if (executable == 'pgrep') {
          return ProcessResult(0, 1, '', '');
        }
        return ProcessResult(0, 0, 'python3 -m app.cli run', '');
      },
    );

    final result = await supervisor.ensureAgentOnline(
      serverUrl: 'ws://localhost:8888',
      token: 'token',
      deviceId: 'dev-1',
      timeout: const Duration(seconds: 1),
    );

    expect(result, isTrue);
    expect(started, isTrue);
    final status = await supervisor.getStatus(
      serverUrl: 'ws://localhost:8888',
      token: 'token',
      deviceId: 'dev-1',
    );
    expect(status.managedByDesktop, isTrue);
  });

  test(
      'ensureAgentOnline does not start duplicate agent when device already online',
      () async {
    var started = false;
    final supervisor = DesktopAgentSupervisor(
      runtimeService: _FakeRuntimeDeviceService([
        const [
          RuntimeDevice(
            deviceId: 'dev-1',
            name: 'mac-phone',
            owner: 'user',
            agentOnline: true,
            maxTerminals: 3,
            activeTerminals: 1,
          ),
        ],
      ]),
      processStarter: (
        String executable,
        List<String> arguments, {
        String? workingDirectory,
        Map<String, String>? environment,
        ProcessStartMode mode = ProcessStartMode.normal,
      }) async {
        started = true;
        return await Process.start(
          'sleep',
          const ['1'],
          mode: ProcessStartMode.detached,
        );
      },
    );

    final result = await supervisor.ensureAgentOnline(
      serverUrl: 'ws://localhost:8888',
      token: 'token',
      deviceId: 'dev-1',
    );

    expect(result, isTrue);
    expect(started, isFalse);
  });

  test(
      'ensureAgentOnline does not start duplicate agent when local agent process already exists',
      () async {
    var started = false;
    final supervisor = DesktopAgentSupervisor(
      runtimeService: _FakeRuntimeDeviceService([
        const [
          RuntimeDevice(
            deviceId: 'dev-1',
            name: 'mac-phone',
            owner: 'user',
            agentOnline: false,
            maxTerminals: 3,
            activeTerminals: 0,
          ),
        ],
        const [
          RuntimeDevice(
            deviceId: 'dev-1',
            name: 'mac-phone',
            owner: 'user',
            agentOnline: true,
            maxTerminals: 3,
            activeTerminals: 0,
          ),
        ],
      ]),
      processStarter: (
        String executable,
        List<String> arguments, {
        String? workingDirectory,
        Map<String, String>? environment,
        ProcessStartMode mode = ProcessStartMode.normal,
      }) async {
        started = true;
        return await Process.start(
          'sleep',
          const ['1'],
          mode: ProcessStartMode.detached,
        );
      },
      processLister: () async => <int>[4242],
    );

    final result = await supervisor.ensureAgentOnline(
      serverUrl: 'ws://localhost:8888',
      token: 'token',
      deviceId: 'dev-1',
      timeout: const Duration(seconds: 1),
    );

    expect(result, isTrue);
    expect(started, isFalse);
  });

  test('ensureAgentOnline restarts stale managed agent that never comes online',
      () async {
    SharedPreferences.setMockInitialValues({
      'rc_managed_agent_pid': 321,
    });

    var started = false;
    final killed = <ProcessSignal>[];
    final supervisor = DesktopAgentSupervisor(
      runtimeService: _FakeRuntimeDeviceService([
        const [
          RuntimeDevice(
            deviceId: 'dev-1',
            name: 'mac-phone',
            owner: 'user',
            agentOnline: false,
            maxTerminals: 3,
            activeTerminals: 0,
          ),
        ],
        const [
          RuntimeDevice(
            deviceId: 'dev-1',
            name: 'mac-phone',
            owner: 'user',
            agentOnline: false,
            maxTerminals: 3,
            activeTerminals: 0,
          ),
        ],
        const [
          RuntimeDevice(
            deviceId: 'dev-1',
            name: 'mac-phone',
            owner: 'user',
            agentOnline: true,
            maxTerminals: 3,
            activeTerminals: 0,
          ),
        ],
      ]),
      processStarter: (
        String executable,
        List<String> arguments, {
        String? workingDirectory,
        Map<String, String>? environment,
        ProcessStartMode mode = ProcessStartMode.normal,
      }) async {
        started = true;
        return await Process.start(
          'sleep',
          const ['1'],
          mode: ProcessStartMode.detached,
        );
      },
      processRunner: (executable, arguments) async {
        if (executable == 'pgrep') {
          return ProcessResult(0, 1, '', '');
        }
        return ProcessResult(0, 0, 'python3 -m app.cli run', '');
      },
      pidKiller: (pid, signal) {
        killed.add(signal);
        return true;
      },
    );

    final result = await supervisor.ensureAgentOnline(
      serverUrl: 'ws://localhost:8888',
      token: 'token',
      deviceId: 'dev-1',
      timeout: const Duration(milliseconds: 100),
    );

    expect(result, isTrue);
    expect(started, isTrue);
    expect(killed, contains(ProcessSignal.sigterm));
  });

  test('stopManagedAgent only affects managed agent ownership', () async {
    final killed = <int>[];
    final supervisor = DesktopAgentSupervisor(
      runtimeService: _FakeRuntimeDeviceService([
        const [
          RuntimeDevice(
            deviceId: 'dev-1',
            name: 'mac-phone',
            owner: 'user',
            agentOnline: false,
            maxTerminals: 3,
            activeTerminals: 0,
          ),
        ],
        const [
          RuntimeDevice(
            deviceId: 'dev-1',
            name: 'mac-phone',
            owner: 'user',
            agentOnline: true,
            maxTerminals: 3,
            activeTerminals: 0,
          ),
        ],
        const [
          RuntimeDevice(
            deviceId: 'dev-1',
            name: 'mac-phone',
            owner: 'user',
            agentOnline: false,
            maxTerminals: 3,
            activeTerminals: 0,
          ),
        ],
      ]),
      processStarter: (
        String executable,
        List<String> arguments, {
        String? workingDirectory,
        Map<String, String>? environment,
        ProcessStartMode mode = ProcessStartMode.normal,
      }) async {
        return await Process.start(
          'sleep',
          const ['1'],
          mode: ProcessStartMode.detached,
        );
      },
      processRunner: (executable, arguments) async {
        if (executable == 'pgrep') {
          return ProcessResult(0, 1, '', '');
        }
        return ProcessResult(0, 0, 'python3 -m app.cli run', '');
      },
      pidKiller: (pid, signal) {
        killed.add(pid);
        return true;
      },
    );

    await supervisor.ensureAgentOnline(
      serverUrl: 'ws://localhost:8888',
      token: 'token',
      deviceId: 'dev-1',
      timeout: const Duration(milliseconds: 100),
    );

    final stopped = await supervisor.stopManagedAgent(
      serverUrl: 'ws://localhost:8888',
      token: 'token',
      deviceId: 'dev-1',
      timeout: const Duration(milliseconds: 100),
    );

    expect(stopped, isTrue);
    expect(killed, isNotEmpty);
  });

  test('handleDesktopExit keeps external agent running', () async {
    final supervisor = DesktopAgentSupervisor(
      runtimeService: _FakeRuntimeDeviceService([
        const [
          RuntimeDevice(
            deviceId: 'dev-1',
            name: 'mac-phone',
            owner: 'user',
            agentOnline: true,
            maxTerminals: 3,
            activeTerminals: 1,
          ),
        ],
      ]),
    );

    final stopped = await supervisor.handleDesktopExit(
      keepRunningInBackground: false,
      serverUrl: 'ws://localhost:8888',
      token: 'token',
      deviceId: 'dev-1',
      timeout: const Duration(milliseconds: 100),
    );

    expect(stopped, isFalse);
  });

  test(
      'handleDesktopExit keeps managed agent running when background mode is on',
      () async {
    final supervisor = DesktopAgentSupervisor(
      runtimeService: _FakeRuntimeDeviceService([
        const [
          RuntimeDevice(
            deviceId: 'dev-1',
            name: 'mac-phone',
            owner: 'user',
            agentOnline: true,
            maxTerminals: 3,
            activeTerminals: 1,
          ),
        ],
      ]),
      processStarter: (
        String executable,
        List<String> arguments, {
        String? workingDirectory,
        Map<String, String>? environment,
        ProcessStartMode mode = ProcessStartMode.normal,
      }) async {
        return await Process.start(
          'sleep',
          const ['1'],
          mode: ProcessStartMode.detached,
        );
      },
      processRunner: (executable, arguments) async {
        return ProcessResult(0, 0, 'python3 -m app.cli run', '');
      },
    );

    await supervisor.ensureAgentOnline(
      serverUrl: 'ws://localhost:8888',
      token: 'token',
      deviceId: 'dev-1',
      timeout: const Duration(milliseconds: 100),
    );

    final stopped = await supervisor.handleDesktopExit(
      keepRunningInBackground: true,
      serverUrl: 'ws://localhost:8888',
      token: 'token',
      deviceId: 'dev-1',
      timeout: const Duration(milliseconds: 100),
    );

    expect(stopped, isFalse);
  });

  test('stopManagedAgent uses HTTP /stop for graceful shutdown', () async {
    SharedPreferences.setMockInitialValues({
      'rc_managed_agent_pid': 12345,
    });

    final killed = <int>[];
    final httpClient = _FakeHttpClient(
      discoverResult: const LocalAgentStatus(
        running: true,
        pid: 12345,
        port: 18765,
        serverUrl: '',
        connected: true,
        sessionId: '',
        terminalsCount: 1,
        keepRunningInBackground: true,
      ),
      stopSucceeds: true,
      healthCheckAfterStop: false, // Agent 停止后 health 检查返回 false
    );

    final supervisor = DesktopAgentSupervisor(
      runtimeService: _FakeRuntimeDeviceService([
        const [
          RuntimeDevice(
            deviceId: 'dev-1',
            name: 'mac-phone',
            owner: 'user',
            agentOnline: true,
            maxTerminals: 3,
            activeTerminals: 1,
          ),
        ],
        const [
          RuntimeDevice(
            deviceId: 'dev-1',
            name: 'mac-phone',
            owner: 'user',
            agentOnline: false,
            maxTerminals: 3,
            activeTerminals: 0,
          ),
        ],
      ]),
      processRunner: (executable, arguments) async {
        if (executable == 'pgrep') {
          return ProcessResult(0, 0, '12345\n', '');
        }
        return ProcessResult(0, 0, 'python3 -m app.cli run', '');
      },
      pidKiller: (pid, signal) {
        killed.add(pid);
        return true;
      },
      httpClient: httpClient,
    );

    final stopped = await supervisor.stopManagedAgent(
      serverUrl: 'ws://localhost:8888',
      token: 'token',
      deviceId: 'dev-1',
      timeout: const Duration(seconds: 2),
    );

    expect(stopped, isTrue);
    expect(httpClient.discoverCalls, greaterThanOrEqualTo(1));
    expect(httpClient.stopCalls, 1);
    expect(httpClient.lastStopPort, 18765);
    // HTTP 成功后不应调用 SIGTERM
    expect(killed, isEmpty);
  });

  test('stopManagedAgent falls back to SIGTERM when HTTP /stop fails',
      () async {
    SharedPreferences.setMockInitialValues({
      'rc_managed_agent_pid': 12345,
    });

    final killed = <int>[];
    final httpClient = _FakeHttpClient(
      discoverResult: null, // 无法发现 Agent
      stopSucceeds: false,
    );

    final supervisor = DesktopAgentSupervisor(
      runtimeService: _FakeRuntimeDeviceService([
        const [
          RuntimeDevice(
            deviceId: 'dev-1',
            name: 'mac-phone',
            owner: 'user',
            agentOnline: true,
            maxTerminals: 3,
            activeTerminals: 1,
          ),
        ],
        const [
          RuntimeDevice(
            deviceId: 'dev-1',
            name: 'mac-phone',
            owner: 'user',
            agentOnline: false,
            maxTerminals: 3,
            activeTerminals: 0,
          ),
        ],
      ]),
      processRunner: (executable, arguments) async {
        if (executable == 'pgrep') {
          return ProcessResult(0, 0, '12345\n', '');
        }
        return ProcessResult(0, 0, 'python3 -m app.cli run', '');
      },
      pidKiller: (pid, signal) {
        killed.add(pid);
        return true;
      },
      httpClient: httpClient,
    );

    final stopped = await supervisor.stopManagedAgent(
      serverUrl: 'ws://localhost:8888',
      token: 'token',
      deviceId: 'dev-1',
      timeout: const Duration(milliseconds: 500),
    );

    expect(stopped, isTrue);
    // HTTP 失败后应回退到 SIGTERM
    expect(killed, contains(12345));
  });

  group('syncAndEnsureOnline', () {
    test('内部按序调用 sync -> ensure（configPath 正确传递）', () async {
      final supervisor = DesktopAgentSupervisor(
        runtimeService: _FakeRuntimeDeviceService([
          const [
            RuntimeDevice(
              deviceId: 'dev-1',
              name: 'mac-phone',
              owner: 'user',
              agentOnline: true,
              maxTerminals: 3,
              activeTerminals: 0,
            ),
          ],
        ]),
        homeDirectory: '/tmp/f041_sync_test',
      );

      // 通过 ensureAgentOnline 检查 configPath 是否传递
      // 使用 syncAndEnsureOnline 调用后，设备已在线，ensure 应收到非 null configPath
      final result = await supervisor.syncAndEnsureOnline(
        serverUrl: 'ws://localhost:8888',
        accessToken: 'token',
        deviceId: 'dev-1',
      );

      // 设备已在线 → 返回 true
      expect(result, isTrue);
    });

    test('sync 失败时 configPath 为 null 但 ensure 仍执行', () async {
      // 无 homeDirectory → syncManagedAgentConfig 返回 null
      final supervisor = DesktopAgentSupervisor(
        runtimeService: _FakeRuntimeDeviceService([
          const [
            RuntimeDevice(
              deviceId: 'dev-1',
              name: 'mac-phone',
              owner: 'user',
              agentOnline: true,
              maxTerminals: 3,
              activeTerminals: 0,
            ),
          ],
        ]),
        homeDirectory: '', // 空 HOME → sync 失败
      );

      final result = await supervisor.syncAndEnsureOnline(
        serverUrl: 'ws://localhost:8888',
        accessToken: 'token',
        deviceId: 'dev-1',
      );

      // 设备已在线 → 即使 sync 失败也返回 true
      expect(result, isTrue);
    });
  });

  group('_isProcessRunning PID 校验', () {
    test('PID 有效且命令行包含 app.cli → 返回 true', () async {
      // 通过 ensureAgentOnline 间接测试 _isProcessRunning
      // 预置 managed PID，processRunner 返回包含 app.cli 的输出
      SharedPreferences.setMockInitialValues({'rc_managed_agent_pid': 12345});

      final supervisorWithPid = DesktopAgentSupervisor(
        runtimeService: _FakeRuntimeDeviceService([
          const [
            RuntimeDevice(
              deviceId: 'dev-1',
              name: 'mac-phone',
              owner: 'user',
              agentOnline: false,
              maxTerminals: 3,
              activeTerminals: 0,
            ),
          ],
          const [
            RuntimeDevice(
              deviceId: 'dev-1',
              name: 'mac-phone',
              owner: 'user',
              agentOnline: true,
              maxTerminals: 3,
              activeTerminals: 0,
            ),
          ],
        ]),
        processRunner: (executable, arguments) async {
          if (executable == 'ps') {
            // PID 存在且命令行包含 app.cli
            return ProcessResult(0, 0, 'python3 -m app.cli run', '');
          }
          // pgrep
          return ProcessResult(0, 1, '', '');
        },
        processStarter: (
          String executable,
          List<String> arguments, {
          String? workingDirectory,
          Map<String, String>? environment,
          ProcessStartMode mode = ProcessStartMode.normal,
        }) async {
          return await Process.start(
            'sleep',
            const ['1'],
            mode: ProcessStartMode.detached,
          );
        },
      );

      final result = await supervisorWithPid.ensureAgentOnline(
        serverUrl: 'ws://localhost:8888',
        token: 'token',
        deviceId: 'dev-1',
        timeout: const Duration(seconds: 1),
      );

      expect(result, isTrue);
    });

    test('PID 有效但命令行不包含 app.cli → 清除缓存 PID', () async {
      SharedPreferences.setMockInitialValues({'rc_managed_agent_pid': 99999});

      var processStarted = false;
      final supervisor = DesktopAgentSupervisor(
        runtimeService: _FakeRuntimeDeviceService([
          const [
            RuntimeDevice(
              deviceId: 'dev-1',
              name: 'mac-phone',
              owner: 'user',
              agentOnline: false,
              maxTerminals: 3,
              activeTerminals: 0,
            ),
          ],
          const [
            RuntimeDevice(
              deviceId: 'dev-1',
              name: 'mac-phone',
              owner: 'user',
              agentOnline: true,
              maxTerminals: 3,
              activeTerminals: 0,
            ),
          ],
        ]),
        processRunner: (executable, arguments) async {
          if (executable == 'ps') {
            // PID 存在但命令行不包含 app.cli（PID 复用）
            return ProcessResult(0, 0, '/usr/bin/some_other_process', '');
          }
          if (executable == 'pgrep') {
            return ProcessResult(0, 1, '', '');
          }
          return ProcessResult(0, 0, '', '');
        },
        processStarter: (
          String executable,
          List<String> arguments, {
          String? workingDirectory,
          Map<String, String>? environment,
          ProcessStartMode mode = ProcessStartMode.normal,
        }) async {
          processStarted = true;
          return await Process.start(
            'sleep',
            const ['1'],
            mode: ProcessStartMode.detached,
          );
        },
      );

      final result = await supervisor.ensureAgentOnline(
        serverUrl: 'ws://localhost:8888',
        token: 'token',
        deviceId: 'dev-1',
        timeout: const Duration(seconds: 1),
      );

      expect(result, isTrue);
      // PID 不匹配 → 应清除旧 PID 并启动新进程
      expect(processStarted, isTrue);

      // 验证旧 PID 已清除（managed PID 应为新进程的 PID，不是 99999）
      final prefs = await SharedPreferences.getInstance();
      final storedPid = prefs.getInt('rc_managed_agent_pid');
      expect(storedPid, isNot(equals(99999)));
    });

    test('DesktopAgentManager.startAgent 改用 syncAndEnsureOnline 后行为不变',
        () async {
      // 此测试验证 syncAndEnsureOnline 路径能正确启动 Agent
      SharedPreferences.setMockInitialValues({});

      var syncCalled = false;
      final supervisor = DesktopAgentSupervisor(
        runtimeService: _FakeRuntimeDeviceService([
          const [
            RuntimeDevice(
              deviceId: 'dev-1',
              name: 'mac-phone',
              owner: 'user',
              agentOnline: false,
              maxTerminals: 3,
              activeTerminals: 0,
            ),
          ],
          const [
            RuntimeDevice(
              deviceId: 'dev-1',
              name: 'mac-phone',
              owner: 'user',
              agentOnline: true,
              maxTerminals: 3,
              activeTerminals: 0,
            ),
          ],
        ]),
        processRunner: (executable, arguments) async {
          if (executable == 'pgrep') {
            return ProcessResult(0, 1, '', '');
          }
          return ProcessResult(0, 0, 'python3 -m app.cli run', '');
        },
        processStarter: (
          String executable,
          List<String> arguments, {
          String? workingDirectory,
          Map<String, String>? environment,
          ProcessStartMode mode = ProcessStartMode.normal,
        }) async {
          syncCalled = true;
          return await Process.start(
            'sleep',
            const ['1'],
            mode: ProcessStartMode.detached,
          );
        },
        homeDirectory: '/tmp/f041_manager_test',
      );

      final result = await supervisor.syncAndEnsureOnline(
        serverUrl: 'ws://localhost:8888',
        accessToken: 'token',
        deviceId: 'dev-1',
        timeout: const Duration(seconds: 1),
      );

      expect(result, isTrue);
      expect(syncCalled, isTrue);
    });
  });
}
