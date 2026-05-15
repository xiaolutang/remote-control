import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xterm/xterm.dart';

void main() {
  testWidgets(
    'TerminalView keeps short content visible during out-of-range scroll offsets',
    (tester) async {
      final terminal = Terminal(maxLines: 1000);
      final scrollController = ScrollController();
      addTearDown(scrollController.dispose);

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SizedBox(
              width: 320,
              height: 160,
              child: TerminalView(
                terminal,
                scrollController: scrollController,
                padding: EdgeInsets.zero,
              ),
            ),
          ),
        ),
      );

      terminal.write('short prompt');
      await tester.pump();

      expect(scrollController.position.maxScrollExtent, 0);

      scrollController.jumpTo(80);
      await tester.pump();

      final dynamic state = tester.state(find.byType(TerminalView));
      final cursorRect = state.cursorRect as Rect;

      expect(cursorRect.top, greaterThanOrEqualTo(0));
      expect(cursorRect.bottom, lessThanOrEqualTo(160));
    },
  );

  testWidgets(
    'TerminalView keeps a short active prompt visible when scrollback is long',
    (tester) async {
      final terminal = Terminal(maxLines: 1000);
      final scrollController = ScrollController();
      addTearDown(scrollController.dispose);

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SizedBox(
              width: 320,
              height: 160,
              child: TerminalView(
                terminal,
                scrollController: scrollController,
                padding: EdgeInsets.zero,
              ),
            ),
          ),
        ),
      );

      terminal.write(List.generate(80, (index) => 'line $index\r\n').join());
      await tester.pump();
      scrollController.jumpTo(scrollController.position.maxScrollExtent);
      await tester.pump();

      terminal.write('\x1b[2J\x1b[Hshort prompt');
      await tester.pump();
      scrollController.jumpTo(scrollController.position.maxScrollExtent);
      await tester.pump();

      final dynamic state = tester.state(find.byType(TerminalView));
      final cursorRect = state.cursorRect as Rect;

      expect(cursorRect.top, greaterThanOrEqualTo(0));
      expect(cursorRect.bottom, lessThanOrEqualTo(160));
    },
  );

  testWidgets(
    'TerminalView keeps a short prompt visible after alternate buffer exits with long scrollback',
    (tester) async {
      final terminal = Terminal(maxLines: 1000);
      final scrollController = ScrollController();
      addTearDown(scrollController.dispose);

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SizedBox(
              width: 320,
              height: 160,
              child: TerminalView(
                terminal,
                scrollController: scrollController,
                padding: EdgeInsets.zero,
              ),
            ),
          ),
        ),
      );

      terminal.write(List.generate(80, (index) => 'line $index\r\n').join());
      await tester.pump();
      scrollController.jumpTo(scrollController.position.maxScrollExtent);
      await tester.pump();

      terminal.write('\x1b[2J\x1b[Hshort prompt');
      await tester.pump();
      terminal.write('\x1b[?1049halt screen');
      await tester.pump();
      terminal.write('\x1b[?1049l');
      await tester.pump();

      scrollController.jumpTo(scrollController.position.maxScrollExtent);
      await tester.pump();

      final dynamic state = tester.state(find.byType(TerminalView));
      final cursorRect = state.cursorRect as Rect;

      expect(cursorRect.top, greaterThanOrEqualTo(0));
      expect(cursorRect.bottom, lessThanOrEqualTo(160));
    },
  );
}
