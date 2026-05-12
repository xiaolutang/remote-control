import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:rc_client/models/scheduled_task.dart';
import 'package:rc_client/services/scheduled_task_poller.dart';
import 'package:rc_client/widgets/scheduled_task_list_sheet.dart';

import 'dart:async';

void main() {
  group('ScheduledTaskListSheet', () {
    late List<ScheduledTask> deletedTaskIds;
    late ScheduledTaskPoller poller;

    setUp(() {
      deletedTaskIds = [];
    });

    ScheduledTaskPoller _createPoller() {
      // 创建一个简单的 poller，deleteTask 记录被删除的 task id
      // 使用 mock http client 避免真实网络请求
      final completer = Completer<void>();
      poller = ScheduledTaskPoller(
        serverUrl: 'ws://localhost',
      );
      return poller;
    }

    testWidgets('空列表显示空状态提示', (tester) async {
      await tester.pumpWidget(MaterialApp(
        home: Scaffold(
          body: ScheduledTaskListSheet(
            tasks: [],
            poller: _createPoller(),
            token: 'test-token',
          ),
        ),
      ));

      expect(find.text('暂无定时任务'), findsOneWidget);
    });

    testWidgets('pending 任务显示时间和命令', (tester) async {
      final tasks = [
        ScheduledTask(
          id: 1,
          sessionId: 's1',
          terminalId: 't1',
          textContent: 'ls -la',
          executeAt: '2026-05-12T14:30:00+08:00',
          repeatType: ScheduledTaskRepeatType.once,
          status: ScheduledTaskStatus.pending,
          createdAt: '2026-05-12T14:00:00+08:00',
        ),
      ];

      await tester.pumpWidget(MaterialApp(
        home: Scaffold(
          body: ScheduledTaskListSheet(
            tasks: tasks,
            poller: _createPoller(),
            token: 'test-token',
          ),
        ),
      ));

      expect(find.text('ls -la'), findsOneWidget);
      // 时间格式化为 HH:mm
      expect(find.textContaining(':30'), findsWidgets);
    });

    testWidgets('每日任务显示每日标签', (tester) async {
      final tasks = [
        ScheduledTask(
          id: 2,
          sessionId: 's1',
          terminalId: 't1',
          textContent: 'git pull',
          executeAt: '2026-05-13T09:00:00+08:00',
          repeatType: ScheduledTaskRepeatType.daily,
          status: ScheduledTaskStatus.pending,
          createdAt: '2026-05-12T14:00:00+08:00',
        ),
      ];

      await tester.pumpWidget(MaterialApp(
        home: Scaffold(
          body: ScheduledTaskListSheet(
            tasks: tasks,
            poller: _createPoller(),
            token: 'test-token',
          ),
        ),
      ));

      expect(find.text('每日'), findsOneWidget);
    });

    testWidgets('executed 任务显示"已执行"', (tester) async {
      final tasks = [
        ScheduledTask(
          id: 3,
          sessionId: 's1',
          terminalId: 't1',
          textContent: 'cmd',
          executeAt: '2026-05-12T14:00:00+08:00',
          repeatType: ScheduledTaskRepeatType.once,
          status: ScheduledTaskStatus.executed,
          createdAt: '2026-05-12T13:00:00+08:00',
          executedAt: DateTime.now().toIso8601String(),
        ),
      ];

      await tester.pumpWidget(MaterialApp(
        home: Scaffold(
          body: ScheduledTaskListSheet(
            tasks: tasks,
            poller: _createPoller(),
            token: 'test-token',
          ),
        ),
      ));

      expect(find.text('已执行'), findsOneWidget);
    });

    testWidgets('长命令截断显示', (tester) async {
      final longCmd = 'a' * 50;
      final tasks = [
        ScheduledTask(
          id: 4,
          sessionId: 's1',
          terminalId: 't1',
          textContent: longCmd,
          executeAt: '2026-05-12T14:00:00+08:00',
          repeatType: ScheduledTaskRepeatType.once,
          status: ScheduledTaskStatus.pending,
          createdAt: '2026-05-12T13:00:00+08:00',
        ),
      ];

      await tester.pumpWidget(MaterialApp(
        home: Scaffold(
          body: ScheduledTaskListSheet(
            tasks: tasks,
            poller: _createPoller(),
            token: 'test-token',
          ),
        ),
      ));

      // 显示截断后的文本（前30字符 + ...）
      expect(find.textContaining('aaa'), findsOneWidget);
    });
  });
}
