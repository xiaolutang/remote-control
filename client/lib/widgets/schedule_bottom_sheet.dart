import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

import '../models/scheduled_task.dart';
import '../services/scheduled_task_service.dart';

/// 定时发送选项菜单。
///
/// 弹出带文本输入框的定时选项，提供快捷时间和自定义时间选项。
/// 选择后通过 ScheduledTaskService.create() 创建任务。
///
/// [textContent] 可选：如果提供则直接使用，否则显示输入框让用户填写。
Future<bool> showScheduleBottomSheet({
  required BuildContext context,
  required String token,
  required String sessionId,
  required String terminalId,
  String? textContent,
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
    isScrollControlled: true,
    builder: (ctx) {
      return _ScheduleBottomSheetContent(
        initialText: textContent,
        onSelect: (r) => Navigator.pop(ctx, r),
      );
    },
  );

  if (result == null) return false;

  try {
    await service.create(
      token: token,
      sessionId: sessionId,
      terminalId: terminalId,
      textContent: result.textContent,
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

class _ScheduleBottomSheetContent extends StatefulWidget {
  final String? initialText;
  final ValueChanged<_ScheduleResult> onSelect;

  const _ScheduleBottomSheetContent({
    this.initialText,
    required this.onSelect,
  });

  @override
  State<_ScheduleBottomSheetContent> createState() =>
      _ScheduleBottomSheetContentState();
}

class _ScheduleBottomSheetContentState
    extends State<_ScheduleBottomSheetContent> {
  late final TextEditingController _textController;
  bool _hasText = false;

  @override
  void initState() {
    super.initState();
    _textController = TextEditingController(text: widget.initialText ?? '');
    _hasText = _textController.text.isNotEmpty;
    _textController.addListener(() {
      final hasText = _textController.text.isNotEmpty;
      if (hasText != _hasText) setState(() => _hasText = hasText);
    });
  }

  @override
  void dispose() {
    _textController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      child: Padding(
        padding: EdgeInsets.fromLTRB(
            16, 0, 16, 16 + MediaQuery.of(context).viewInsets.bottom),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (widget.initialText == null) ...[
              TextField(
                controller: _textController,
                autofocus: true,
                maxLines: 2,
                minLines: 1,
                decoration: const InputDecoration(
                  hintText: '输入要定时发送的命令...',
                  border: OutlineInputBorder(),
                ),
              ),
              const SizedBox(height: 12),
            ],
            ListTile(
                leading: const Icon(Icons.timer),
                title: const Text('5 分钟后'),
                enabled: _hasText,
                onTap: () => widget.onSelect(_ScheduleResult(
                  textContent: _textController.text,
                  executeAt: DateTime.now().add(const Duration(minutes: 5)),
                  repeatType: ScheduledTaskRepeatType.once,
                )),
              ),
              ListTile(
                leading: const Icon(Icons.timer),
                title: const Text('30 分钟后'),
                enabled: _hasText,
                onTap: () => widget.onSelect(_ScheduleResult(
                  textContent: _textController.text,
                  executeAt: DateTime.now().add(const Duration(minutes: 30)),
                  repeatType: ScheduledTaskRepeatType.once,
                )),
              ),
              ListTile(
                leading: const Icon(Icons.timer),
                title: const Text('1 小时后'),
                enabled: _hasText,
                onTap: () => widget.onSelect(_ScheduleResult(
                  textContent: _textController.text,
                  executeAt: DateTime.now().add(const Duration(hours: 1)),
                  repeatType: ScheduledTaskRepeatType.once,
                )),
              ),
              ListTile(
                leading: const Icon(Icons.access_time),
                title: const Text('自定义时间'),
                enabled: _hasText,
                onTap: () async {
                  final picked = await showTimePicker(
                    context: context,
                    initialTime: TimeOfDay.now(),
                  );
                  if (picked == null || !context.mounted) return;
                  final now = DateTime.now();
                  var executeAt = DateTime(
                    now.year, now.month, now.day,
                    picked.hour, picked.minute,
                  );
                  if (executeAt.isBefore(now)) {
                    executeAt = executeAt.add(const Duration(days: 1));
                  }
                  widget.onSelect(_ScheduleResult(
                    textContent: _textController.text,
                    executeAt: executeAt,
                    repeatType: ScheduledTaskRepeatType.once,
                  ));
                },
              ),
              ListTile(
                leading: const Icon(Icons.repeat),
                title: const Text('每日重复'),
                enabled: _hasText,
                onTap: () async {
                  final picked = await showTimePicker(
                    context: context,
                    initialTime: TimeOfDay.now(),
                  );
                  if (picked == null || !context.mounted) return;
                  final now = DateTime.now();
                  var executeAt = DateTime(
                    now.year, now.month, now.day,
                    picked.hour, picked.minute,
                  );
                  if (executeAt.isBefore(now)) {
                    executeAt = executeAt.add(const Duration(days: 1));
                  }
                  widget.onSelect(_ScheduleResult(
                    textContent: _textController.text,
                    executeAt: executeAt,
                    repeatType: ScheduledTaskRepeatType.daily,
                  ));
                },
              ),
            ],
          ),
        ),
      );
}
}

class _ScheduleResult {
  final String textContent;
  final DateTime executeAt;
  final ScheduledTaskRepeatType repeatType;

  _ScheduleResult({
    required this.textContent,
    required this.executeAt,
    required this.repeatType,
  });
}
