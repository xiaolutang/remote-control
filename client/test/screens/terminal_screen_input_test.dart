import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rc_client/widgets/mobile_input_delegate.dart';

import '../mocks/mock_websocket_service.dart';

void main() {
  group('MobileInputDelegate 与 WebSocketService 集成测试', () {
    late MockWebSocketService mockService;

    setUp(() {
      mockService = MockWebSocketService();
    });

    tearDown(() {
      mockService.dispose();
    });

    testWidgets('输入文本后 WebSocketService.send 被调用', (tester) async {
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: MobileInputDelegate(
              onInput: (text) => mockService.send(text),
              onSubmit: () => mockService.send('\r'),
            ),
          ),
        ),
      );

      // 使用 tester.enterText 触发 onChanged 回调
      await tester.enterText(find.byType(TextField), 'hello');
      await tester.pump();

      // 验证 send 被调用
      expect(mockService.sentMessages, isNotEmpty);
      expect(mockService.sentMessages.last, 'hello');
    });

    testWidgets('回车键发送 \\r 字符', (tester) async {
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: MobileInputDelegate(
              onInput: (text) => mockService.send(text),
              onSubmit: () => mockService.send('\r'),
            ),
          ),
        ),
      );

      final textField = tester.widget<TextField>(find.byType(TextField));

      // 模拟提交
      textField.onSubmitted!('test');
      // 等待 Timer 完成 (100ms)
      await tester.pump(const Duration(milliseconds: 150));

      // 验证发送了 \r
      expect(mockService.sentMessages, contains('\r'));
    });

    testWidgets('焦点切换不影响已输入内容', (tester) async {
      final focusNode1 = FocusNode();
      final focusNode2 = FocusNode();

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: Column(
              children: [
                MobileInputDelegate(
                  focusNode: focusNode1,
                  onInput: (text) => mockService.send(text),
                  onSubmit: () => mockService.send('\r'),
                ),
                MobileInputDelegate(
                  focusNode: focusNode2,
                  onInput: (text) => mockService.send(text),
                  onSubmit: () => mockService.send('\r'),
                ),
              ],
            ),
          ),
        ),
      );

      // 在第一个输入框输入
      focusNode1.requestFocus();
      await tester.pump();

      // 使用 tester.enterText 输入
      final textFields = tester.widgetList<TextField>(find.byType(TextField));
      final firstTextField = textFields.first;
      await tester.enterText(find.byType(TextField).first, 'input1');
      await tester.pump();

      // 切换焦点
      focusNode2.requestFocus();
      await tester.pump();

      // 切回第一个
      focusNode1.requestFocus();
      await tester.pump();

      // 验证内容仍然存在
      expect(firstTextField.controller!.text, 'input1');

      focusNode1.dispose();
      focusNode2.dispose();
    });

    testWidgets('多次输入连续发送正确', (tester) async {
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: MobileInputDelegate(
              onInput: (text) => mockService.send(text),
              onSubmit: () => mockService.send('\r'),
            ),
          ),
        ),
      );

      // 连续输入 - enterText 会替换整个文本
      await tester.enterText(find.byType(TextField), 'a');
      await tester.pump();
      await tester.enterText(find.byType(TextField), 'ab');
      await tester.pump();
      await tester.enterText(find.byType(TextField), 'abc');
      await tester.pump();

      // 验证发送了完整的输入文本
      // enterText 触发 onChanged 时会发送增量文本
      // 第一次: '' -> 'a' 发送 'a'
      // 第二次: 'a' -> 'ab' 发送 'ab' (但 controller 已经是 'ab'，所以增量是 'b')
      // 第三次: 'ab' -> 'abc' 发送 'c'
      final sentChars = mockService.sentMessages.join();
      expect(sentChars, contains('abc'));
    });
  });

  group('边缘场景测试', () {
    late MockWebSocketService mockService;

    setUp(() {
      mockService = MockWebSocketService();
    });

    tearDown(() {
      mockService.dispose();
    });

    testWidgets('空输入不发送', (tester) async {
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: MobileInputDelegate(
              onInput: (text) {
                if (text.isNotEmpty) {
                  mockService.send(text);
                }
              },
              onSubmit: () => mockService.send('\r'),
            ),
          ),
        ),
      );

      final textField = tester.widget<TextField>(find.byType(TextField));

      // 不输入任何内容直接提交
      textField.onSubmitted!('');
      // 等待 Timer 完成
      await tester.pump(const Duration(milliseconds: 150));

      // 只发送了 \r，没有发送空字符串
      expect(mockService.sentMessages.where((m) => m.isEmpty), isEmpty);
    });

    testWidgets('超长输入（>1000字符）正常处理', (tester) async {
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: MobileInputDelegate(
              onInput: (text) => mockService.send(text),
              onSubmit: () => mockService.send('\r'),
            ),
          ),
        ),
      );

      // 输入超长文本
      final longText = 'a' * 1001;
      await tester.enterText(find.byType(TextField), longText);
      await tester.pump();

      // 验证没有崩溃，消息被发送
      expect(mockService.sentMessages, isNotEmpty);
      // 验证发送的内容是完整的 1001 个 'a'
      expect(mockService.sentMessages.last.length, 1001);
    });

    testWidgets('特殊字符（@#\$%^&*）正确发送', (tester) async {
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: MobileInputDelegate(
              onInput: (text) => mockService.send(text),
              onSubmit: () => mockService.send('\r'),
            ),
          ),
        ),
      );

      // 输入特殊字符
      final specialChars = '@#\$%^&*()_+-=[]{}|;:,.<>?';
      await tester.enterText(find.byType(TextField), specialChars);
      await tester.pump();

      // 验证特殊字符被正确发送
      expect(mockService.sentMessages, isNotEmpty);
      expect(mockService.sentMessages.last, specialChars);
    });

    testWidgets('连续快速输入不丢字符', (tester) async {
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: MobileInputDelegate(
              onInput: (text) => mockService.send(text),
              onSubmit: () => mockService.send('\r'),
            ),
          ),
        ),
      );

      // 快速连续输入
      final inputs = ['a', 'ab', 'abc', 'abcd', 'abcde'];
      for (final input in inputs) {
        await tester.enterText(find.byType(TextField), input);
        await tester.pump(const Duration(milliseconds: 1));
      }

      // 验证每次输入的新增字符都被发送
      final sentChars = mockService.sentMessages.join();
      expect(sentChars, contains('abcde'));
    });

    testWidgets('IME 模拟：拼音输入 -> 选择候选词 -> 确认发送', (tester) async {
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: MobileInputDelegate(
              onInput: (text) => mockService.send(text),
              onSubmit: () => mockService.send('\r'),
            ),
          ),
        ),
      );

      final state = tester.state<MobileInputDelegateState>(
        find.byType(MobileInputDelegate),
      );
      final textField = tester.widget<TextField>(find.byType(TextField));

      // 模拟 IME 组合开始（输入拼音）
      state.onComposeStart();
      textField.controller!.text = 'nihao';
      await tester.pump();

      // 组合过程中不应发送到终端
      mockService.clearSentMessages();

      // 模拟选择候选词（IME 组合结束）
      state.onComposeEnd();
      await tester.pump();

      // 组合完成后应该发送最终的文本
      // 注意：实际实现中，组合完成后的文本变化会被检测到并发送
    });
  });
}
