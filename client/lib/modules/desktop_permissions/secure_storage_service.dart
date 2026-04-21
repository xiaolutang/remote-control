import 'dart:convert';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// 统一管理敏感凭证的安全存储访问。
///
/// 设计目标：
/// 1. 收口 macOS Keychain 访问路径，避免多处各自 new storage。
/// 2. 单 key 按需读取，并在内存中去重/缓存，避免一次访问放大为多次弹窗。
/// 3. 支持批量持久化认证信息，把密码/token/refresh_token 收敛为一次写入。
class SecureStorageService {
  SecureStorageService({FlutterSecureStorage? storage})
      : _storage = storage ?? _defaultStorage;

  static final SecureStorageService instance = SecureStorageService();

  static const String passwordKey = 'rc_password';
  static const String tokenKey = 'rc_token';
  static const String refreshTokenKey = 'rc_refresh_token';
  static const String _trackedBundleKey = 'rc_auth_bundle';

  static const Set<String> _trackedKeys = <String>{
    passwordKey,
    tokenKey,
    refreshTokenKey,
  };

  static final FlutterSecureStorage _defaultStorage = FlutterSecureStorage(
    aOptions: const AndroidOptions(encryptedSharedPreferences: true),
    iOptions:
        const IOSOptions(accessibility: KeychainAccessibility.first_unlock),
    // Keep macOS secure storage behavior identical across debug and
    // release builds until stable signing/keychain-sharing is set up.
    mOptions: const MacOsOptions(useDataProtectionKeyChain: false),
  );

  final FlutterSecureStorage _storage;
  final Map<String, String?> _cache = <String, String?>{};
  final Map<String, Future<String?>> _trackedReadFutures =
      <String, Future<String?>>{};
  Future<void>? _trackedBundleLoadFuture;
  bool _trackedBundleLoaded = false;

  Future<String?> read(String key) async {
    if (_cache.containsKey(key)) {
      return _cache[key];
    }

    if (_trackedKeys.contains(key)) {
      return _readTrackedKey(key);
    }

    final value = await _storage.read(key: key);
    _cache[key] = value;
    return value;
  }

  Future<Map<String, String?>> readTrackedEntries(Iterable<String> keys) async {
    final requestedKeys = keys.where(_trackedKeys.contains).toSet();
    if (requestedKeys.isEmpty) {
      return const <String, String?>{};
    }

    final result = <String, String?>{};
    final missingKeys = <String>{};
    for (final key in requestedKeys) {
      if (_cache.containsKey(key)) {
        result[key] = _cache[key];
      } else {
        missingKeys.add(key);
      }
    }

    if (missingKeys.isEmpty) {
      return result;
    }

    await _loadTrackedBundleIfPresent();

    for (final key in requestedKeys) {
      if (_cache.containsKey(key)) {
        result[key] = _cache[key];
      }
    }

    for (final key in requestedKeys) {
      if (result.containsKey(key)) {
        continue;
      }
      result[key] = await _readTrackedLegacyKey(key);
    }

    return result;
  }

  Future<void> write({
    required String key,
    String? value,
  }) async {
    if (_trackedKeys.contains(key)) {
      await writeTrackedEntries(<String, String?>{key: value});
      return;
    }

    await _storage.write(key: key, value: value);
    _cache[key] = value;
  }

  Future<void> writeTrackedEntries(Map<String, String?> entries) async {
    final trackedEntries = <String, String?>{};
    for (final entry in entries.entries) {
      if (_trackedKeys.contains(entry.key)) {
        trackedEntries[entry.key] = entry.value;
      }
    }
    if (trackedEntries.isEmpty) {
      return;
    }

    final untouchedKeys = _trackedKeys.difference(trackedEntries.keys.toSet());
    final needsBundleLoad =
        untouchedKeys.any((key) => !_cache.containsKey(key));
    if (needsBundleLoad) {
      await _loadTrackedBundleIfPresent();
    }
    for (final entry in trackedEntries.entries) {
      _cache[entry.key] = entry.value;
    }
    await _persistTrackedLegacyEntries(trackedEntries);
    await _persistTrackedBundle();
  }

  Future<void> delete({required String key}) async {
    if (_trackedKeys.contains(key)) {
      await writeTrackedEntries(<String, String?>{key: null});
      return;
    }

    await _storage.delete(key: key);
    _cache.remove(key);
  }

  Future<void> clearAllTrackedKeys() async {
    await _storage.delete(key: _trackedBundleKey);
    for (final key in _trackedKeys) {
      await _storage.delete(key: key);
      _cache.remove(key);
    }
    _trackedReadFutures.clear();
    _trackedBundleLoaded = false;
    _trackedBundleLoadFuture = null;
  }

  void clearMemoryCache() {
    _cache.clear();
    _trackedReadFutures.clear();
    _trackedBundleLoaded = false;
    _trackedBundleLoadFuture = null;
  }

  Future<void> warmUpTrackedKeys() async {
    if (_trackedKeys.every(_cache.containsKey)) {
      return;
    }
    await readTrackedEntries(_trackedKeys);
  }

  Future<String?> _readTrackedKey(String key) async {
    final values = await readTrackedEntries(<String>[key]);
    return values[key];
  }

  Future<String?> _readTrackedLegacyKey(String key) async {
    final pending = _trackedReadFutures[key];
    if (pending != null) {
      return pending;
    }

    final future = () async {
      final value = await _storage.read(key: key);
      _cache[key] = value;
      if (value != null && value.isNotEmpty) {
        await _persistTrackedBundle();
      }
      return value;
    }();
    _trackedReadFutures[key] = future;

    try {
      return await future;
    } finally {
      _trackedReadFutures.remove(key);
    }
  }

  Future<void> _loadTrackedBundleIfPresent() async {
    if (_trackedBundleLoaded) {
      return;
    }
    if (_trackedBundleLoadFuture != null) {
      return _trackedBundleLoadFuture;
    }

    _trackedBundleLoadFuture = () async {
      final raw = await _storage.read(key: _trackedBundleKey);
      if (raw != null && raw.isNotEmpty) {
        try {
          final decoded = jsonDecode(raw);
          if (decoded is Map) {
            for (final key in _trackedKeys) {
              final value = decoded[key];
              if (value is String) {
                _cache[key] = value;
              } else if (value == null) {
                _cache[key] = null;
              }
            }
          }
        } catch (_) {
          // Ignore a corrupted bundle and fall back to legacy per-key entries.
        }
      }
      _trackedBundleLoaded = true;
    }();

    try {
      await _trackedBundleLoadFuture;
    } finally {
      _trackedBundleLoadFuture = null;
    }
  }

  Future<void> _persistTrackedBundle() async {
    final payload = <String, String>{};
    for (final key in _trackedKeys) {
      final value = _cache[key];
      if (value != null && value.isNotEmpty) {
        payload[key] = value;
      }
    }

    if (payload.isEmpty) {
      await _storage.delete(key: _trackedBundleKey);
      return;
    }

    await _storage.write(
      key: _trackedBundleKey,
      value: jsonEncode(payload),
    );
  }

  Future<void> _persistTrackedLegacyEntries(
    Map<String, String?> entries,
  ) async {
    for (final entry in entries.entries) {
      if (entry.value == null || entry.value!.isEmpty) {
        await _storage.delete(key: entry.key);
      } else {
        await _storage.write(key: entry.key, value: entry.value);
      }
    }
  }
}
