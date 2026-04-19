import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../models/agent_lifecycle_state.dart';
import '../models/config.dart';
import 'config_service.dart';
import 'desktop_agent_supervisor.dart';

void _logDesktopAgentManager(String message) {
  if (Platform.environment.containsKey('FLUTTER_TEST')) {
    return;
  }
  debugPrint('[DesktopAgentManager] $message');
}

enum DesktopAgentStateKind {
  unsupported,
  unconfigured,
  offline,
  starting,
  managedOnline,
  externalOnline,
  startFailed,
}

/// F075: Agent 断连恢复状态
enum DesktopAgentRecoveryState {
  /// 正常运行或未启动
  none,

  /// 检测到断连（瞬态，快速判断后转入 recoverable）
  disconnecting,

  /// 在 TTL 窗口内，等待恢复
  recoverable,

  /// TTL 超时，不可恢复
  expired,

  /// 正在尝试恢复（重启 agent + reconnect）
  recovering,

  /// 恢复失败
  recoveryFailed,
}

class DesktopAgentState {
  const DesktopAgentState({
    required this.kind,
    this.workdir,
    this.message,
    this.recoveryState = DesktopAgentRecoveryState.none,
  });

  final DesktopAgentStateKind kind;
  final String? workdir;
  final String? message;

  /// F075: 恢复状态
  final DesktopAgentRecoveryState recoveryState;

  bool get online =>
      (kind == DesktopAgentStateKind.managedOnline ||
          kind == DesktopAgentStateKind.externalOnline) &&
      recoveryState == DesktopAgentRecoveryState.none;

  bool get managed => kind == DesktopAgentStateKind.managedOnline;

  /// Sentinel value for [copyWith] to distinguish "not provided" from null.
  static const Object _unset = Object();

  DesktopAgentState copyWith({
    DesktopAgentStateKind? kind,
    String? workdir,
    Object? message = _unset,
    DesktopAgentRecoveryState? recoveryState,
  }) {
    return DesktopAgentState(
      kind: kind ?? this.kind,
      workdir: workdir ?? this.workdir,
      message: identical(message, _unset) ? this.message : message as String?,
      recoveryState: recoveryState ?? this.recoveryState,
    );
  }
}

/// Agent 生命周期唯一权威
///
/// 桌面端 Agent 的发现/启动/停止/所有权/登录登出/App 生命周期。
/// extends ChangeNotifier，注册为全局 Provider。
class DesktopAgentManager extends ChangeNotifier {
  DesktopAgentManager({
    String serverUrl = '',
    String token = '',
    String deviceId = '',
    DesktopAgentSupervisor? supervisor,
    ConfigService? configService,
    Duration? recoveryRetryDelayOverride,
  })  : _serverUrl = serverUrl,
        _token = token,
        _deviceId = deviceId,
        _supervisor = supervisor ?? DesktopAgentSupervisor(),
        _configService = configService ?? ConfigService(),
        _recoveryRetryDelayOverride = recoveryRetryDelayOverride;

  String _serverUrl;
  String _token;
  String _deviceId;
  String? _username;
  final DesktopAgentSupervisor _supervisor;
  final ConfigService _configService;
  final Duration? _recoveryRetryDelayOverride;

  DesktopAgentState _state =
      const DesktopAgentState(kind: DesktopAgentStateKind.unconfigured);
  AgentOwnershipInfo? _ownershipInfo;

  // --- Getters ---

  DesktopAgentState get agentState => _state;
  AgentOwnershipInfo? get ownershipInfo => _ownershipInfo;
  bool get isPlatformSupported => _supervisor.supported;

  /// 向后兼容：BootstrapService 通过构造函数传入凭证
  String get serverUrl => _serverUrl;
  String get token => _token;
  String get deviceId => _deviceId;

  void _updateState(DesktopAgentState newState) {
    if (_state.kind != newState.kind ||
        _state.recoveryState != newState.recoveryState ||
        _state.message != newState.message) {
      _state = newState;
      notifyListeners();
    }
  }

  // ============================================================
  // F075: Agent 断连恢复状态机
  // ============================================================

