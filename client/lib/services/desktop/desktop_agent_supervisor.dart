import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:path/path.dart' as p;
import 'package:shared_preferences/shared_preferences.dart';

import '../../models/runtime_device.dart';
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
    SecureStorageService? secureStorageService,
    DesktopTerminationSnapshotService? terminationSnapshotService,
    String? homeDirectory,
  })  : _runtimeService = runtimeService,
        _processStarter = processStarter ?? Process.start,
        _processRunner = processRunner ?? Process.run,
        _pidKiller = pidKiller ?? Process.killPid,
        _processLister = processLister,
        _httpClient = httpClient,
        _secureStorage = secureStorageService ?? SecureStorageService.instance,
        _terminationSnapshotService =
            terminationSnapshotService ?? DesktopTerminationSnapshotService(),
        _homeDirectory = homeDirectory;

  final RuntimeDeviceService? _runtimeService;
  final AgentProcessStarter _processStarter;
  final AgentProcessRunner _processRunner;
  final AgentPidKiller _pidKiller;
  final AgentProcessLister? _processLister;
  final DesktopAgentHttpClient? _httpClient;
  final SecureStorageService _secureStorage;
  final DesktopTerminationSnapshotService _terminationSnapshotService;
  final String? _homeDirectory;
  Future<bool>? _pendingEnsureFuture;
  String? _pendingEnsureKey;

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
        managedPid != null && await _isProcessRunning(managedPid);
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

    final before =
        _findDevice(await runtimeService.listDevices(token), deviceId);
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
        _logDesktopAgent(
            'ensureAgentOnline waiting existing managed pid=$managedPid');
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

    // 检测是否为 bundled agent（包含 rc-agent 二进制）
    final isBundled = _isBundledAgentDir(workdir);
    _logDesktopAgent('ensureAgentOnline isBundled=$isBundled');

    try {
      Process process;
      if (isBundled) {
        // 使用内嵌 rc-agent 二进制启动
        final rcAgentPath = p.join(workdir.path, 'rc-agent');
        _logDesktopAgent(
            'ensureAgentOnline starting bundled agent: $rcAgentPath');
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
          _logDesktopAgent(
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
        _logDesktopAgent(
            'ensureAgentOnline starting python3 source mode');
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
  }) {
    return _runEnsureSingleFlight(
      serverUrl: serverUrl,
      deviceId: deviceId,
      agentWorkdir: agentWorkdir,
      operation: () async {
        _logDesktopAgent('syncAndEnsureOnline start device=$deviceId');
        final configPath = await syncManagedAgentConfig(
          serverUrl: serverUrl,
          accessToken: accessToken,
          deviceId: deviceId,
        );
        _logDesktopAgent(
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
      _logDesktopAgent('ensure single-flight join existing attempt key=$key');
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
    Duration timeout = const Duration(seconds: 8),
  }) async {
    // Explicit stop cancels any stale in-flight start bookkeeping.
    _pendingEnsureFuture = null;
    _pendingEnsureKey = null;

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
      final refreshed =
          _findDevice(await runtimeService.listDevices(token), deviceId);
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
      final stopSent =
          await client.sendStop(status.port, graceTimeout: graceTimeout);
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
      final resolvedRefreshToken =
          await _secureStorage.read(SecureStorageService.refreshTokenKey);
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
      await Future<void>.delayed(const Duration(milliseconds: 600));
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
    if (!await _isProcessRunning(pid)) {
      await _clearManagedAgentPid();
    }
  }

  Future<int?> _loadManagedAgentPid() async {
    return _terminationSnapshotService.loadManagedAgentPid();
  }

  Future<void> _saveManagedAgentPid(int pid) async {
    await _terminationSnapshotService.saveManagedAgentPid(pid);
  }

  Future<void> _clearManagedAgentPid() async {
    await _terminationSnapshotService.clearManagedAgentPid();
  }

  Future<bool> _isProcessRunning(int pid) async {
    try {
      final result =
          await _processRunner('ps', ['-p', '$pid', '-o', 'command=']);
      if (result.exitCode != 0) return false;
      final output = result.stdout.toString().trim();
      return isAgentRunCommand(output);
    } catch (_) {
      return false;
    }
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
    if (basename == 'python3' || basename == 'python') {
      // 检查命令行是否包含 -m app.cli
      var i = 1;
      while (i < tokens.length - 1) {
        if (tokens[i] == '-m' && i + 1 < tokens.length && tokens[i + 1] == 'app.cli') {
          return true;
        }
        i++;
      }
    }

    return false;
  }

  Future<List<int>> _listLocalAgentPids() async {
    if (_processLister != null) {
      return _processLister();
    }
    try {
      final pids = <int>[];
      final seenPids = <int>{};

      // 粗粒度 pgrep 获取 rc-agent 相关 PID
      // 不依赖 \b 等 macOS/BSD pgrep 不可靠的模式
      final rcAgentResult =
          await _processRunner('pgrep', ['-f', 'rc-agent']);
      if (rcAgentResult.exitCode == 0) {
        await _verifyAndAddPids(
          rcAgentResult.stdout.toString(),
          pids,
          seenPids,
        );
      }

      // 粗粒度 pgrep 获取 app.cli 相关 PID
      final cliResult =
          await _processRunner('pgrep', ['-f', 'app\\.cli']);
      if (cliResult.exitCode == 0) {
        await _verifyAndAddPids(
          cliResult.stdout.toString(),
          pids,
          seenPids,
        );
      }

      return pids;
    } catch (_) {
      return const [];
    }
  }

  /// 解析 pgrep 输出中的 PID，用 `ps -p {pid} -o command=` 获取完整命令行，
  /// 再用共享分类器 [isAgentRunCommand] 过滤非 daemon 进程。
  Future<void> _verifyAndAddPids(
    String pgrepOutput,
    List<int> pids,
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
          pids.add(pid);
        }
      } catch (_) {
        // ps 调用失败，跳过此 PID
      }
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
    _logDesktopAgent(
        '_resolveAgentWorkdir: preferredWorkdir=$preferredWorkdir');
    for (final candidate
        in _candidateAgentDirs(preferredWorkdir: preferredWorkdir)) {
      final looksLike = _looksLikeAgentDir(candidate);
      _logDesktopAgent(
          '_resolveAgentWorkdir: checking ${candidate.path}, looksLike=$looksLike');
      if (looksLike) {
        _logDesktopAgent('_resolveAgentWorkdir: resolved ${candidate.path}');
        return candidate;
      }
    }
    _logDesktopAgent('_resolveAgentWorkdir: no valid workdir found');
    return null;
  }

  /// 判断目录是否为 bundled agent（包含 rc-agent 二进制）
  bool _isBundledAgentDir(Directory dir) {
    return _looksLikeBundledAgent(dir);
  }

  Iterable<Directory> _candidateAgentDirs({String? preferredWorkdir}) sync* {
    _logDesktopAgent('_candidateAgentDirs: preferredWorkdir=$preferredWorkdir');
    _logDesktopAgent('_candidateAgentDirs: current=${Directory.current.path}');
    _logDesktopAgent(
        '_candidateAgentDirs: resolvedExecutable=${Platform.resolvedExecutable}');

    // 最高优先级：检查 .app bundle 内嵌 Agent（Contents/Resources/agent/）
    final bundledAgentDir = _resolveBundledAgentDir();
    if (bundledAgentDir != null) {
      _logDesktopAgent(
          '_candidateAgentDirs: bundledAgentDir=${bundledAgentDir.path}');
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
    _logDesktopAgent(
        '_candidateAgentDirs: executableDir=${executableDir?.path}');
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
    } catch (_) {
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
    } catch (_) {}
    return null;
  }
}
