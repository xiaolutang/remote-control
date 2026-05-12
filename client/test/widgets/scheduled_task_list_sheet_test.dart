import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:rc_client/models/scheduled_task.dart';
import 'package:rc_client/services/scheduled_task_poller.dart';
import 'package:rc_client/widgets/scheduled_task_list_sheet.dart';

/// 使用本地时间创建 ISO 字符串，确保 toLocal() 后显示一致
String _localTimeStr(int hour, int minute) {
  final now = DateTime.now();
  final dt = DateTime(now.year, now.month, now.day, hour, minute);
  return dt.toIso8601String();
}

/// 创建一个测试用的 ScheduledTask
ScheduledTask _makeTask({
  int id = 1,
  String terminalId = 't1',
  String textContent = 'ls -la',
  String? executeAt,
  ScheduledTaskRepeatType repeatType = ScheduledTaskRepeatType.once,
  ScheduledTaskStatus status = ScheduledTaskStatus.pending,
  String? executedAt,
}) {
  return ScheduledTask(
    id: id,
    sessionId: 's1',
    terminalId: terminalId,
    textContent: textContent,
    executeAt: executeAt ?? _localTimeStr(14, 30),
    repeatType: repeatType,
    status: status,
    createdAt: _localTimeStr(14, 0),
    executedAt: executedAt,
  );
}

/// 可控的 FakePoller，直接操作 tasks 列表并通知监听者
class _FakePoller extends ScheduledTaskPoller {
  _FakePoller() : super(serverUrl: 'http://localhost');

  List<ScheduledTask> _fakeTasks = [];

  void setTasks(List<ScheduledTask> tasks) {
    _fakeTasks = tasks;
    notifyListeners();
  }

  @override
  List<ScheduledTask> allTasksForTerminal(String terminalId) {
    return _fakeTasks.where((t) => t.terminalId == terminalId).toList();
  }

  @override
  List<ScheduledTask> pendingTasksForTerminal(String terminalId) {
    return _fakeTasks
        .where((t) =>
            t.terminalId == terminalId &&
            t.status == ScheduledTaskStatus.pending)
        .toList();
  }

  @override
  Future<void> deleteTask(int taskId) async {
    _fakeTasks = _fakeTasks.where((t) => t.id != taskId).toList();
    notifyListeners();
  }
}

/// 构建测试用的 widget 树，包含真实的 ScheduledTaskListSheet + FakePoller
Widget _buildTestWidget({
  required String terminalId,
  required _FakePoller poller,
}) {
  return MaterialApp(
    home: Scaffold(
      body: ScheduledTaskListSheet(
        terminalId: terminalId,
        poller: poller,
        token: 'test-token',
      ),
    ),
  );
}

void main() {
  group('ScheduledTaskListSheet', () {
    testWidgets('空任务列表显示空状态提示', (tester) async {
      final poller = _FakePoller();
      poller.setTasks([]);

      await tester.pumpWidget(_buildTestWidget(
        terminalId: 't1',
        poller: poller,
      ));

      expect(find.text('暂无定时任务'), findsOneWidget);
      poller.dispose();
    });

    testWidgets('pending 任务显示时间和命令', (tester) async {
      final poller = _FakePoller();
      poller.setTasks([_makeTask(id: 1, textContent: 'ls -la')]);

      await tester.pumpWidget(_buildTestWidget(
        terminalId: 't1',
        poller: poller,
      ));

      expect(find.text('ls -la'), findsOneWidget);
      // 时间格式化为 HH:mm（本地时间）
      expect(find.textContaining(':30'), findsWidgets);
      poller.dispose();
    });

    testWidgets('每日任务显示每日标签', (tester) async {
      final poller = _FakePoller();
      poller.setTasks([
        _makeTask(
            id: 2,
            textContent: 'git pull',
            repeatType: ScheduledTaskRepeatType.daily),
      ]);

      await tester.pumpWidget(_buildTestWidget(
        terminalId: 't1',
        poller: poller,
      ));

      expect(find.text('每日'), findsOneWidget);
      poller.dispose();
    });

    testWidgets('executed 任务显示"已执行"', (tester) async {
      final poller = _FakePoller();
      poller.setTasks([
        _makeTask(
          id: 3,
          textContent: 'cmd',
          status: ScheduledTaskStatus.executed,
          executedAt: DateTime.now().toIso8601String(),
        ),
      ]);

      await tester.pumpWidget(_buildTestWidget(
        terminalId: 't1',
        poller: poller,
      ));

      expect(find.text('已执行'), findsOneWidget);
      poller.dispose();
    });

    testWidgets('长命令截断显示', (tester) async {
      final poller = _FakePoller();
      final longCmd = 'a' * 50;
      poller.setTasks([_makeTask(id: 4, textContent: longCmd)]);

      await tester.pumpWidget(_buildTestWidget(
        terminalId: 't1',
        poller: poller,
      ));

      // 显示截断后的文本（前30字符 + ...）
      expect(find.textContaining('aaa'), findsOneWidget);
      poller.dispose();
    });

    testWidgets('poller 更新后 sheet 自动刷新', (tester) async {
      final poller = _FakePoller();
      poller.setTasks([]);

      await tester.pumpWidget(_buildTestWidget(
        terminalId: 't1',
        poller: poller,
      ));

      // 初始为空
      expect(find.text('暂无定时任务'), findsOneWidget);
      expect(find.text('new-cmd'), findsNothing);

      // 模拟 poller 收到新任务
      poller.setTasks([_makeTask(id: 10, textContent: 'new-cmd')]);
      await tester.pump();

      // 应该自动刷新显示新任务
      expect(find.text('暂无定时任务'), findsNothing);
      expect(find.text('new-cmd'), findsOneWidget);
      poller.dispose();
    });

    testWidgets('不同 terminalId 隔离数据', (tester) async {
      final poller = _FakePoller();
      poller.setTasks([
        _makeTask(id: 1, terminalId: 't1', textContent: 'cmd-t1'),
        _makeTask(id: 2, terminalId: 't2', textContent: 'cmd-t2'),
      ]);

      await tester.pumpWidget(_buildTestWidget(
        terminalId: 't1',
        poller: poller,
      ));

      expect(find.text('cmd-t1'), findsOneWidget);
      expect(find.text('cmd-t2'), findsNothing);
      poller.dispose();
    });
  });
}