  /// 恢复 TTL 窗口（与 server 端 stale TTL 90s 对齐）
  static const Duration recoveryTimeout = Duration(seconds: 90);

  /// 最大恢复重试次数
  static const int maxRecoveryAttempts = 3;

  /// 恢复重试间隔
  static const Duration recoveryRetryDelay = Duration(seconds: 5);

  Timer? _recoveryTimer;
  int _recoveryAttempts = 0;
  int _recoveryEpoch = 0; // 用于取消 in-flight 的异步恢复操作

  /// 当 WebSocketService / 上层检测到 agent 断连时调用
  ///
  /// [reason] 用于区分断连类型（网络断连 vs 进程死亡）。
  /// [isProcessAlive] 由调用方提供进程存活检测结果（因为 Manager
  /// 本身不持有 managedPid，通过 Supervisor 间接判断）。
  void onAgentDisconnect({
    required String reason,
    bool isProcessAlive = false,
  }) {
    if (_state.recoveryState != DesktopAgentRecoveryState.none) return;

    _logDesktopAgentManager(
      'onAgentDisconnect: reason=$reason isProcessAlive=$isProcessAlive',
    );

    _updateState(_state.copyWith(
      recoveryState: DesktopAgentRecoveryState.recoverable,
      message: 'Agent 断连: $reason',
    ));

    _startRecoveryTimeout();

    // 如果进程已死，立即尝试恢复
    if (!isProcessAlive) {
      _attemptRecovery();
    }
    // 如果进程还活着（网络断连），等待 agent 自动重连；
    // agent 重连成功后由上层调用 onAgentReconnected()。
  }

  /// Agent 重连成功后由上层调用
  void onAgentReconnected() {
    _logDesktopAgentManager('onAgentReconnected: recovery restored');
    _recoveryEpoch++;
    _recoveryTimer?.cancel();
    _recoveryTimer = null;
    _recoveryAttempts = 0;
    _updateState(_state.copyWith(
      recoveryState: DesktopAgentRecoveryState.none,
      message: null,
    ));
  }

  /// 取消恢复状态机（登出 / 手动停止时调用）
  void cancelRecovery() {
    _recoveryEpoch++;
    _recoveryTimer?.cancel();
    _recoveryTimer = null;
    _recoveryAttempts = 0;
  }

  void _startRecoveryTimeout() {
    _recoveryTimer?.cancel();
    _recoveryTimer = Timer(recoveryTimeout, _onRecoveryExpired);
  }

  void _onRecoveryExpired() {
    _logDesktopAgentManager('onRecoveryExpired: TTL exceeded');
    _recoveryAttempts = 0;
    _updateState(_state.copyWith(
      recoveryState: DesktopAgentRecoveryState.expired,
      message: 'Agent 恢复超时，连接已失效',
    ));
  }

  /// F075: 仅供测试使用 -- 手动触发 TTL 超时逻辑
  @visibleForTesting
  void triggerRecoveryExpiredForTest() => _onRecoveryExpired();

