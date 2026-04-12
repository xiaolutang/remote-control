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

class DesktopAgentState {
  const DesktopAgentState({
    required this.kind,
    this.workdir,
    this.message,
  });

  final DesktopAgentStateKind kind;
  final String? workdir;
  final String? message;

  bool get online =>
      kind == DesktopAgentStateKind.managedOnline ||
      kind == DesktopAgentStateKind.externalOnline;

  bool get managed => kind == DesktopAgentStateKind.managedOnline;
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
  })  : _serverUrl = serverUrl,
        _token = token,
        _deviceId = deviceId,
        _supervisor = supervisor ?? DesktopAgentSupervisor(),
        _configService = configService ?? ConfigService();

  String _serverUrl;
  String _token;
  String _deviceId;
  String? _username;
  final DesktopAgentSupervisor _supervisor;
  final ConfigService _configService;

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
    if (_state.kind != newState.kind) {
      _state = newState;
      notifyListeners();
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

  Future<DesktopAgentState> loadState() async {
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
      return DesktopAgentState(
        kind: status.managedByDesktop
            ? DesktopAgentStateKind.managedOnline
            : DesktopAgentStateKind.externalOnline,
        workdir: workdir,
      );
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
    return loadState();
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
