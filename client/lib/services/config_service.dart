import 'dart:convert';
import 'dart:io';
import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../models/config.dart';

/// 配置服务
class ConfigService {
  ConfigService({bool? useDebugDefaults})
      : _useDebugDefaults = useDebugDefaults ?? kDebugMode;

  static const String _keyPrefix = 'rc_client_';
  // 开发服务器地址
  // 桌面端使用 localhost，手机端需要使用电脑的局域网 IP
  static const String _debugServerUrlDesktop = AppConfig.defaultServerUrl;
  // 真机开发时需设置为电脑的局域网 IP（如 ws://192.168.x.x:8888）
  static const String _debugServerUrlMobile = AppConfig.defaultServerUrl;
  final bool _useDebugDefaults;

  Future<AppConfig> loadConfig() async {
    final prefs = await SharedPreferences.getInstance();
    final jsonStr = prefs.getString('${_keyPrefix}config');

    if (jsonStr == null) {
      return _defaultConfig();
    }

    try {
      final json = jsonDecode(jsonStr) as Map<String, dynamic>;
      final config = AppConfig.fromJson(json);
      // Debug 模式下强制使用当前服务器地址
      if (_useDebugDefaults) {
        return config.copyWith(serverUrl: _debugServerUrl);
      }
      return config;
    } catch (e) {
      return _defaultConfig();
    }
  }

  String get _debugServerUrl {
    // 手机端：模拟器使用 localhost，真机使用局域网 IP
    if (Platform.isAndroid || Platform.isIOS) {
      // 检测是否为模拟器/模拟器环境
      // iOS 模拟器和 Android 模拟器与主机在同一网络命名空间，可以使用 localhost
      final isSimulator = _isSimulator();
      if (isSimulator) {
        return _debugServerUrlDesktop; // 模拟器使用 localhost
      }
      return _debugServerUrlMobile; // 真机使用局域网 IP
    }
    return _debugServerUrlDesktop;
  }

  /// 检测是否运行在模拟器/模拟器环境中
  bool _isSimulator() {
    if (Platform.isIOS) {
      // iOS 模拟器可通过 SIMULATOR_DEVICE_NAME 环境变量判断
      // Debug 模式且无该变量时假设为模拟器（开发阶段多数用模拟器）
      return kDebugMode;
    }
    if (Platform.isAndroid) {
      // Android 真机在 Debug 模式下也需要局域网 IP
      // 仅当检测到模拟器特征时才使用 localhost
      final model = Platform.environment['RO_PRODUCT_MODEL'] ?? '';
      final isEmulator = model.contains('sdk') || model.contains('Emulator');
      return isEmulator;
    }
    return false;
  }

  AppConfig _defaultConfig() {
    if (_useDebugDefaults) {
      return AppConfig(serverUrl: _debugServerUrl);
    }
    return const AppConfig();
  }

  Future<void> saveConfig(AppConfig config) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('${_keyPrefix}config', jsonEncode(config.toJson()));
  }

  Future<void> clearConfig() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove('${_keyPrefix}config');
  }
}
