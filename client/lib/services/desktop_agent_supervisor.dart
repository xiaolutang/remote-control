import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:path/path.dart' as p;
import 'package:shared_preferences/shared_preferences.dart';

import '../models/runtime_device.dart';
import 'desktop_agent_exit_bridge.dart';
import 'desktop_agent_http_client.dart';
import 'runtime_device_service.dart';

typedef AgentProcessStarter = Future<Process> Function(
  String executable,
  List<String> arguments, {
  String? workingDirectory,
  Map<String, String>? environment,
  ProcessStartMode mode,
});

typedef AgentProcessRunner = Future<ProcessResult> Function(
  String executable,
  List<String> arguments,
);

typedef AgentPidKiller = bool Function(int pid, ProcessSignal signal);
typedef AgentProcessLister = Future<List<int>> Function();

void _logDesktopAgent(String message) {
  if (Platform.environment.containsKey('FLUTTER_TEST')) {
    return;
  }
  debugPrint('[DesktopAgent] $message');
}

void _logManagedRuntime(String message) {
  if (Platform.environment.containsKey('FLUTTER_TEST')) {
    return;
  }
  debugPrint('[ManagedRuntime] $message');
}

class DesktopAgentStatus {
  const DesktopAgentStatus({
    required this.supported,
    required this.online,
    required this.managedByDesktop,
  });

  final bool supported;
  final bool online;
  final bool managedByDesktop;
}

class DesktopAgentSupervisor {
  DesktopAgentSupervisor({
    RuntimeDeviceService? runtimeService,
    AgentProcessStarter? processStarter,
    AgentProcessRunner? processRunner,
    AgentPidKiller? pidKiller,
    AgentProcessLister? processLister,
    DesktopAgentHttpClient? httpClient,
    String? homeDirectory,
  })  : _runtimeService = runtimeService,
        _processStarter = processStarter ?? Process.start,
        _processRunner = processRunner ?? Process.run,
        _pidKiller = pidKiller ?? Process.killPid,
        _processLister = processLister,
        _httpClient = httpClient,
        _homeDirectory = homeDirectory;

  static const String _managedAgentPidKey = 'rc_managed_agent_pid';

  final RuntimeDeviceService? _runtimeService;
  final AgentProcessStarter _processStarter;
  final AgentProcessRunner _processRunner;
  final AgentPidKiller _pidKiller;
  final AgentProcessLister? _processLister;
  final DesktopAgentHttpClient? _httpClient;
  final String? _homeDirectory;

  bool get supported => !Platform.isAndroid && !Platform.isIOS;

  Future<DesktopAgentStatus> getStatus({
    required String serverUrl,
    required String token,
    required String deviceId,
  }) async {
    if (!supported) {
      return const DesktopAgentStatus(
        supported: false,
        online: false,
        managedByDesktop: false,
      );
    }

    final runtimeService =
        _runtimeService ?? RuntimeDeviceService(serverUrl: serverUrl);
    final devices = await runtimeService.listDevices(token);
    final current = _findDevice(devices, deviceId);
    final managedPid = await _loadManagedAgentPid();
    final managedRunning = managedPid != null && await _isProcessRunning(managedPid);
    if (managedPid != null && !managedRunning) {
      await _clearManagedAgentPid();
    }

    return DesktopAgentStatus(
      supported: true,
      online: current?.agentOnline ?? false,
      managedByDesktop: managedRunning,
    );
  }

