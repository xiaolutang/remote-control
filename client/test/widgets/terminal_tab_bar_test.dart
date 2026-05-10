import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rc_client/models/runtime_terminal.dart';
import 'package:rc_client/widgets/terminal_tab_bar.dart';

void main() {
  group('TerminalTabBar', () {
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

    testWidgets('renders N tabs with correct titles', (tester) async {
      final terminals = createTerminals(3);

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: TerminalTabBar(
              terminals: terminals,
              selectedTerminalId: 't1',
              onSwitch: (_) {},
              onCreate: () {},
            ),
          ),
        ),
      );

      expect(find.text('Terminal 1'), findsOneWidget);
      expect(find.text('Terminal 2'), findsOneWidget);
      expect(find.text('Terminal 3'), findsOneWidget);
    });

    testWidgets('selected tab has visual distinction', (tester) async {
      final terminals = createTerminals(2);

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: TerminalTabBar(
              terminals: terminals,
              selectedTerminalId: 't0',
              onSwitch: (_) {},
              onCreate: () {},
            ),
          ),
        ),
      );

      // Find tabs by key (InkWell has the key)
      final selectedTab = find.byKey(const Key('tab-t0'));
      final unselectedTab = find.byKey(const Key('tab-t1'));

      expect(selectedTab, findsOneWidget);
      expect(unselectedTab, findsOneWidget);

      // Find the Container child inside each InkWell for decoration check
      final selectedContainer = tester.widget<Container>(
        find.descendant(
          of: selectedTab,
          matching: find.byType(Container),
        ),
      );
      final unselectedContainer = tester.widget<Container>(
        find.descendant(
          of: unselectedTab,
          matching: find.byType(Container),
        ),
      );

      final selectedDecoration = selectedContainer.decoration as BoxDecoration?;
      final unselectedDecoration =
          unselectedContainer.decoration as BoxDecoration?;

      // Selected should have bottom border indicator
      expect(
        selectedDecoration?.border?.bottom.width,
        greaterThan(unselectedDecoration?.border?.bottom.width ?? 0),
      );
    });

    testWidgets('tapping a tab triggers onSwitch with correct terminalId',
        (tester) async {
      final terminals = createTerminals(3);
      String? switchedId;

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: TerminalTabBar(
              terminals: terminals,
              selectedTerminalId: 't0',
              onSwitch: (id) => switchedId = id,
              onCreate: () {},
            ),
          ),
        ),
      );

      await tester.tap(find.byKey(const Key('tab-t2')));
      await tester.pump();

      expect(switchedId, 't2');
    });

    testWidgets('tapping + button triggers onCreate', (tester) async {
      final terminals = createTerminals(2);
      var createCalled = false;

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: TerminalTabBar(
              terminals: terminals,
              selectedTerminalId: 't0',
              onSwitch: (_) {},
              onCreate: () => createCalled = true,
            ),
          ),
        ),
      );

      await tester.tap(find.byKey(const Key('tab-bar-create')));
      await tester.pump();

      expect(createCalled, isTrue);
    });

    testWidgets('+ button is disabled when createDisabled is true',
        (tester) async {
      final terminals = createTerminals(5);
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: TerminalTabBar(
              terminals: terminals,
              selectedTerminalId: 't0',
              createDisabled: true,
              onSwitch: (_) {},
              onCreate: () {},
            ),
          ),
        ),
      );

      final createButton = find.byKey(const Key('tab-bar-create'));
      expect(createButton, findsOneWidget);

      // IconButton should be disabled — find the IconButton ancestor
      final iconButton = tester.widget<IconButton>(find.descendant(
        of: createButton,
        matching: find.byType(IconButton),
      ));
      expect(iconButton.onPressed, isNull);
    });

    testWidgets('+ button is enabled when createDisabled is false',
        (tester) async {
      final terminals = createTerminals(3);
      var createCalled = false;

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: TerminalTabBar(
              terminals: terminals,
              selectedTerminalId: 't0',
              createDisabled: false,
              onSwitch: (_) {},
              onCreate: () => createCalled = true,
            ),
          ),
        ),
      );

      await tester.tap(find.byKey(const Key('tab-bar-create')));
      await tester.pump();

      expect(createCalled, isTrue);
    });

    testWidgets('+ button is clickable with 0 terminals', (tester) async {
      var createCalled = false;

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: TerminalTabBar(
              terminals: [],
              selectedTerminalId: null,
              onSwitch: (_) {},
              onCreate: () => createCalled = true,
            ),
          ),
        ),
      );

      await tester.tap(find.byKey(const Key('tab-bar-create')));
      await tester.pump();

      expect(createCalled, isTrue);
    });

    testWidgets('tab text overflow does not break layout', (tester) async {
      final terminals = [
        RuntimeTerminal(
          terminalId: 't0',
          title: 'A very long terminal title that should be truncated properly',
          cwd: '~',
          command: '/bin/bash',
          status: 'running',
          views: {},
        ),
      ];

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SizedBox(
              width: 200,
              child: TerminalTabBar(
                terminals: terminals,
                selectedTerminalId: 't0',
                onSwitch: (_) {},
                onCreate: () {},
              ),
            ),
          ),
        ),
      );

      // Should render without overflow error
      expect(find.byType(TerminalTabBar), findsOneWidget);
      expect(tester.takeException(), isNull);
    });

    testWidgets('renders context menu on tab long press with correct position',
        (tester) async {
      final terminals = createTerminals(2);
      String? contextMenuId;
      Offset? contextMenuPosition;

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: TerminalTabBar(
              terminals: terminals,
              selectedTerminalId: 't0',
              onSwitch: (_) {},
              onCreate: () {},
              onContextMenu: (id, position) {
                contextMenuId = id;
                contextMenuPosition = position;
              },
            ),
          ),
        ),
      );

      // Manual long press gesture: SingleChildScrollView swallows tester.longPress
      final tabCenter = tester.getCenter(find.byKey(const Key('tab-t1')));
      final gesture = await tester.startGesture(tabCenter);
      await tester.pump(const Duration(milliseconds: 600));
      await gesture.up();
      await tester.pump();

      expect(contextMenuId, 't1');
      expect(contextMenuPosition, isNotNull);
      // Position should be close to the tab's center
      expect(
        (contextMenuPosition! - tabCenter).distance,
        lessThan(50),
      );
    });

    testWidgets('secondary click triggers onContextMenu with position',
        (tester) async {
      final terminals = createTerminals(2);
      String? contextMenuId;
      Offset? contextMenuPosition;

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: TerminalTabBar(
              terminals: terminals,
              selectedTerminalId: 't0',
              onSwitch: (_) {},
              onCreate: () {},
              onContextMenu: (id, position) {
                contextMenuId = id;
                contextMenuPosition = position;
              },
            ),
          ),
        ),
      );

      // Simulate secondary tap (right-click)
      await tester.tap(
        find.byKey(const Key('tab-t1')),
        buttons: kSecondaryMouseButton,
      );
      await tester.pump();

      expect(contextMenuId, 't1');
      expect(contextMenuPosition, isNotNull);
    });

    testWidgets('renders many tabs in scrollable viewport without overflow',
        (tester) async {
      // Use long titles to force overflow beyond viewport width
      final terminals = List.generate(
        10,
        (i) => RuntimeTerminal(
          terminalId: 't$i',
          title: 'Terminal ${i + 1} — Long Title',
          cwd: '~',
          command: '/bin/bash',
          status: 'running',
          views: {},
        ),
      );

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SizedBox(
              width: 300,
              child: TerminalTabBar(
                terminals: terminals,
                selectedTerminalId: 't0',
                onSwitch: (_) {},
                onCreate: () {},
              ),
            ),
          ),
        ),
      );

      // First tab should be visible
      expect(find.byKey(const Key('tab-t0')), findsOneWidget);
      // Last tab exists in the widget tree (inside ScrollView)
      expect(find.byKey(const Key('tab-t9')), findsOneWidget);
      // Should render without overflow error
      expect(tester.takeException(), isNull);
    });

    testWidgets('scrolls to reveal off-screen tab', (tester) async {
      final terminals = List.generate(
        10,
        (i) => RuntimeTerminal(
          terminalId: 't$i',
          title: 'Terminal ${i + 1} — Long Title',
          cwd: '~',
          command: '/bin/bash',
          status: 'running',
          views: {},
        ),
      );

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SizedBox(
              width: 300,
              child: TerminalTabBar(
                terminals: terminals,
                selectedTerminalId: 't0',
                onSwitch: (_) {},
                onCreate: () {},
              ),
            ),
          ),
        ),
      );

      // Find the ScrollView and fling left to scroll
      final scrollView = find.byType(SingleChildScrollView);
      expect(scrollView, findsOneWidget);

      await tester.fling(scrollView, const Offset(-300, 0), 500);
      await tester.pump();

      // After scrolling, last tab should now be visible
      // The scroll should succeed without errors
      expect(tester.takeException(), isNull);
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
            body: TerminalTabBar(
              terminals: terminals,
              selectedTerminalId: 't0',
              onSwitch: (id) => switchedId = id,
              onCreate: () {},
            ),
          ),
        ),
      );

      // Both terminals should render
      expect(find.byKey(const Key('tab-t0')), findsOneWidget);
      expect(find.byKey(const Key('tab-t1')), findsOneWidget);

      // Closed terminal should be rendered but not switchable
      await tester.tap(find.byKey(const Key('tab-t1')));
      await tester.pump();
      expect(switchedId, isNull);
    });
  });
}
