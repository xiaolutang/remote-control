import 'package:flutter_test/flutter_test.dart';
import 'package:rc_client/models/shortcut_item.dart';
import 'package:rc_client/models/terminal_shortcut.dart';
import 'package:rc_client/services/config_service.dart';
import 'package:rc_client/services/shortcut_config_service.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  group('ShortcutConfigService', () {
    late ShortcutConfigService service;

    setUp(() {
      SharedPreferences.setMockInitialValues({});
      service = ShortcutConfigService(
        configService: ConfigService(useDebugDefaults: false),
      );
    });

    test('loads default Claude command pack on first use', () async {
      final items = await service.loadShortcutItems();

      expect(items.map((item) => item.id), containsAll([
        'claude_help',
        'claude_status',
        'claude_clear',
        'claude_compact',
      ]));
    });

    test('persists enabled state and order changes', () async {
      final items = await service.loadShortcutItems();
      final reordered = [
        items[1].copyWith(order: 1),
        items[0].copyWith(order: 2, enabled: false),
        ...items.skip(2),
      ];

      await service.saveShortcutItems(reordered);
      final restored = await service.loadShortcutItems();

      expect(restored.first.id, items[1].id);
      expect(restored[1].id, items[0].id);
      expect(restored[1].enabled, isFalse);
    });

    test('backfills default Claude commands when saved config is partial', () async {
      await service.saveShortcutItems(const [
        ShortcutItem(
          id: 'claude_help',
          label: '/help',
          source: ShortcutItemSource.builtin,
          section: ShortcutItemSection.smart,
          action: TerminalShortcutAction(
            type: TerminalShortcutActionType.sendText,
            value: '/help\r',
          ),
        ),
      ]);

      final restored = await service.loadShortcutItems();

      expect(restored.map((item) => item.id), containsAll([
        'claude_help',
        'claude_status',
        'claude_clear',
        'claude_compact',
      ]));
    });

    test('restore defaults resets saved customizations', () async {
      final items = await service.loadShortcutItems();
      await service.saveShortcutItems([
        items.first.copyWith(enabled: false, pinned: true),
      ]);

      final restored = await service.restoreDefaultShortcutItems();

      expect(restored.length, greaterThan(1));
      expect(restored.any((item) => item.id == 'claude_help'), isTrue);
      expect(
        restored.where((item) => item.id == 'claude_help').single.enabled,
        isTrue,
      );
    });

    test('toggleShortcutItem updates a single entry', () async {
      await service.toggleShortcutItem('claude_help', false);

      final restored = await service.loadShortcutItems();
      final item = restored.firstWhere((candidate) => candidate.id == 'claude_help');
      expect(item.enabled, isFalse);
    });

    test('reorderShortcutItems rewrites order for known ids only', () async {
      final items = await service.loadShortcutItems();

      await service.reorderShortcutItems([
        'claude_compact',
        'claude_help',
      ]);

      final restored = await service.loadShortcutItems();
      final sorted = List<ShortcutItem>.from(restored)
        ..sort((a, b) => a.order.compareTo(b.order));

      expect(sorted.first.id, 'claude_compact');
      expect(sorted[1].id, 'claude_help');
      expect(sorted.length, items.length);
    });

    test('adds project shortcut items and keeps project source', () async {
      await service.addProjectShortcutItem(
        'project-a',
        const ShortcutItem(
          id: 'project_test',
          label: 'pnpm test',
          source: ShortcutItemSource.user,
          section: ShortcutItemSection.smart,
          action: TerminalShortcutAction(
            type: TerminalShortcutActionType.sendText,
            value: 'pnpm test\r',
          ),
        ),
      );

      final items = await service.loadProjectShortcutItems('project-a');
      expect(items.single.id, 'project_test');
      expect(items.single.source, ShortcutItemSource.project);
      expect(items.single.scope, ShortcutItemScope.project);
    });

    test('loadCombinedShortcutItems merges default and project items', () async {
      await service.addProjectShortcutItem(
        'project-a',
        const ShortcutItem(
          id: 'project_build',
          label: 'pnpm build',
          source: ShortcutItemSource.project,
          section: ShortcutItemSection.smart,
          action: TerminalShortcutAction(
            type: TerminalShortcutActionType.sendText,
            value: 'pnpm build\r',
          ),
        ),
      );

      final combined = await service.loadCombinedShortcutItems(projectId: 'project-a');

      expect(combined.any((item) => item.id == 'claude_help'), isTrue);
      expect(combined.any((item) => item.id == 'project_build'), isTrue);
    });

    test('persists Claude navigation mode overrides', () async {
      await service.saveClaudeNavigationMode(ClaudeNavigationMode.application);

      final restored = await service.loadClaudeNavigationMode();

      expect(restored, ClaudeNavigationMode.application);
    });

    test('project shortcut items are isolated per project id', () async {
      await service.addProjectShortcutItem(
        'project-a',
        const ShortcutItem(
          id: 'project_a_test',
          label: 'pnpm test',
          source: ShortcutItemSource.project,
          section: ShortcutItemSection.smart,
          action: TerminalShortcutAction(
            type: TerminalShortcutActionType.sendText,
            value: 'pnpm test\r',
          ),
        ),
      );
      await service.addProjectShortcutItem(
        'project-b',
        const ShortcutItem(
          id: 'project_b_lint',
          label: 'pnpm lint',
          source: ShortcutItemSource.project,
          section: ShortcutItemSection.smart,
          action: TerminalShortcutAction(
            type: TerminalShortcutActionType.sendText,
            value: 'pnpm lint\r',
          ),
        ),
      );

      final projectAItems = await service.loadProjectShortcutItems('project-a');
      final projectBItems = await service.loadProjectShortcutItems('project-b');

      expect(projectAItems.map((item) => item.id), contains('project_a_test'));
      expect(projectAItems.map((item) => item.id), isNot(contains('project_b_lint')));
      expect(projectBItems.map((item) => item.id), contains('project_b_lint'));
      expect(projectBItems.map((item) => item.id), isNot(contains('project_a_test')));
    });
  });
}