  Future<bool> ensureAgentOnline({
    required String serverUrl,
    required String token,
    required String deviceId,
    Duration timeout = const Duration(seconds: 12),
    String? agentWorkdir,
    String? agentConfigPath,
  }) async {
    _logDesktopAgent(
      'ensureAgentOnline start device=$deviceId supported=$supported workdir_arg=${agentWorkdir ?? ''}',
    );
    if (!supported) {
      _logDesktopAgent('ensureAgentOnline unsupported platform');
      return false;
    }

    final runtimeService =
        _runtimeService ?? RuntimeDeviceService(serverUrl: serverUrl);

    final before = _findDevice(await runtimeService.listDevices(token), deviceId);
    _logDesktopAgent(
      'ensureAgentOnline before agentOnline=${before?.agentOnline ?? false}',
    );
    if (before?.agentOnline ?? false) {
      await _clearStaleManagedAgentPid();
      _logDesktopAgent('ensureAgentOnline device already online');
      return true;
    }

    final managedPid = await _loadManagedAgentPid();
    _logDesktopAgent('ensureAgentOnline managedPid=${managedPid ?? -1}');
    if (managedPid != null) {
      if (await _isProcessRunning(managedPid)) {
        _logDesktopAgent('ensureAgentOnline waiting existing managed pid=$managedPid');
        final recovered = await _waitForAgentOnline(
          runtimeService: runtimeService,
          token: token,
          deviceId: deviceId,
          timeout: timeout,
        );
        _logDesktopAgent(
          'ensureAgentOnline existing managed wait result=$recovered',
        );
        if (recovered) {
          return true;
        }
        _logDesktopAgent(
          'ensureAgentOnline existing managed pid stale, terminating and restarting',
        );
        await _terminateProcess(managedPid);
        await _clearManagedAgentPid();
      } else {
        await _clearManagedAgentPid();
        _logDesktopAgent('ensureAgentOnline cleared stale managed pid');
      }
    }

    final existingLocalAgents = await _listLocalAgentPids();
    _logDesktopAgent(
      'ensureAgentOnline existingLocalAgents=${existingLocalAgents.join(",")}',
    );
    if (existingLocalAgents.isNotEmpty) {
      _logDesktopAgent('ensureAgentOnline waiting existing external agent');
      return _waitForAgentOnline(
        runtimeService: runtimeService,
        token: token,
        deviceId: deviceId,
        timeout: timeout,
      );
    }

    final workdir = _resolveAgentWorkdir(preferredWorkdir: agentWorkdir);
    if (workdir == null) {
      _logDesktopAgent('ensureAgentOnline no workdir resolved');
      return false;
    }
    _logDesktopAgent('ensureAgentOnline resolved workdir=${workdir.path}');

    try {
      final process = await _processStarter(
        'python3',
        <String>[
          '-m',
          'app.cli',
          if (agentConfigPath != null && agentConfigPath.isNotEmpty) ...[
            '--config',
            agentConfigPath,
          ],
          'run',
        ],
        workingDirectory: workdir.path,
        environment: <String, String>{
          if (agentConfigPath != null && agentConfigPath.isNotEmpty)
            'RC_AGENT_CONFIG_DIR': File(agentConfigPath).parent.path,
          if (kDebugMode) 'RC_SSL_INSECURE': '1',
        },
        mode: ProcessStartMode.detachedWithStdio,
      );
      await _saveManagedAgentPid(process.pid);
      _logDesktopAgent('ensureAgentOnline started pid=${process.pid}');
      unawaited(_captureManagedRuntimeOutput(process));
    } catch (_) {
      _logDesktopAgent('ensureAgentOnline process start threw');
      return false;
    }

    final online = await _waitForAgentOnline(
      runtimeService: runtimeService,
      token: token,
      deviceId: deviceId,
      timeout: timeout,
    );
    _logDesktopAgent('ensureAgentOnline wait result=$online');
    if (!online) {
      await stopManagedAgent(
        serverUrl: serverUrl,
        token: token,
        deviceId: deviceId,
        timeout: const Duration(seconds: 2),
      );
      _logDesktopAgent('ensureAgentOnline stopManagedAgent after failed wait');
    }
    return online;
  }

  /// 原子操作：同步配置 + 启动 Agent，不可分割
  ///
  /// 内部先 syncManagedAgentConfig 写入最新凭证，
  /// 再 ensureAgentOnline 启动进程。调用方无法跳过 sync。
  Future<bool> syncAndEnsureOnline({
    required String serverUrl,
    required String accessToken,
    required String deviceId,
    Duration timeout = const Duration(seconds: 12),
    String? agentWorkdir,
  }) async {
    _logDesktopAgent('syncAndEnsureOnline start device=$deviceId');
    final configPath = await syncManagedAgentConfig(
      serverUrl: serverUrl,
      accessToken: accessToken,
      deviceId: deviceId,
    );
    _logDesktopAgent(
      'syncAndEnsureOnline configPath=${configPath ?? ""}',
    );
    return ensureAgentOnline(
      serverUrl: serverUrl,
      token: accessToken,
      deviceId: deviceId,
      timeout: timeout,
      agentWorkdir: agentWorkdir,
      agentConfigPath: configPath,
    );
  }

