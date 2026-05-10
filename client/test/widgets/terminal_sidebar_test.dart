import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rc_client/models/runtime_terminal.dart';
import 'package:rc_client/widgets/terminal_sidebar.dart';

void main() {
  group('TerminalSidebar', () {
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

    Widget buildSubject({
      List<RuntimeTerminal> terminals = const [],
      String? selectedTerminalId,
      ValueChanged<String>? onSwitch,
      VoidCallback? onCreate,
      bool createDisabled = false,
      void Function(String, Offset)? onContextMenu,
    }) {
      return MaterialApp(
        home: Scaffold(
          body: Row(
            children: [
              TerminalSidebar(
                terminals: terminals,
                selectedTerminalId: selectedTerminalId,
                onSwitch: onSwitch ?? (_) {},
                onCreate: onCreate ?? () {},
                createDisabled: createDisabled,
                onContextMenu: onContextMenu,
              ),
              const Expanded(child: Placeholder()),
            ],
          ),
        ),
      );
    }

    testWidgets('collapsed state renders N terminal icons with selection indicator',
        (tester) async {
      final terminals = createTerminals(3);

      await tester.pumpWidget(buildSubject(
        terminals: terminals,
        selectedTerminalId: 't1',
      ));

      // All 3 terminal items should be present
      expect(find.byKey(const Key('sidebar-t0')), findsOneWidget);
      expect(find.byKey(const Key('sidebar-t1')), findsOneWidget);
      expect(find.byKey(const Key('sidebar-t2')), findsOneWidget);

      // Terminal icons should be visible
      expect(find.byIcon(Icons.terminal), findsNWidgets(3));

      // Selected item should have a non-transparent indicator
      final selectedItem = find.byKey(const Key('sidebar-t1'));
      final animatedContainers = tester.widgetList<AnimatedContainer>(
        find.descendant(
          of: selectedItem,
          matching: find.byType(AnimatedContainer),
        ),
      );
      // The first AnimatedContainer is the 3px indicator
      final indicator = animatedContainers.first;
      final decoration = indicator.decoration as BoxDecoration;
      expect(decoration.color, isNot(Colors.transparent));
    });

    testWidgets('hover expands to show terminal titles', (tester) async {
      final terminals = createTerminals(2);

      await tester.pumpWidget(buildSubject(
        terminals: terminals,
        selectedTerminalId: 't0',
      ));

      // Initially collapsed - titles should NOT be visible
      expect(find.text('Terminal 1'), findsNothing);
      expect(find.text('Terminal 2'), findsNothing);

      // Hover into the sidebar
      final sidebar = find.byType(TerminalSidebar);
      final gesture = await tester.createGesture(
        kind: PointerDeviceKind.mouse,
      );
      await gesture.addPointer(location: Offset.zero);
      await tester.pump();
      await gesture.moveTo(tester.getCenter(sidebar));
      await tester.pumpAndSettle();

      // After expand, titles should be visible
      expect(find.text('Terminal 1'), findsOneWidget);
      expect(find.text('Terminal 2'), findsOneWidget);

      // Hover out
      await gesture.moveTo(const Offset(500, 500));
      await tester.pumpAndSettle();

      // After leaving, titles should be gone
      expect(find.text('Terminal 1'), findsNothing);
      expect(find.text('Terminal 2'), findsNothing);
    });

    testWidgets('clicking terminal item triggers onSwitch with correct terminalId',
        (tester) async {
      final terminals = createTerminals(3);
      String? switchedId;

      await tester.pumpWidget(buildSubject(
        terminals: terminals,
        selectedTerminalId: 't0',
        onSwitch: (id) => switchedId = id,
      ));

      await tester.tap(find.byKey(const Key('sidebar-t2')));
      await tester.pump();

      expect(switchedId, 't2');
    });

    testWidgets('clicking create button triggers onCreate', (tester) async {
      final terminals = createTerminals(2);
      var createCalled = false;

      await tester.pumpWidget(buildSubject(
        terminals: terminals,
        selectedTerminalId: 't0',
        onCreate: () => createCalled = true,
      ));

      await tester.tap(find.byKey(const Key('sidebar-create')));
      await tester.pump();

      expect(createCalled, isTrue);
    });

    testWidgets('createDisabled=true disables create button', (tester) async {
      final terminals = createTerminals(5);

      await tester.pumpWidget(buildSubject(
        terminals: terminals,
        selectedTerminalId: 't0',
        createDisabled: true,
        onCreate: () {},
      ));

      final createButton = find.byKey(const Key('sidebar-create'));
      expect(createButton, findsOneWidget);

      // IconButton inside should be disabled
      final iconButton = tester.widget<IconButton>(find.descendant(
        of: createButton,
        matching: find.byType(IconButton),
      ));
      expect(iconButton.onPressed, isNull);
    });

    testWidgets('right-click terminal triggers onContextMenu', (tester) async {
      final terminals = createTerminals(2);
      String? contextMenuId;
      Offset? contextMenuPosition;

      await tester.pumpWidget(buildSubject(
        terminals: terminals,
        selectedTerminalId: 't0',
        onContextMenu: (id, position) {
          contextMenuId = id;
          contextMenuPosition = position;
        },
      ));

      // Simulate secondary tap (right-click)
      await tester.tap(
        find.byKey(const Key('sidebar-t1')),
        buttons: kSecondaryMouseButton,
      );
      await tester.pump();

      expect(contextMenuId, 't1');
      expect(contextMenuPosition, isNotNull);
    });

    testWidgets('0 terminals shows only create button', (tester) async {
      var createCalled = false;

      await tester.pumpWidget(buildSubject(
        terminals: [],
        selectedTerminalId: null,
        onCreate: () => createCalled = true,
      ));

      // No terminal items
      expect(find.byIcon(Icons.terminal), findsNothing);
      // Create button still present
      expect(find.byKey(const Key('sidebar-create')), findsOneWidget);
      // Create button should work
      await tester.tap(find.byKey(const Key('sidebar-create')));
      await tester.pump();
      expect(createCalled, isTrue);
    });

    testWidgets('many terminals are scrollable in ListView', (tester) async {
      // Create enough terminals to overflow a typical test viewport height
      final terminals = List.generate(
        30,
        (i) => RuntimeTerminal(
          terminalId: 't$i',
          title: 'Terminal ${i + 1}',
          cwd: '~',
          command: '/bin/bash',
          status: 'running',
          views: {},
        ),
      );

      await tester.pumpWidget(buildSubject(
        terminals: terminals,
        selectedTerminalId: 't0',
      ));

      // ListView should be present
      expect(find.byType(ListView), findsOneWidget);

      // First item should be visible
      expect(find.byKey(const Key('sidebar-t0')), findsOneWidget);
      // Last item may not be built yet (ListView lazy loading)
      // but it exists in the data model

      // Scroll down
      await tester.fling(
        find.byType(ListView),
        const Offset(0, -300),
        500,
      );
      await tester.pump();

      // Should scroll without error
      expect(tester.takeException(), isNull);
    });

    testWidgets('leaving sidebar collapses back to 48px', (tester) async {
      final terminals = createTerminals(2);

      await tester.pumpWidget(buildSubject(
        terminals: terminals,
        selectedTerminalId: 't0',
      ));

      // Initially collapsed - no titles visible
      expect(find.text('Terminal 1'), findsNothing);

      // Hover in
      final sidebar = find.byType(TerminalSidebar);
      final gesture = await tester.createGesture(
        kind: PointerDeviceKind.mouse,
      );
      await gesture.addPointer(location: Offset.zero);
      await tester.pump();
      await gesture.moveTo(tester.getCenter(sidebar));
      await tester.pumpAndSettle();

      // Now expanded - titles visible
      expect(find.text('Terminal 1'), findsOneWidget);

      // Hover out
      await gesture.moveTo(const Offset(500, 500));
      await tester.pumpAndSettle();

      // Collapsed again - titles gone
      expect(find.text('Terminal 1'), findsNothing);
    });
  });
}
