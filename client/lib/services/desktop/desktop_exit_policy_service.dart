import 'dart:convert';

import 'package:flutter/widgets.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../../models/config.dart';
import '../app_logger.dart';
import '../config_service.dart';

class DesktopExitPolicyService {
  DesktopExitPolicyService({
    ConfigService? configService,
  }) : _configService = configService;

  final ConfigService? _configService;
  SharedPreferences? _prefs;

  Future<SharedPreferences> _ensurePrefs() async =>
      _prefs ??= await SharedPreferences.getInstance();

  Future<DesktopExitPolicy> loadPolicy() async {
    WidgetsFlutterBinding.ensureInitialized();
    final prefs = await _ensurePrefs();
    final jsonStr = prefs.getString('rc_client_config');
    if (jsonStr == null || jsonStr.isEmpty) {
      return DesktopExitPolicy.stopAgentOnExit;
    }
    try {
      final json = jsonDecode(jsonStr) as Map<String, dynamic>;
      return AppConfig.fromJson(json).desktopExitPolicy;
    } catch (e) {
      AppLogger('ExitPolicy').warning('loadPolicy JSON parse failed: $e');
      return DesktopExitPolicy.stopAgentOnExit;
    }
  }

  Future<bool> keepAgentRunningInBackground() async {
    return (await loadPolicy()) ==
        DesktopExitPolicy.keepAgentRunningInBackground;
  }

  Future<AppConfig> savePolicy(DesktopExitPolicy policy) async {
    final configService = _configService ?? ConfigService();
    final config = await configService.loadConfig();
    if (config.desktopExitPolicy == policy) {
      return config;
    }

    final updated = config.copyWith(desktopExitPolicy: policy);
    await configService.saveConfig(updated);
    return updated;
  }

  Future<AppConfig> setKeepAgentRunningInBackground(bool value) {
    return savePolicy(
      value
          ? DesktopExitPolicy.keepAgentRunningInBackground
          : DesktopExitPolicy.stopAgentOnExit,
    );
  }
}
