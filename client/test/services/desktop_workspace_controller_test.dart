import 'package:flutter_test/flutter_test.dart';
import 'package:rc_client/models/runtime_device.dart';
import 'package:rc_client/models/runtime_terminal.dart';
import 'package:rc_client/services/desktop_agent_bootstrap_service.dart';
import 'package:rc_client/services/desktop_agent_manager.dart';
import 'package:rc_client/services/desktop_workspace_controller.dart';
import 'package:rc_client/services/runtime_device_service.dart';
import 'package:rc_client/services/runtime_selection_controller.dart';
import 'package:shared_preferences/shared_preferences.dart';

class _FakeRuntimeSelectionController extends RuntimeSelectionController {
  _FakeRuntimeSelectionController({
    required List<RuntimeDevice> devices,
    required List<RuntimeTerminal> terminals,
    this.isDesktopPlatformOverride = true,
  })  : _devices = devices,
        _terminals = terminals,
        super(
          serverUrl: 'ws://localhost:8888',
          token: 'token',
          runtimeService: RuntimeDeviceService(serverUrl: 'ws://localhost:8888'),
        );

  List<RuntimeDevice> _devices;
  List<RuntimeTerminal> _terminals;
  final bool isDesktopPlatformOverride;

  @override
  bool get isDesktopPlatform => isDesktopPlatformOverride;

  @override
  List<RuntimeDevice> get devices => List.unmodifiable(_devices);

  @override
  List<RuntimeTerminal> get terminals => List.unmodifiable(_terminals);

  @override
  RuntimeDevice? get selectedDevice => _devices.isEmpty ? null : _devices.first;

  @override
  String? get selectedDeviceId => selectedDevice?.deviceId;

  @override
  Future<void> initialize() async {}

  @override
  Future<void> loadDevices() async {
    notifyListeners();
  }

  @override
  Future<void> selectDevice(String deviceId, {bool notify = true}) async {}

  // 暴露 notifyListeners 以便测试模拟状态变化
  void notifyStateChange() => notifyListeners();
}

// 用于观察 loadState 调用的测试替身
class _ObservableBootstrapService extends DesktopAgentBootstrapService {
  _ObservableBootstrapService({required this.loadStateCallback});

  final DesktopAgentState Function() loadStateCallback;
  int startCalls = 0;
  int handleExitCalls = 0;

  @override
  Future<DesktopAgentState> loadAgentState({
    required String serverUrl,
    required String token,
    required String deviceId,
  }) async {
    return loadStateCallback();
  }

  @override
  Future<DesktopAgentState> startAgent({
    required String serverUrl,
    required String token,
    required String deviceId,
    Duration timeout = const Duration(seconds: 12),
  }) async {
    startCalls += 1;
    return loadStateCallback();
  }

  @override
  Future<void> syncNativeTerminationState({
    required bool keepRunningInBackground,
  }) async {}

  @override
  Future<bool> handleDesktopExit({
    required bool keepRunningInBackground,
    required String serverUrl,
    required String token,
    required String deviceId,
    Duration timeout = const Duration(seconds: 8),
  }) async {
    handleExitCalls += 1;
    return true;
  }
}

class _FakeBootstrapService extends DesktopAgentBootstrapService {
  _FakeBootstrapService({
    required this.resultState,
    this.loadStateValue = const DesktopAgentState(
      kind: DesktopAgentStateKind.offline,
    ),
    this.onStartCall,
  });

  final DesktopAgentState resultState;
  final DesktopAgentState loadStateValue;
  final void Function()? onStartCall;
  int startCalls = 0;
  int handleExitCalls = 0;
  bool? lastKeepRunningValue;

  @override
  Future<DesktopAgentState> loadAgentState({
    required String serverUrl,
    required String token,
    required String deviceId,
  }) async {
    return loadStateValue;
  }

  @override
  Future<DesktopAgentState> startAgent({
    required String serverUrl,
    required String token,
    required String deviceId,
    Duration timeout = const Duration(seconds: 12),
  }) async {
    startCalls += 1;
    onStartCall?.call();
    return resultState;
  }

  @override
  Future<void> syncNativeTerminationState({
    required bool keepRunningInBackground,
  }) async {}

