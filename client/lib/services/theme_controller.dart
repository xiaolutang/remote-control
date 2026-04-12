import 'package:flutter/material.dart';

import '../models/config.dart';
import 'config_service.dart';

class ThemeController extends ChangeNotifier {
  ThemeController({ConfigService? configService})
      : _configService = configService ?? ConfigService();

  final ConfigService _configService;
  ThemeMode _themeMode = ThemeMode.system;

  ThemeMode get themeMode => _themeMode;

  Future<void> load() async {
    final config = await _configService.loadConfig();
    _themeMode = _toThemeMode(config.themeMode);
    notifyListeners();
  }

  Future<void> setThemeMode(ThemeMode mode) async {
    if (_themeMode == mode) return;
    _themeMode = mode;
    notifyListeners();

    final config = await _configService.loadConfig();
    await _configService.saveConfig(
      config.copyWith(themeMode: _toAppThemeMode(mode)),
    );
  }

  static ThemeMode _toThemeMode(AppThemeMode mode) {
    switch (mode) {
      case AppThemeMode.light:
        return ThemeMode.light;
      case AppThemeMode.dark:
        return ThemeMode.dark;
      case AppThemeMode.system:
        return ThemeMode.system;
    }
  }

  static AppThemeMode _toAppThemeMode(ThemeMode mode) {
    switch (mode) {
      case ThemeMode.light:
        return AppThemeMode.light;
      case ThemeMode.dark:
        return AppThemeMode.dark;
      case ThemeMode.system:
        return AppThemeMode.system;
    }
  }
}
