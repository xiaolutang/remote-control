import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rc_client/models/runtime_terminal.dart';
import 'package:rc_client/widgets/terminal_page_indicator.dart';

import '../helpers/test_terminals.dart';

void main() {
  group('TerminalPageIndicator', () {

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
          body: TerminalPageIndicator(
            terminals: terminals,
            selectedTerminalId: selectedTerminalId,
            onSwitch: onSwitch ?? (_) {},
            onCreate: onCreate ?? () {},
            createDisabled: createDisabled,
            onContextMenu: onContextMenu,
          ),
        ),
      );
    }

    testWidgets('renders "1/3" format page label', (tester) async {
      final terminals = createTestTerminals(3);

      await tester.pumpWidget(buildSubject(
        terminals: terminals,
        selectedTerminalId: 't0',
      ));

      expect(find.byKey(const Key('page-indicator-label')), findsOneWidget);
      expect(find.text('1/3'), findsOneWidget);
    });

    testWidgets('clicking left arrow switches to previous terminal',
        (tester) async {
      final terminals = createTestTerminals(3);
      String? switchedId;

      await tester.pumpWidget(buildSubject(
        terminals: terminals,
        selectedTerminalId: 't1',
        onSwitch: (id) => switchedId = id,
      ));

      await tester.tap(find.byKey(const Key('page-indicator-left')));
      await tester.pump();

      expect(switchedId, 't0');
    });

    testWidgets('clicking right arrow switches to next terminal',
        (tester) async {
      final terminals = createTestTerminals(3);
      String? switchedId;

      await tester.pumpWidget(buildSubject(
        terminals: terminals,
        selectedTerminalId: 't0',
        onSwitch: (id) => switchedId = id,
      ));

      await tester.tap(find.byKey(const Key('page-indicator-right')));
      await tester.pump();

      expect(switchedId, 't1');
    });

    testWidgets('left arrow is disabled at first terminal', (tester) async {
      final terminals = createTestTerminals(3);
      final switchedIds = <String>[];

      await tester.pumpWidget(buildSubject(
        terminals: terminals,
        selectedTerminalId: 't0',
        onSwitch: (id) => switchedIds.add(id),
      ));

      final leftButton = tester.widget<IconButton>(
        find.byKey(const Key('page-indicator-left')),
      );
      expect(leftButton.onPressed, isNull);
    });

    testWidgets('right arrow is disabled at last terminal', (tester) async {
      final terminals = createTestTerminals(3);
      final switchedIds = <String>[];

      await tester.pumpWidget(buildSubject(
        terminals: terminals,
        selectedTerminalId: 't2',
        onSwitch: (id) => switchedIds.add(id),
      ));

      final rightButton = tester.widget<IconButton>(
        find.byKey(const Key('page-indicator-right')),
      );
      expect(rightButton.onPressed, isNull);
    });

    testWidgets('tapping center opens BottomSheet with terminal list',
        (tester) async {
      final terminals = createTestTerminals(3);

      await tester.pumpWidget(buildSubject(
        terminals: terminals,
        selectedTerminalId: 't0',
      ));

      // Tap center to open BottomSheet
      await tester.tap(find.byKey(const Key('page-indicator-center')));
      await tester.pumpAndSettle();

      // BottomSheet should show terminal titles
      expect(find.text('终端列表'), findsOneWidget);
      expect(find.text('Terminal 1'), findsOneWidget);
      expect(find.text('Terminal 2'), findsOneWidget);
      expect(find.text('Terminal 3'), findsOneWidget);
    });

    testWidgets('BottomSheet tapping terminal triggers onSwitch and closes',
        (tester) async {
      final terminals = createTestTerminals(3);
      String? switchedId;

      await tester.pumpWidget(buildSubject(
        terminals: terminals,
        selectedTerminalId: 't0',
        onSwitch: (id) => switchedId = id,
      ));

      // Open BottomSheet
      await tester.tap(find.byKey(const Key('page-indicator-center')));
      await tester.pumpAndSettle();

      // Tap terminal t2 in the list
      await tester
          .tap(find.byKey(const Key('bottom-sheet-terminal-t2')));
      await tester.pumpAndSettle();

      expect(switchedId, 't2');
      // BottomSheet should be closed
      expect(find.text('终端列表'), findsNothing);
    });

    testWidgets('BottomSheet tapping create triggers onCreate', (tester) async {
      final terminals = createTestTerminals(2);
      var createCalled = false;

      await tester.pumpWidget(buildSubject(
        terminals: terminals,
        selectedTerminalId: 't0',
        onCreate: () => createCalled = true,
      ));

      // Open BottomSheet
      await tester.tap(find.byKey(const Key('page-indicator-center')));
      await tester.pumpAndSettle();

      // Tap create button
      await tester.tap(find.byKey(const Key('page-indicator-create')));
      await tester.pumpAndSettle();

      expect(createCalled, isTrue);
    });

    testWidgets('long press on center triggers onContextMenu', (tester) async {
      final terminals = createTestTerminals(3);
      String? contextMenuId;

      await tester.pumpWidget(buildSubject(
        terminals: terminals,
        selectedTerminalId: 't0',
        onContextMenu: (id, position) => contextMenuId = id,
      ));

      // Long press the center area
      await tester.longPress(find.byKey(const Key('page-indicator-center')));
      await tester.pump();

      expect(contextMenuId, 't0');
    });

    testWidgets('0 terminals renders nothing (SizedBox.shrink)',
        (tester) async {
      await tester.pumpWidget(buildSubject(
        terminals: [],
        selectedTerminalId: null,
      ));

      expect(find.byType(TerminalPageIndicator), findsOneWidget);
      expect(find.byKey(const Key('page-indicator-label')), findsNothing);
      expect(find.byKey(const Key('page-indicator-left')), findsNothing);
      expect(find.byKey(const Key('page-indicator-right')), findsNothing);

      // Verify SizedBox.shrink is used
      final sizedBox = tester.widget<SizedBox>(find.descendant(
        of: find.byType(TerminalPageIndicator),
        matching: find.byType(SizedBox),
      ));
      expect(sizedBox.width, equals(0));
      expect(sizedBox.height, equals(0));
    });

    testWidgets('1 terminal shows "1/1" with both arrows disabled',
        (tester) async {
      final terminals = createTestTerminals(1);

      await tester.pumpWidget(buildSubject(
        terminals: terminals,
        selectedTerminalId: 't0',
      ));

      expect(find.text('1/1'), findsOneWidget);

      final leftButton = tester.widget<IconButton>(
        find.byKey(const Key('page-indicator-left')),
      );
      final rightButton = tester.widget<IconButton>(
        find.byKey(const Key('page-indicator-right')),
      );

      expect(leftButton.onPressed, isNull);
      expect(rightButton.onPressed, isNull);
    });

    testWidgets('height is fixed at 32px', (tester) async {
      final terminals = createTestTerminals(3);

      await tester.pumpWidget(buildSubject(
        terminals: terminals,
        selectedTerminalId: 't0',
      ));

      // Find the Container with fixed height
      final container = tester.widget<Container>(find.descendant(
        of: find.byType(TerminalPageIndicator),
        matching: find.byType(Container),
      ));

      final constraints = container.constraints;
      expect(constraints, isNotNull);
      expect(constraints!.maxHeight, equals(32));
    });

    testWidgets('page label updates with different selected terminal',
        (tester) async {
      final terminals = createTestTerminals(5);

      await tester.pumpWidget(buildSubject(
        terminals: terminals,
        selectedTerminalId: 't3',
      ));

      expect(find.text('4/5'), findsOneWidget);
    });

    testWidgets('create button in BottomSheet is disabled when createDisabled',
        (tester) async {
      final terminals = createTestTerminals(2);

      await tester.pumpWidget(buildSubject(
        terminals: terminals,
        selectedTerminalId: 't0',
        createDisabled: true,
      ));

      // Open BottomSheet
      await tester.tap(find.byKey(const Key('page-indicator-center')));
      await tester.pumpAndSettle();

      // Find the create button in BottomSheet
      final createButton = find.byKey(const Key('page-indicator-create'));
      expect(createButton, findsOneWidget);

      // The inner IconButton should be disabled
      final iconButton = tester.widget<IconButton>(find.descendant(
        of: createButton,
        matching: find.byType(IconButton),
      ));
      expect(iconButton.onPressed, isNull);
    });
  });
}