  @override
  Future<bool> handleDesktopExit({
    required bool keepRunningInBackground,
    required String serverUrl,
    required String token,
    required String deviceId,
    Duration timeout = const Duration(seconds: 8),
  }) async {
    handleExitCalls += 1;
    lastKeepRunningValue = keepRunningInBackground;
    return true;
  }
}

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  test('startLocalAgent delegates to bootstrap service and exposes createFailed on failure', () async {
    final bootstrap = _FakeBootstrapService(
      resultState: const DesktopAgentState(
        kind: DesktopAgentStateKind.startFailed,
        message: '本机 Agent 启动失败',
      ),
    );
    final runtime = _FakeRuntimeSelectionController(
      devices: const [
        RuntimeDevice(
          deviceId: 'mbp-01',
          name: 'mac-phone',
          owner: 'user1',
          agentOnline: false,
          maxTerminals: 3,
          activeTerminals: 0,
        ),
      ],
      terminals: const [],
    );
    final controller = DesktopWorkspaceController(
      serverUrl: 'ws://localhost:8888',
      token: 'token',
      agentBootstrapService: bootstrap,
    );

    controller.attachRuntimeController(runtime);
    await controller.startLocalAgent();

    // 自动启动逻辑已移除，只有手动调用 startLocalAgent 一次
    expect(bootstrap.startCalls, 1);
    expect(controller.state.kind, WorkspaceStateKind.createFailed);
  });

  test('startLocalAgent exposes readyToCreateFirstTerminal when bootstrap succeeds', () async {
    final bootstrap = _FakeBootstrapService(
      resultState: const DesktopAgentState(
        kind: DesktopAgentStateKind.managedOnline,
      ),
      loadStateValue: const DesktopAgentState(
        kind: DesktopAgentStateKind.managedOnline,
      ),
    );
    // 使用可变列表来模拟 Agent 启动后状态变化
    final devices = <RuntimeDevice>[
      const RuntimeDevice(
        deviceId: 'mbp-01',
        name: 'mac-phone',
        owner: 'user1',
        agentOnline: true,  // Agent 启动成功后，服务端应该返回在线
        maxTerminals: 3,
        activeTerminals: 0,
      ),
    ];
    final runtime = _FakeRuntimeSelectionController(
      devices: devices,
      terminals: const [],
    );
    final controller = DesktopWorkspaceController(
      serverUrl: 'ws://localhost:8888',
      token: 'token',
      agentBootstrapService: bootstrap,
    );

    controller.attachRuntimeController(runtime);
    await controller.startLocalAgent();

    expect(bootstrap.startCalls, 1);
    expect(controller.state.kind, WorkspaceStateKind.readyToCreateFirstTerminal);
    expect(controller.state.deviceReady, true);
  });

  test('handleViewDispose calls handleDesktopExit when keepAgentRunningInBackground is false', () async {
    final bootstrap = _FakeBootstrapService(
      resultState: const DesktopAgentState(
        kind: DesktopAgentStateKind.managedOnline,
      ),
      loadStateValue: const DesktopAgentState(
        kind: DesktopAgentStateKind.managedOnline,
      ),
    );
    final runtime = _FakeRuntimeSelectionController(
      devices: const [
        RuntimeDevice(
          deviceId: 'mbp-01',
          name: 'mac-phone',
          owner: 'user1',
          agentOnline: true,
          maxTerminals: 3,
          activeTerminals: 1,
        ),
      ],
      terminals: const [],
    );
    final controller = DesktopWorkspaceController(
      serverUrl: 'ws://localhost:8888',
      token: 'token',
      agentBootstrapService: bootstrap,
    );

    controller.attachRuntimeController(runtime);
    await controller.setKeepAgentRunningInBackground(false);
    await controller.handleViewDispose();

    expect(bootstrap.handleExitCalls, 1);
    expect(bootstrap.lastKeepRunningValue, false);
  });

  test('handleViewDispose does not call handleDesktopExit when keepAgentRunningInBackground is true', () async {
    final bootstrap = _FakeBootstrapService(
      resultState: const DesktopAgentState(
        kind: DesktopAgentStateKind.managedOnline,
      ),
      loadStateValue: const DesktopAgentState(
        kind: DesktopAgentStateKind.managedOnline,
      ),
    );
    final runtime = _FakeRuntimeSelectionController(
      devices: const [
        RuntimeDevice(
          deviceId: 'mbp-01',
          name: 'mac-phone',
          owner: 'user1',
          agentOnline: true,
          maxTerminals: 3,
          activeTerminals: 1,
        ),
      ],
      terminals: const [],
    );
    final controller = DesktopWorkspaceController(
      serverUrl: 'ws://localhost:8888',
      token: 'token',
      agentBootstrapService: bootstrap,
    );

    controller.attachRuntimeController(runtime);
    await controller.setKeepAgentRunningInBackground(true);
    await controller.handleViewDispose();

    expect(bootstrap.handleExitCalls, 0);
  });

  // F028: 关闭最后一个 terminal 后的桌面工作台状态归一化
  test('onTerminalClosed resets startFailed state when last terminal is closed', () async {
    final bootstrap = _FakeBootstrapService(
      resultState: const DesktopAgentState(
        kind: DesktopAgentStateKind.startFailed,
        message: 'Agent 启动失败',
      ),
      loadStateValue: const DesktopAgentState(
        kind: DesktopAgentStateKind.startFailed,
        message: 'Agent 启动失败',
      ),
    );
    final runtime = _FakeRuntimeSelectionController(
      devices: const [
        RuntimeDevice(
          deviceId: 'mbp-01',
          name: 'mac-phone',
          owner: 'user1',
          agentOnline: false,
          maxTerminals: 3,
          activeTerminals: 1,
        ),
      ],
      terminals: const [
        RuntimeTerminal(
          terminalId: 'term-1',
          title: 'Terminal',
          cwd: '/tmp',
          command: '/bin/bash',
          status: 'closed',
          views: {'mobile': 0, 'desktop': 0},
        ),
      ],
    );
    final controller = DesktopWorkspaceController(
      serverUrl: 'ws://localhost:8888',
      token: 'token',
      agentBootstrapService: bootstrap,
    );

    controller.attachRuntimeController(runtime);

    // 模拟之前启动失败
    await controller.startLocalAgent();
    expect(controller.state.kind, WorkspaceStateKind.createFailed);

    // 关闭最后一个 terminal
    await controller.onTerminalClosed('term-1');

    // 状态应该归一化为 readyToCreateFirstTerminal，而不是继续显示 createFailed
    expect(controller.state.kind, WorkspaceStateKind.readyToCreateFirstTerminal);
    expect(controller.state.hasUsableTerminal, false);
  });

  // 回归测试：确保缓存状态与 API 状态不一致时能够刷新
  test('_syncDesktopState refreshes cache when API state differs from cached state', () async {
    // 场景：缓存显示在线，但 API 返回离线
    // 预期：应该刷新缓存以保持一致性

    int loadStateCalls = 0;
    DesktopAgentState loadStateReturnValue = const DesktopAgentState(
      kind: DesktopAgentStateKind.managedOnline,
    );

    // 使用可变的设备列表来模拟状态变化
    final devices = <RuntimeDevice>[
      const RuntimeDevice(
        deviceId: 'mbp-01',
        name: 'mac-phone',
        owner: 'user1',
        agentOnline: true,  // 初始：在线
        maxTerminals: 3,
        activeTerminals: 1,
      ),
    ];

    final terminals = <RuntimeTerminal>[
      const RuntimeTerminal(
        terminalId: 'term-1',
        title: 'Terminal',
        cwd: '/tmp',
        command: '/bin/bash',
        status: 'attached',
        views: {'mobile': 0, 'desktop': 1},
      ),
    ];

    final runtime = _FakeRuntimeSelectionController(
      devices: devices,
      terminals: terminals,
    );

    // 创建一个可以观察 loadState 调用的 bootstrap service
    final observableBootstrap = _ObservableBootstrapService(
      loadStateCallback: () {
        loadStateCalls++;
        return loadStateReturnValue;
      },
    );

    final controller = DesktopWorkspaceController(
      serverUrl: 'ws://localhost:8888',
      token: 'token',
      agentBootstrapService: observableBootstrap,
    );

    // 首次附加 runtime controller，触发第一次状态加载
    controller.attachRuntimeController(runtime);

    // 等待异步操作完成
    await Future.delayed(const Duration(milliseconds: 100));

    final firstLoadCalls = loadStateCalls;
    expect(firstLoadCalls, greaterThanOrEqualTo(1),
        reason: '首次附加应该触发 loadState');

    // 模拟 API 返回离线状态（Agent 断开）
    devices[0] = const RuntimeDevice(
      deviceId: 'mbp-01',
      name: 'mac-phone',
      owner: 'user1',
      agentOnline: false,  // API 返回：离线
      maxTerminals: 3,
      activeTerminals: 1,
    );

    // 模拟 UI 重建时重新附加 runtime controller（实际应用中由 context.watch 触发）
    controller.attachRuntimeController(runtime);

    // 等待状态同步
    await Future.delayed(const Duration(milliseconds: 100));

    // 验证：由于缓存（online=true）与 API（online=false）不一致
    // 应该触发新的 loadState 调用来刷新缓存
    expect(loadStateCalls, greaterThan(firstLoadCalls),
        reason: '当缓存状态与 API 状态不一致时，应该刷新缓存');
  });

  test('onTerminalClosed allows retry after bootstrap failure', () async {
    int startCalls = 0;
    final bootstrap = _FakeBootstrapService(
      resultState: const DesktopAgentState(
        kind: DesktopAgentStateKind.managedOnline,
      ),
      loadStateValue: const DesktopAgentState(
        kind: DesktopAgentStateKind.offline,
      ),
      onStartCall: () {
        startCalls += 1;
      },
    );
    final runtime = _FakeRuntimeSelectionController(
      devices: const [
        RuntimeDevice(
          deviceId: 'mbp-01',
          name: 'mac-phone',
          owner: 'user1',
          agentOnline: false,
          maxTerminals: 3,
          activeTerminals: 0,
        ),
      ],
      terminals: const [
        RuntimeTerminal(
          terminalId: 'term-1',
          title: 'Terminal',
          cwd: '/tmp',
          command: '/bin/bash',
          status: 'closed',
          views: {'mobile': 0, 'desktop': 0},
        ),
      ],
    );
    final controller = DesktopWorkspaceController(
      serverUrl: 'ws://localhost:8888',
      token: 'token',
      agentBootstrapService: bootstrap,
    );

    controller.attachRuntimeController(runtime);

    // 关闭最后一个 terminal
    await controller.onTerminalClosed('term-1');

    // 用户应该可以重新尝试创建 terminal
    expect(controller.state.kind, WorkspaceStateKind.readyToCreateFirstTerminal);

    // 重新尝试启动
    await controller.startLocalAgent();
    expect(startCalls, greaterThanOrEqualTo(1));
  });

  group('mobile deviceOffline', () {
    test('mobile shows deviceOffline when agent goes offline with selected terminal', () {
      final runtime = _FakeRuntimeSelectionController(
        devices: const [
          RuntimeDevice(
            deviceId: 'mbp-01',
            name: 'mac-phone',
            owner: 'user1',
            agentOnline: false,
            maxTerminals: 3,
            activeTerminals: 1,
          ),
        ],
        terminals: const [
          RuntimeTerminal(
            terminalId: 'term-1',
            title: 'Terminal',
            cwd: '/tmp',
            command: '/bin/bash',
            status: 'attached',
            views: {'mobile': 1, 'desktop': 0},
          ),
        ],
        isDesktopPlatformOverride: false,
      );
      final controller = DesktopWorkspaceController(
        serverUrl: 'ws://localhost:8888',
        token: 'token',
        agentBootstrapService: _FakeBootstrapService(
          resultState: const DesktopAgentState(kind: DesktopAgentStateKind.offline),
        ),
      );

      controller.attachRuntimeController(runtime);
      controller.selectTerminal('term-1');

      expect(controller.state.kind, WorkspaceStateKind.deviceOffline);
      expect(controller.state.deviceReady, false);
    });

    test('mobile shows deviceOffline when agent goes offline without terminal', () {
      final runtime = _FakeRuntimeSelectionController(
        devices: const [
          RuntimeDevice(
            deviceId: 'mbp-01',
            name: 'mac-phone',
            owner: 'user1',
            agentOnline: false,
            maxTerminals: 3,
            activeTerminals: 0,
          ),
        ],
        terminals: const [],
        isDesktopPlatformOverride: false,
      );
      final controller = DesktopWorkspaceController(
        serverUrl: 'ws://localhost:8888',
        token: 'token',
        agentBootstrapService: _FakeBootstrapService(
          resultState: const DesktopAgentState(kind: DesktopAgentStateKind.offline),
        ),
      );

      controller.attachRuntimeController(runtime);

      expect(controller.state.kind, WorkspaceStateKind.deviceOffline);
      expect(controller.state.deviceReady, false);
    });

    test('desktop shows readyWithTerminal when agent offline but terminal selected', () {
      final runtime = _FakeRuntimeSelectionController(
        devices: const [
          RuntimeDevice(
            deviceId: 'mbp-01',
            name: 'mac-phone',
            owner: 'user1',
            agentOnline: false,
            maxTerminals: 3,
            activeTerminals: 1,
          ),
        ],
        terminals: const [
          RuntimeTerminal(
            terminalId: 'term-1',
            title: 'Terminal',
            cwd: '/tmp',
            command: '/bin/bash',
            status: 'attached',
            views: {'mobile': 0, 'desktop': 1},
          ),
        ],
        isDesktopPlatformOverride: true,
      );
      final controller = DesktopWorkspaceController(
        serverUrl: 'ws://localhost:8888',
        token: 'token',
        agentBootstrapService: _FakeBootstrapService(
          resultState: const DesktopAgentState(kind: DesktopAgentStateKind.offline),
        ),
      );

      controller.attachRuntimeController(runtime);
      controller.selectTerminal('term-1');

      expect(controller.state.kind, WorkspaceStateKind.readyWithTerminal);
      expect(controller.state.deviceReady, false);
    });
  });
}