  Future<void> _attemptRecovery() async {
    if (_recoveryAttempts >= maxRecoveryAttempts) {
      _logDesktopAgentManager(
        '_attemptRecovery: max attempts ($maxRecoveryAttempts) reached',
      );
      _recoveryTimer?.cancel();
      _recoveryTimer = null;
      _updateState(_state.copyWith(
        recoveryState: DesktopAgentRecoveryState.recoveryFailed,
        message: 'Agent 恢复失败（已重试 $maxRecoveryAttempts 次）',
      ));
      return;
    }

    // 如果已经 expired 或 recoveryFailed，不再重试
    final currentRecovery = _state.recoveryState;
    if (currentRecovery == DesktopAgentRecoveryState.expired ||
        currentRecovery == DesktopAgentRecoveryState.recoveryFailed) {
      return;
    }

    final epoch = _recoveryEpoch;
    _recoveryAttempts++;
    _logDesktopAgentManager(
      '_attemptRecovery: attempt $_recoveryAttempts/$maxRecoveryAttempts',
    );

    _updateState(_state.copyWith(
      recoveryState: DesktopAgentRecoveryState.recovering,
      message: '正在恢复 Agent（第 $_recoveryAttempts 次）',
    ));

    try {
      final config = await _configService.loadConfig();
      final workdir = _resolveConfiguredWorkdir(config);

      // epoch 守卫：如果 recovery 已被取消，不再继续
      if (_recoveryEpoch != epoch) return;

      final online = await _supervisor.syncAndEnsureOnline(
        serverUrl: _serverUrl,
        accessToken: _token,
        deviceId: _deviceId,
        agentWorkdir: workdir,
      );

      // epoch 守卫：异步操作后再次检查
      if (_recoveryEpoch != epoch) return;

      if (online) {
        _logDesktopAgentManager('_attemptRecovery: agent online');
        _recoveryTimer?.cancel();
        _recoveryTimer = null;
        _recoveryAttempts = 0;
        _updateState(_state.copyWith(
          recoveryState: DesktopAgentRecoveryState.none,
          kind: DesktopAgentStateKind.managedOnline,
          message: null,
        ));
      } else {
        _logDesktopAgentManager(
          '_attemptRecovery: still offline, retrying in ${recoveryRetryDelay.inSeconds}s',
        );
        // 回到 recoverable 状态等待下次重试
        _updateState(_state.copyWith(
          recoveryState: DesktopAgentRecoveryState.recoverable,
        ));
        await Future<void>.delayed(
          _recoveryRetryDelayOverride ?? recoveryRetryDelay,
        );
        // epoch 守卫：delay 后再次检查
        if (_recoveryEpoch != epoch) return;
        _attemptRecovery();
      }
    } catch (e) {
      if (_recoveryEpoch != epoch) return;
      _logDesktopAgentManager('_attemptRecovery: exception - $e');
      _recoveryTimer?.cancel();
      _recoveryTimer = null;
      _updateState(_state.copyWith(
        recoveryState: DesktopAgentRecoveryState.recoveryFailed,
        message: 'Agent 恢复失败: $e',
      ));
    }
  }

  // ============================================================
  // 生命周期方法（原 AgentLifecycleManager 职责）
  // ============================================================

  /// 登录成功后启动 Agent（原子操作：sync + ensure 不可分割）
  Future<void> onLogin({
    required String serverUrl,
    required String token,
    required String deviceId,
    required String username,
  }) async {
    _serverUrl = serverUrl;
    _token = token;
    _deviceId = deviceId;
    _username = username;

    if (!isPlatformSupported) {
      _updateState(
          const DesktopAgentState(kind: DesktopAgentStateKind.unsupported));
      return;
    }

    _logDesktopAgentManager(
      'onLogin: starting agent for user=$username device=$deviceId',
    );
    _updateState(
        const DesktopAgentState(kind: DesktopAgentStateKind.starting));

    try {
      final config = await _configService.loadConfig();
      final online = await _supervisor.syncAndEnsureOnline(
        serverUrl: serverUrl,
        accessToken: token,
        deviceId: deviceId,
        agentWorkdir: config.desktopAgentWorkdir,
      );

      if (online) {
        _ownershipInfo = AgentOwnershipInfo(
          serverUrl: serverUrl,
          username: username,
          deviceId: deviceId,
        );
        await _saveOwnership(_ownershipInfo!);
        _updateState(
            const DesktopAgentState(kind: DesktopAgentStateKind.managedOnline));
        _logDesktopAgentManager('onLogin: agent started successfully');
      } else {
        _updateState(const DesktopAgentState(
          kind: DesktopAgentStateKind.startFailed,
          message: '本机 Agent 启动失败',
        ));
        _logDesktopAgentManager('onLogin: agent start failed');
      }
    } catch (e) {
      _updateState(const DesktopAgentState(
        kind: DesktopAgentStateKind.startFailed,
        message: '本机 Agent 启动失败',
      ));
      _logDesktopAgentManager('onLogin: agent start failed with exception - $e');
    }
  }

