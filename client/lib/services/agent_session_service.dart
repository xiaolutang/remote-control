import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

import '../models/agent_session_event.dart';
import 'http_client_factory.dart';
import 'server_url_helper.dart';

/// Agent SSE 会话服务异常
class AgentSessionException implements Exception {
  const AgentSessionException({
    required this.message,
    this.code,
    this.statusCode,
  });

  final String message;
  final String? code;
  final int? statusCode;

  @override
  String toString() => message;
}

/// Agent SSE 会话服务
///
/// 消费服务端 B080 Agent SSE API，支持：
/// - 启动 Agent 会话（POST run → SSE 流）
/// - 用户回复（POST respond）
/// - 取消会话（POST cancel）
/// - 断连恢复（GET resume → SSE 流）
/// - keepalive 注释帧过滤
/// - 会话超时处理（10 分钟）
class AgentSessionService {
  AgentSessionService({
    required this.serverUrl,
    http.Client? client,
  }) : _client = client ?? HttpClientFactory.create();

  final String serverUrl;
  final http.Client _client;

  /// 会话超时时间（10 分钟）
  static const Duration sessionTimeout = Duration(minutes: 10);

  String get _httpUrl => serverUrlToHttpBase(serverUrl);

  Map<String, String> _headers(String token) => {
        'Authorization': 'Bearer $token',
        'Content-Type': 'application/json',
        'Accept': 'text/event-stream',
      };

  Map<String, String> _jsonHeaders(String token) => {
        'Authorization': 'Bearer $token',
        'Content-Type': 'application/json',
      };

  /// 当前活跃会话 ID
  String? _activeSessionId;

  /// 获取当前活跃会话 ID
  String? get activeSessionId => _activeSessionId;

  /// 启动 Agent 会话，返回 SSE 事件流
  ///
  /// 调用 POST /runtime/devices/{deviceId}/assistant/agent/run
  /// 成功时返回 SSE 事件流。
  /// 设备离线等错误时通过流发射 [AgentFallbackEvent]，调用方可降级到 planner。
  Stream<AgentSessionEvent> runSession({
    required String deviceId,
    required String intent,
    required String token,
    String? conversationId,
  }) {
    final controller = StreamController<AgentSessionEvent>();

    () async {
      try {
        final body = <String, dynamic>{
          'intent': intent,
          if (conversationId != null) 'conversation_id': conversationId,
        };

        final request = http.Request(
          'POST',
          Uri.parse(
              '$_httpUrl/api/runtime/devices/$deviceId/assistant/agent/run'),
        )
          ..headers.addAll(_headers(token))
          ..body = jsonEncode(body);

        final response = await _client.send(request);

        if (response.statusCode != 200) {
          final responseBody = await response.stream.bytesToString();
          _handleNon200Response(
            response: response,
            responseBody: responseBody,
            controller: controller,
          );
          return;
        }

        await _processSSEStream(
          response: response,
          controller: controller,
        );
      } catch (e) {
        if (!controller.isClosed) {
          controller.addError(e);
          controller.close();
        }
      }
    }();

    return controller.stream;
  }

  /// 用户回复 Agent 问题
  ///
  /// POST /runtime/devices/{deviceId}/assistant/agent/{sessionId}/respond
  Future<bool> respond({
    required String deviceId,
    required String sessionId,
    required String answer,
    required String token,
  }) async {
    final response = await _client.post(
      Uri.parse(
          '$_httpUrl/api/runtime/devices/$deviceId/assistant/agent/$sessionId/respond'),
      headers: _jsonHeaders(token),
      body: jsonEncode({'answer': answer}),
    );
    if (response.statusCode == 200) {
      final data = jsonDecode(response.body) as Map<String, dynamic>;
      return data['ok'] == true;
    }
    throw AgentSessionException(
      message: '回复 Agent 失败 (${response.statusCode})',
      statusCode: response.statusCode,
    );
  }

  /// 取消会话
  ///
  /// POST /runtime/devices/{deviceId}/assistant/agent/{sessionId}/cancel
  Future<bool> cancel({
    required String deviceId,
    required String sessionId,
    required String token,
  }) async {
    final response = await _client.post(
      Uri.parse(
          '$_httpUrl/api/runtime/devices/$deviceId/assistant/agent/$sessionId/cancel'),
      headers: _jsonHeaders(token),
    );
    if (response.statusCode == 200) {
      final data = jsonDecode(response.body) as Map<String, dynamic>;
      return data['ok'] == true;
    }
    throw AgentSessionException(
      message: '取消会话失败 (${response.statusCode})',
      statusCode: response.statusCode,
    );
  }

  /// 断连恢复
  ///
  /// GET /runtime/devices/{deviceId}/assistant/agent/{sessionId}/resume
  /// 服务端根据 session 状态：
  /// - exploring → 继续实时流
  /// - asking → 重发 QuestionEvent
  /// - completed → 重发 ResultEvent
  /// - expired/error → 返回 ErrorEvent
  Stream<AgentSessionEvent> resumeSession({
    required String deviceId,
    required String sessionId,
    required String token,
  }) {
    final controller = StreamController<AgentSessionEvent>();

    () async {
      try {
        _activeSessionId = sessionId;

        final request = http.Request(
          'GET',
          Uri.parse(
              '$_httpUrl/api/runtime/devices/$deviceId/assistant/agent/$sessionId/resume'),
        )..headers.addAll(_headers(token));

        final response = await _client.send(request);

        if (response.statusCode != 200) {
          final responseBody = await response.stream.bytesToString();
          _handleNon200Response(
            response: response,
            responseBody: responseBody,
            controller: controller,
          );
          return;
        }

        await _processSSEStream(
          response: response,
          controller: controller,
        );
      } catch (e) {
        if (!controller.isClosed) {
          controller.addError(e);
          controller.close();
        }
      }
    }();

    return controller.stream;
  }

