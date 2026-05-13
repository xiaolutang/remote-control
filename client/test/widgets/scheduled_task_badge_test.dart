import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rc_client/models/scheduled_task.dart';
import 'package:rc_client/widgets/scheduled_task_badge.dart';

/// 使用本地时间创建 ISO 字符串，确保 toLocal() 后显示一致
String _localTimeStr(int hour, int minute) {
  final now = DateTime.now();
  final dt = DateTime(now.year, now.month, now.day, hour, minute);
  return dt.toIso8601String();
}

ScheduledTask _makeTask({
  int id = 1,
  String terminalId = 'term-1',
  String textContent = 'ls -la',
  String? executeAt,
  ScheduledTaskRepeatType repeatType = ScheduledTaskRepeatType.once,
  ScheduledTaskStatus status = ScheduledTaskStatus.pending,
}) {
  return ScheduledTask(
    id: id,
    sessionId: 'sess-1',
    terminalId: terminalId,
    textContent: textContent,
    executeAt: executeAt ?? _localTimeStr(8, 30),
    repeatType: repeatType,
    status: status,
    createdAt: '2026-05-12T10:00:00Z',
  );
}

Widget buildSubject({
  List<ScheduledTask> tasks = const [],
  void Function(int taskId)? onCancel,
}) {
  return MaterialApp(
    home: Scaffold(
      body: ScheduledTaskBadge(
        tasks: tasks,
        onCancel: onCancel ?? (_) {},
      ),
    ),
  );
}

void main() {
  group('ScheduledTaskBadge', () {
    testWidgets('空任务列表 → 不渲染', (tester) async {
      await tester.pumpWidget(buildSubject(tasks: []));

      expect(find.byType(ScheduledTaskBadge), findsOneWidget);
      // 应该是 SizedBox.shrink
      expect(find.byType(SizedBox), findsOneWidget);
    });

    testWidgets('pending 任务 → 显示时间 + 命令摘要 + 取消按钮',
        (tester) async {
      final task = _makeTask();
      await tester.pumpWidget(buildSubject(tasks: [task]));

      // 显示本地时间 08:30
      expect(find.text('08:30'), findsOneWidget);
      // 显示命令摘要
      expect(find.text('ls -la'), findsOneWidget);
      // 显示取消按钮
      expect(
          find.byKey(const Key('scheduled-task-cancel-1')), findsOneWidget);
    });

    testWidgets('长命令 → 截断显示', (tester) async {
      final longCmd = 'a' * 30;
      final task = _makeTask(textContent: longCmd);
      await tester.pumpWidget(buildSubject(tasks: [task]));

      // 应该显示截断后的文本
      expect(find.text('${longCmd.substring(0, 20)}...'), findsOneWidget);
      // 不应显示完整文本
      expect(find.text(longCmd), findsNothing);
    });

    testWidgets('每日任务 → 显示"每日"标签', (tester) async {
      final task = _makeTask(repeatType: ScheduledTaskRepeatType.daily);
      await tester.pumpWidget(buildSubject(tasks: [task]));

      expect(find.text('每日'), findsOneWidget);
    });

    testWidgets('once 任务不显示"每日"标签', (tester) async {
      final task = _makeTask(repeatType: ScheduledTaskRepeatType.once);
      await tester.pumpWidget(buildSubject(tasks: [task]));

      expect(find.text('每日'), findsNothing);
    });

    testWidgets('点击取消按钮 → 调用 onCancel', (tester) async {
      int? cancelledTaskId;
      final task = _makeTask(id: 42);
      await tester.pumpWidget(buildSubject(
        tasks: [task],
        onCancel: (taskId) => cancelledTaskId = taskId,
      ));

      await tester.tap(find.byKey(const Key('scheduled-task-cancel-42')));
      await tester.pump();

      expect(cancelledTaskId, 42);
    });

    testWidgets('多个任务 → 只显示最近一条 + 余数提示', (tester) async {
      final tasks = [
        _makeTask(id: 1, textContent: 'cmd1', executeAt: _localTimeStr(8, 0)),
        _makeTask(id: 2, textContent: 'cmd2', executeAt: _localTimeStr(9, 0)),
      ];
      await tester.pumpWidget(buildSubject(tasks: tasks));

      // 只显示最近一条（08:00 更早，排在前面）
      expect(find.text('08:00'), findsOneWidget);
      expect(find.text('cmd1'), findsOneWidget);
      // 不显示第二条任务的时间
      expect(find.text('09:00'), findsNothing);
      expect(find.text('cmd2'), findsNothing);
      // 显示余数提示
      expect(find.text('还有 1 个定时任务'), findsOneWidget);
    });

    testWidgets('无效时间字符串 → 原样显示', (tester) async {
      final task = _makeTask(executeAt: 'invalid-time');
      await tester.pumpWidget(buildSubject(tasks: [task]));

      expect(find.text('invalid-time'), findsOneWidget);
    });
  });
}
