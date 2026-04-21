import 'dart:async';
import 'dart:io';

import 'package:flutter/foundation.dart';

import '../models/runtime_terminal.dart';
import 'config_service.dart';
import 'desktop_agent_manager.dart';
import 'desktop_agent_bootstrap_service.dart';
import 'runtime_selection_controller.dart';

void _logWorkspaceAction(String message) {
  if (Platform.environment.containsKey("FLUTTER_TEST")) {
    return;
  }
  debugPrint("[WorkspaceAction] $message");
}

enum WorkspaceStateKind {
  bootstrappingAgent,
  readyToCreateFirstTerminal,
  readyWithTerminal,
  createInProgress,
  createFailed,
  deviceOffline,
}

class WorkspaceState {
  const WorkspaceState({
    required this.kind,
    required this.hasUsableTerminal,
    required this.deviceReady,
    this.selectedTerminal,
  });

  final WorkspaceStateKind kind;
  final bool hasUsableTerminal;
  final bool deviceReady;
  final RuntimeTerminal? selectedTerminal;
}

class DesktopWorkspaceController extends ChangeNotifier {
  DesktopWorkspaceController({
    required this.serverUrl,
    required this.token,
    required DesktopAgentBootstrapService agentBootstrapService,
    ConfigService? configService,
  })  : _agentBootstrapService = agentBootstrapService,
        _configService = configService ?? ConfigService();

  final String serverUrl;
  final String token;
  final DesktopAgentBootstrapService _agentBootstrapService;
  final ConfigService _configService;

  RuntimeSelectionController? _runtimeController;
  String? _selectedTerminalId;
  bool _keepAgentRunningInBackground = true;
  bool _desktopActionInFlight = false;
  DesktopAgentState? _desktopAgentState;
  String? _lastKnownDeviceId;
  bool _lastWasDesktopPlatform = false;
  bool? _lastKnownAgentOnline; // 手机端缓存上次的在线状态
  bool get keepAgentRunningInBackground => _keepAgentRunningInBackground;
  bool get desktopActionInFlight => _desktopActionInFlight;
  DesktopAgentState? get desktopAgentState => _desktopAgentState;

  WorkspaceState get state => _deriveWorkspaceState();

  RuntimeTerminal? get selectedTerminal {
    final runtime = _runtimeController;
    if (runtime == null) {
      return null;
    }
    _selectedTerminalId = _resolveSelectedTerminalId(
      runtime.terminals,
      _selectedTerminalId,
    );
    return _findTerminal(runtime.terminals, _selectedTerminalId);
  }

  void attachRuntimeController(RuntimeSelectionController controller) {
    final isSameController = identical(_runtimeController, controller);
    _runtimeController = controller;
    _lastWasDesktopPlatform = controller.isDesktopPlatform;
    // 只在 controller 实例变化时重置 _lastKnownDeviceId，保留变化检测能力
    if (!isSameController) {
      _lastKnownDeviceId = controller.selectedDevice?.deviceId;
    }
    _syncDesktopState(controller);
  }

  Future<void> refresh() async {
    final runtime = _runtimeController;
    if (runtime == null) return;
    await _refreshDevicesAndSync(runtime);
  }

  Future<void> setKeepAgentRunningInBackground(bool value) async {
    final config = await _configService.loadConfig();
    if (config.keepAgentRunningInBackground == value &&
        config.desktopBackgroundModeUserSet &&
        _keepAgentRunningInBackground == value) {
      return;
    }
    await _configService.saveConfig(
      config.copyWith(
        keepAgentRunningInBackground: value,
        desktopBackgroundModeUserSet: true,
      ),
    );
    await _agentBootstrapService.syncNativeTerminationState(
      keepRunningInBackground: value,
    );
    _keepAgentRunningInBackground = value;
    notifyListeners();
  }

  Future<void> retryAutoBootstrap() async {
    // 自动启动逻辑已移除，现在由全局 DesktopAgentManager 管理
    // 这个方法现在直接调用 startLocalAgent
    await startLocalAgent();
  }

