import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rc_client/widgets/tui_selector.dart';

void main() {
  group('TuiSelector.parseOptions', () {
    test('检测数字选项（1. xxx, 2. xxx）生成对应按钮', () {
      const output = '''
Select an option:
  1. Option A
  2. Option B
  3. Option C
''';

      final options = TuiSelector.parseOptions(output);

      expect(options.length, 3);
      expect(options[0].key, '1');
      expect(options[0].label, 'Option A');
      expect(options[0].type, TuiOptionType.numbered);

      expect(options[1].key, '2');
      expect(options[1].label, 'Option B');

      expect(options[2].key, '3');
      expect(options[2].label, 'Option C');
    });

    test('检测 [y/n] 选项生成 Yes/No 按钮', () {
      const output = 'Do you want to continue? [y/n]';

      final options = TuiSelector.parseOptions(output);

      expect(options.length, 2);
      expect(options.any((o) => o.key == 'y' && o.type == TuiOptionType.yesNo), true);
      expect(options.any((o) => o.key == 'n' && o.type == TuiOptionType.yesNo), true);
    });

    test('检测 > 提示符生成确认按钮', () {
      const output = 'Press Enter to continue or Ctrl+C to exit';

      final options = TuiSelector.parseOptions(output);

      expect(options.any((o) => o.key == '\r' && o.type == TuiOptionType.confirm), true);
    });

    test('无选项时不返回任何按钮', () {
      const output = '''
This is just some output text.
No options here.
Just regular terminal content.
''';

      final options = TuiSelector.parseOptions(output);

      expect(options, isEmpty);
    });

    test('选项超过 9 个时正确处理', () {
      final buffer = StringBuffer('Select:\n');
      for (var i = 1; i <= 12; i++) {
        buffer.writeln('  $i. Option $i');
      }

      final options = TuiSelector.parseOptions(buffer.toString());

      expect(options.length, 9); // 只匹配单个数字 1-9
      expect(options.last.key, '9');
    });

    test('特殊字符选项（含空格、括号）正确解析', () {
      const output = '''
  1. Option (with parentheses)
  2. Option-with-dash
  3. Option_with_underscore
''';

      final options = TuiSelector.parseOptions(output);

      expect(options.length, 3);
      expect(options[0].label, 'Option (with parentheses)');
      expect(options[1].label, 'Option-with-dash');
      expect(options[2].label, 'Option_with_underscore');
    });

    test('混合选项类型正确解析', () {
      const output = '''
Choose an action:
  1. Create new file
  2. Open existing file
Confirm? [y/n]
Press Enter to start
''';

      final options = TuiSelector.parseOptions(output);

      expect(options.any((o) => o.key == '1' && o.type == TuiOptionType.numbered), true);
      expect(options.any((o) => o.key == '2' && o.type == TuiOptionType.numbered), true);
      expect(options.any((o) => o.key == 'y' && o.type == TuiOptionType.yesNo), true);
      expect(options.any((o) => o.key == 'n' && o.type == TuiOptionType.yesNo), true);
      expect(options.any((o) => o.key == '\r' && o.type == TuiOptionType.confirm), true);
    });

    test('带括号数字选项格式正确解析', () {
      const output = '''
  1) First option
  2) Second option
''';

      final options = TuiSelector.parseOptions(output);

      expect(options.length, 2);
      expect(options[0].key, '1');
      expect(options[0].label, 'First option');
    });

    test('重复选项去重', () {
      const output = '''
[y/n] Do you want to continue?
[y/n] Please confirm:
''';

      final options = TuiSelector.parseOptions(output);

      expect(options.where((o) => o.key == 'y').length, 1);
      expect(options.where((o) => o.key == 'n').length, 1);
    });
  });

  group('TuiSelector Widget', () {
    testWidgets('显示解析出的选项按钮', (tester) async {
      final selectedKeys = <String>[];

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: TuiSelector(
              terminalOutput: '  1. Option A\n  2. Option B',
              onSelect: (key) => selectedKeys.add(key),
            ),
          ),
        ),
      );

      expect(find.text('1'), findsOneWidget);
      expect(find.text('2'), findsOneWidget);
    });

    testWidgets('点击按钮调用 onSelect', (tester) async {
      final selectedKeys = <String>[];

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: TuiSelector(
              terminalOutput: '  1. Option A',
              onSelect: (key) => selectedKeys.add(key),
            ),
          ),
        ),
      );

      await tester.tap(find.text('1'));
      await tester.pump();

      expect(selectedKeys, contains('1'));
    });

    testWidgets('空输出不显示任何内容', (tester) async {
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: TuiSelector(
              terminalOutput: '',
              onSelect: (_) {},
            ),
          ),
        ),
      );

      expect(find.byType(SizedBox), findsOneWidget);
    });

    testWidgets('更新终端输出时刷新选项', (tester) async {
      final selectedKeys = <String>[];

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: TuiSelector(
              terminalOutput: '  1. Option A',
              onSelect: (key) => selectedKeys.add(key),
            ),
          ),
        ),
      );

      expect(find.text('1'), findsOneWidget);
      expect(find.text('2'), findsNothing);

      // 更新输出
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: TuiSelector(
              terminalOutput: '  1. Option A\n  2. Option B',
              onSelect: (key) => selectedKeys.add(key),
            ),
          ),
        ),
      );

      expect(find.text('1'), findsOneWidget);
      expect(find.text('2'), findsOneWidget);
    });

    testWidgets('Yes/No 按钮显示正确图标', (tester) async {
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: TuiSelector(
              terminalOutput: '[y/n] Continue?',
              onSelect: (_) {},
            ),
          ),
        ),
      );

      expect(find.byIcon(Icons.check), findsOneWidget);
      expect(find.byIcon(Icons.close), findsOneWidget);
    });
  });
}
