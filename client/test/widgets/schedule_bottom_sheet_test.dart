import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:rc_client/models/scheduled_task.dart';
import 'package:rc_client/widgets/mobile_input_delegate.dart';
import 'package:rc_client/widgets/schedule_bottom_sheet.dart';

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

  group('ScheduleBottomSheet', () {
    testWidgets('无初始文本时显示输入框', (tester) async {
      await tester.pumpWidget(MaterialApp(
        home: Scaffold(
          body: Builder(
            builder: (context) => ElevatedButton(
              onPressed: () => showScheduleBottomSheet(
                context: context,
                token: 'tok',
                sessionId: 's1',
                terminalId: 't1',
                serverUrl: 'http://localhost',
              ),
              child: const Text('open'),
            ),
          ),
        ),
      ));

      await tester.tap(find.text('open'));
      await tester.pumpAndSettle();

      // 应该显示文本输入框和 hintText
      expect(find.byType(TextField), findsOneWidget);
      expect(find.text('输入要定时发送的命令...'), findsOneWidget);
    });

    testWidgets('有初始文本时不显示输入框', (tester) async {
      await tester.pumpWidget(MaterialApp(
        home: Scaffold(
          body: Builder(
            builder: (context) => ElevatedButton(
              onPressed: () => showScheduleBottomSheet(
                context: context,
                token: 'tok',
                sessionId: 's1',
                terminalId: 't1',
                textContent: 'ls -la',
                serverUrl: 'http://localhost',
              ),
              child: const Text('open'),
            ),
          ),
        ),
      ));

      await tester.tap(find.text('open'));
      await tester.pumpAndSettle();

      // 有初始文本时不显示输入框
      expect(find.byType(TextField), findsNothing);
    });

    testWidgets('显示所有时间选项', (tester) async {
      await tester.pumpWidget(MaterialApp(
        home: Scaffold(
          body: Builder(
            builder: (context) => ElevatedButton(
              onPressed: () => showScheduleBottomSheet(
                context: context,
                token: 'tok',
                sessionId: 's1',
                terminalId: 't1',
                textContent: 'cmd',
                serverUrl: 'http://localhost',
              ),
              child: const Text('open'),
            ),
          ),
        ),
      ));

      await tester.tap(find.text('open'));
      await tester.pumpAndSettle();

      expect(find.text('5 分钟后'), findsOneWidget);
      expect(find.text('30 分钟后'), findsOneWidget);
      expect(find.text('1 小时后'), findsOneWidget);
      expect(find.text('自定义时间'), findsOneWidget);
      expect(find.text('每日重复'), findsOneWidget);
    });

    testWidgets('无文本时时间选项禁用，有文本后启用', (tester) async {
      await tester.pumpWidget(MaterialApp(
        home: Scaffold(
          body: Builder(
            builder: (context) => ElevatedButton(
              onPressed: () => showScheduleBottomSheet(
                context: context,
                token: 'tok',
                sessionId: 's1',
                terminalId: 't1',
                serverUrl: 'http://localhost',
              ),
              child: const Text('open'),
            ),
          ),
        ),
      ));

      await tester.tap(find.text('open'));
      await tester.pumpAndSettle();

      // 无文本时 ListTile 应禁用
      final disabledTiles = tester.widgetList<ListTile>(
        find.byType(ListTile),
      );
      for (final tile in disabledTiles) {
        expect(tile.enabled, isFalse);
      }

      // 输入文本
      await tester.enterText(find.byType(TextField), 'ls');
      await tester.pump();

      // 有文本后 ListTile 应启用
      final enabledTiles = tester.widgetList<ListTile>(
        find.byType(ListTile),
      );
      for (final tile in enabledTiles) {
        expect(tile.enabled, isTrue);
      }
    });

    testWidgets('有初始文本时选项直接启用', (tester) async {
      await tester.pumpWidget(MaterialApp(
        home: Scaffold(
          body: Builder(
            builder: (context) => ElevatedButton(
              onPressed: () => showScheduleBottomSheet(
                context: context,
                token: 'tok',
                sessionId: 's1',
                terminalId: 't1',
                textContent: 'echo hello',
                serverUrl: 'http://localhost',
              ),
              child: const Text('open'),
            ),
          ),
        ),
      ));

      await tester.tap(find.text('open'));
      await tester.pumpAndSettle();

      // 有初始文本时选项应直接启用
      final tiles = tester.widgetList<ListTile>(
        find.byType(ListTile),
      );
      for (final tile in tiles) {
        expect(tile.enabled, isTrue);
      }
    });
  });
}