  /// 处理 SSE 流，解析事件并添加到 controller
  Future<void> _processSSEStream({
    required http.StreamedResponse response,
    required StreamController<AgentSessionEvent> controller,
  }) async {
    String? currentEvent;
    StringBuffer? dataBuffer;

    await for (final line in response.stream
        .transform(utf8.decoder)
        .transform(const LineSplitter())) {
      // 注释行（keepalive 等），忽略
      if (line.startsWith(':')) {
        continue;
      }

      // event: 行
      if (line.startsWith('event:')) {
        currentEvent = line.substring(6).trim();
        dataBuffer = StringBuffer();
        continue;
      }

      // data: 行
      if (line.startsWith('data:')) {
        final dataContent = line.substring(5).trim();
        if (dataBuffer != null) {
          if (dataBuffer.isNotEmpty) dataBuffer.write('\n');
          dataBuffer.write(dataContent);
        }
        continue;
      }

      // 空行表示事件结束
      if (line.isEmpty && currentEvent != null && dataBuffer != null) {
        final event = _parseEvent(currentEvent, dataBuffer.toString());
        if (event != null) {
          // 会话超时检查
          if (event is AgentErrorEvent && event.code == 'SESSION_EXPIRED') {
            _activeSessionId = null;
          }

          controller.add(event);

          // result 或 error 事件后关闭流
          if (event is AgentResultEvent || event is AgentErrorEvent) {
            await controller.close();
            return;
          }
        }
        currentEvent = null;
        dataBuffer = null;
      }
    }

    // 流结束，关闭 controller
    if (!controller.isClosed) {
      await controller.close();
    }
  }

  /// 解析 SSE 事件
  AgentSessionEvent? _parseEvent(String eventType, String data) {
    try {
      final json = jsonDecode(data) as Map<String, dynamic>;
      switch (eventType) {
        case 'trace':
          return AgentTraceEvent.fromJson(json);
        case 'question':
          return AgentQuestionEvent.fromJson(json);
        case 'result':
          return AgentResultEvent.fromJson(json);
        case 'error':
          return AgentErrorEvent.fromJson(json);
        default:
          return null;
      }
    } on FormatException {
      return null;
    }
  }

  /// 处理非 200 响应
  void _handleNon200Response({
    required http.StreamedResponse response,
    required String responseBody,
    required StreamController<AgentSessionEvent> controller,
  }) {
    final statusCode = response.statusCode;

    // 尝试解析服务端错误 JSON
    Map<String, dynamic>? errorData;
    try {
      errorData = jsonDecode(responseBody) as Map<String, dynamic>;
    } on FormatException {
      // 非 JSON 响应
    }

    final errorCode = errorData?['code'] as String?;
    final errorMessage =
        errorData?['message'] as String? ?? errorData?['detail'] as String?;

    // 409 Conflict：Agent 不可用（设备离线等），触发降级
    if (statusCode == 409) {
      controller.add(AgentFallbackEvent(
        reason: errorMessage ?? 'Agent 不可用',
        code: errorCode ?? 'AGENT_OFFLINE',
      ));
      controller.close();
      return;
    }

    // 410 Gone：会话已过期
    if (statusCode == 410) {
      controller.add(AgentErrorEvent(
        code: errorCode ?? 'SESSION_EXPIRED',
        message: errorMessage ?? '会话已过期',
      ));
      controller.close();
      return;
    }

    // 其他错误
    controller.addError(
      AgentSessionException(
        message: errorMessage ?? 'Agent 会话请求失败 ($statusCode)',
        code: errorCode,
        statusCode: statusCode,
      ),
    );
    controller.close();
  }

  /// 回写执行结果
  ///
  /// POST /runtime/devices/{deviceId}/assistant/agent/{sessionId}/report
  /// 执行完成后（无论成功或失败）回写执行结果，用于评估 trace。
  /// 成功时服务端触发别名持久化。
  Future<void> reportExecution({
    required String deviceId,
    required String sessionId,
    required bool success,
    String? executedCommand,
    String? failureStep,
    String? token,
  }) async {
    final headers = <String, String>{
      'Content-Type': 'application/json',
    };
    if (token != null) {
      headers['Authorization'] = 'Bearer $token';
    }

    final response = await _client.post(
      Uri.parse(
          '$_httpUrl/api/runtime/devices/$deviceId/assistant/agent/$sessionId/report'),
      headers: headers,
      body: jsonEncode({
        'success': success,
        if (executedCommand != null) 'executed_command': executedCommand,
        if (failureStep != null) 'failure_step': failureStep,
      }),
    );

    if (response.statusCode != 200) {
      throw AgentSessionException(
        message: '回写执行结果失败 (${response.statusCode})',
        statusCode: response.statusCode,
      );
    }
  }

  /// 释放资源
  void dispose() {
    _client.close();
  }
}
