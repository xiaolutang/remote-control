import 'dart:convert';
import 'package:shared_preferences/shared_preferences.dart';
import '../models/config.dart';
import 'environment_service.dart';

/// 配置服务
class ConfigService {
  ConfigService({EnvironmentService? environmentService})
      : _environmentService = environmentService ?? EnvironmentService.instance;

  static const String _keyPrefix = 'rc_client_';

  final EnvironmentService _environmentService;

  Future<AppConfig> loadConfig() async {
    final prefs = await SharedPreferences.getInstance();
    final jsonStr = prefs.getString('${_keyPrefix}config');

    final serverUrl = _environmentService.currentServerUrl;

    if (jsonStr == null) {
      return AppConfig(serverUrl: serverUrl);
    }

    try {
      final json = jsonDecode(jsonStr) as Map<String, dynamic>;
      final config = AppConfig.fromJson(json, serverUrl: serverUrl);
      final hasExplicitBackgroundChoice =
          json['desktopBackgroundModeUserSet'] == true;
      if (!hasExplicitBackgroundChoice && config.keepAgentRunningInBackground) {
        return config.copyWith(
          keepAgentRunningInBackground: false,
          desktopBackgroundModeUserSet: false,
        );
      }
      return config;
    } catch (e) {
      return AppConfig(serverUrl: serverUrl);
    }
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