  /// 退出登录时关闭 Agent，使用存留凭证
  Future<void> onLogout() async {
    if (!isPlatformSupported) return;

    cancelRecovery(); // F075: 取消恢复状态机

    _logDesktopAgentManager('onLogout: stopping agent');
    try {
      await _supervisor.stopManagedAgent(
        serverUrl: _serverUrl,
        token: _token,
        deviceId: _deviceId,
        timeout: const Duration(seconds: 8),
      );
      _logDesktopAgentManager('onLogout: agent stopped');
    } catch (e) {
      _logDesktopAgentManager('onLogout: agent stop failed - $e');
    } finally {
      _ownershipInfo = null;
      await _clearSavedOwnership();
      await _supervisor.deleteManagedAgentConfig();
      _serverUrl = '';
      _token = '';
      _deviceId = '';
      _username = null;
      _updateState(
          const DesktopAgentState(kind: DesktopAgentStateKind.offline));
    }
  }

  /// App 启动时恢复 Agent（检查 ownership 并复用/重启）
  Future<void> onAppStart({
    required String serverUrl,
    required String token,
    required String username,
    required String deviceId,
  }) async {
    if (!isPlatformSupported) {
      _updateState(
          const DesktopAgentState(kind: DesktopAgentStateKind.unsupported));
      return;
    }

    _serverUrl = serverUrl;
    _token = token;
    _deviceId = deviceId;
    _username = username;

    _logDesktopAgentManager(
      'onAppStart: user=$username device=$deviceId',
    );

    try {
      final status = await _supervisor.getStatus(
        serverUrl: serverUrl,
        token: token,
        deviceId: deviceId,
      );

      if (status.online) {
        final currentOwnership = AgentOwnershipInfo(
          serverUrl: serverUrl,
          username: username,
          deviceId: deviceId,
        );
        final savedOwnership = await _loadSavedOwnership();

        if (savedOwnership != null &&
            savedOwnership.matches(currentOwnership)) {
          _ownershipInfo = currentOwnership;
          _updateState(const DesktopAgentState(
              kind: DesktopAgentStateKind.managedOnline));
          _logDesktopAgentManager('onAppStart: reusing existing agent');
        } else if (!status.managedByDesktop) {
          _ownershipInfo = currentOwnership;
          _updateState(const DesktopAgentState(
              kind: DesktopAgentStateKind.externalOnline));
          _logDesktopAgentManager('onAppStart: reusing external agent');
        } else {
          _logDesktopAgentManager(
            'onAppStart: agent belongs to different user, restarting',
          );
          await _supervisor.stopManagedAgent(
            serverUrl: serverUrl,
            token: token,
            deviceId: deviceId,
          );
          await onLogin(
            serverUrl: serverUrl,
            token: token,
            deviceId: deviceId,
            username: username,
          );
        }
      } else {
        _logDesktopAgentManager('onAppStart: agent not running, starting');
        await onLogin(
          serverUrl: serverUrl,
          token: token,
          deviceId: deviceId,
          username: username,
        );
      }
    } catch (e) {
      _logDesktopAgentManager('onAppStart: error - $e, starting new agent');
      await onLogin(
        serverUrl: serverUrl,
        token: token,
        deviceId: deviceId,
        username: username,
      );
    }
  }

  /// App 关闭时根据配置决定是否停止 Agent
  Future<void> onAppClose() async {
    if (!isPlatformSupported) return;

    final config = await _configService.loadConfig();
    if (config.keepAgentRunningInBackground) {
      _logDesktopAgentManager('onAppClose: keeping agent running');
      return;
    }

    _logDesktopAgentManager('onAppClose: stopping agent');
    await onLogout();
  }

  // ============================================================
  // 原有方法（向后兼容 BootstrapService & workspace）
  // ============================================================

