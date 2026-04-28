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
