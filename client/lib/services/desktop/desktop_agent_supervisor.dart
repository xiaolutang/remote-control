import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:path/path.dart' as p;
import 'package:shared_preferences/shared_preferences.dart';

import '../../models/config.dart';
import '../../models/runtime_device.dart';
import '../app_logger.dart';
import 'desktop_agent_http_client.dart';
import 'desktop_termination_snapshot_service.dart';
import '../runtime_device_service.dart';
import '../../modules/desktop_permissions/secure_storage_service.dart';

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

final AppLogger _logAgent = AppLogger('DesktopAgent');
final AppLogger _logRuntime = AppLogger('ManagedRuntime');

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

class _AgentProcessInfo {
  const _AgentProcessInfo({
    required this.pid,
    required this.commandLine,
  });

  final int pid;
  final String commandLine;
}

class DesktopAgentSupervisor {
  DesktopAgentSupervisor({
    RuntimeDeviceService? runtimeService,
    AgentProcessStarter? processStarter,
    AgentProcessStarter? sleepInhibitorStarter,
    AgentProcessRunner? processRunner,
    AgentPidKiller? pidKiller,
    AgentProcessLister? processLister,
    DesktopAgentHttpClient? httpClient,
    SecureStorageService? secureStorageService,
    DesktopTerminationSnapshotService? terminationSnapshotService,
    String? homeDirectory,
    bool preventSleepWhileManagedAgentRuns = true,
  })  : _runtimeService = runtimeService,
        _processStarter = processStarter ?? Process.start,
        _sleepInhibitorStarter = sleepInhibitorStarter ?? Process.start,
        _processStarterIsDefault = processStarter == null,
        _sleepInhibitorStarterIsDefault = sleepInhibitorStarter == null,
        _processRunner = processRunner ?? Process.run,
        _pidKiller = pidKiller ?? Process.killPid,
        _processLister = processLister,
        _httpClient = httpClient,
        _secureStorage = secureStorageService ?? SecureStorageService.instance,
        _terminationSnapshotService =
            terminationSnapshotService ?? DesktopTerminationSnapshotService(),
        _homeDirectory = homeDirectory,
        _preventSleepWhileManagedAgentRuns = preventSleepWhileManagedAgentRuns;

  final RuntimeDeviceService? _runtimeService;
  final AgentProcessStarter _processStarter;
  final AgentProcessStarter _sleepInhibitorStarter;
  final bool _processStarterIsDefault;
  final bool _sleepInhibitorStarterIsDefault;
  final AgentProcessRunner _processRunner;
  final AgentPidKiller _pidKiller;
  final AgentProcessLister? _processLister;
  final DesktopAgentHttpClient? _httpClient;
  final SecureStorageService _secureStorage;
  final DesktopTerminationSnapshotService _terminationSnapshotService;
  final String? _homeDirectory;
  final bool _preventSleepWhileManagedAgentRuns;
  Future<bool>? _pendingEnsureFuture;
  String? _pendingEnsureKey;
  int? _sleepInhibitorAttachedAgentPid;
  SharedPreferences? _prefs;