  Future<bool> stopManagedAgent({
    required String serverUrl,
    required String token,
    required String deviceId,
    Duration timeout = const Duration(seconds: 8),
  }) async {
    if (!supported) {
      return false;
    }

    final pid = await _loadManagedAgentPid();
    if (pid == null) {
      return false;
    }

    if (!await _isProcessRunning(pid)) {
      await _clearManagedAgentPid();
      return true;
    }

    // 优先尝试 HTTP /stop 优雅关闭
    final httpStopped = await _tryHttpStop(timeout: timeout);
    if (httpStopped) {
      await _clearManagedAgentPid();
      return true;
    }

    // HTTP 失败时回退到 SIGTERM
    await _terminateProcess(pid);

    final runtimeService =
        _runtimeService ?? RuntimeDeviceService(serverUrl: serverUrl);
    final deadline = DateTime.now().add(timeout);
    while (DateTime.now().isBefore(deadline)) {
      await Future<void>.delayed(const Duration(milliseconds: 400));
      final refreshed = _findDevice(await runtimeService.listDevices(token), deviceId);
      if (!(refreshed?.agentOnline ?? false)) {
        await _clearManagedAgentPid();
        return true;
      }
    }

    if (!await _isProcessRunning(pid)) {
      await _clearManagedAgentPid();
      return true;
    }
    return false;
  }

  /// 尝试通过 HTTP /stop 优雅关闭 Agent
  Future<bool> _tryHttpStop({required Duration timeout}) async {
    final client = _httpClient ?? DesktopAgentHttpClient();
    try {
      final status = await client.discoverAgent();
      if (status == null || status.port == 0) {
        return false;
      }

      final graceTimeout = timeout.inSeconds.clamp(1, 10);
      final stopSent = await client.sendStop(status.port, graceTimeout: graceTimeout);
      if (!stopSent) {
        return false;
      }

      // 等待 Agent 自行退出
      final deadline = DateTime.now().add(timeout);
      while (DateTime.now().isBefore(deadline)) {
        await Future<void>.delayed(const Duration(milliseconds: 300));
        final health = await client.checkHealth(status.port);
        if (!health) {
          return true;
        }
      }
      return false;
    } catch (_) {
      return false;
    }
  }

  Future<bool> handleDesktopExit({
    required bool keepRunningInBackground,
    required String serverUrl,
    required String token,
    required String deviceId,
    Duration timeout = const Duration(seconds: 8),
  }) async {
    if (keepRunningInBackground) {
      return false;
    }
    final status = await getStatus(
      serverUrl: serverUrl,
      token: token,
      deviceId: deviceId,
    );
    if (!status.managedByDesktop) {
      return false;
    }
    return stopManagedAgent(
      serverUrl: serverUrl,
      token: token,
      deviceId: deviceId,
      timeout: timeout,
    );
  }

  Future<void> clearManagedOwnership() => _clearManagedAgentPid();

  /// managed-agent 配置文件的相对路径（macOS）
  static const String managedAgentConfigRelativePath =
      'Library/Application Support/com.aistudio.rcClient/managed-agent/config.json';

