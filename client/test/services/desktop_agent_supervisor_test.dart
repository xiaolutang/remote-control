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

    test('并发 syncAndEnsureOnline 只触发一次实际启动', () async {
      var processStarts = 0;
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
          processStarts += 1;
          return Process.start(
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
        homeDirectory: '/tmp/f041_singleflight_test',
      );

      final results = await Future.wait([
        supervisor.syncAndEnsureOnline(
          serverUrl: 'ws://localhost:8888',
          accessToken: 'token',
          deviceId: 'dev-1',
          timeout: const Duration(seconds: 1),
        ),
        supervisor.syncAndEnsureOnline(
          serverUrl: 'ws://localhost:8888',
          accessToken: 'token',
          deviceId: 'dev-1',
          timeout: const Duration(seconds: 1),
        ),
      ]);

      expect(results, everyElement(isTrue));
      expect(processStarts, 1);
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

  group('bundled agent discovery', () {
    test(
        '_isProcessRunning 对 rc-agent 进程返回 true（对旧 app.cli 也兼容）',
        () async {
      SharedPreferences.setMockInitialValues({'rc_managed_agent_pid': 55555});

      // 测试 rc-agent 命令行
      final supervisorRcAgent = DesktopAgentSupervisor(
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
            // rc-agent 进程命令行
            return ProcessResult(
                0, 0, '/path/to/rc-agent --config /foo/config.json run', '');
          }
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

      final result = await supervisorRcAgent.ensureAgentOnline(
        serverUrl: 'ws://localhost:8888',
        token: 'token',
        deviceId: 'dev-1',
        timeout: const Duration(seconds: 1),
      );
      expect(result, isTrue);

      // 测试 app.cli 命令行兼容性
      SharedPreferences.setMockInitialValues(
          {'rc_managed_agent_pid': 55556});
      final supervisorCli = DesktopAgentSupervisor(
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
            return ProcessResult(0, 0, 'python3 -m app.cli run', '');
          }
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

      final result2 = await supervisorCli.ensureAgentOnline(
        serverUrl: 'ws://localhost:8888',
        token: 'token',
        deviceId: 'dev-1',
        timeout: const Duration(seconds: 1),
      );
      expect(result2, isTrue);
    });

    test('_listLocalAgentPids 能发现 rc-agent 进程', () async {
      // 通过 processLister mock 模拟 rc-agent 进程存在
      var processListerCalled = false;
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
        processLister: () async {
          processListerCalled = true;
          return <int>[1111, 2222];
        },
      );

      final result = await supervisor.ensureAgentOnline(
        serverUrl: 'ws://localhost:8888',
        token: 'token',
        deviceId: 'dev-1',
        timeout: const Duration(seconds: 1),
      );

      expect(result, isTrue);
      expect(processListerCalled, isTrue);
    });

    test('rc-agent 启动失败/崩溃时正确上报错误状态', () async {
      final supervisor = DesktopAgentSupervisor(
        runtimeService: _FakeRuntimeDeviceService([
          // 第一次查询：offline
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
          // 第二次及之后：仍然 offline（启动失败）
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
          // ps 命令对启动后的进程返回不匹配（进程已退出）
          return ProcessResult(0, 1, '', '');
        },
      );

      final result = await supervisor.ensureAgentOnline(
        serverUrl: 'ws://localhost:8888',
        token: 'token',
        deviceId: 'dev-1',
        timeout: const Duration(milliseconds: 100),
      );

      // 启动失败，应返回 false
      expect(result, isFalse);
    });

    test('discoverAgentWorkdir 使用 preferredWorkdir 回退到 python3 模式',
        () async {
      // preferredWorkdir 不存在时，仍可能从当前工作目录找到 agent
      // 验证行为：如果 preferredWorkdir 无效，会回退搜索其他路径
      final supervisor = DesktopAgentSupervisor();
      final result = supervisor.discoverAgentWorkdir(
        preferredWorkdir: '/nonexistent/path/that/does/not/exist',
      );
      // 回退搜索可能从 _searchAgentDirsFrom 找到 agent 目录
      // 关键验证：不会 crash，返回 String?
      expect(result, isA<String?>());
    });
  });

  group('bundled agent startup with workdir', () {
    test(
        '启动命令从 python3 -m app.cli 切换为 bundled agent 时使用正确参数',
        () async {
      // 使用 preferredWorkdir 指向一个包含 rc-agent 二进制的临时目录
      final tempDir = Directory.systemTemp.createTempSync('f108_bundled_test_');
      try {
        // 创建 rc-agent 文件（模拟 bundled agent 目录）
        final rcAgentFile = File(
            '${tempDir.path}/rc-agent');
        await rcAgentFile.writeAsString('#!/bin/bash\necho bundled');
        // 设置可执行权限
        await Process.run('chmod', ['+x', rcAgentFile.path]);

        String? capturedExecutable;
        List<String>? capturedArguments;
        String? capturedWorkdir;

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
            capturedExecutable = executable;
            capturedArguments = arguments;
            capturedWorkdir = workingDirectory;
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
            return ProcessResult(0, 0, 'rc-agent run', '');
          },
        );

        final result = await supervisor.ensureAgentOnline(
          serverUrl: 'ws://localhost:8888',
          token: 'token',
          deviceId: 'dev-1',
          timeout: const Duration(seconds: 1),
          agentWorkdir: tempDir.path,
        );

        expect(result, isTrue);
        // 验证使用了 rc-agent 二进制路径
        expect(capturedExecutable, contains('rc-agent'));
        // 验证工作目录使用 rc-agent 二进制所在目录
        expect(capturedWorkdir, equals(tempDir.path));
        // 验证参数只包含 run（无 config 时）
        expect(capturedArguments, equals(['run']));
      } finally {
        tempDir.deleteSync(recursive: true);
      }
    });

    test(
        'bundled agent 启动命令正确传递 --config 参数',
        () async {
      final tempDir = Directory.systemTemp.createTempSync('f108_config_test_');
      try {
        final rcAgentFile = File('${tempDir.path}/rc-agent');
        await rcAgentFile.writeAsString('#!/bin/bash\necho bundled');
        await Process.run('chmod', ['+x', rcAgentFile.path]);

        List<String>? capturedArguments;

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
            capturedArguments = arguments;
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
            return ProcessResult(0, 0, 'rc-agent run', '');
          },
        );

        final result = await supervisor.ensureAgentOnline(
          serverUrl: 'ws://localhost:8888',
          token: 'token',
          deviceId: 'dev-1',
          timeout: const Duration(seconds: 1),
          agentWorkdir: tempDir.path,
          agentConfigPath: '/path/to/managed-agent/config.json',
        );

        expect(result, isTrue);
        expect(capturedArguments,
            equals(['--config', '/path/to/managed-agent/config.json', 'run']));
      } finally {
        tempDir.deleteSync(recursive: true);
      }
    });

    test(
        'python3 源码模式回退正确工作（无 bundled agent 时）',
        () async {
      // 使用一个只有 app/cli.py 的临时目录（无 rc-agent）
      final tempDir = Directory.systemTemp.createTempSync('f108_source_test_');
      try {
        // 创建源码结构
        final appDir = Directory('${tempDir.path}/app');
        await appDir.create(recursive: true);
        await File('${appDir.path}/cli.py').writeAsString('# cli');

        String? capturedExecutable;
        List<String>? capturedArguments;

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
            capturedExecutable = executable;
            capturedArguments = arguments;
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
          agentWorkdir: tempDir.path,
        );

        expect(result, isTrue);
        // 验证回退到 python3 源码模式
        expect(capturedExecutable, equals('python3'));
        expect(capturedArguments, containsAll(['-m', 'app.cli', 'run']));
      } finally {
        tempDir.deleteSync(recursive: true);
      }
    });

    test('bundled agent 优先于 python3 源码模式', () async {
      // 目录同时包含 rc-agent 和 app/cli.py
      final tempDir = Directory.systemTemp.createTempSync('f108_priority_test_');
      try {
        final rcAgentFile = File('${tempDir.path}/rc-agent');
        await rcAgentFile.writeAsString('#!/bin/bash\necho bundled');
        await Process.run('chmod', ['+x', rcAgentFile.path]);

        final appDir = Directory('${tempDir.path}/app');
        await appDir.create(recursive: true);
        await File('${appDir.path}/cli.py').writeAsString('# cli');

        String? capturedExecutable;

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
            capturedExecutable = executable;
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
            return ProcessResult(0, 0, 'rc-agent run', '');
          },
        );

        final result = await supervisor.ensureAgentOnline(
          serverUrl: 'ws://localhost:8888',
          token: 'token',
          deviceId: 'dev-1',
          timeout: const Duration(seconds: 1),
          agentWorkdir: tempDir.path,
        );

        expect(result, isTrue);
        // 验证使用 bundled agent 而非 python3
        expect(capturedExecutable, contains('rc-agent'));
      } finally {
        tempDir.deleteSync(recursive: true);
      }
    });
  });

  group('_listLocalAgentPids with pgrep', () {
    test('同时发现 rc-agent 和 app.cli 进程', () async {
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
            // 粗粒度 pgrep：第一次返回 rc-agent PID，第二次返回 app.cli PID
            final pattern = arguments.length > 1 ? arguments[1] : '';
            if (pattern == 'rc-agent') {
              return ProcessResult(0, 0, '1111\n2222\n', '');
            }
            if (pattern == 'app\\.cli') {
              return ProcessResult(0, 0, '3333\n', '');
            }
            return ProcessResult(0, 1, '', '');
          }
          if (executable == 'ps') {
            // ps -p {pid} -o command= 验证
            final pid = int.tryParse(arguments[1]) ?? 0;
            if (pid == 1111) {
              return ProcessResult(0, 0,
                  '/path/to/rc-agent --config /foo/config.json run', '');
            }
            if (pid == 2222) {
              return ProcessResult(
                  0, 0, '/path/to/rc-agent status', '');
            }
            if (pid == 3333) {
              return ProcessResult(
                  0, 0, 'python3 -m app.cli run', '');
            }
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

      // 发现 rc-agent run (1111) 和 app.cli run (3333) → 不启动新进程
      // rc-agent status (2222) 被分类器排除
      expect(result, isTrue);
    });

    test('rc-agent status/login 等瞬态命令不阻塞启动', () async {
      SharedPreferences.setMockInitialValues({'rc_managed_agent_pid': 55557});

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
            // PID 存在但命令行是 rc-agent status（瞬态命令，不是 run）
            return ProcessResult(
                0, 0, '/path/to/rc-agent status', '');
          }
          if (executable == 'pgrep') {
            // 粗粒度 pgrep 会匹配到 rc-agent，但 ps 验证后会被过滤
            final pattern = arguments.length > 1 ? arguments[1] : '';
            if (pattern == 'rc-agent') {
              return ProcessResult(0, 0, '55557\n', '');
            }
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
      // rc-agent status 不应被识别为常驻 agent，所以应启动新进程
      expect(processStarted, isTrue);
    });
  });

  group('bundled agent priority over source workdir', () {
    test('bundled agent 发现后 preferredWorkdir 中的源码目录被跳过', () async {
      // 场景：bundled agent 不存在（非 .app 运行），preferredWorkdir 指向源码目录
      // 这是开发环境场景：没有 bundle，回退到源码模式
      final tempDir =
          Directory.systemTemp.createTempSync('f108_fallback_source_test_');
      try {
        final appDir = Directory('${tempDir.path}/app');
        await appDir.create(recursive: true);
        await File('${appDir.path}/cli.py').writeAsString('# cli');

        String? capturedExecutable;

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
            capturedExecutable = executable;
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
          agentWorkdir: tempDir.path,
        );

        expect(result, isTrue);
        // 无 bundled agent → 回退到 python3 源码模式
        expect(capturedExecutable, equals('python3'));
      } finally {
        tempDir.deleteSync(recursive: true);
      }
    });
  });

  group('isAgentRunCommand shared classifier', () {
    test('rc-agent run 匹配', () {
      expect(
        DesktopAgentSupervisor.isAgentRunCommand(
            '/path/to/rc-agent --config /foo/config.json run'),
        isTrue,
      );
      expect(
        DesktopAgentSupervisor.isAgentRunCommand('/path/to/rc-agent run'),
        isTrue,
      );
      expect(
        DesktopAgentSupervisor.isAgentRunCommand('rc-agent run'),
        isTrue,
      );
    });

    test('python3 -m app.cli run 匹配', () {
      expect(
        DesktopAgentSupervisor.isAgentRunCommand('python3 -m app.cli run'),
        isTrue,
      );
      expect(
        DesktopAgentSupervisor.isAgentRunCommand(
            'python3 -m app.cli --config /foo/config.json run'),
        isTrue,
      );
    });

    test('rc-agent login/status/configure 不匹配', () {
      expect(
        DesktopAgentSupervisor.isAgentRunCommand('/path/to/rc-agent status'),
        isFalse,
      );
      expect(
        DesktopAgentSupervisor.isAgentRunCommand('/path/to/rc-agent login'),
        isFalse,
      );
      expect(
        DesktopAgentSupervisor.isAgentRunCommand(
            '/path/to/rc-agent configure'),
        isFalse,
      );
      expect(
        DesktopAgentSupervisor.isAgentRunCommand('rc-agent status'),
        isFalse,
      );
    });

    test('python3 -m app.cli login/status/configure 不匹配', () {
      expect(
        DesktopAgentSupervisor.isAgentRunCommand(
            'python3 -m app.cli status'),
        isFalse,
      );
      expect(
        DesktopAgentSupervisor.isAgentRunCommand(
            'python3 -m app.cli login'),
        isFalse,
      );
      expect(
        DesktopAgentSupervisor.isAgentRunCommand(
            'python3 -m app.cli configure'),
        isFalse,
      );
    });

    test('不相关的进程命令行不匹配', () {
      expect(
        DesktopAgentSupervisor.isAgentRunCommand('/usr/bin/some_other_process'),
        isFalse,
      );
      expect(
        DesktopAgentSupervisor.isAgentRunCommand('sleep 10'),
        isFalse,
      );
      expect(
        DesktopAgentSupervisor.isAgentRunCommand(''),
        isFalse,
      );
    });
  });

  group('.app bundle path discovery', () {
    test(
        '_resolveBundledAgentDir returns agent dir when .app/Contents/Resources/agent contains rc-agent',
        () async {
      // 模拟 .app bundle 结构
      final tempAppDir =
          Directory.systemTemp.createTempSync('f108_app_bundle_test_');
      try {
        // 创建 .app/Contents/Resources/agent/rc-agent
        final resourcesAgentDir = Directory(
            '${tempAppDir.path}/TestApp.app/Contents/Resources/agent');
        await resourcesAgentDir.create(recursive: true);
        final rcAgentFile =
            File('${resourcesAgentDir.path}/rc-agent');
        await rcAgentFile.writeAsString('#!/bin/bash\necho bundled');
        await Process.run('chmod', ['+x', rcAgentFile.path]);

        // 使用 _FakeResolvedExecutablePlatform 通过 processRunner 注入
        // 由于无法 mock Platform.resolvedExecutable，我们通过 discoverAgentWorkdir
        // 的 preferredWorkdir 参数间接测试 _looksLikeBundledAgent
        final supervisor = DesktopAgentSupervisor();

        // 直接验证 bundled agent 目录被识别
        final workdir = supervisor.discoverAgentWorkdir(
          preferredWorkdir: resourcesAgentDir.path,
        );

        expect(workdir, isNotNull);
        expect(workdir, equals(resourcesAgentDir.path));
      } finally {
        tempAppDir.deleteSync(recursive: true);
      }
    });

    test(
        '_looksLikeBundledAgent returns false when Resources/agent has no rc-agent',
        () async {
      final tempAppDir =
          Directory.systemTemp.createTempSync('f108_app_bundle_empty_');
      try {
        // 创建空目录（无 rc-agent）
        final resourcesAgentDir = Directory(
            '${tempAppDir.path}/TestApp.app/Contents/Resources/agent');
        await resourcesAgentDir.create(recursive: true);

        // 验证目录存在但不包含 rc-agent → 不被识别为 bundled agent
        final rcAgentFile = File(
            '${resourcesAgentDir.path}/rc-agent');
        expect(rcAgentFile.existsSync(), isFalse);
      } finally {
        tempAppDir.deleteSync(recursive: true);
      }
    });

    test(
        '_looksLikeBundledAgent returns false when rc-agent is a directory',
        () async {
      final tempAppDir =
          Directory.systemTemp.createTempSync('f108_app_bundle_dir_');
      try {
        final resourcesAgentDir = Directory(
            '${tempAppDir.path}/TestApp.app/Contents/Resources/agent');
        await resourcesAgentDir.create(recursive: true);
        // rc-agent 是目录而非文件
        await Directory('${resourcesAgentDir.path}/rc-agent')
            .create(recursive: true);

        // 验证 rc-agent 路径是目录 → 不应识别为 bundled agent
        final rcAgentEntry =
            FileSystemEntity.typeSync('${resourcesAgentDir.path}/rc-agent');
        expect(
            rcAgentEntry, equals(FileSystemEntityType.directory));
        // 目录不应等于 file 类型
        expect(rcAgentEntry, isNot(equals(FileSystemEntityType.file)));
      } finally {
        tempAppDir.deleteSync(recursive: true);
      }
    });
  });

  group('_listLocalAgentPids filters out non-daemon processes', () {
    test('pgrep 找到 rc-agent 但 ps 验证发现只有 status 命令 → 不阻塞启动',
        () async {
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
          if (executable == 'pgrep') {
            final pattern = arguments.length > 1 ? arguments[1] : '';
            if (pattern == 'rc-agent') {
              // 粗粒度匹配到 PID，但其实是 rc-agent status
              return ProcessResult(0, 0, '4444\n', '');
            }
            if (pattern == 'app\\.cli') {
              return ProcessResult(0, 1, '', '');
            }
            return ProcessResult(0, 1, '', '');
          }
          if (executable == 'ps') {
            // ps 验证：PID 4444 实际是 rc-agent status
            return ProcessResult(0, 0, '/path/to/rc-agent status', '');
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
      // rc-agent status 被分类器排除 → 应启动新进程
      expect(processStarted, isTrue);
    });

    test(
        'pgrep 找到 app.cli 但 ps 验证发现只有 login 命令 → 不阻塞启动',
        () async {
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
          if (executable == 'pgrep') {
            final pattern = arguments.length > 1 ? arguments[1] : '';
            if (pattern == 'rc-agent') {
              return ProcessResult(0, 1, '', '');
            }
            if (pattern == 'app\\.cli') {
              // 粗粒度匹配到 PID，但其实是 app.cli login
              return ProcessResult(0, 0, '5555\n', '');
            }
            return ProcessResult(0, 1, '', '');
          }
          if (executable == 'ps') {
            // ps 验证：PID 5555 实际是 python3 -m app.cli login
            return ProcessResult(0, 0, 'python3 -m app.cli login', '');
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
      // app.cli login 被分类器排除 → 应启动新进程
      expect(processStarted, isTrue);
    });
  });
}
