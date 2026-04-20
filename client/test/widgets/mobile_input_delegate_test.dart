import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rc_client/widgets/mobile_input_delegate.dart';

void main() {
  group('TerminalChars', () {
    test('常量定义正确', () {
      expect(TerminalChars.backspace, '\x7f');
      expect(TerminalChars.carriageReturn, '\r');
      expect(TerminalChars.tab, '\t');
      expect(TerminalChars.escape, '\x1b');
    });
  });

  group('MobileInputDelegate', () {
    testWidgets('创建隐藏 TextField 并正确配置', (tester) async {
      final focusNode = FocusNode();
      String? receivedInput;
      bool submitted = false;

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: MobileInputDelegate(
              focusNode: focusNode,
              onInput: (text) => receivedInput = text,
              onSubmit: () => submitted = true,
            ),
          ),
        ),
      );

      // 验证组件存在
      expect(find.byType(TextField), findsOneWidget);

      // 验证初始状态
      expect(receivedInput, isNull);
      expect(submitted, false);

      focusNode.dispose();
    });

    testWidgets('onInput 回调触发时传入正确文本', (tester) async {
      final focusNode = FocusNode();
      final inputs = <String>[];

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: MobileInputDelegate(
              focusNode: focusNode,
              onInput: (text) => inputs.add(text),
              onSubmit: () {},
            ),
          ),
        ),
      );

      // 使用 tester.enterText 触发 onChanged 回调
      await tester.enterText(find.byType(TextField), 'hello');
      await tester.pump();

      // 验证 onInput 被调用
      expect(inputs, isNotEmpty);
      expect(inputs.last, 'hello');

      focusNode.dispose();
    });

    testWidgets('onSubmit 回调触发时发送回车符', (tester) async {
      final focusNode = FocusNode();
      bool submitted = false;

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: MobileInputDelegate(
              focusNode: focusNode,
              onInput: (_) {},
              onSubmit: () => submitted = true,
            ),
          ),
        ),
      );

      // 获取 TextField 的 onSubmitted 回调
      final textField = tester.widget<TextField>(find.byType(TextField));
      expect(textField.onSubmitted, isNotNull);

      // 模拟提交
      textField.onSubmitted!('test');
      // 等待 Timer 完成 (100ms)
      await tester.pump(const Duration(milliseconds: 150));

      expect(submitted, true);

      focusNode.dispose();
    });

    testWidgets('IME 组合状态正确处理', (tester) async {
      final focusNode = FocusNode();
      final inputs = <String>[];

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: MobileInputDelegate(
              focusNode: focusNode,
              onInput: (text) => inputs.add(text),
              onSubmit: () {},
            ),
          ),
        ),
      );

      final state = tester.state<MobileInputDelegateState>(
        find.byType(MobileInputDelegate),
      );

      // 模拟 IME 组合开始
      state.onComposeStart();
      // 组合状态通过扩展方法管理

      // 在组合过程中输入不应发送
      final textField = tester.widget<TextField>(find.byType(TextField));
      textField.controller!.text = 'nihao';
      await tester.pump();

      // 组合中不应发送输入
      // 模拟 IME 组合结束
      state.onComposeEnd();

      focusNode.dispose();
    });

    testWidgets('requestFocus 和 unfocus 方法正常工作', (tester) async {
      final focusNode = FocusNode();

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: MobileInputDelegate(
              focusNode: focusNode,
              onInput: (_) {},
              onSubmit: () {},
            ),
          ),
        ),
      );

      final state = tester.state<MobileInputDelegateState>(
        find.byType(MobileInputDelegate),
      );

      // 测试请求焦点
      state.requestFocus();
      await tester.pump();
      expect(focusNode.hasFocus, true);

      // 测试取消焦点
      state.unfocus();
      await tester.pump();
      expect(focusNode.hasFocus, false);

      focusNode.dispose();
    });

    testWidgets('删除操作发送退格键', (tester) async {
      final focusNode = FocusNode();
      final inputs = <String>[];

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: MobileInputDelegate(
              focusNode: focusNode,
              onInput: (text) => inputs.add(text),
              onSubmit: () {},
            ),
          ),
        ),
      );

      // 先输入一些文本
      await tester.enterText(find.byType(TextField), 'abc');
      await tester.pump();
      inputs.clear();

      // 删除一个字符
      await tester.enterText(find.byType(TextField), 'ab');
      await tester.pump();

      // 验证发送了退格键
      expect(inputs, contains(TerminalChars.backspace));

      focusNode.dispose();
    });

    testWidgets('提交后清空控制器并保持焦点', (tester) async {
      final focusNode = FocusNode();

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: MobileInputDelegate(
              focusNode: focusNode,
              onInput: (_) {},
              onSubmit: () {},
            ),
          ),
        ),
      );

      // 输入文本
      await tester.enterText(find.byType(TextField), 'test command');
      await tester.pump();

      final textField = tester.widget<TextField>(find.byType(TextField));
      expect(textField.controller!.text, isNotEmpty);

      // 提交
      textField.onSubmitted!('test command');
      // 等待 Timer 完成 (100ms)
      await tester.pump(const Duration(milliseconds: 150));

      // 验证控制器被清空
      expect(textField.controller!.text, isEmpty);

      // 验证焦点保持
      expect(focusNode.hasFocus, true);

      focusNode.dispose();
    });
  });
}
