import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';

/// 默认端口范围
const List<int> kAgentPortRange = [18765, 18766, 18767, 18768, 18769];

/// 状态文件路径（macOS）
const String kStateFilePathMacOS =
    'Library/Application Support/remote-control/agent-state.json';

/// 状态文件路径（Linux）
const String kStateFilePathLinux = '.local/share/remote-control/agent-state.json';

/// 状态文件路径（Windows）
const String kStateFilePathWindows = 'remote-control\\agent-state.json';

void _logHttpClient(String message) {
  if (Platform.environment.containsKey('FLUTTER_TEST')) {
    return;
  }
  debugPrint('[DesktopAgentHttpClient] $message');
}

/// 本地 Agent 状态
class LocalAgentStatus {
  const LocalAgentStatus({
    required this.running,
    required this.pid,
    required this.port,
    required this.serverUrl,
    required this.connected,
    required this.sessionId,
    required this.terminalsCount,
    required this.keepRunningInBackground,
  });

  final bool running;
  final int pid;
  final int port;
  final String serverUrl;
  final bool connected;
  final String sessionId;
  final int terminalsCount;
  final bool keepRunningInBackground;

  factory LocalAgentStatus.fromJson(Map<String, dynamic> json) {
    return LocalAgentStatus(
      running: json['running'] as bool? ?? false,
      pid: json['pid'] as int? ?? 0,
      port: json['port'] as int? ?? 0,
      serverUrl: json['server_url'] as String? ?? '',
      connected: json['connected'] as bool? ?? false,
      sessionId: json['session_id'] as String? ?? '',
      terminalsCount: json['terminals_count'] as int? ?? 0,
      keepRunningInBackground:
          json['keep_running_in_background'] as bool? ?? true,
    );
  }
}

/// 本地 Agent HTTP 客户端
///
/// 用于 Flutter 桌面端与本地 Agent HTTP Server 通信。
/// 支持状态文件发现和端口扫描两种发现方式。
class DesktopAgentHttpClient {
  DesktopAgentHttpClient({
    Duration timeout = const Duration(seconds: 3),
    String? homeDirectory,
  })  : _timeout = timeout,
        _homeDirectory = homeDirectory;

  final Duration _timeout;
  final String? _homeDirectory;
  HttpClient? _httpClient;

  /// 发现本地运行的 Agent
  ///
  /// 优先通过状态文件发现，失败则扫描端口范围。
  Future<LocalAgentStatus?> discoverAgent() async {
    // 1. 尝试通过状态文件发现
    final statusFromStateFile = await _discoverViaStateFile();
    if (statusFromStateFile != null) {
      _logHttpClient('discovered agent via state file: port=${statusFromStateFile.port}');
      return statusFromStateFile;
    }

    // 2. 扫描端口范围
    final statusFromPortScan = await _discoverViaPortScan();
    if (statusFromPortScan != null) {
      _logHttpClient('discovered agent via port scan: port=${statusFromPortScan.port}');
      return statusFromPortScan;
    }

    _logHttpClient('no local agent found');
    return null;
  }

  /// 检查指定端口的 Agent 是否健康
  Future<bool> checkHealth(int port) async {
    try {
      final client = await _getClient();
      final request = await client
          .getUrl(Uri.parse('http://127.0.0.1:$port/health'))
          .timeout(_timeout);
      final response = await request.close().timeout(_timeout);
      if (response.statusCode == 200) {
        final body = await _readResponseBody(response);
        final json = jsonDecode(body) as Map<String, dynamic>;
        return json['status'] == 'ok';
      }
      return false;
    } catch (e) {
      _logHttpClient('checkHealth failed: $e');
      return false;
    }
  }

  /// 获取 Agent 状态
  Future<LocalAgentStatus?> getStatus(int port) async {
    try {
      final client = await _getClient();
      final request = await client
          .getUrl(Uri.parse('http://127.0.0.1:$port/status'))
          .timeout(_timeout);
      final response = await request.close().timeout(_timeout);
      if (response.statusCode == 200) {
        final body = await _readResponseBody(response);
        final json = jsonDecode(body) as Map<String, dynamic>;
        return LocalAgentStatus.fromJson(json);
      }
      return null;
    } catch (e) {
      _logHttpClient('getStatus failed: $e');
      return null;
    }
  }