  Future<void> startLocalAgent() async {
    final runtime = _runtimeController;
    final device = runtime?.selectedDevice;
    if (runtime == null || device == null) {
      _logWorkspaceAction('startLocalAgent skipped runtime_or_device_null');
      return;
    }
    _logWorkspaceAction(
      'startLocalAgent device=${device.deviceId} state=${state.kind.name}',
    );
    _desktopActionInFlight = true;
    _desktopAgentState = DesktopAgentState(
      kind: DesktopAgentStateKind.starting,
      workdir: _desktopAgentState?.workdir,
    );
    notifyListeners();
    _desktopAgentState = await _agentBootstrapService.startAgent(
      serverUrl: serverUrl,
      token: token,
      deviceId: device.deviceId,
    );
    _logWorkspaceAction(
      'startLocalAgent result=$_desktopAgentState',
    );
    // 如果启动失败，保留失败状态，不刷新（避免覆盖失败状态）
    if (_desktopAgentState?.kind != DesktopAgentStateKind.startFailed) {
      await _refreshDevicesAndSync(runtime);
    }
    _desktopActionInFlight = false;
    notifyListeners();
  }

  Future<bool> stopLocalAgent() async {
    final runtime = _runtimeController;
    final device = runtime?.selectedDevice;
    if (runtime == null || device == null) {
      return false;
    }
    _desktopActionInFlight = true;
    notifyListeners();
    final stopped = await _agentBootstrapService.stopManagedAgent(
      serverUrl: serverUrl,
      token: token,
      deviceId: device.deviceId,
    );
    await _refreshDevicesAndSync(runtime);
    _desktopActionInFlight = false;
    notifyListeners();
    return stopped;
  }

  Future<RuntimeTerminal?> createTerminal({
    required String title,
    required String cwd,
    required String command,
  }) async {
    final runtime = _runtimeController;
    final device = runtime?.selectedDevice;
    if (runtime == null || device == null) {
      _logWorkspaceAction('createTerminal skipped runtime_or_device_null');
      return null;
    }

    final stateBeforeCreate = state;
    _logWorkspaceAction(
      'createTerminal start device=${device.deviceId} state=${stateBeforeCreate.kind.name} deviceReady=${stateBeforeCreate.deviceReady}',
    );
    var effectiveDevice = device;
    if (stateBeforeCreate.kind ==
        WorkspaceStateKind.readyToCreateFirstTerminal) {
      if (!stateBeforeCreate.deviceReady) {
        _desktopActionInFlight = true;
        _desktopAgentState = DesktopAgentState(
          kind: DesktopAgentStateKind.starting,
          workdir: _desktopAgentState?.workdir,
        );
        notifyListeners();
        _desktopAgentState = await _agentBootstrapService.startAgent(
          serverUrl: serverUrl,
          token: token,
          deviceId: device.deviceId,
        );
        _logWorkspaceAction(
          'createTerminal bootstrap result=${_desktopAgentState?.kind.name}',
        );
        final recovered = _desktopAgentState?.online ?? false;
        await runtime.loadDevices();
        final refreshed = runtime.selectedDevice;
        if (!recovered || refreshed == null || !refreshed.agentOnline) {
          _logWorkspaceAction(
            'createTerminal abort after bootstrap recovered=$recovered refreshedOnline=${refreshed?.agentOnline}',
          );
          _desktopActionInFlight = false;
          notifyListeners();
          return null;
        }
        effectiveDevice = refreshed;
        await _refreshDesktopState(runtime, refreshed.deviceId);
        _desktopActionInFlight = false;
      } else {
        await _refreshDevicesAndSync(runtime);
        final refreshed = runtime.selectedDevice;
        if (refreshed != null) {
          effectiveDevice = refreshed;
        }
        _logWorkspaceAction(
          'createTerminal refreshed deviceOnline=${effectiveDevice.agentOnline} active=${effectiveDevice.activeTerminals}/${effectiveDevice.maxTerminals}',
        );
      }
    }

    if (!effectiveDevice.canCreateTerminal) {
      _logWorkspaceAction(
        'createTerminal denied canCreate=false deviceOnline=${effectiveDevice.agentOnline} active=${effectiveDevice.activeTerminals}/${effectiveDevice.maxTerminals}',
      );
      notifyListeners();
      return null;
    }

    notifyListeners();
    final terminal = await runtime.createTerminal(
      title: title,
      cwd: cwd,
      command: command,
    );
    _logWorkspaceAction(
      'createTerminal result=${terminal?.terminalId ?? "null"}',
    );
    if (terminal != null) {
      _selectedTerminalId = terminal.terminalId;
    }
    notifyListeners();
    return terminal;
  }

