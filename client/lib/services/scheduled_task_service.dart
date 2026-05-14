import 'dart:convert';

import '../models/scheduled_task.dart';
import 'api_service_base.dart';

/// 定时任务 HTTP 服务
///
/// 对接 POST /api/scheduled-tasks 等接口。
/// services/ 不依赖 screens/ 或 widgets/（架构约束）。
class ScheduledTaskService extends ApiServiceBase {
  ScheduledTaskService({
    required super.serverUrl,
    super.client,
  });

  /// 创建定时任务
  ///
  /// 返回新建任务的 ID。
  /// [textContent] 由 steps 每步的 command 用 `\r` 拼接。
  /// [executeAt] ISO 8601 格式字符串。
  /// [repeatType] 重复类型枚举。
  Future<int> create({
    required String token,
    required String sessionId,
    required String terminalId,
    required String textContent,
    required String executeAt,
    required ScheduledTaskRepeatType repeatType,
  }) async {
    final response = await client.post(
      Uri.parse('$httpUrl/api/scheduled-tasks'),
      headers: authHeaders(token),
      body: jsonEncode({
        'session_id': sessionId,
        'terminal_id': terminalId,
        'text_content': textContent,
        'execute_at': executeAt,
        'repeat_type': repeatType.toApiString(),
      }),
    );

    if (response.statusCode == 201 || response.statusCode == 200) {
      final data = jsonDecode(response.body) as Map<String, dynamic>;
      return data['id'] as int;
    }

    final data = response.body.isNotEmpty
        ? jsonDecode(response.body) as Map<String, dynamic>
        : <String, dynamic>{};
    throw ScheduledTaskException(
      statusCode: response.statusCode,
      message: data['detail']?.toString() ?? '创建定时任务失败',
    );
  }

  /// 获取定时任务列表
  Future<List<ScheduledTask>> list({
    required String token,
    String? sessionId,
    String? status,
  }) async {
    final queryParams = <String, String>{};
    if (sessionId != null) queryParams['session_id'] = sessionId;
    if (status != null) queryParams['status'] = status;

    final uri = Uri.parse('$httpUrl/api/scheduled-tasks')
        .replace(queryParameters: queryParams.isEmpty ? null : queryParams);
    final response = await client.get(uri, headers: authHeaders(token));

    if (response.statusCode == 200) {
      final data = jsonDecode(response.body) as Map<String, dynamic>;
      final tasks = data['tasks'] as List<dynamic>;
      return tasks
          .map((t) => ScheduledTask.fromJson(t as Map<String, dynamic>))
          .toList();
    }

    throw ScheduledTaskException(
      statusCode: response.statusCode,
      message: '获取定时任务列表失败',
    );
  }

  /// 删除定时任务
  Future<void> delete({
    required String token,
    required int taskId,
  }) async {
    final response = await client.delete(
      Uri.parse('$httpUrl/api/scheduled-tasks/$taskId'),
      headers: authHeaders(token),
    );

    if (response.statusCode == 204 || response.statusCode == 200) return;

    throw ScheduledTaskException(
      statusCode: response.statusCode,
      message: '删除定时任务失败',
    );
  }
}

/// 定时任务操作异常
class ScheduledTaskException implements Exception {
  const ScheduledTaskException({
    required this.statusCode,
    required this.message,
  });

  final int statusCode;
  final String message;

  @override
  String toString() => 'ScheduledTaskException($statusCode): $message';
}
