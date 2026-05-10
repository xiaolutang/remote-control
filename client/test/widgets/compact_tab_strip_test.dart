import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rc_client/models/runtime_terminal.dart';
import 'package:rc_client/widgets/compact_tab_strip.dart';

void main() {
  group('CompactTabStrip', () {
    List<RuntimeTerminal> createTerminals(int count) {
      return List.generate(
        count,
        (i) => RuntimeTerminal(
          terminalId: 't$i',
          title: 'Terminal ${i + 1}',
          cwd: '~',
          command: '/bin/bash',
          status: 'running',
          views: {},
        ),
      );
    }

    testWidgets('renders terminal numbers and visible titles', (tester) async {
      final terminals = createTerminals(3);

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: CompactTabStrip(
              terminals: terminals,
              selectedTerminalId: 't0',
              onSwitch: (_) {},
              onCreate: () {},
            ),
          ),
        ),
      );

      // Should show compact numbers: 1, 2, 3
      expect(find.text('1'), findsOneWidget);
      expect(find.text('2'), findsOneWidget);
      expect(find.text('3'), findsOneWidget);

      // Should also show visible titles
      expect(find.text('Terminal 1'), findsOneWidget);
      expect(find.text('Terminal 2'), findsOneWidget);
      expect(find.text('Terminal 3'), findsOneWidget);
    });

    testWidgets('clicking a tab triggers onSwitch with correct terminalId',
        (tester) async {
      final terminals = createTerminals(3);
      String? switchedId;

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: CompactTabStrip(
              terminals: terminals,
              selectedTerminalId: 't0',
              onSwitch: (id) => switchedId = id,
              onCreate: () {},
            ),
          ),
        ),
      );

      await tester.tap(find.byKey(const Key('compact-tab-t2')));
      await tester.pump();

      expect(switchedId, 't2');
    });

    testWidgets('clicking + triggers onCreate', (tester) async {
      final terminals = createTerminals(2);
      var createCalled = false;

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: CompactTabStrip(
              terminals: terminals,
              selectedTerminalId: 't0',
              onSwitch: (_) {},
              onCreate: () => createCalled = true,
            ),
          ),
        ),
      );

      await tester.tap(find.byKey(const Key('compact-tab-create')));
      await tester.pump();

      expect(createCalled, isTrue);
    });

    testWidgets('swiping left triggers onSwitch to next terminal',
        (tester) async {
      final terminals = createTerminals(3);
      String? switchedId;

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SizedBox(
              width: 400,
              height: 60,
              child: CompactTabStrip(
                terminals: terminals,
                selectedTerminalId: 't0',
                onSwitch: (id) => switchedId = id,
                onCreate: () {},
              ),
            ),
          ),
        ),
      );

      // Swipe left (from right to left) to go to next terminal
      await tester.fling(
        find.byType(CompactTabStrip),
        const Offset(-100, 0),
        500,
      );
      await tester.pump();

      expect(switchedId, 't1');
    });

    testWidgets('swiping right triggers onSwitch to previous terminal',
        (tester) async {
      final terminals = createTerminals(3);
      String? switchedId;

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SizedBox(
              width: 400,
              height: 60,
              child: CompactTabStrip(
                terminals: terminals,
                selectedTerminalId: 't2',
                onSwitch: (id) => switchedId = id,
                onCreate: () {},
              ),
            ),
          ),
        ),
      );

      // Swipe right (from left to right) to go to previous terminal
      await tester.fling(
        find.byType(CompactTabStrip),
        const Offset(100, 0),
        500,
      );
      await tester.pump();

      expect(switchedId, 't1');
    });

    testWidgets('swipe on first terminal does not switch when at boundary',
        (tester) async {
      final terminals = createTerminals(3);
      final switchedIds = <String>[];

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SizedBox(
              width: 400,
              height: 60,
              child: CompactTabStrip(
                terminals: terminals,
                selectedTerminalId: 't0',
                onSwitch: (id) => switchedIds.add(id),
                onCreate: () {},
              ),
            ),
          ),
        ),
      );

      // Swipe right on first terminal — should not trigger switch
      await tester.fling(
        find.byType(CompactTabStrip),
        const Offset(100, 0),
        500,
      );
      await tester.pump();

      expect(switchedIds, isEmpty);
    });

    testWidgets('swipe on last terminal does not switch when at boundary',
        (tester) async {
      final terminals = createTerminals(3);
      final switchedIds = <String>[];

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SizedBox(
              width: 400,
              height: 60,
              child: CompactTabStrip(
                terminals: terminals,
                selectedTerminalId: 't2',
                onSwitch: (id) => switchedIds.add(id),
                onCreate: () {},
              ),
            ),
          ),
        ),
      );

      // Swipe left on last terminal — should not trigger switch
      await tester.fling(
        find.byType(CompactTabStrip),
        const Offset(-100, 0),
        500,
      );
      await tester.pump();

      expect(switchedIds, isEmpty);
    });

    testWidgets('long press on tab triggers onLongPress', (tester) async {
      final terminals = createTerminals(2);
      String? longPressedId;

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: CompactTabStrip(
              terminals: terminals,
              selectedTerminalId: 't0',
              onSwitch: (_) {},
              onCreate: () {},
              onLongPress: (id) => longPressedId = id,
            ),
          ),
        ),
      );

      // Manual long press gesture: SingleChildScrollView swallows tester.longPress
      final gesture = await tester.startGesture(
        tester.getCenter(find.byKey(const Key('compact-tab-t1'))),
      );
      await tester.pump(const Duration(milliseconds: 600));
      await gesture.up();
      await tester.pump();

      expect(longPressedId, 't1');
    });

    testWidgets('selected tab has visual distinction', (tester) async {
      final terminals = createTerminals(3);

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: CompactTabStrip(
              terminals: terminals,
              selectedTerminalId: 't1',
              onSwitch: (_) {},
              onCreate: () {},
            ),
          ),
        ),
      );

      // The selected tab should have a different visual state
      final selectedTab = find.byKey(const Key('compact-tab-t1'));
      final unselectedTab = find.byKey(const Key('compact-tab-t0'));

      expect(selectedTab, findsOneWidget);
      expect(unselectedTab, findsOneWidget);

      // Check decoration difference: selected should have primary color, unselected transparent
      final selectedDecoratedBoxes = tester.widgetList<DecoratedBox>(
        find.descendant(
          of: selectedTab,
          matching: find.byType(DecoratedBox),
        ),
      );
      final unselectedDecoratedBoxes = tester.widgetList<DecoratedBox>(
        find.descendant(
          of: unselectedTab,
          matching: find.byType(DecoratedBox),
        ),
      );

      // Find the first DecoratedBox with BoxDecoration (our tab decoration)
      final selectedDeco = selectedDecoratedBoxes
          .map((db) => db.decoration)
          .whereType<BoxDecoration>()
          .firstOrNull;
      final unselectedDeco = unselectedDecoratedBoxes
          .map((db) => db.decoration)
          .whereType<BoxDecoration>()
          .firstOrNull;

      expect(
        selectedDeco?.color != unselectedDeco?.color,
        isTrue,
      );
    });

    testWidgets('renders with empty terminal list', (tester) async {
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: CompactTabStrip(
              terminals: [],
              selectedTerminalId: null,
              onSwitch: (_) {},
              onCreate: () {},
            ),
          ),
        ),
      );

      // Should still render the create button
      expect(find.byKey(const Key('compact-tab-create')), findsOneWidget);
    });

    testWidgets('+ button is disabled when createDisabled is true',
        (tester) async {
      final terminals = createTerminals(5);

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: CompactTabStrip(
              terminals: terminals,
              selectedTerminalId: 't0',
              createDisabled: true,
              onSwitch: (_) {},
              onCreate: () {},
            ),
          ),
        ),
      );

      final createButton = find.byKey(const Key('compact-tab-create'));
      expect(createButton, findsOneWidget);

      final iconButton = tester.widget<IconButton>(find.descendant(
        of: createButton,
        matching: find.byType(IconButton),
      ));
      expect(iconButton.onPressed, isNull);
    });

    testWidgets('renders titles with truncation at 5 terminals without overflow',
        (tester) async {
      final terminals = createTerminals(5);

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SizedBox(
              width: 400,
              height: 60,
              child: CompactTabStrip(
                terminals: terminals,
                selectedTerminalId: 't0',
                onSwitch: (_) {},
                onCreate: () {},
              ),
            ),
          ),
        ),
      );

      // Should show compact numbers: 1, 2, 3, 4, 5
      expect(find.text('1'), findsOneWidget);
      expect(find.text('2'), findsOneWidget);
      expect(find.text('3'), findsOneWidget);
      expect(find.text('4'), findsOneWidget);
      expect(find.text('5'), findsOneWidget);

      // Titles should still be rendered (with overflow: ellipsis truncation)
      expect(find.text('Terminal 1'), findsOneWidget);
      expect(find.text('Terminal 2'), findsOneWidget);
      expect(find.text('Terminal 3'), findsOneWidget);
      expect(find.text('Terminal 4'), findsOneWidget);
      expect(find.text('Terminal 5'), findsOneWidget);

      // Should render without overflow error
      expect(tester.takeException(), isNull);
    });

    testWidgets('tap and swipe still work with 5 terminals', (tester) async {
      final terminals = createTerminals(5);
      String? switchedId;

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SizedBox(
              width: 400,
              height: 60,
              child: CompactTabStrip(
                terminals: terminals,
                selectedTerminalId: 't0',
                onSwitch: (id) => switchedId = id,
                onCreate: () {},
              ),
            ),
          ),
        ),
      );

      // Tap last tab — need to scroll into view first (SingleChildScrollView)
      await tester.ensureVisible(find.byKey(const Key('compact-tab-t4')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('compact-tab-t4')));
      await tester.pump();
      expect(switchedId, 't4');

      // Swipe left from first selected should work
      switchedId = null;
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SizedBox(
              width: 400,
              height: 60,
              child: CompactTabStrip(
                terminals: terminals,
                selectedTerminalId: 't2',
                onSwitch: (id) => switchedId = id,
                onCreate: () {},
              ),
            ),
          ),
        ),
      );

      await tester.fling(
        find.byType(CompactTabStrip),
        const Offset(-100, 0),
        500,
      );
      await tester.pump();
      expect(switchedId, 't3');
    });

    testWidgets('closed terminal renders but is not switchable', (tester) async {
      final terminals = [
        RuntimeTerminal(
          terminalId: 't0',
          title: 'Running',
          cwd: '~',
          command: '/bin/bash',
          status: 'running',
          views: {},
        ),
        RuntimeTerminal(
          terminalId: 't1',
          title: 'Closed',
          cwd: '~',
          command: '/bin/bash',
          status: 'closed',
          views: {},
        ),
      ];
      String? switchedId;

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: CompactTabStrip(
              terminals: terminals,
              selectedTerminalId: 't0',
              onSwitch: (id) => switchedId = id,
              onCreate: () {},
            ),
          ),
        ),
      );

      // Both terminals should render
      expect(find.byKey(const Key('compact-tab-t0')), findsOneWidget);
      expect(find.byKey(const Key('compact-tab-t1')), findsOneWidget);
      // Numbers: 1 and 2
      expect(find.text('1'), findsOneWidget);
      expect(find.text('2'), findsOneWidget);

      // Closed terminal should be rendered but not switchable
      await tester.tap(find.byKey(const Key('compact-tab-t1')));
      await tester.pump();
      expect(switchedId, isNull);
    });

    testWidgets('swipe skips closed terminal to next attachable one',
        (tester) async {
      final terminals = [
        RuntimeTerminal(
          terminalId: 't0',
          title: 'Running 1',
          cwd: '~',
          command: '/bin/bash',
          status: 'running',
          views: {},
        ),
        RuntimeTerminal(
          terminalId: 't1',
          title: 'Closed',
          cwd: '~',
          command: '/bin/bash',
          status: 'closed',
          views: {},
        ),
        RuntimeTerminal(
          terminalId: 't2',
          title: 'Running 2',
          cwd: '~',
          command: '/bin/bash',
          status: 'running',
          views: {},
        ),
      ];
      String? switchedId;

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SizedBox(
              width: 400,
              height: 60,
              child: CompactTabStrip(
                terminals: terminals,
                selectedTerminalId: 't0',
                onSwitch: (id) => switchedId = id,
                onCreate: () {},
              ),
            ),
          ),
        ),
      );

      // Swipe left should skip closed t1 and land on t2
      await tester.fling(
        find.byType(CompactTabStrip),
        const Offset(-100, 0),
        500,
      );
      await tester.pump();

      expect(switchedId, 't2');
    });

    testWidgets('swipe does not switch when all neighbors are closed',
        (tester) async {
      final terminals = [
        RuntimeTerminal(
          terminalId: 't0',
          title: 'Running',
          cwd: '~',
          command: '/bin/bash',
          status: 'running',
          views: {},
        ),
        RuntimeTerminal(
          terminalId: 't1',
          title: 'Closed',
          cwd: '~',
          command: '/bin/bash',
          status: 'closed',
          views: {},
        ),
      ];
      final switchedIds = <String>[];

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SizedBox(
              width: 400,
              height: 60,
              child: CompactTabStrip(
                terminals: terminals,
                selectedTerminalId: 't0',
                onSwitch: (id) => switchedIds.add(id),
                onCreate: () {},
              ),
            ),
          ),
        ),
      );

      // Swipe left — t1 is closed, no attachable neighbor
      await tester.fling(
        find.byType(CompactTabStrip),
        const Offset(-100, 0),
        500,
      );
      await tester.pump();

      expect(switchedIds, isEmpty);
    });

    testWidgets('overflow scroll does not trigger terminal switch',
        (tester) async {
      // 8 terminals — overflows 400px, ScrollView will consume horizontal drag
      final terminals = createTerminals(8);
      final switchedIds = <String>[];

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SizedBox(
              width: 400,
              height: 60,
              child: CompactTabStrip(
                terminals: terminals,
                selectedTerminalId: 't0',
                onSwitch: (id) => switchedIds.add(id),
                onCreate: () {},
              ),
            ),
          ),
        ),
      );

      // Slow fling (drag) to scroll — ScrollView should consume it
      await tester.fling(
        find.byType(CompactTabStrip),
        const Offset(-60, 0),
        200, // slower speed → ScrollView wins
      );
      await tester.pump();

      // Should NOT switch terminal — ScrollView consumed the drag
      expect(switchedIds, isEmpty);
    });
  });
}
