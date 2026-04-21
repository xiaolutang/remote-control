import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xterm/xterm.dart';

void main() {
  testWidgets(
    'TerminalView reports local caret geometry with a non-identity global transform',
    (tester) async {
      final focusNode = FocusNode();
      addTearDown(focusNode.dispose);

      final terminal = Terminal(maxLines: 1000);

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: Padding(
              padding: const EdgeInsets.only(left: 120, top: 90),
              child: SizedBox(
                width: 220,
                height: 100,
                child: TerminalView(
                  terminal,
                  focusNode: focusNode,
                  padding: EdgeInsets.zero,
                  keyboardType: TextInputType.text,
                ),
              ),
            ),
          ),
        ),
      );

      focusNode.requestFocus();
      await tester.pump();

      tester.testTextInput.log.clear();

      terminal.write('hello');
      await tester.pump();

      final editableCall = tester.testTextInput.log.lastWhere(
        (call) => call.method == 'TextInput.setEditableSizeAndTransform',
      );
      final editableArgs = editableCall.arguments as Map<dynamic, dynamic>;
      final transform =
          List<double>.from(editableArgs['transform'] as List<dynamic>);

      expect(editableArgs['width'], 220.0);
      expect(editableArgs['height'], 100.0);
      expect(transform[12], 120.0);
      expect(transform[13], 90.0);

      final caretCall = tester.testTextInput.log.lastWhere(
        (call) => call.method == 'TextInput.setCaretRect',
      );
      final caretArgs = caretCall.arguments as Map<dynamic, dynamic>;

      expect((caretArgs['x'] as num).toDouble(), greaterThan(0));
      expect((caretArgs['x'] as num).toDouble(), lessThan(120));
      expect((caretArgs['y'] as num).toDouble(), 0.0);
      expect((caretArgs['height'] as num).toDouble(), greaterThan(0));
    },
  );
}
