import 'dart:io';
import 'package:flutter/foundation.dart';

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
/// 未设置时回退到 IP 推断（通过 [_isPrivateIp] 判断 RFC 1918 私有地址）。
bool isLocalTestEnv(String serverIp) {
  final explicit = integrationEnv('RC_TEST_IS_LOCAL');
  if (explicit.isNotEmpty) {
    return explicit.toLowerCase() == 'true';
  }
  return isPrivateIp(serverIp);
}

/// 纯函数：判断 IP 是否为本地/私有地址（loopback + RFC 1918）。
@visibleForTesting
bool isPrivateIp(String ip) {
  if (ip == 'localhost' || ip == '127.0.0.1') return true;
  if (ip.startsWith('192.168.')) return true;
  if (ip.startsWith('10.')) return true;
  final match = RegExp(r'^172\.(1[6-9]|2\d|3[01])\.').firstMatch(ip);
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
