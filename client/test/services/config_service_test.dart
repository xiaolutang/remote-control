import 'package:flutter_test/flutter_test.dart';
import 'package:rc_client/models/config.dart';
import 'package:rc_client/models/shortcut_item.dart';
import 'package:rc_client/models/terminal_shortcut.dart';
import 'package:rc_client/services/config_service.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  group('ConfigService', () {
    setUp(() {
      SharedPreferences.setMockInitialValues({});
    });

    test('returns debug defaults when no saved config exists', () async {
      final service = ConfigService(useDebugDefaults: true);

      final config = await service.loadConfig();

      // Debug 模式下返回以 ws:// 开头、含 /rc 路径的服务器地址
      expect(config.serverUrl, startsWith('ws://'));
      expect(config.serverUrl, contains('/rc'));
      expect(config.shortcutItems, isEmpty);
    });

    test('preserves saved shortcut config in debug mode', () async {
      final service = ConfigService(useDebugDefaults: true);
      const saved = AppConfig(
        serverUrl: 'ws://10.0.0.2:8888',
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

      // Debug 模式下 serverUrl 会被覆盖为 debug 默认值
      expect(restored.serverUrl, startsWith('ws://'));
      expect(restored.serverUrl, contains('/rc'));
      expect(restored.themeMode, AppThemeMode.dark);
      expect(restored.keepAgentRunningInBackground, isFalse);
      expect(restored.shortcutItems.single.id, 'claude_help');
      expect(restored.shortcutItems.single.enabled, isFalse);
    });
  });
}
