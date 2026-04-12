import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rc_client/models/shortcut_item.dart';
import 'package:rc_client/models/terminal_shortcut.dart';
import 'package:rc_client/widgets/terminal_shortcut_bar.dart';

void main() {
  testWidgets('renders claude shortcuts and forwards taps', (tester) async {
    final pressed = <String>[];
    final items = TerminalShortcutProfile.claudeCode.shortcuts
        .asMap()
        .entries
        .map(
          (entry) => ShortcutItem.fromTerminalShortcut(
            entry.value,
            order: entry.key + 1,
          ),
        )
        .toList(growable: false);

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: TerminalShortcutBar(
            items: items,
            onItemPressed: (item) => pressed.add(item.id),
          ),
        ),
      ),
    );

    expect(find.text('Esc'), findsOneWidget);
    expect(find.text('Ctrl+C'), findsOneWidget);
    expect(find.text('Enter'), findsOneWidget);

    await tester.tap(find.text('Ctrl+C'));
    await tester.pump();
    await tester.tap(find.text('上一项'));
    await tester.pump();

    expect(pressed, ['ctrl_c', 'prev_item']);
  });

  testWidgets('returns empty widget for empty shortcut list', (tester) async {
    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(
          body: TerminalShortcutBar(
            items: [],
            onItemPressed: _noop,
          ),
        ),
      ),
    );

    expect(find.byType(OutlinedButton), findsNothing);
  });
}

void _noop(ShortcutItem _) {}
