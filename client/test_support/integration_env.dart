import 'dart:io';

Map<String, String>? _cachedLocalEnv;

String integrationEnv(
  String key, {
  String fallback = '',
}) {
  final fromEnv = Platform.environment[key]?.trim();
  if (fromEnv != null && fromEnv.isNotEmpty) {
    return fromEnv;
  }

  final local = _loadLocalEnv()[key]?.trim();
  if (local != null && local.isNotEmpty) {
    return local;
  }

  return fallback;
}

/// 判断当前集成测试是否运行在本地 Docker 环境。
///
/// 优先读取环境变量 `RC_TEST_IS_LOCAL`（值为 "true" 时为本地）；
/// 未设置时回退到 IP 推断（localhost / 127.0.0.1 / 192.168.* / 10.* / 172.16-31.*）。
bool isLocalTestEnv(String serverIp) {
  final explicit = integrationEnv('RC_TEST_IS_LOCAL');
  if (explicit.isNotEmpty) {
    return explicit.toLowerCase() == 'true';
  }
  if (serverIp == 'localhost' || serverIp == '127.0.0.1') return true;
  // RFC 1918 私有地址段：本地 Docker 典型场景
  if (serverIp.startsWith('192.168.')) return true;
  if (serverIp.startsWith('10.')) return true;
  final match = RegExp(r'^172\.(1[6-9]|2\d|3[01])\.').firstMatch(serverIp);
  if (match != null) return true;
  return false;
}

Map<String, String> _loadLocalEnv() {
  final cached = _cachedLocalEnv;
  if (cached != null) {
    return cached;
  }

  final file = File('.local.env');
  if (!file.existsSync()) {
    _cachedLocalEnv = <String, String>{};
    return _cachedLocalEnv!;
  }

  final env = <String, String>{};
  for (final rawLine in file.readAsLinesSync()) {
    final line = rawLine.trim();
    if (line.isEmpty || line.startsWith('#')) {
      continue;
    }
    final separator = line.indexOf('=');
    if (separator <= 0) {
      continue;
    }
    final key = line.substring(0, separator).trim();
    final value = line.substring(separator + 1).trim();
    if (key.isEmpty) {
      continue;
    }
    env[key] = value;
  }

  _cachedLocalEnv = env;
  return env;
}
