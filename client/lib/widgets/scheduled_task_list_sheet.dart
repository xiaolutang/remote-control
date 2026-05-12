import 'package:flutter/material.dart';

import '../models/scheduled_task.dart';
import '../services/scheduled_task_poller.dart';

/// 定时任务列表管理 BottomSheet。
///
/// 展示当前终端的定时任务列表，支持取消 pending 任务和删除已结束任务。
/// 客户端过滤：executed/expired 超过 24 小时的任务不展示。
class ScheduledTaskListSheet extends StatelessWidget {
  final List<ScheduledTask> tasks;
  final ScheduledTaskPoller poller;
  final String token;

  const ScheduledTaskListSheet({
    super.key,
    required this.tasks,
    required this.poller,
    required this.token,
  });

  /// 显示定时任务列表
  static Future<void> show({
    required BuildContext context,
    required List<ScheduledTask> tasks,
    required ScheduledTaskPoller poller,
    required String token,
  }) {
    return showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      isScrollControlled: true,
      builder: (_) => ScheduledTaskListSheet(
        tasks: tasks,
        poller: poller,
        token: token,
      ),
    );
  }

  /// 过滤掉 executed/expired 超过 24 小时的任务
  List<ScheduledTask> get _visibleTasks {
    final now = DateTime.now();
    return tasks.where((t) {
      if (t.status == ScheduledTaskStatus.pending) return true;
      // executed/expired 任务检查是否在 24 小时内
      final endTime = t.executedAt != null && t.executedAt!.isNotEmpty
          ? DateTime.tryParse(t.executedAt!)
          : null;
      if (endTime == null) return true; // 无时间戳则保留
      return now.difference(endTime).inHours < 24;
    }).toList();
  }

  @override
  Widget build(BuildContext context) {
    final visibleTasks = _visibleTasks;
    final theme = Theme.of(context);

    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              '定时任务',
              style: theme.textTheme.titleMedium?.copyWith(
                fontWeight: FontWeight.w700,
              ),
            ),
            const SizedBox(height: 8),
            if (visibleTasks.isEmpty)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 24),
                child: Center(
                  child: Text(
                    '暂无定时任务',
                    style: TextStyle(color: theme.disabledColor),
                  ),
                ),
              )
            else
              ...visibleTasks.map((task) => _buildTaskItem(context, task)),
          ],
        ),
      ),
    );
  }

  Widget _buildTaskItem(BuildContext context, ScheduledTask task) {
    final theme = Theme.of(context);
    final isPending = task.status == ScheduledTaskStatus.pending;
    final timeStr = _formatTime(task.executeAt);
    final cmdPreview = task.textContent.length > 30
        ? '${task.textContent.substring(0, 30)}...'
        : task.textContent;

    return ListTile(
      contentPadding: EdgeInsets.zero,
      leading: Icon(
        isPending ? Icons.schedule : Icons.check_circle_outline,
        color: isPending ? Colors.orange : theme.disabledColor,
        size: 20,
      ),
      title: Text(
        cmdPreview,
        style: TextStyle(
          color: isPending ? null : theme.disabledColor,
          decoration: isPending ? null : TextDecoration.lineThrough,
        ),
        maxLines: 1,
        overflow: TextOverflow.ellipsis,
      ),
      subtitle: Row(
        children: [
          Text(
            timeStr,
            style: TextStyle(
              fontSize: 12,
              color: isPending ? Colors.orange : theme.disabledColor,
            ),
          ),
          if (task.repeatType == ScheduledTaskRepeatType.daily) ...[
            const SizedBox(width: 4),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 1),
              decoration: BoxDecoration(
                color: Colors.orange.shade100,
                borderRadius: BorderRadius.circular(4),
              ),
              child: const Text(
                '每日',
                style: TextStyle(fontSize: 10, color: Colors.orange),
              ),
            ),
          ],
          if (!isPending) ...[
            const SizedBox(width: 4),
            Text(
              task.status == ScheduledTaskStatus.executed ? '已执行' : '已过期',
              style: TextStyle(fontSize: 10, color: theme.disabledColor),
            ),
          ],
        ],
      ),
      trailing: IconButton(
        icon: Icon(
          isPending ? Icons.cancel_outlined : Icons.delete_outline,
          size: 18,
          color: theme.disabledColor,
        ),
        onPressed: () => poller.deleteTask(task.id),
      ),
    );
  }

  String _formatTime(String isoStr) {
    final dt = DateTime.tryParse(isoStr);
    if (dt == null) return isoStr;
    return '${dt.hour.toString().padLeft(2, '0')}:${dt.minute.toString().padLeft(2, '0')}';
  }
}
