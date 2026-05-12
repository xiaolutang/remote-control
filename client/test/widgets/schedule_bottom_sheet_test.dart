import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:rc_client/widgets/mobile_input_delegate.dart';

void main() {
  group('MobileInputDelegate', () {
    testWidgets('发送按钮短按触发 onSubmit', (tester) async {
      var submitted = false;
      await tester.pumpWidget(MaterialApp(
        home: Scaffold(
          body: MobileInputDelegate(
            onInput: (_) {},
            onSubmit: () => submitted = true,
          ),
        ),
      ));

      await tester.tap(find.byIcon(Icons.send));
      await tester.pumpAndSettle();
      expect(submitted, isTrue);
    });

    testWidgets('长按发送按钮触发 onScheduleSend', (tester) async {
      var scheduleCalled = false;
      await tester.pumpWidget(MaterialApp(
        home: Scaffold(
          body: MobileInputDelegate(
            onInput: (_) {},
            onSubmit: () {},
            onScheduleSend: (text) async {
              scheduleCalled = true;
              return true;
            },
          ),
        ),
      ));

      await tester.enterText(find.byType(TextField), 'ls -la');
      await tester.longPress(find.byIcon(Icons.send));
      await tester.pumpAndSettle();

      expect(scheduleCalled, isTrue);
    });

    testWidgets('无 onScheduleSend 时长按不报错', (tester) async {
      await tester.pumpWidget(MaterialApp(
        home: Scaffold(
          body: MobileInputDelegate(
            onInput: (_) {},
            onSubmit: () {},
          ),
        ),
      ));

      await tester.longPress(find.byIcon(Icons.send));
      await tester.pumpAndSettle();
    });

    testWidgets('onScheduleSend 传入当前输入框文本', (tester) async {
      String? receivedText;
      await tester.pumpWidget(MaterialApp(
        home: Scaffold(
          body: MobileInputDelegate(
            onInput: (_) {},
            onSubmit: () {},
            onScheduleSend: (text) async {
              receivedText = text;
              return true;
            },
          ),
        ),
      ));

      await tester.enterText(find.byType(TextField), 'git pull');
      await tester.longPress(find.byIcon(Icons.send));
      await tester.pumpAndSettle();

      expect(receivedText, 'git pull');
    });
  });
}
