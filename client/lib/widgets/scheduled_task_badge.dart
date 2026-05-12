import 'package:flutter/material.dart';

import '../models/scheduled_task.dart';

/// 定时任务标签
///
/// 在终端上方展示 pending 状态的定时任务。
/// 显示：时间 + 命令摘要（前 20 字符）+ 取消按钮
///
/// 使用方式：
/// ```dart
/// ScheduledTaskBadge(
///   tasks: poller.tasksForTerminal(terminalId),
///   onCancel: (taskId) => poller.deleteTask(taskId),
/// )
/// ```
class ScheduledTaskBadge extends StatelessWidget {
  final List<ScheduledTask> tasks;
  final void Function(int taskId) onCancel;

  const ScheduledTaskBadge({
    super.key,
    required this.tasks,
    required this.onCancel,
  });

  @override
  Widget build(BuildContext context) {
    if (tasks.isEmpty) return const SizedBox.shrink();

    return Column(
      children: tasks.map((task) => _buildTaskBar(context, task)).toList(),
    );
  }

  Widget _buildTaskBar(BuildContext context, ScheduledTask task) {
    final timeStr = _formatTime(task.executeAt);
    final cmdPreview = task.textContent.length > 20
        ? '${task.textContent.substring(0, 20)}...'
        : task.textContent;

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(
        color: Colors.orange.shade50,
        border: Border(bottom: BorderSide(color: Colors.orange.shade200)),
      ),
      child: Row(
        children: [
          const Icon(Icons.schedule, size: 14, color: Colors.orange),
          const SizedBox(width: 4),
          Text(
            timeStr,
            style: TextStyle(fontSize: 12, color: Colors.orange.shade700),
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              cmdPreview,
              style: TextStyle(fontSize: 12, color: Colors.grey.shade700),
              overflow: TextOverflow.ellipsis,
            ),
          ),
          if (task.repeatType == ScheduledTaskRepeatType.daily)
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
          IconButton(
            key: Key('scheduled-task-cancel-${task.id}'),
            icon: const Icon(Icons.close, size: 14),
            padding: EdgeInsets.zero,
            constraints: const BoxConstraints(minWidth: 24, minHeight: 24),
            onPressed: () => onCancel(task.id),
          ),
        ],
      ),
    );
  }

  String _formatTime(String isoStr) {
    final dt = DateTime.tryParse(isoStr);
    if (dt == null) return isoStr;
    return '${dt.hour.toString().padLeft(2, '0')}:${dt.minute.toString().padLeft(2, '0')}';
  }
}
