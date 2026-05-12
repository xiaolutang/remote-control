import 'dart:convert';

import 'package:http/http.dart' as http;

import '../models/scheduled_task.dart';
import '../utils/json_helpers.dart' show readIntFromJson, readListFromJson;
import 'auth_service.dart';
import 'http_client_factory.dart';
import 'server_url_helper.dart';

class ScheduledTaskException implements Exception {
  ScheduledTaskException({
    required this.statusCode,
    required this.message,
    this.reason,
  });

  final int statusCode;
  final String message;
  final String? reason;

  @override
  String toString() => 'ScheduledTaskException($statusCode): $message';
}

class ScheduledTaskService {
  ScheduledTaskService({
    required this.serverUrl,
    http.Client? client,
  }) : _client = client ?? HttpClientFactory.create();

  final String serverUrl;
  final http.Client _client;

  String get _httpUrl => serverUrlToHttpBase(serverUrl);

  Map<String, String> _headers(String token) => {
        'Authorization': 'Bearer $token',
        'Content-Type': 'application/json',
      };

  /// 创建定时任务，返回 task_id
  Future<int> create({
    required String token,
    required String sessionId,
    required String terminalId,
    required String textContent,
    required String executeAt,
    required ScheduledTaskRepeatType repeatType,
  }) async {
    final response = await _client.post(
      Uri.parse('$_httpUrl/api/scheduled-tasks'),
      headers: _headers(token),
      body: jsonEncode({
        'session_id': sessionId,
        'terminal_id': terminalId,
        'text_content': textContent,
        'execute_at': executeAt,
        'repeat_type': repeatType.name,
      }),
    );
    if (response.statusCode == 201) {
      final data = jsonDecode(response.body) as Map<String, dynamic>;
      return readIntFromJson(data['task_id']);
    }
    _throwError(response, '创建定时任务失败');
  }

  /// 查询定时任务列表
  Future<List<ScheduledTask>> list({
    required String token,
    String? sessionId,
    String? status,
  }) async {
    final queryParams = <String, String>{};
    if (sessionId != null) queryParams['session_id'] = sessionId;
    if (status != null) queryParams['status'] = status;

    final uri = queryParams.isEmpty
        ? Uri.parse('$_httpUrl/api/scheduled-tasks')
        : Uri.parse('$_httpUrl/api/scheduled-tasks')
            .replace(queryParameters: queryParams);
    final response = await _client.get(uri, headers: _headers(token));

    if (response.statusCode == 200) {
      final data = jsonDecode(response.body) as Map<String, dynamic>;
      return readListFromJson(data['tasks'], ScheduledTask.fromJson);
    }
    _throwError(response, '加载定时任务失败');
  }

  /// 删除定时任务
  Future<void> delete({required String token, required int taskId}) async {
    final response = await _client.delete(
      Uri.parse('$_httpUrl/api/scheduled-tasks/$taskId'),
      headers: _headers(token),
    );
    if (response.statusCode == 204) return;
    _throwError(response, '删除定时任务失败');
  }

  Never _throwError(http.Response response, String defaultMessage) {
    Map<String, dynamic>? data;
    try {
      data = jsonDecode(response.body) as Map<String, dynamic>;
    } on FormatException {
      throw ScheduledTaskException(
        statusCode: response.statusCode,
        message: '$defaultMessage (${response.statusCode})',
      );
    }
    if (response.statusCode == 401) {
      final errorCode = data['error_code'] as String?;
      switch (errorCode) {
        case 'TOKEN_REPLACED':
          throw AuthException(AuthErrorCode.tokenReplaced, '您已在其他设备登录');
        case 'TOKEN_EXPIRED':
          throw AuthException(AuthErrorCode.tokenExpired, '登录已过期');
        case 'TOKEN_INVALID':
          throw AuthException(AuthErrorCode.tokenInvalid, '认证信息无效');
      }
    }
    final detail = data['detail'];
    if (detail is Map<String, dynamic>) {
      throw ScheduledTaskException(
        statusCode: response.statusCode,
        message: (detail['message'] as String? ?? defaultMessage).trim(),
        reason: (detail['reason'] as String?)?.trim(),
      );
    }
    throw ScheduledTaskException(
      statusCode: response.statusCode,
      message: (detail as String? ?? defaultMessage).trim(),
    );
  }
}