  /// 同步 managed-agent 配置文件（写入最新 token 等凭证）
  ///
  /// 在启动 Agent 进程之前调用，确保 Agent 能读到最新的认证信息。
  /// 返回配置文件的绝对路径。
  Future<String?> syncManagedAgentConfig({
    required String serverUrl,
    required String accessToken,
    required String deviceId,
  }) async {
    if (!supported) return null;
    final home = _homeDirectory ?? Platform.environment['HOME'];
    if (home == null || home.isEmpty) return null;

    try {
      final prefs = await SharedPreferences.getInstance();
      // refresh_token 从 SecureStorage 读取（与 AuthService 使用一致配置）
      const secureStorage = FlutterSecureStorage(
        aOptions: AndroidOptions(encryptedSharedPreferences: true),
        iOptions: IOSOptions(accessibility: KeychainAccessibility.first_unlock),
        mOptions: MacOsOptions(useDataProtectionKeyChain: !kDebugMode),
      );
      final refreshToken = await secureStorage.read(key: 'rc_refresh_token');
      final username = prefs.getString('rc_username');

      final managedConfigFile = File(
        p.join(home, managedAgentConfigRelativePath),
      );
      await managedConfigFile.parent.create(recursive: true);

      final payload = <String, dynamic>{
        'server_url': serverUrl,
        'access_token': accessToken,
        'token': accessToken,
        'device_id': deviceId,
        'command': '/bin/bash',
        'shell_mode': false,
        'auto_reconnect': true,
        'max_retries': 60,
        'reconnect_max_attempts': 60,
        'reconnect_base_delay': 1.0,
        'heartbeat_interval': 30.0,
      };
      if (refreshToken != null && refreshToken.isNotEmpty) {
        payload['refresh_token'] = refreshToken;
      }
      if (username != null && username.isNotEmpty) {
        payload['username'] = username;
      }

      await managedConfigFile.writeAsString(
        const JsonEncoder.withIndent('  ').convert(payload),
        flush: true,
      );
      _logDesktopAgent('syncManagedAgentConfig: wrote $managedConfigFile');
      return managedConfigFile.path;
    } catch (e) {
      _logDesktopAgent('syncManagedAgentConfig: error - $e');
      return null;
    }
  }

  /// 删除 managed-agent 的物理配置文件（含 token 等敏感信息）
  Future<void> deleteManagedAgentConfig() async {
    if (!supported) return;
    final home = _homeDirectory ?? Platform.environment['HOME'];
    if (home == null || home.isEmpty) return;

    final configPath = p.join(home, managedAgentConfigRelativePath);
    try {
      await File(configPath).delete();
      _logDesktopAgent('deleteManagedAgentConfig: deleted $configPath');
    } on FileSystemException catch (_) {
      // 文件不存在，无需处理
    } catch (e) {
      _logDesktopAgent('deleteManagedAgentConfig: error - $e');
    }
  }

  Future<void> syncNativeTerminationState({
    required bool keepRunningInBackground,
  }) async {
    if (!supported) {
      return;
    }
    await DesktopAgentExitBridge.syncKeepRunningInBackground(
      keepRunningInBackground,
    );
    final pid = await _loadManagedAgentPid();
    await DesktopAgentExitBridge.syncManagedAgentPid(pid);
  }

  String? discoverAgentWorkdir({String? preferredWorkdir}) {
    return _resolveAgentWorkdir(preferredWorkdir: preferredWorkdir)?.path;
  }

  Future<bool> _waitForAgentOnline({
    required RuntimeDeviceService runtimeService,
    required String token,
    required String deviceId,
    required Duration timeout,
  }) async {
    final deadline = DateTime.now().add(timeout);
    while (DateTime.now().isBefore(deadline)) {
      await Future<void>.delayed(const Duration(milliseconds: 600));
      final refreshed = _findDevice(await runtimeService.listDevices(token), deviceId);
      if (refreshed?.agentOnline ?? false) {
        return true;
      }
    }
    return false;
  }

  RuntimeDevice? _findDevice(List<RuntimeDevice> devices, String deviceId) {
    for (final device in devices) {
      if (device.deviceId == deviceId) {
        return device;
      }
    }
    return null;
  }

  Future<void> _clearStaleManagedAgentPid() async {
    final pid = await _loadManagedAgentPid();
    if (pid == null) {
      return;
    }
    if (!await _isProcessRunning(pid)) {
      await _clearManagedAgentPid();
    }
  }