  Future<void> onTerminalClosed(String terminalId) async {
    final runtime = _runtimeController;
    if (runtime == null) {
      return;
    }
    _selectedTerminalId = _resolveSelectedTerminalId(
      runtime.terminals,
      _selectedTerminalId == terminalId ? null : _selectedTerminalId,
    );
    final hasUsableTerminal =
        runtime.terminals.any((terminal) => !terminal.isClosed);
    if (!hasUsableTerminal) {
      // 关闭最后一个终端后，重置状态以允许用户重新创建
      // 清除历史 bootstrap 失败状态，允许用户重新尝试
      if (_desktopAgentState?.kind == DesktopAgentStateKind.startFailed) {
        _desktopAgentState = null;
      }
    }
    notifyListeners();
  }

  void selectTerminal(String? terminalId) {
    _selectedTerminalId = terminalId;
    notifyListeners();
  }

  Future<void> handleViewDispose() async {
    if (_lastWasDesktopPlatform &&
        _lastKnownDeviceId != null &&
        !_keepAgentRunningInBackground) {
      await _agentBootstrapService.handleDesktopExit(
        keepRunningInBackground: _keepAgentRunningInBackground,
        serverUrl: serverUrl,
        token: token,
        deviceId: _lastKnownDeviceId!,
        timeout: const Duration(seconds: 1),
      );
    }
  }

  void _syncDesktopState(RuntimeSelectionController controller) {
    final device = controller.selectedDevice;
    _logWorkspaceAction(
      '_syncDesktopState called isDesktop=${controller.isDesktopPlatform} '
      'device=${device?.deviceId} agentOnline=${device?.agentOnline} '
      '_desktopAgentState=${_desktopAgentState?.kind.name} '
      '_lastKnownDeviceId=$_lastKnownDeviceId',
    );
    if (!controller.isDesktopPlatform || device == null) {
      // 手机端：当设备状态变化时，通知 UI 更新
      // 虽然 _desktopAgentState 为 null，但 device?.agentOnline 可能已更新
      final agentOnline = device?.agentOnline;
      final deviceChanged =
          device != null && _lastKnownDeviceId != device.deviceId;
      final onlineChanged = agentOnline != _lastKnownAgentOnline;
      if (deviceChanged || onlineChanged) {
        _lastKnownDeviceId = device?.deviceId;
        _lastKnownAgentOnline = agentOnline;
        _logWorkspaceAction(
          '_syncDesktopState: mobile state changed deviceChanged=$deviceChanged onlineChanged=$onlineChanged agentOnline=$agentOnline',
        );
        notifyListeners();
      }
      _logWorkspaceAction(
          '_syncDesktopState: early return - not desktop or no device');
      return;
    }
    // 当缓存状态与 API 返回状态不一致时，刷新本地缓存以保持一致性
    final shouldRefresh = _desktopAgentState == null ||
        _lastKnownDeviceId != device.deviceId ||
        _desktopAgentState?.online != device.agentOnline;
    if (shouldRefresh) {
      _logWorkspaceAction(
          '_syncDesktopState: refreshing desktop state for device ${device.deviceId} '
          '(cached=${_desktopAgentState?.online}, api=${device.agentOnline})');
      unawaited(_refreshDesktopState(controller, device.deviceId));
    }

    // 注意：自动启动 Agent 的逻辑已移除
    // Agent 生命周期现在由全局 DesktopAgentManager 管理（在 main.dart 中初始化）
    // 桌面端 Agent 在 App 启动时通过 DesktopAgentManager.onAppStart() 恢复/启动
    // 页面只负责 UI 展示和状态消费，不再主动启动 Agent
  }

  Future<void> _refreshDesktopState(
    RuntimeSelectionController controller,
    String deviceId,
  ) async {
    final config = await _configService.loadConfig();
    final state = await _agentBootstrapService.loadAgentState(
      serverUrl: serverUrl,
      token: token,
      deviceId: deviceId,
    );
    if (_lastKnownDeviceId != null && _lastKnownDeviceId != deviceId) {
      return;
    }
    await _agentBootstrapService.syncNativeTerminationState(
      keepRunningInBackground: config.keepAgentRunningInBackground,
    );
    _keepAgentRunningInBackground = config.keepAgentRunningInBackground;
    _desktopAgentState = state;
    notifyListeners();
  }

