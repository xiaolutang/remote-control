import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

import '../models/scheduled_task.dart';
import '../services/scheduled_task_service.dart';

/// 定时发送选项菜单。
///
/// 长按发送按钮后弹出，提供快捷时间和自定义时间选项。
/// 选择后通过 ScheduledTaskService.create() 创建任务。
Future<bool> showScheduleBottomSheet({
  required BuildContext context,
  required String token,
  required String sessionId,
  required String terminalId,
  required String textContent,
  required String serverUrl,
  http.Client? client,
}) async {
  final service = ScheduledTaskService(
    serverUrl: serverUrl,
    client: client,
  );

  final result = await showModalBottomSheet<_ScheduleResult>(
    context: context,
    showDragHandle: true,
    builder: (ctx) {
      return SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              ListTile(
                leading: const Icon(Icons.timer),
                title: const Text('5 分钟后'),
                onTap: () => Navigator.pop(
                  ctx,
                  _ScheduleResult(
                    executeAt: DateTime.now().add(const Duration(minutes: 5)),
                    repeatType: ScheduledTaskRepeatType.once,
                  ),
                ),
              ),
              ListTile(
                leading: const Icon(Icons.timer),
                title: const Text('30 分钟后'),
                onTap: () => Navigator.pop(
                  ctx,
                  _ScheduleResult(
                    executeAt: DateTime.now().add(const Duration(minutes: 30)),
                    repeatType: ScheduledTaskRepeatType.once,
                  ),
                ),
              ),
              ListTile(
                leading: const Icon(Icons.timer),
                title: const Text('1 小时后'),
                onTap: () => Navigator.pop(
                  ctx,
                  _ScheduleResult(
                    executeAt: DateTime.now().add(const Duration(hours: 1)),
                    repeatType: ScheduledTaskRepeatType.once,
                  ),
                ),
              ),
              ListTile(
                leading: const Icon(Icons.access_time),
                title: const Text('自定义时间'),
                onTap: () async {
                  final picked = await showTimePicker(
                    context: ctx,
                    initialTime: TimeOfDay.now(),
                  );
                  if (picked == null || !ctx.mounted) return;
                  final now = DateTime.now();
                  var executeAt = DateTime(
                    now.year, now.month, now.day,
                    picked.hour, picked.minute,
                  );
                  if (executeAt.isBefore(now)) {
                    executeAt = executeAt.add(const Duration(days: 1));
                  }
                  Navigator.pop(
                    ctx,
                    _ScheduleResult(
                      executeAt: executeAt,
                      repeatType: ScheduledTaskRepeatType.once,
                    ),
                  );
                },
              ),
              ListTile(
                leading: const Icon(Icons.repeat),
                title: const Text('每日重复'),
                onTap: () async {
                  final picked = await showTimePicker(
                    context: ctx,
                    initialTime: TimeOfDay.now(),
                  );
                  if (picked == null || !ctx.mounted) return;
                  final now = DateTime.now();
                  var executeAt = DateTime(
                    now.year, now.month, now.day,
                    picked.hour, picked.minute,
                  );
                  if (executeAt.isBefore(now)) {
                    executeAt = executeAt.add(const Duration(days: 1));
                  }
                  Navigator.pop(
                    ctx,
                    _ScheduleResult(
                      executeAt: executeAt,
                      repeatType: ScheduledTaskRepeatType.daily,
                    ),
                  );
                },
              ),
            ],
          ),
        ),
      );
    },
  );

  if (result == null) return false;

  try {
    await service.create(
      token: token,
      sessionId: sessionId,
      terminalId: terminalId,
      textContent: textContent,
      executeAt: result.executeAt.toUtc().toIso8601String(),
      repeatType: result.repeatType,
    );
    if (context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('定时任务已创建'),
          duration: Duration(seconds: 2),
        ),
      );
    }
    return true;
  } on ScheduledTaskException catch (e) {
    if (context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(e.message),
          duration: const Duration(seconds: 3),
        ),
      );
    }
    return false;
  }
}

class _ScheduleResult {
  final DateTime executeAt;
  final ScheduledTaskRepeatType repeatType;

  _ScheduleResult({required this.executeAt, required this.repeatType});
}