  Future<int?> _loadManagedAgentPid() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getInt(_managedAgentPidKey);
  }

  Future<void> _saveManagedAgentPid(int pid) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setInt(_managedAgentPidKey, pid);
    await DesktopAgentExitBridge.syncManagedAgentPid(pid);
  }

  Future<void> _clearManagedAgentPid() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_managedAgentPidKey);
    await DesktopAgentExitBridge.syncManagedAgentPid(null);
  }

  Future<bool> _isProcessRunning(int pid) async {
    try {
      final result =
          await _processRunner('ps', ['-p', '$pid', '-o', 'command=']);
      if (result.exitCode != 0) return false;
      final output = result.stdout.toString().trim();
      return output.contains('app.cli') || output.contains('app\\.cli');
    } catch (_) {
      return false;
    }
  }

  Future<List<int>> _listLocalAgentPids() async {
    if (_processLister != null) {
      return _processLister();
    }
    try {
      final result = await _processRunner('pgrep', ['-f', 'app\\.cli run']);
      if (result.exitCode != 0) {
        return const [];
      }
      final pids = <int>[];
      for (final line in result.stdout.toString().split('\n')) {
        final trimmed = line.trim();
        if (trimmed.isEmpty) {
          continue;
        }
        final pid = int.tryParse(trimmed);
        if (pid != null) {
          pids.add(pid);
        }
      }
      return pids;
    } catch (_) {
      return const [];
    }
  }

  Future<void> _terminateProcess(
    int pid, {
    Duration gracePeriod = const Duration(seconds: 2),
  }) async {
    _pidKiller(pid, ProcessSignal.sigterm);
    final deadline = DateTime.now().add(gracePeriod);
    while (DateTime.now().isBefore(deadline)) {
      if (!await _isProcessRunning(pid)) {
        return;
      }
      await Future<void>.delayed(const Duration(milliseconds: 150));
    }
    if (await _isProcessRunning(pid)) {
      _pidKiller(pid, ProcessSignal.sigkill);
    }
  }

  Future<void> _captureManagedRuntimeOutput(Process process) async {
    try {
      unawaited(
        process.stdout
            .transform(utf8.decoder)
            .transform(const LineSplitter())
            .forEach((line) => _logManagedRuntime('stdout $line')),
      );
    } catch (_) {}
    try {
      unawaited(
        process.stderr
            .transform(utf8.decoder)
            .transform(const LineSplitter())
            .forEach((line) => _logManagedRuntime('stderr $line')),
      );
    } catch (_) {}
  }

  Directory? _resolveAgentWorkdir({String? preferredWorkdir}) {
    _logDesktopAgent('_resolveAgentWorkdir: preferredWorkdir=$preferredWorkdir');
    for (final candidate in _candidateAgentDirs(preferredWorkdir: preferredWorkdir)) {
      final looksLike = _looksLikeAgentDir(candidate);
      _logDesktopAgent('_resolveAgentWorkdir: checking ${candidate.path}, looksLike=$looksLike');
      if (looksLike) {
        _logDesktopAgent('_resolveAgentWorkdir: resolved ${candidate.path}');
        return candidate;
      }
    }
    _logDesktopAgent('_resolveAgentWorkdir: no valid workdir found');
    return null;
  }

  Iterable<Directory> _candidateAgentDirs({String? preferredWorkdir}) sync* {
    _logDesktopAgent('_candidateAgentDirs: preferredWorkdir=$preferredWorkdir');
    _logDesktopAgent('_candidateAgentDirs: current=${Directory.current.path}');
    _logDesktopAgent('_candidateAgentDirs: resolvedExecutable=${Platform.resolvedExecutable}');

    if (preferredWorkdir != null && preferredWorkdir.isNotEmpty) {
      yield Directory(preferredWorkdir);
    }

    final envOverride = Platform.environment['RC_AGENT_WORKDIR'];
    if (envOverride != null && envOverride.isNotEmpty) {
      yield Directory(envOverride);
    }

    final executableDir = _resolveExecutableDirectory();
    _logDesktopAgent('_candidateAgentDirs: executableDir=${executableDir?.path}');
    if (executableDir != null) {
      yield* _searchAgentDirsFrom(executableDir);
    }

    yield* _searchAgentDirsFrom(Directory.current);
  }

  Directory? _resolveExecutableDirectory() {
    try {
      final executable = File(Platform.resolvedExecutable);
      if (executable.existsSync()) {
        return executable.parent;
      }
    } catch (_) {}
    return null;
  }

  Iterable<Directory> _searchAgentDirsFrom(Directory start) sync* {
    var cursor = start.absolute;
    for (var i = 0; i < 16; i++) {
      yield Directory(p.join(cursor.path, 'agent'));
      yield Directory(p.join(cursor.path, 'remote-control', 'agent'));
      if (cursor.parent.path != cursor.path) {
        yield Directory(p.join(cursor.parent.path, 'agent'));
      }
      if (cursor.parent.path == cursor.path) {
        break;
      }
      cursor = cursor.parent;
    }
  }

  bool _looksLikeAgentDir(Directory dir) {
    return dir.existsSync() && File(p.join(dir.path, 'app', 'cli.py')).existsSync();
  }
}