  /// 发送停止命令
  Future<bool> sendStop(int port, {int graceTimeout = 5}) async {
    try {
      final client = await _getClient();
      final request = await client
          .postUrl(Uri.parse('http://127.0.0.1:$port/stop'))
          .timeout(_timeout);
      request.headers.contentType = ContentType.json;
      final payload = jsonEncode({'grace_timeout': graceTimeout});
      request.write(utf8.encode(payload));
      final response = await request.close().timeout(_timeout);
      if (response.statusCode == 200) {
        final body = await _readResponseBody(response);
        final json = jsonDecode(body) as Map<String, dynamic>;
        return json['ok'] == true;
      }
      return false;
    } catch (e) {
      _logHttpClient('sendStop failed: $e');
      return false;
    }
  }

  /// 更新 keep_running_in_background 配置
  Future<bool> updateConfig(int port, {required bool keepRunningInBackground}) async {
    try {
      final client = await _getClient();
      final request = await client
          .postUrl(Uri.parse('http://127.0.0.1:$port/config'))
          .timeout(_timeout);
      request.headers.contentType = ContentType.json;
      final payload = jsonEncode({
        'keep_running_in_background': keepRunningInBackground,
      });
      request.write(utf8.encode(payload));
      final response = await request.close().timeout(_timeout);
      if (response.statusCode == 200) {
        final body = await _readResponseBody(response);
        final json = jsonDecode(body) as Map<String, dynamic>;
        return json['ok'] == true;
      }
      return false;
    } catch (e) {
      _logHttpClient('updateConfig failed: $e');
      return false;
    }
  }

  /// 获取终端列表
  Future<List<Map<String, dynamic>>> getTerminals(int port) async {
    try {
      final client = await _getClient();
      final request = await client
          .getUrl(Uri.parse('http://127.0.0.1:$port/terminals'))
          .timeout(_timeout);
      final response = await request.close().timeout(_timeout);
      if (response.statusCode == 200) {
        final body = await _readResponseBody(response);
        final json = jsonDecode(body) as Map<String, dynamic>;
        final terminals = json['terminals'] as List<dynamic>? ?? [];
        return terminals.cast<Map<String, dynamic>>();
      }
      return [];
    } catch (e) {
      _logHttpClient('getTerminals failed: $e');
      return [];
    }
  }

  /// 关闭客户端
  void close() {
    _httpClient?.close();
    _httpClient = null;
  }

  // ============== 私有方法 ==============

  Future<HttpClient> _getClient() async {
    _httpClient ??= HttpClient();
    return _httpClient!;
  }

  Future<LocalAgentStatus?> _discoverViaStateFile() async {
    final stateFile = await _getStateFile();
    if (stateFile == null || !stateFile.existsSync()) {
      return null;
    }

    try {
      final content = await stateFile.readAsString();
      final json = jsonDecode(content) as Map<String, dynamic>;
      final pid = json['pid'] as int?;
      final port = json['port'] as int?;

      if (pid == null || port == null) {
        return null;
      }

      // 检查进程是否存活
      if (!await _isProcessAlive(pid)) {
        _logHttpClient('state file process $pid is not alive');
        return null;
      }

      // 验证端口健康
      if (await checkHealth(port)) {
        return getStatus(port);
      }
      return null;
    } catch (e) {
      _logHttpClient('read state file failed: $e');
      return null;
    }
  }

  Future<LocalAgentStatus?> _discoverViaPortScan() async {
    for (final port in kAgentPortRange) {
      if (await checkHealth(port)) {
        return getStatus(port);
      }
    }
    return null;
  }

  Future<File?> _getStateFile() async {
    final home = _homeDirectory ?? Platform.environment['HOME'];
    if (home == null || home.isEmpty) {
      return null;
    }

    String relativePath;
    if (Platform.isMacOS) {
      relativePath = kStateFilePathMacOS;
    } else if (Platform.isWindows) {
      relativePath = kStateFilePathWindows;
    } else {
      relativePath = kStateFilePathLinux;
    }

    return File('$home/$relativePath');
  }

  Future<bool> _isProcessAlive(int pid) async {
    try {
      final result = await Process.run('ps', ['-p', '$pid']);
      return result.exitCode == 0;
    } catch (_) {
      return false;
    }
  }

  Future<String> _readResponseBody(HttpClientResponse response) async {
    final completer = Completer<String>();
    final buffer = StringBuffer();
    response.transform(utf8.decoder).listen(
      (data) => buffer.write(data),
      onDone: () => completer.complete(buffer.toString()),
      onError: (e) => completer.completeError(e),
    );
    return completer.future.timeout(_timeout);
  }
}
