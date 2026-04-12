import 'dart:async';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:rc_client/models/config.dart';
import 'package:rc_client/models/runtime_device.dart';
import 'package:rc_client/services/desktop_agent_manager.dart';
import 'package:rc_client/services/desktop_agent_supervisor.dart';
import 'package:rc_client/services/config_service.dart';
import 'package:rc_client/services/runtime_device_service.dart';

/// Fake RuntimeDeviceService for integration testing
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

/// Mock ConfigService for integration testing
class IntegrationMockConfigService implements ConfigService {
  AppConfig _config;

  IntegrationMockConfigService({AppConfig? config})
      : _config = config ?? const AppConfig();

  void setConfig(AppConfig config) => _config = config;

  @override
  Future<AppConfig> loadConfig() async => _config;

  @override
  Future<void> saveConfig(AppConfig config) async {
    _config = config;
  }

  @override
  Future<void> clearConfig() async {
    _config = const AppConfig();
  }
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  group('Agent Lifecycle Integration Tests', () {
    late IntegrationMockConfigService mockConfigService;

    setUp(() {
      SharedPreferences.setMockInitialValues({});
      mockConfigService = IntegrationMockConfigService();
    });

    group('登录 → Agent 启动流程', () {
      test('桌面端登录成功后 Agent 自动启动', () async {
        final manager = DesktopAgentManager(
          supervisor: DesktopAgentSupervisor(
            runtimeService: _FakeRuntimeDeviceService([
              const [
                RuntimeDevice(
                  deviceId: 'device-123',
                  name: 'mac-test',
                  owner: 'testuser',
                  agentOnline: false,
                  maxTerminals: 3,
                  activeTerminals: 0,
                ),
              ],
              const [
                RuntimeDevice(
                  deviceId: 'device-123',
                  name: 'mac-test',
                  owner: 'testuser',
                  agentOnline: true,
                  maxTerminals: 3,
                  activeTerminals: 0,
                ),
              ],
            ]),
            processStarter: (executable, arguments,
                    {workingDirectory, environment, mode = ProcessStartMode.normal}) async =>
                Process.start('sleep', const ['1'], mode: ProcessStartMode.detached),
            processRunner: (executable, arguments) async =>
                ProcessResult(0, 0, 'python3 -m app.cli run', ''),
          ),
          configService: mockConfigService,
        );

        await manager.onLogin(
          serverUrl: 'ws://localhost:8888',
          token: 'test-token',
          username: 'testuser',
          deviceId: 'device-123',
        );

        expect(manager.agentState.kind, DesktopAgentStateKind.managedOnline);
        expect(manager.ownershipInfo, isNotNull);
        expect(manager.ownershipInfo!.serverUrl, 'ws://localhost:8888');
        expect(manager.ownershipInfo!.username, 'testuser');
        expect(manager.ownershipInfo!.deviceId, 'device-123');
      });

      test('移动端登录成功后不启动 Agent', () async {
        final manager = DesktopAgentManager(
          supervisor: _MobileFakeSupervisor(),
          configService: mockConfigService,
        );

        await manager.onLogin(
          serverUrl: 'ws://localhost:8888',
          token: 'test-token',
          username: 'testuser',
          deviceId: 'device-123',
        );

        // 移动端：unsupported
        expect(manager.agentState.kind, DesktopAgentStateKind.unsupported);
      });
    });

    group('登出 → Agent 关闭流程', () {
      test('桌面端登出后 Agent 自动关闭', () async {
        final manager = DesktopAgentManager(
          serverUrl: 'ws://localhost:8888',
          token: 'test-token',
          deviceId: 'device-123',
          supervisor: DesktopAgentSupervisor(
            runtimeService: _FakeRuntimeDeviceService([
              const [
                RuntimeDevice(
                  deviceId: 'device-123',
                  name: 'mac-test',
                  owner: 'testuser',
                  agentOnline: false,
                  maxTerminals: 3,
                  activeTerminals: 0,
                ),
              ],
              const [
                RuntimeDevice(
                  deviceId: 'device-123',
                  name: 'mac-test',
                  owner: 'testuser',
                  agentOnline: true,
                  maxTerminals: 3,
                  activeTerminals: 0,
                ),
              ],
            ]),
            processStarter: (executable, arguments,
                    {workingDirectory, environment, mode = ProcessStartMode.normal}) async =>
                Process.start('sleep', const ['1'], mode: ProcessStartMode.detached),
            processRunner: (executable, arguments) async {
              if (executable == 'ps') {
                return ProcessResult(0, 0, 'python3 -m app.cli run', '');
              }
              return ProcessResult(0, 1, '', '');
            },
          ),
          configService: mockConfigService,
        );

        // 先登录
        await manager.onLogin(
          serverUrl: 'ws://localhost:8888',
          token: 'test-token',
          username: 'testuser',
          deviceId: 'device-123',
        );

        // 登出
        await manager.onLogout();

        expect(manager.agentState.kind, DesktopAgentStateKind.offline);
        expect(manager.ownershipInfo, isNull);
        expect(manager.token, '');
      });
    });

    group('App 重启恢复 Agent 流程', () {
      test('App 重启时复用已运行的 Agent（ownership 匹配）', () async {
        SharedPreferences.setMockInitialValues({
          'rc_agent_ownership':
              '{"server_url":"ws://localhost:8888","username":"testuser","device_id":"device-123"}',
        });

        final manager = DesktopAgentManager(
          supervisor: DesktopAgentSupervisor(
            runtimeService: _FakeRuntimeDeviceService([
              const [
                RuntimeDevice(
                  deviceId: 'device-123',
                  name: 'mac-test',
                  owner: 'testuser',
                  agentOnline: true,
                  maxTerminals: 3,
                  activeTerminals: 1,
                ),
              ],
            ]),
            processRunner: (executable, arguments) async =>
                ProcessResult(0, 0, 'python3 -m app.cli run', ''),
          ),
          configService: mockConfigService,
        );

        await manager.onAppStart(
          serverUrl: 'ws://localhost:8888',
          token: 'test-token',
          username: 'testuser',
          deviceId: 'device-123',
        );

        expect(manager.agentState.kind, DesktopAgentStateKind.managedOnline);
        expect(manager.ownershipInfo, isNotNull);
        expect(manager.ownershipInfo!.username, 'testuser');
      });

      test('App 重启时 Agent 不在线则启动新 Agent', () async {
        final manager = DesktopAgentManager(
          supervisor: DesktopAgentSupervisor(
            runtimeService: _FakeRuntimeDeviceService([
              const [
                RuntimeDevice(
                  deviceId: 'device-123',
                  name: 'mac-test',
                  owner: 'testuser',
                  agentOnline: false,
                  maxTerminals: 3,
                  activeTerminals: 0,
                ),
              ],
              const [
                RuntimeDevice(
                  deviceId: 'device-123',
                  name: 'mac-test',
                  owner: 'testuser',
                  agentOnline: true,
                  maxTerminals: 3,
                  activeTerminals: 0,
                ),
              ],
            ]),
            processStarter: (executable, arguments,
                    {workingDirectory, environment, mode = ProcessStartMode.normal}) async =>
                Process.start('sleep', const ['1'], mode: ProcessStartMode.detached),
            processRunner: (executable, arguments) async =>
                ProcessResult(0, 0, 'python3 -m app.cli run', ''),
          ),
          configService: mockConfigService,
        );

        await manager.onAppStart(
          serverUrl: 'ws://localhost:8888',
          token: 'test-token',
          username: 'testuser',
          deviceId: 'device-123',
        );

        expect(manager.agentState.kind, DesktopAgentStateKind.managedOnline);
      });
    });

    group('App 关闭时 Agent 状态决策', () {
      test('keepAgentRunningInBackground=true 时 Agent 继续运行', () async {
        mockConfigService.setConfig(const AppConfig(
          keepAgentRunningInBackground: true,
        ));

        final manager = DesktopAgentManager(
          supervisor: DesktopAgentSupervisor(
            runtimeService: _FakeRuntimeDeviceService([
              const [
                RuntimeDevice(
                  deviceId: 'device-123',
                  name: 'mac-test',
                  owner: 'testuser',
                  agentOnline: false,
                  maxTerminals: 3,
                  activeTerminals: 0,
                ),
              ],
              const [
                RuntimeDevice(
                  deviceId: 'device-123',
                  name: 'mac-test',
                  owner: 'testuser',
                  agentOnline: true,
                  maxTerminals: 3,
                  activeTerminals: 0,
                ),
              ],
            ]),
            processStarter: (executable, arguments,
                    {workingDirectory, environment, mode = ProcessStartMode.normal}) async =>
                Process.start('sleep', const ['1'], mode: ProcessStartMode.detached),
            processRunner: (executable, arguments) async =>
                ProcessResult(0, 0, 'python3 -m app.cli run', ''),
          ),
          configService: mockConfigService,
        );

        // 先登录
        await manager.onLogin(
          serverUrl: 'ws://localhost:8888',
          token: 'test-token',
          username: 'testuser',
          deviceId: 'device-123',
        );
        final stateBefore = manager.agentState.kind;

        // App 关闭
        await manager.onAppClose();

        // Agent 应该继续运行（状态不变）
        expect(manager.agentState.kind, stateBefore);
      });

      test('keepAgentRunningInBackground=false 时 Agent 关闭', () async {
        mockConfigService.setConfig(const AppConfig(
          keepAgentRunningInBackground: false,
        ));

        final manager = DesktopAgentManager(
          supervisor: DesktopAgentSupervisor(
            processRunner: (executable, arguments) async =>
                ProcessResult(0, 1, '', ''),
          ),
          configService: mockConfigService,
        );

        await manager.onAppClose();
        expect(manager.agentState.kind, DesktopAgentStateKind.offline);
      });
    });

    group('完整生命周期流程', () {
      test('完整流程：登录 → 使用 → 登出', () async {
        final manager = DesktopAgentManager(
          supervisor: DesktopAgentSupervisor(
            runtimeService: _FakeRuntimeDeviceService([
              const [
                RuntimeDevice(
                  deviceId: 'device-123',
                  name: 'mac-test',
                  owner: 'testuser',
                  agentOnline: false,
                  maxTerminals: 3,
                  activeTerminals: 0,
                ),
              ],
              const [
                RuntimeDevice(
                  deviceId: 'device-123',
                  name: 'mac-test',
                  owner: 'testuser',
                  agentOnline: true,
                  maxTerminals: 3,
                  activeTerminals: 0,
                ),
              ],
            ]),
            processStarter: (executable, arguments,
                    {workingDirectory, environment, mode = ProcessStartMode.normal}) async =>
                Process.start('sleep', const ['1'], mode: ProcessStartMode.detached),
            processRunner: (executable, arguments) async {
              if (executable == 'ps') {
                return ProcessResult(0, 0, 'python3 -m app.cli run', '');
              }
              return ProcessResult(0, 1, '', '');
            },
          ),
          configService: mockConfigService,
        );

        // 1. 用户登录
        await manager.onLogin(
          serverUrl: 'ws://localhost:8888',
          token: 'test-token',
          username: 'testuser',
          deviceId: 'device-123',
        );
        expect(manager.agentState.kind, DesktopAgentStateKind.managedOnline);

        // 2. 用户登出
        await manager.onLogout();
        expect(manager.agentState.kind, DesktopAgentStateKind.offline);
        expect(manager.ownershipInfo, isNull);
      });

      test('完整流程：App 重启 → 恢复 Agent → 使用 → 关闭', () async {
        mockConfigService.setConfig(const AppConfig(
          keepAgentRunningInBackground: true,
        ));

        SharedPreferences.setMockInitialValues({
          'rc_agent_ownership':
              '{"server_url":"ws://localhost:8888","username":"testuser","device_id":"device-123"}',
        });

        final manager = DesktopAgentManager(
          supervisor: DesktopAgentSupervisor(
            runtimeService: _FakeRuntimeDeviceService([
              const [
                RuntimeDevice(
                  deviceId: 'device-123',
                  name: 'mac-test',
                  owner: 'testuser',
                  agentOnline: true,
                  maxTerminals: 3,
                  activeTerminals: 1,
                ),
              ],
            ]),
            processRunner: (executable, arguments) async =>
                ProcessResult(0, 0, 'python3 -m app.cli run', ''),
          ),
          configService: mockConfigService,
        );

        // 1. App 启动，恢复 Agent
        await manager.onAppStart(
          serverUrl: 'ws://localhost:8888',
          token: 'test-token',
          username: 'testuser',
          deviceId: 'device-123',
        );
        expect(manager.agentState.kind, DesktopAgentStateKind.managedOnline);

        // 2. App 关闭（keepAgentRunningInBackground=true）
        await manager.onAppClose();
        expect(manager.agentState.kind,
            DesktopAgentStateKind.managedOnline); // Agent 继续运行
      });
    });
  });
}

/// Mobile fake supervisor (supported=false)
class _MobileFakeSupervisor extends DesktopAgentSupervisor {
  @override
  bool get supported => false;
}
