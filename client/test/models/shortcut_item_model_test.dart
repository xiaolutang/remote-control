import 'package:flutter_test/flutter_test.dart';
import 'package:rc_client/models/shortcut_item.dart';
import 'package:rc_client/models/terminal_shortcut.dart';

void main() {
  group('ShortcutItem', () {
    test('serializes and deserializes different sources correctly', () {
      final item = ShortcutItem(
        id: 'project_test',
        label: 'pnpm test',
        source: ShortcutItemSource.project,
        section: ShortcutItemSection.smart,
        action: const TerminalShortcutAction(
          type: TerminalShortcutActionType.sendText,
          value: 'pnpm test\r',
        ),
        pinned: true,
        order: 12,
        useCount: 4,
        lastUsedAt: DateTime.utc(2026, 3, 28, 12, 0, 0),
        scope: ShortcutItemScope.project,
      );

      final roundTrip = ShortcutItem.fromJson(item.toJson());

      expect(roundTrip.id, item.id);
      expect(roundTrip.source, ShortcutItemSource.project);
      expect(roundTrip.section, ShortcutItemSection.smart);
      expect(roundTrip.action.toTerminalPayload(), 'pnpm test\r');
      expect(roundTrip.pinned, true);
      expect(roundTrip.order, 12);
      expect(roundTrip.useCount, 4);
      expect(roundTrip.lastUsedAt, DateTime.utc(2026, 3, 28, 12, 0, 0));
      expect(roundTrip.scope, ShortcutItemScope.project);
    });

    test('markUsed updates use count and last used timestamp', () {
      final base = ShortcutItem(
        id: 'claude_help',
        label: '/help',
        source: ShortcutItemSource.builtin,
        section: ShortcutItemSection.smart,
        action: const TerminalShortcutAction(
          type: TerminalShortcutActionType.sendText,
          value: '/help\r',
        ),
      );

      final updated = base.markUsed(DateTime.utc(2026, 3, 28, 18, 30, 0));

      expect(updated.useCount, 1);
      expect(updated.lastUsedAt, DateTime.utc(2026, 3, 28, 18, 30, 0));
      expect(base.useCount, 0);
      expect(base.lastUsedAt, isNull);
    });

    test('can be created from terminal shortcut as builtin core item', () {
      final item = ShortcutItem.fromTerminalShortcut(
        TerminalShortcutProfile.claudeCode.shortcuts.first,
        order: 1,
      );

      expect(item.source, ShortcutItemSource.builtin);
      expect(item.section, ShortcutItemSection.core);
      expect(item.order, 1);
    });
  });

  group('ShortcutItemSorter', () {
    test('keeps core items stable by order regardless of usage', () {
      final layout = ShortcutItemSorter.partitionAndSort([
        ShortcutItem(
          id: 'enter',
          label: 'Enter',
          source: ShortcutItemSource.builtin,
          section: ShortcutItemSection.core,
          order: 2,
          useCount: 99,
          lastUsedAt: DateTime.utc(2026, 3, 28, 20, 0, 0),
          action: const TerminalShortcutAction(
            type: TerminalShortcutActionType.sendText,
            value: '\r',
          ),
        ),
        ShortcutItem(
          id: 'esc',
          label: 'Esc',
          source: ShortcutItemSource.builtin,
          section: ShortcutItemSection.core,
          order: 1,
          useCount: 1,
          lastUsedAt: DateTime.utc(2026, 3, 28, 21, 0, 0),
          action: const TerminalShortcutAction(
            type: TerminalShortcutActionType.sendEscapeSequence,
            value: '\x1b',
          ),
        ),
      ]);

      expect(layout.coreItems.map((item) => item.id).toList(), ['esc', 'enter']);
    });

    test('sorts smart items by pinned then recent then order', () {
      final layout = ShortcutItemSorter.partitionAndSort([
        ShortcutItem(
          id: 'project_build',
          label: 'pnpm build',
          source: ShortcutItemSource.project,
          section: ShortcutItemSection.smart,
          pinned: false,
          order: 5,
          lastUsedAt: DateTime.utc(2026, 3, 28, 19, 0, 0),
          action: const TerminalShortcutAction(
            type: TerminalShortcutActionType.sendText,
            value: 'pnpm build\r',
          ),
        ),
        ShortcutItem(
          id: 'claude_help',
          label: '/help',
          source: ShortcutItemSource.builtin,
          section: ShortcutItemSection.smart,
          pinned: true,
          order: 99,
          action: const TerminalShortcutAction(
            type: TerminalShortcutActionType.sendText,
            value: '/help\r',
          ),
        ),
        ShortcutItem(
          id: 'user_status',
          label: '/status',
          source: ShortcutItemSource.user,
          section: ShortcutItemSection.smart,
          order: 2,
          lastUsedAt: DateTime.utc(2026, 3, 28, 20, 0, 0),
          action: const TerminalShortcutAction(
            type: TerminalShortcutActionType.sendText,
            value: '/status\r',
          ),
        ),
      ]);

      expect(
        layout.smartItems.map((item) => item.id).toList(),
        ['claude_help', 'user_status', 'project_build'],
      );
    });

    test('filters disabled items out of both sections', () {
      final layout = ShortcutItemSorter.partitionAndSort([
        ShortcutItem(
          id: 'hidden',
          label: 'Hidden',
          source: ShortcutItemSource.user,
          section: ShortcutItemSection.smart,
          enabled: false,
          action: const TerminalShortcutAction(
            type: TerminalShortcutActionType.sendText,
            value: 'hidden\r',
          ),
        ),
      ]);

      expect(layout.coreItems, isEmpty);
      expect(layout.smartItems, isEmpty);
    });
  });
}
