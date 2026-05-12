import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;

import '../models/scheduled_task.dart';
import 'scheduled_task_service.dart';

/// 定时任务轮询器
///
/// 每 30 秒调用 ScheduledTaskService.list() 获取当前 session 的 pending 任务。
/// 创建成功后可立即触发刷新（不等轮询）。
/// 取消操作调用 DELETE API 后自动刷新列表。
class ScheduledTaskPoller extends ChangeNotifier {
  ScheduledTaskPoller({required String serverUrl, http.Client? client})
      : _service = ScheduledTaskService(serverUrl: serverUrl, client: client);

  final ScheduledTaskService _service;
  Timer? _pollTimer;
  String? _token;
  String? _sessionId;

  List<ScheduledTask> _tasks = [];
  List<ScheduledTask> get tasks => _tasks;

  bool _isLoading = false;
  bool get isLoading => _isLoading;

  /// 启动轮询
  void startPolling(String token, String sessionId) {
    _token = token;
    _sessionId = sessionId;
    stopPolling();
    refresh(); // 立即首次加载
    _pollTimer = Timer.periodic(const Duration(seconds: 30), (_) => refresh());
  }

  /// 停止轮询
  void stopPolling() {
    _pollTimer?.cancel();
    _pollTimer = null;
  }

  /// 手动刷新（创建/删除后调用）
  Future<void> refresh() async {
    if (_token == null || _sessionId == null) return;
    _isLoading = true;
    notifyListeners();
    try {
      _tasks = await _service.list(
        token: _token!,
        sessionId: _sessionId,
      );
    } catch (_) {
      // 轮询失败静默处理，保持上次结果
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  /// 取消/删除任务
  Future<void> deleteTask(int taskId) async {
    if (_token == null) return;
    await _service.delete(token: _token!, taskId: taskId);
    await refresh(); // 删除后立即刷新
  }

  /// 获取指定 terminal 的 pending 任务（用于 badge 展示）
  List<ScheduledTask> pendingTasksForTerminal(String terminalId) {
    return _tasks
        .where((t) =>
            t.terminalId == terminalId &&
            t.status == ScheduledTaskStatus.pending)
        .toList();
  }

  /// 获取指定 terminal 的全部任务（用于管理列表）
  List<ScheduledTask> allTasksForTerminal(String terminalId) {
    return _tasks.where((t) => t.terminalId == terminalId).toList();
  }

  @override
  void dispose() {
    stopPolling();
    super.dispose();
  }
}