  Future<SharedPreferences> _ensurePrefs() async =>
      _prefs ??= await SharedPreferences.getInstance();

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
    final managedRunning =
        managedPid != null && await _isManagedProcessRunning(managedPid);
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
    Duration timeout = TimingConstants.agentStartTimeout,
    String? agentWorkdir,
    String? agentConfigPath,
  }) {
    return _runEnsureSingleFlight(
      serverUrl: serverUrl,
      deviceId: deviceId,
      agentWorkdir: agentWorkdir,
      operation: () => _ensureAgentOnlineInternal(
        serverUrl: serverUrl,
        token: token,
        deviceId: deviceId,
        timeout: timeout,
        agentWorkdir: agentWorkdir,
        agentConfigPath: agentConfigPath,
      ),
    );
  }

  Future<bool> _ensureAgentOnlineInternal({
    required String serverUrl,
    required String token,
    required String deviceId,
    Duration timeout = TimingConstants.agentStartTimeout,
    String? agentWorkdir,
    String? agentConfigPath,
  }) async {
    _logAgent.info(
      'ensureAgentOnline start device=$deviceId supported=$supported workdir_arg=${agentWorkdir ?? ''}',
    );
    if (!supported) {
      _logAgent.info('ensureAgentOnline unsupported platform');
      return false;
    }

    final runtimeService =
        _runtimeService ?? RuntimeDeviceService(serverUrl: serverUrl);

    final before =
        _findDevice(await runtimeService.listDevices(token), deviceId);
    _logAgent.info(
      'ensureAgentOnline before agentOnline=${before?.agentOnline ?? false}',
    );
    if (before?.agentOnline ?? false) {
      await _reconcileManagedAgentProcesses();
      final managedPid = await _loadManagedAgentPid();
      if (managedPid != null && await _isManagedProcessRunning(managedPid)) {
        await _ensureSleepInhibitedForManagedAgent(managedPid);
      }
      _logAgent.info('ensureAgentOnline device already online');
      return true;
    }

    final managedPid = await _loadManagedAgentPid();
    _logAgent.info('ensureAgentOnline managedPid=${managedPid ?? -1}');
    if (managedPid != null) {
      if (await _isManagedProcessRunning(managedPid)) {
        _logAgent
            .info('ensureAgentOnline waiting existing managed pid=$managedPid');
        final recovered = await _waitForAgentOnline(
          runtimeService: runtimeService,
          token: token,
          deviceId: deviceId,
          timeout: timeout,
        );
        _logAgent.info(
          'ensureAgentOnline existing managed wait result=$recovered',
        );
        if (recovered) {
          await _ensureSleepInhibitedForManagedAgent(managedPid);
          return true;
        }
        _logAgent.info(
          'ensureAgentOnline existing managed pid stale, terminating and restarting',
        );
        await _terminateProcess(managedPid);
        await _clearManagedAgentPid();
      } else {
        await _clearManagedAgentPid();
        _logAgent.info('ensureAgentOnline cleared stale managed pid');
      }
    }

    final existingLocalAgents = await _listLocalAgentProcesses();
    _logAgent.info(
      'ensureAgentOnline existingLocalAgents=${existingLocalAgents.map((p) => p.pid).join(",")}',
    );
    if (existingLocalAgents.isNotEmpty) {
      final managedPid = await _pruneDuplicateManagedAgents(
        existingLocalAgents,
      );
      _logAgent.info('ensureAgentOnline waiting existing external agent');
      final recovered = await _waitForAgentOnline(
        runtimeService: runtimeService,
        token: token,
        deviceId: deviceId,
        timeout: timeout,
      );
      if (recovered && managedPid != null) {
        await _saveManagedAgentPid(managedPid);
        await _ensureSleepInhibitedForManagedAgent(managedPid);
      }
      return recovered;
    }

    final workdir = _resolveAgentWorkdir(preferredWorkdir: agentWorkdir);
    if (workdir == null) {
      _logAgent.info('ensureAgentOnline no workdir resolved');
      return false;
    }
    _logAgent.info('ensureAgentOnline resolved workdir=${workdir.path}');

    // 检测是否为 bundled agent（包含 rc-agent 二进制）
    final isBundled = _isBundledAgentDir(workdir);
    _logAgent.info('ensureAgentOnline isBundled=$isBundled');

    try {
      Process process;
      if (isBundled) {
        // 使用内嵌 rc-agent 二进制启动
        final rcAgentPath = p.join(workdir.path, 'rc-agent');
        _logAgent
            .info('ensureAgentOnline starting bundled agent: $rcAgentPath');
        try {
          process = await _processStarter(
            rcAgentPath,
            <String>[
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
        } catch (e) {
          // bundled agent 启动失败，回退到源码模式
          _logAgent.info(
              'ensureAgentOnline bundled agent failed: $e, falling back to python3');
          process = await _processStarter(
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
        }
      } else {
        // 回退到 python3 源码模式（向后兼容开发环境）
        _logAgent.info('ensureAgentOnline starting python3 source mode');
        process = await _processStarter(
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
      }
      await _saveManagedAgentPid(process.pid);
      await _ensureSleepInhibitedForManagedAgent(process.pid);
      _logAgent.info('ensureAgentOnline started pid=${process.pid}');
      unawaited(_captureManagedRuntimeOutput(process));
    } catch (e) {
      _logAgent.info('ensureAgentOnline process start failed: $e');
      return false;
    }

    final online = await _waitForAgentOnline(
      runtimeService: runtimeService,
      token: token,
      deviceId: deviceId,
      timeout: timeout,
    );
    _logAgent.info('ensureAgentOnline wait result=$online');
    if (!online) {
      await stopManagedAgent(
        serverUrl: serverUrl,
        token: token,
        deviceId: deviceId,
        timeout: TimingConstants.agentGracePeriod,
      );
      _logAgent.info('ensureAgentOnline stopManagedAgent after failed wait');
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
    Duration timeout = TimingConstants.agentStartTimeout,
    String? agentWorkdir,
  }) {
    return _runEnsureSingleFlight(
      serverUrl: serverUrl,
      deviceId: deviceId,
      agentWorkdir: agentWorkdir,
      operation: () async {
        _logAgent.info('syncAndEnsureOnline start device=$deviceId');
        final configPath = await syncManagedAgentConfig(
          serverUrl: serverUrl,
          accessToken: accessToken,
          deviceId: deviceId,
        );
        _logAgent.info(
          'syncAndEnsureOnline configPath=${configPath ?? ""}',
        );
        return _ensureAgentOnlineInternal(
          serverUrl: serverUrl,
          token: accessToken,
          deviceId: deviceId,
          timeout: timeout,
          agentWorkdir: agentWorkdir,
          agentConfigPath: configPath,
        );
      },
    );
  }

  Future<bool> _runEnsureSingleFlight({
    required String serverUrl,
    required String deviceId,
    required Future<bool> Function() operation,
    String? agentWorkdir,
  }) {
    final key = '$serverUrl|$deviceId|${agentWorkdir ?? ''}';
    final pending = _pendingEnsureFuture;
    if (pending != null && _pendingEnsureKey == key) {
      _logAgent.info('ensure single-flight join existing attempt key=$key');
      return pending;
    }

    final future = operation();
    _pendingEnsureFuture = future;
    _pendingEnsureKey = key;
    future.whenComplete(() {
      if (identical(_pendingEnsureFuture, future)) {
        _pendingEnsureFuture = null;
        _pendingEnsureKey = null;
      }
    });
    return future;
  }

  Future<bool> stopManagedAgent({
    required String serverUrl,
    required String token,
    required String deviceId,
    Duration timeout = TimingConstants.agentStopTimeout,
  }) async {
    // Explicit stop cancels any stale in-flight start bookkeeping.
    _pendingEnsureFuture = null;
    _pendingEnsureKey = null;

    if (!supported) {
      return false;
    }

    final pid = await _loadManagedAgentPid();
    if (pid == null) {
      final orphanedPids = await _listLocalManagedAgentPids();
      if (orphanedPids.isEmpty) {
        return false;
      }
      _logAgent.info(
        'stopManagedAgent found orphaned managed agents=${orphanedPids.join(",")}',
      );
      return _stopManagedAgentPids(orphanedPids, timeout: timeout);
    }

    if (!await _isManagedProcessRunning(pid)) {
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
      await Future<void>.delayed(TimingConstants.agentStopPollInterval);
      final refreshed =
          _findDevice(await runtimeService.listDevices(token), deviceId);
      if (!(refreshed?.agentOnline ?? false)) {
        await _clearManagedAgentPid();
        return true;
      }
    }

    if (!await _isManagedProcessRunning(pid)) {
      await _clearManagedAgentPid();
      return true;
    }
    return false;
  }

  Future<bool> _stopManagedAgentPids(
    List<int> pids, {
    required Duration timeout,
  }) async {
    final httpStopped = await _tryHttpStop(timeout: timeout);
    if (httpStopped) {
      final remaining = <int>[];
      for (final pid in pids) {
        if (await _isManagedProcessRunning(pid)) {
          remaining.add(pid);
        }
      }
      if (remaining.isEmpty) {
        await _clearManagedAgentPid();
        return true;
      }
      pids = remaining;
    }

    for (final pid in pids) {
      if (await _isManagedProcessRunning(pid)) {
        await _terminateProcess(pid);
      }
    }

    for (final pid in pids) {
      if (await _isManagedProcessRunning(pid)) {
        return false;
      }
    }
    await _clearManagedAgentPid();
    return true;
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
      final stopSent =
          await client.sendStop(status.port, graceTimeout: graceTimeout);
      if (!stopSent) {
        return false;
      }

      // 等待 Agent 自行退出
      final deadline = DateTime.now().add(timeout);
      while (DateTime.now().isBefore(deadline)) {
        await Future<void>.delayed(TimingConstants.agentHttpStopPollInterval);
        final health = await client.checkHealth(status.port);
        if (!health) {
          return true;
        }
      }
      return false;
    } catch (e) {
      _logAgent.info('_tryHttpStop failed: $e');
      return false;
    }
  }

  Future<bool> handleDesktopExit({
    required bool keepRunningInBackground,
    required String serverUrl,
    required String token,
    required String deviceId,
    Duration timeout = TimingConstants.agentStopTimeout,
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
      final prefs = await _ensurePrefs();
      final resolvedRefreshToken =
          await _secureStorage.read(SecureStorageService.refreshTokenKey);
      final username = prefs.getString('rc_username');

      final managedConfigFile = File(
        _managedAgentConfigPath(home),
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
      if (resolvedRefreshToken != null && resolvedRefreshToken.isNotEmpty) {
        payload['refresh_token'] = resolvedRefreshToken;
      }
      if (username != null && username.isNotEmpty) {
        payload['username'] = username;
      }

      await managedConfigFile.writeAsString(
        const JsonEncoder.withIndent('  ').convert(payload),
        flush: true,
      );
      _logAgent.info('syncManagedAgentConfig: wrote $managedConfigFile');
      return managedConfigFile.path;
    } catch (e) {
      _logAgent.info('syncManagedAgentConfig: error - $e');
      return null;
    }
  }

  /// 删除 managed-agent 的物理配置文件（含 token 等敏感信息）
  Future<void> deleteManagedAgentConfig() async {
    if (!supported) return;
    final home = _homeDirectory ?? Platform.environment['HOME'];
    if (home == null || home.isEmpty) return;

    final configPath = _managedAgentConfigPath(home);
    try {
      await File(configPath).delete();
      _logAgent.info('deleteManagedAgentConfig: deleted $configPath');
    } on FileSystemException catch (e) {
      _logAgent.info('deleteManagedAgentConfig file not found: $e');
      // 文件不存在，无需处理
    } catch (e) {
      _logAgent.info('deleteManagedAgentConfig: error - $e');
    }
  }

  Future<void> syncNativeTerminationState({
    required bool keepRunningInBackground,
  }) async {
    if (!supported) {
      return;
    }
    await _terminationSnapshotService.syncCurrentSnapshot(
      keepRunningInBackground: keepRunningInBackground,
    );
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
      await Future<void>.delayed(TimingConstants.agentOnlinePollInterval);
      final refreshed =
          _findDevice(await runtimeService.listDevices(token), deviceId);
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
    if (!await _isManagedProcessRunning(pid)) {
      await _clearManagedAgentPid();
    }
  }

  Future<void> _reconcileManagedAgentProcesses() async {
    await _clearStaleManagedAgentPid();
    final processes = await _listLocalAgentProcesses();
    final managedPid = await _pruneDuplicateManagedAgents(processes);
    if (managedPid != null) {
      await _saveManagedAgentPid(managedPid);
    }
  }

  Future<void> _ensureSleepInhibitedForManagedAgent(int agentPid) async {
    if (!_preventSleepWhileManagedAgentRuns || !Platform.isMacOS) {
      return;
    }
    if (_sleepInhibitorAttachedAgentPid == agentPid) {
      return;
    }
    // Tests often inject a fake agent starter; do not launch a real
    // caffeinate process unless production Process.start is in use or the
    // test explicitly injects a sleep inhibitor starter.
    if (!_processStarterIsDefault && _sleepInhibitorStarterIsDefault) {
      return;
    }
    try {
      final inhibitor = await _sleepInhibitorStarter(
        'caffeinate',
        <String>[
          // Keep CPU/disk awake while allowing display sleep.
          '-im',
          '-w',
          '$agentPid',
        ],
        mode: ProcessStartMode.detached,
      );
      _sleepInhibitorAttachedAgentPid = agentPid;
      _logAgent.info(
        'started sleep inhibitor pid=${inhibitor.pid} agentPid=$agentPid',
      );
    } catch (e) {
      _logAgent.info('failed to start sleep inhibitor for pid=$agentPid: $e');
    }
  }

  Future<int?> _loadManagedAgentPid() async {
    return _terminationSnapshotService.loadManagedAgentPid();
  }

  Future<void> _saveManagedAgentPid(int pid) async {
    await _terminationSnapshotService.saveManagedAgentPid(pid);
  }

  Future<void> _clearManagedAgentPid() async {
    _sleepInhibitorAttachedAgentPid = null;
    await _terminationSnapshotService.clearManagedAgentPid();
  }

  Future<bool> _isProcessRunning(int pid) =>
      _isPidMatching(pid, isAgentRunCommand);

  Future<bool> _isManagedProcessRunning(int pid) =>
      _isPidMatching(pid, _isManagedConfigCommand);

  Future<bool> _isPidMatching(
    int pid,
    bool Function(String) classifier,
  ) async {
    try {
      final output = await _commandLineForPid(pid);
      return output != null && classifier(output);
    } catch (e) {
      _logAgent.info('_isPidMatching failed: $e');
      return false;
    }
  }

  Future<String?> _commandLineForPid(int pid) async {
    final result = await _processRunner('ps', ['-p', '$pid', '-o', 'command=']);
    if (result.exitCode != 0) return null;
    return result.stdout.toString().trim();
  }

  /// 共享命令行分类器：判断命令行是否为 Agent 常驻 run 进程。
  ///
  /// 识别两种模式：
  /// - `rc-agent ... run`（bundled 二进制模式）
  /// - `python3 -m app.cli ... run`（源码模式）
  ///
  /// 排除 `rc-agent login/status/configure` 和
  /// `python3 -m app.cli login/status/configure` 等非 daemon 命令。
  static bool isAgentRunCommand(String commandLine) {
    final trimmed = commandLine.trim();
    if (trimmed.isEmpty) return false;

    // 按空白拆分命令行 token，取第一个作为可执行路径
    final tokens = trimmed.split(RegExp(r'\s+'));
    if (tokens.isEmpty) return false;

    final executable = tokens.first;
    final basename = p.basename(executable);

    // 判断最后一个 token 是否为 "run" 子命令
    final lastArg = tokens.last;
    if (lastArg != 'run') return false;

    // Bundled 模式：可执行文件名为 rc-agent
    if (basename == 'rc-agent') return true;

    // 源码模式：python3 -m app.cli ... run
    if (basename == 'python3' || basename == 'python' || basename == 'Python') {
      // 检查命令行是否包含 -m app.cli
      var i = 1;
      while (i < tokens.length - 1) {
        if (tokens[i] == '-m' &&
            i + 1 < tokens.length &&
            tokens[i + 1] == 'app.cli') {
          return true;
        }
        i++;
      }
    }

    return false;
  }

  Future<List<int>> _listLocalManagedAgentPids() async {
    final processes = await _listLocalAgentProcesses();
    return processes
        .where((process) => _isManagedConfigCommand(process.commandLine))
        .map((process) => process.pid)
        .toList();
  }

  Future<List<_AgentProcessInfo>> _listLocalAgentProcesses() async {
    if (_processLister != null) {
      final pids = await _processLister();
      return [
        for (final pid in pids) _AgentProcessInfo(pid: pid, commandLine: ''),
      ];
    }
    try {
      final seenPids = <int>{};
      final processes = <_AgentProcessInfo>[];

      // 粗粒度 pgrep 获取 rc-agent 相关 PID
      // 不依赖 \b 等 macOS/BSD pgrep 不可靠的模式
      final results = await Future.wait<ProcessResult>([
        _processRunner('pgrep', ['-f', 'rc-agent']),
        _processRunner('pgrep', ['-f', 'app\\.cli']),
      ]);
      for (final result in results) {
        if (result.exitCode == 0) {
          await _verifyAndAddPids(
            result.stdout.toString(),
            processes,
            seenPids,
          );
        }
      }

      return processes;
    } catch (e) {
      _logAgent.info('_listLocalAgentPids failed: $e');
      return const [];
    }
  }

  /// 解析 pgrep 输出中的 PID，用 `ps -p {pid} -o command=` 获取完整命令行，
  /// 再用共享分类器 [isAgentRunCommand] 过滤非 daemon 进程。
  Future<void> _verifyAndAddPids(
    String pgrepOutput,
    List<_AgentProcessInfo> processes,
    Set<int> seenPids,
  ) async {
    for (final line in pgrepOutput.split('\n')) {
      final trimmed = line.trim();
      if (trimmed.isEmpty) continue;
      final pid = int.tryParse(trimmed);
      if (pid == null || seenPids.contains(pid)) continue;
      seenPids.add(pid);

      try {
        final psResult = await _processRunner(
          'ps',
          ['-p', '$pid', '-o', 'command='],
        );
        if (psResult.exitCode != 0) continue;
        final commandLine = psResult.stdout.toString().trim();
        if (isAgentRunCommand(commandLine)) {
          processes.add(
            _AgentProcessInfo(pid: pid, commandLine: commandLine),
          );
        }
      } catch (e) {
        _logAgent.info('_verifyAndAddPids ps failed for pid=$pid: $e');
        // ps 调用失败，跳过此 PID
      }
    }
  }

  Future<int?> _pruneDuplicateManagedAgents(
    List<_AgentProcessInfo> processes,
  ) async {
    final managed = processes
        .where((process) => _isManagedConfigCommand(process.commandLine))
        .toList();
    if (managed.isEmpty) return null;
    managed.sort((a, b) => a.pid.compareTo(b.pid));
    final keep = managed.removeAt(0);
    if (managed.isEmpty) return keep.pid;
    _logAgent.info(
      'prune duplicate managed agents keep=${keep.pid} kill=${managed.map((p) => p.pid).join(",")}',
    );
    for (final process in managed) {
      if (await _isManagedProcessRunning(process.pid)) {
        await _terminateProcess(process.pid);
      }
    }
    return keep.pid;
  }

  // Mirror: AppDelegate.swift isManagedAgentRunCommand — 修改匹配规则时必须同步
  bool _isManagedConfigCommand(String commandLine) {
    if (commandLine.isEmpty) return false;
    final home = _homeDirectory ?? Platform.environment['HOME'];
    if (home == null || home.isEmpty) return false;
    final trimmed = commandLine.trim();
    if (!isAgentRunCommand(trimmed)) return false;
    final configPath = _managedAgentConfigPath(home);
    return trimmed.contains('--config $configPath ');
  }

  String _managedAgentConfigPath(String home) =>
      p.join(home, managedAgentConfigRelativePath);

  Future<void> _terminateProcess(
    int pid, {
    Duration gracePeriod = TimingConstants.agentGracePeriod,
  }) async {
    if (_sleepInhibitorAttachedAgentPid == pid) {
      _sleepInhibitorAttachedAgentPid = null;
    }
    _pidKiller(pid, ProcessSignal.sigterm);
    final deadline = DateTime.now().add(gracePeriod);
    while (DateTime.now().isBefore(deadline)) {
      if (!await _isProcessRunning(pid)) {
        return;
      }
      await Future<void>.delayed(TimingConstants.agentTerminatePollInterval);
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
            .forEach((line) => _logRuntime.info('stdout $line')),
      );
    } catch (e) {
      _logRuntime.info('_captureManagedRuntimeOutput stdout failed: $e');
    }
    try {
      unawaited(
        process.stderr
            .transform(utf8.decoder)
            .transform(const LineSplitter())
            .forEach((line) => _logRuntime.info('stderr $line')),
      );
    } catch (e) {
      _logRuntime.info('_captureManagedRuntimeOutput stderr failed: $e');
    }
  }

  Directory? _resolveAgentWorkdir({String? preferredWorkdir}) {
    _logAgent.info('_resolveAgentWorkdir: preferredWorkdir=$preferredWorkdir');
    for (final candidate
        in _candidateAgentDirs(preferredWorkdir: preferredWorkdir)) {
      final looksLike = _looksLikeAgentDir(candidate);
      _logAgent.info(
          '_resolveAgentWorkdir: checking ${candidate.path}, looksLike=$looksLike');
      if (looksLike) {
        _logAgent.info('_resolveAgentWorkdir: resolved ${candidate.path}');
        return candidate;
      }
    }
    _logAgent.info('_resolveAgentWorkdir: no valid workdir found');
    return null;
  }

  /// 判断目录是否为 bundled agent（包含 rc-agent 二进制）
  bool _isBundledAgentDir(Directory dir) {
    return _looksLikeBundledAgent(dir);
  }

  Iterable<Directory> _candidateAgentDirs({String? preferredWorkdir}) sync* {
    _logAgent.info('_candidateAgentDirs: preferredWorkdir=$preferredWorkdir');
    _logAgent.info('_candidateAgentDirs: current=${Directory.current.path}');
    _logAgent.info(
        '_candidateAgentDirs: resolvedExecutable=${Platform.resolvedExecutable}');

    // 最高优先级：检查 .app bundle 内嵌 Agent（Contents/Resources/agent/）
    final bundledAgentDir = _resolveBundledAgentDir();
    if (bundledAgentDir != null) {
      _logAgent
          .info('_candidateAgentDirs: bundledAgentDir=${bundledAgentDir.path}');
      yield bundledAgentDir;
    }

    if (preferredWorkdir != null && preferredWorkdir.isNotEmpty) {
      yield Directory(preferredWorkdir);
    }

    final envOverride = Platform.environment['RC_AGENT_WORKDIR'];
    if (envOverride != null && envOverride.isNotEmpty) {
      yield Directory(envOverride);
    }

    final executableDir = _resolveExecutableDirectory();
    _logAgent.info('_candidateAgentDirs: executableDir=${executableDir?.path}');
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
    } catch (e) {
      _logAgent.info('_resolveExecutableDirectory failed: $e');
    }
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
    return dir.existsSync() &&
        (File(p.join(dir.path, 'app', 'cli.py')).existsSync() ||
            _looksLikeBundledAgent(dir));
  }

  /// 检查目录是否包含内嵌的 rc-agent 二进制
  bool _looksLikeBundledAgent(Directory dir) {
    if (!dir.existsSync()) return false;
    final rcAgent = File(p.join(dir.path, 'rc-agent'));
    if (!rcAgent.existsSync()) return false;
    try {
      final stat = rcAgent.statSync();
      if (stat.type != FileSystemEntityType.file) return false;
      // 校验可执行权限（Unix: owner/group/other 任一有 x 位）
      return (stat.mode & 0x111) != 0;
    } catch (e) {
      _logAgent.info('_looksLikeBundledAgent stat failed: $e');
      return false;
    }
  }

  /// 从 .app bundle 可执行文件路径解析出 Contents/Resources/agent/ 目录
  /// [resolvedExecutableProvider] 可注入，用于测试；默认使用 Platform.resolvedExecutable
  Directory? _resolveBundledAgentDir({
    String Function()? resolvedExecutableProvider,
  }) {
    try {
      final resolved =
          (resolvedExecutableProvider ?? () => Platform.resolvedExecutable)();
      // macOS .app bundle 结构：xxx.app/Contents/MacOS/{executable}
      // 内嵌 Agent 位于：xxx.app/Contents/Resources/agent/
      if (resolved.contains('.app/Contents/MacOS/')) {
        final appBundleRoot = resolved.substring(
          0,
          resolved.indexOf('.app/Contents/MacOS/') + '.app'.length,
        );
        final resourcesAgentDir = Directory(
          p.join(appBundleRoot, 'Contents', 'Resources', 'agent'),
        );
        if (_looksLikeBundledAgent(resourcesAgentDir)) {
          return resourcesAgentDir;
        }
      }
    } catch (e) {
      _logAgent.info('_resolveBundledAgentDir failed: $e');
    }
    return null;
  }
}
