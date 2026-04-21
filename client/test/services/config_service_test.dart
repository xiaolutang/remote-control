import 'package:flutter_test/flutter_test.dart';
import 'package:rc_client/models/app_environment.dart';
import 'package:rc_client/models/config.dart';
import 'package:rc_client/models/shortcut_item.dart';
import 'package:rc_client/models/terminal_shortcut.dart';
import 'package:rc_client/services/config_service.dart';
import 'package:rc_client/services/environment_service.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  group('ConfigService', () {
    late EnvironmentService envService;

    setUp(() async {
      SharedPreferences.setMockInitialValues({});
      envService = EnvironmentService(debugModeProvider: () => true);
      await envService.loadSavedState();
      EnvironmentService.setInstance(envService);
    });

    test(
        'returns serverUrl from EnvironmentService when no saved config exists',
        () async {
      final service = ConfigService();

      final config = await service.loadConfig();

      expect(config.serverUrl, 'ws://localhost');
      expect(config.keepAgentRunningInBackground, isFalse);
      expect(config.shortcutItems, isEmpty);
    });

    test('preserves saved fields and uses EnvironmentService serverUrl',
        () async {
      final service = ConfigService();
      const saved = AppConfig(
        serverUrl: 'ws://old-value:8888/rc',
        themeMode: AppThemeMode.dark,
        keepAgentRunningInBackground: false,
        shortcutItems: [
          ShortcutItem(
            id: 'claude_help',
            label: '/help',
            source: ShortcutItemSource.builtin,
            section: ShortcutItemSection.smart,
            action: TerminalShortcutAction(
              type: TerminalShortcutActionType.sendText,
              value: '/help\r',
            ),
            enabled: false,
          ),
        ],
      );

      await service.saveConfig(saved);
      final restored = await service.loadConfig();

      // serverUrl 由 EnvironmentService 提供，不读取持久化值
      expect(restored.serverUrl, 'ws://localhost');
      expect(restored.themeMode, AppThemeMode.dark);
      expect(restored.keepAgentRunningInBackground, isFalse);
      expect(restored.shortcutItems.single.id, 'claude_help');
      expect(restored.shortcutItems.single.enabled, isFalse);
    });

    test('toJson does not contain serverUrl', () async {
      const config = AppConfig(serverUrl: 'ws://test/rc');
      final json = config.toJson();
      expect(json.containsKey('serverUrl'), isFalse);
    });

    test('fromJson uses injected serverUrl', () async {
      final json = {'themeMode': 'dark'};
      final config = AppConfig.fromJson(json, serverUrl: 'ws://custom/rc');
      expect(config.serverUrl, 'ws://custom/rc');
      expect(config.themeMode, AppThemeMode.dark);
    });

    test('uses production URL when environment is production', () async {
      await envService.switchEnvironment(AppEnvironment.production);
      final service = ConfigService();
      final config = await service.loadConfig();
      expect(config.serverUrl, 'wss://rc.xiaolutang.top/rc');
    });

    test('legacy saved keep-running=true is migrated back to false', () async {
      final service = ConfigService();
      const legacy = AppConfig(
        keepAgentRunningInBackground: true,
      );

      await service.saveConfig(legacy);
      final restored = await service.loadConfig();

      expect(restored.keepAgentRunningInBackground, isFalse);
      expect(restored.desktopBackgroundModeUserSet, isFalse);
    });

    test('explicit keep-running choice is preserved', () async {
      final service = ConfigService();
      const explicit = AppConfig(
        keepAgentRunningInBackground: true,
        desktopBackgroundModeUserSet: true,
      );

      await service.saveConfig(explicit);
      final restored = await service.loadConfig();

      expect(restored.keepAgentRunningInBackground, isTrue);
      expect(restored.desktopBackgroundModeUserSet, isTrue);
    });
  });
}