  Future<DesktopAgentState> loadState({bool autoHeal = true}) async {
    if (!isPlatformSupported) {
      return const DesktopAgentState(kind: DesktopAgentStateKind.unsupported);
    }

    final config = await _configService.loadConfig();
    final workdir = _resolveConfiguredWorkdir(config);

    _logDesktopAgentManager(
      'loadState device=$_deviceId workdir=${workdir ?? ""}',
    );

    final status = await _supervisor.getStatus(
      serverUrl: _serverUrl,
      token: _token,
      deviceId: _deviceId,
    );

    if (status.online) {
      _updateState(DesktopAgentState(
        kind: status.managedByDesktop
            ? DesktopAgentStateKind.managedOnline
            : DesktopAgentStateKind.externalOnline,
        workdir: workdir,
      ));
      return _state;
    }

    // Agent 离线且有有效凭证 → 触发自愈（syncAndEnsureOnline 会 kill 僵尸 + 重启）
    if (autoHeal && _serverUrl.isNotEmpty && _token.isNotEmpty && _deviceId.isNotEmpty) {
      _logDesktopAgentManager('loadState: agent offline, triggering self-heal');
      try {
        final healed = await _supervisor.syncAndEnsureOnline(
          serverUrl: _serverUrl,
          accessToken: _token,
          deviceId: _deviceId,
          agentWorkdir: workdir,
        );
        if (healed) {
          _updateState(const DesktopAgentState(
              kind: DesktopAgentStateKind.managedOnline));
          return _state;
        }
      } catch (e) {
        _logDesktopAgentManager('loadState: self-heal failed - $e');
      }
    }

    if (workdir == null) {
      return const DesktopAgentState(
        kind: DesktopAgentStateKind.unconfigured,
        message: '未找到可用的 Agent 工作目录',
      );
    }

    return DesktopAgentState(
      kind: DesktopAgentStateKind.offline,
      workdir: workdir,
    );
  }

  Future<DesktopAgentState> startAgent({
    Duration timeout = const Duration(seconds: 12),
  }) async {
    final config = await _configService.loadConfig();
    final workdir = _resolveConfiguredWorkdir(config);

    _logDesktopAgentManager(
      'startAgent device=$_deviceId workdir=${workdir ?? ""}',
    );

    if (workdir == null) {
      return const DesktopAgentState(
        kind: DesktopAgentStateKind.unconfigured,
        message: '未找到可用的 Agent 工作目录',
      );
    }

    final started = await _supervisor.syncAndEnsureOnline(
      serverUrl: _serverUrl,
      accessToken: _token,
      deviceId: _deviceId,
      agentWorkdir: workdir,
    );

    if (!started) {
      return DesktopAgentState(
        kind: DesktopAgentStateKind.startFailed,
        workdir: workdir,
        message: '本机 Agent 启动失败',
      );
    }
    return loadState(autoHeal: false);
  }

  Future<bool> stopManagedAgent({
    Duration timeout = const Duration(seconds: 8),
  }) {
    return _supervisor.stopManagedAgent(
      serverUrl: _serverUrl,
      token: _token,
      deviceId: _deviceId,
      timeout: timeout,
    );
  }

  Future<String?> discoverConfiguredWorkdir() async {
    final config = await _configService.loadConfig();
    return _resolveConfiguredWorkdir(config);
  }

  // ============================================================
  // Private
  // ============================================================

  String? _resolveConfiguredWorkdir(AppConfig config) {
    final explicit = config.desktopAgentWorkdir.trim();
    return _supervisor.discoverAgentWorkdir(
      preferredWorkdir: explicit.isEmpty ? null : explicit,
    );
  }

  // --- Ownership persistence ---

  static const String _ownershipKey = 'rc_agent_ownership';

  Future<AgentOwnershipInfo?> _loadSavedOwnership() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final jsonStr = prefs.getString(_ownershipKey);
      if (jsonStr == null || jsonStr.isEmpty) return null;
      final json = jsonDecode(jsonStr) as Map<String, dynamic>;
      return AgentOwnershipInfo.fromJson(json);
    } catch (e) {
      _logDesktopAgentManager('_loadSavedOwnership: error - $e');
      return null;
    }
  }

  Future<void> _saveOwnership(AgentOwnershipInfo ownership) async {
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString(_ownershipKey, jsonEncode(ownership.toJson()));
    } catch (e) {
      _logDesktopAgentManager('_saveOwnership: error - $e');
    }
  }

  Future<void> _clearSavedOwnership() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.remove(_ownershipKey);
    } catch (e) {
      _logDesktopAgentManager('_clearSavedOwnership: error - $e');
    }
  }
}