  /// 统一刷新设备列表并同步桌面状态
  Future<void> _refreshDevicesAndSync(
    RuntimeSelectionController runtime, {
    String? deviceId,
  }) async {
    await runtime.loadDevices();
    final target = deviceId ?? runtime.selectedDevice?.deviceId;
    if (target != null) {
      await _refreshDesktopState(runtime, target);
    }
  }

  WorkspaceState _deriveWorkspaceState() {
    final runtime = _runtimeController;
    final device = runtime?.selectedDevice;
    final terminals = runtime?.terminals ?? const <RuntimeTerminal>[];
    final selected = selectedTerminal;
    final hasUsableTerminal = terminals.any((terminal) => !terminal.isClosed);
    final isDesktop = runtime?.isDesktopPlatform ?? false;
    final desktopEmptyWorkspace = isDesktop && !hasUsableTerminal;
    // 统一使用服务端返回的设备在线状态（device.agentOnline）作为唯一真理来源
    // 本地 Agent 状态（_desktopAgentState）仅用于控制 UI 和管理 Agent 生命周期
    final deviceReady = device?.agentOnline ?? false;
    final bootstrapTarget = desktopEmptyWorkspace && !deviceReady;
    final explicitBootstrapFailed = bootstrapTarget &&
        _desktopAgentState?.kind == DesktopAgentStateKind.startFailed;
    final explicitBootstrapInFlight = bootstrapTarget &&
        _desktopActionInFlight &&
        _desktopAgentState?.kind == DesktopAgentStateKind.starting;

    // 手机端设备离线时优先展示离线页面（即使有选中终端也如此，因为终端连接已断开）
    // 桌面端保留终端视图，用户可通过菜单重启 Agent
    final isMobile = !isDesktop;
    if (!deviceReady && isMobile) {
      return WorkspaceState(
        kind: WorkspaceStateKind.deviceOffline,
        hasUsableTerminal: hasUsableTerminal,
        deviceReady: false,
      );
    }
    if (selected != null) {
      return WorkspaceState(
        kind: runtime?.creatingTerminal == true
            ? WorkspaceStateKind.createInProgress
            : WorkspaceStateKind.readyWithTerminal,
        selectedTerminal: selected,
        hasUsableTerminal: hasUsableTerminal,
        deviceReady: deviceReady,
      );
    }
    if (explicitBootstrapInFlight) {
      return const WorkspaceState(
        kind: WorkspaceStateKind.bootstrappingAgent,
        hasUsableTerminal: false,
        deviceReady: false,
      );
    }
    if (explicitBootstrapFailed) {
      return const WorkspaceState(
        kind: WorkspaceStateKind.createFailed,
        hasUsableTerminal: false,
        deviceReady: false,
      );
    }
    final idleKind = runtime?.creatingTerminal == true
        ? WorkspaceStateKind.createInProgress
        : WorkspaceStateKind.readyToCreateFirstTerminal;
    if (desktopEmptyWorkspace) {
      return WorkspaceState(
        kind: idleKind,
        hasUsableTerminal: false,
        deviceReady: deviceReady,
      );
    }
    return WorkspaceState(
      kind: idleKind,
      hasUsableTerminal: hasUsableTerminal,
      deviceReady: true,
    );
  }

  String? _resolveSelectedTerminalId(
    List<RuntimeTerminal> terminals,
    String? currentId,
  ) {
    if (terminals.isEmpty) {
      return null;
    }
    if (currentId != null) {
      for (final terminal in terminals) {
        if (terminal.terminalId == currentId && !terminal.isClosed) {
          return currentId;
        }
      }
    }
    for (final terminal in terminals) {
      if (!terminal.isClosed) {
        return terminal.terminalId;
      }
    }
    return null;
  }

  RuntimeTerminal? _findTerminal(
    List<RuntimeTerminal> terminals,
    String? terminalId,
  ) {
    if (terminalId == null) {
      return null;
    }
    for (final terminal in terminals) {
      if (terminal.terminalId == terminalId) {
        return terminal;
      }
    }
    return null;
  }
}
