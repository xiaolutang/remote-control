import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

import '../models/agent_conversation_projection.dart';
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

  Future<AgentConversationProjection> fetchConversation({
    required String deviceId,
    String? terminalId,
    required String token,
  }) async {
    final resolvedTerminalId = _resolveTerminalId(terminalId);
    final response = await _client.get(
      Uri.parse('$_httpUrl/api/runtime/devices/$deviceId'
          '/terminals/$resolvedTerminalId/assistant/conversation'),
      headers: _jsonHeaders(token),
    );
    if (response.statusCode == 200) {
      final json = jsonDecode(response.body) as Map<String, dynamic>;
      return AgentConversationProjection.fromJson(json);
    }
    _throwResponseException(
      statusCode: response.statusCode,
      responseBody: response.body,
      fallbackMessage: '获取 Agent 对话失败',
    );
  }

  Stream<AgentConversationEventItem> streamConversation({
    required String deviceId,
    String? terminalId,
    required String token,
    int afterIndex = -1,
  }) {
    final controller = StreamController<AgentConversationEventItem>();

    () async {
      try {
        final resolvedTerminalId = _resolveTerminalId(terminalId);
        final request = http.Request(
          'GET',
          Uri.parse('$_httpUrl/api/runtime/devices/$deviceId'
              '/terminals/$resolvedTerminalId/assistant/conversation/stream'
              '?after_index=$afterIndex'),
        )..headers.addAll(_headers(token));

        final response = await _client.send(request);

        if (response.statusCode != 200) {
          final responseBody = await response.stream.bytesToString();
          controller.addError(
            _buildResponseException(
              statusCode: response.statusCode,
              responseBody: responseBody,
              fallbackMessage: '订阅 Agent 对话失败',
            ),
          );
          await controller.close();
          return;
        }

        await _processConversationStream(
          response: response,
          controller: controller,
        );
      } catch (e) {
        if (!controller.isClosed) {
          controller.addError(e);
          await controller.close();
        }
      }
    }();

    return controller.stream;
  }

  /// 弹性对话事件流：自动重连，带指数退避。
  ///
  /// 对比 [streamConversation]，此方法返回的 Stream 在底层连接断开时会
  /// 自动重连，无需调用方管理重试逻辑。收到 `closed` 事件或超过最大重试
  /// 次数后流正常结束。
  Stream<AgentConversationEventItem> streamConversationResilient({
    required String deviceId,
    String? terminalId,
    required String token,
    int afterIndex = -1,
    int maxReconnectAttempts = 5,
  }) {
    final outerController = StreamController<AgentConversationEventItem>();

    var reconnectAttempts = 0;
    var currentIndex = afterIndex;
    StreamSubscription<AgentConversationEventItem>? innerSub;
    Timer? reconnectTimer;

    void dispose() {
      innerSub?.cancel();
      innerSub = null;
      reconnectTimer?.cancel();
      reconnectTimer = null;
    }

    void connect() {
      innerSub = streamConversation(
        deviceId: deviceId,
        terminalId: terminalId,
        token: token,
        afterIndex: currentIndex,
      ).listen(
        (event) {
          currentIndex = event.eventIndex;
          reconnectAttempts = 0;
          outerController.add(event);
          if (event.type == 'closed') {
            dispose();
            if (!outerController.isClosed) outerController.close();
          }
        },
        onError: (Object _) {
          innerSub = null;
          if (outerController.isClosed) return;
          // scheduleReconnect 声明在 connect 之后，通过 Timer 间接调用
          reconnectTimer?.cancel();
          reconnectAttempts++;
          if (reconnectAttempts > maxReconnectAttempts) {
            if (!outerController.isClosed) outerController.close();
            return;
          }
          final delay = Duration(
            seconds: 2 * (1 << (reconnectAttempts - 1).clamp(0, 4)),
          );
          reconnectTimer = Timer(delay, connect);
        },
        onDone: () {
          innerSub = null;
          if (outerController.isClosed) return;
          reconnectTimer?.cancel();
          reconnectAttempts++;
          if (reconnectAttempts > maxReconnectAttempts) {
            if (!outerController.isClosed) outerController.close();
            return;
          }
          final delay = Duration(
            seconds: 1 * (1 << (reconnectAttempts - 1).clamp(0, 4)),
          );
          reconnectTimer = Timer(delay, connect);
        },
      );
    }

    connect();

    outerController.onCancel = () {
      dispose();
    };

    return outerController.stream;
  }

  /// 启动 Agent 会话，返回 SSE 事件流
  ///
  /// 调用 POST /runtime/devices/{deviceId}/assistant/agent/run
  /// 成功时返回 SSE 事件流。
  /// 非 200 响应统一转换为 [AgentErrorEvent]，由调用方直接展示错误。
  Stream<AgentSessionEvent> runSession({
    required String deviceId,
    String? terminalId,
    required String intent,
    required String token,
    String? conversationId,
    String? clientEventId,
    int? truncateAfterIndex, // -1 = 全部截断，null = 不截断
  }) {
    final controller = StreamController<AgentSessionEvent>();

    () async {
      try {
        final resolvedTerminalId = _resolveTerminalId(terminalId);
        final body = <String, dynamic>{
          'intent': intent,
          'client_event_id': clientEventId ?? _newClientEventId('run'),
          if (conversationId != null) 'conversation_id': conversationId,
          if (truncateAfterIndex != null)
            'truncate_after_index': truncateAfterIndex,
        };

        final request = http.Request(
          'POST',
          Uri.parse('$_httpUrl/api/runtime/devices/$deviceId'
              '/terminals/$resolvedTerminalId/assistant/agent/run'),
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
    String? terminalId,
    required String sessionId,
    required String answer,
    required String token,
    String? questionId,
    String? clientEventId,
  }) async {
    final resolvedTerminalId = _resolveTerminalId(terminalId);
    final response = await _client.post(
      Uri.parse('$_httpUrl/api/runtime/devices/$deviceId'
          '/terminals/$resolvedTerminalId/assistant/agent/$sessionId/respond'),
      headers: _jsonHeaders(token),
      body: jsonEncode({
        'answer': answer,
        'question_id': questionId,
        'client_event_id': clientEventId ?? _newClientEventId('answer'),
      }),
    );
    if (response.statusCode == 200) {
      final data = jsonDecode(response.body) as Map<String, dynamic>;
      return data['ok'] == true || data['status'] == 'ok';
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
    String? terminalId,
    required String sessionId,
    required String token,
  }) async {
    final resolvedTerminalId = _resolveTerminalId(terminalId);
    final response = await _client.post(
      Uri.parse('$_httpUrl/api/runtime/devices/$deviceId'
          '/terminals/$resolvedTerminalId/assistant/agent/$sessionId/cancel'),
      headers: _jsonHeaders(token),
    );
    if (response.statusCode == 200) {
      final data = jsonDecode(response.body) as Map<String, dynamic>;
      return data['ok'] == true || data['status'] == 'ok';
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
    String? terminalId,
    required String sessionId,
    required String token,
  }) {
    final controller = StreamController<AgentSessionEvent>();

    () async {
      try {
        final resolvedTerminalId = _resolveTerminalId(terminalId);
        _activeSessionId = sessionId;

        final request = http.Request(
          'GET',
          Uri.parse('$_httpUrl/api/runtime/devices/$deviceId'
              '/terminals/$resolvedTerminalId/assistant/agent/$sessionId/resume'),
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
        case 'session_created':
          return AgentSessionCreatedEvent.fromJson(json);
        // --- 新事件类型 ---
        case 'phase_change':
          return PhaseChangeEvent.fromJson(json);
        case 'streaming_text':
          return StreamingTextEvent.fromJson(json);
        case 'tool_step':
          return ToolStepEvent.fromJson(json);
        // --- 保留事件 ---
        case 'question':
          return AgentQuestionEvent.fromJson(json);
        case 'result':
          return AgentResultEvent.fromJson(json);
        case 'error':
          return AgentErrorEvent.fromJson(json);
        // --- 旧事件类型：兼容丢弃（不 crash） ---
        case 'trace':
        case 'assistant_message':
          return null;
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
    final exception = _buildResponseException(
      statusCode: statusCode,
      responseBody: responseBody,
      fallbackMessage: 'Agent 会话请求失败',
    );

    controller.add(AgentErrorEvent(
      code: exception.code ?? _defaultErrorCodeForStatus(statusCode),
      message: _friendlyErrorMessage(
        exception.message,
        code: exception.code,
        statusCode: statusCode,
      ),
    ));
    controller.close();
  }

  String _defaultErrorCodeForStatus(int statusCode) {
    switch (statusCode) {
      case 409:
        return 'AGENT_UNAVAILABLE';
      case 410:
        return 'SESSION_EXPIRED';
      case 429:
        return 'RATE_LIMITED';
      default:
        return 'AGENT_REQUEST_FAILED';
    }
  }

  String _friendlyErrorMessage(
    String rawMessage, {
    String? code,
    required int statusCode,
  }) {
    final normalizedCode = (code ?? '').trim().toLowerCase();
    final normalizedMessage = rawMessage.toLowerCase();
    final tokenProblem = normalizedCode == 'service_llm_budget_blocked' ||
        normalizedMessage.contains('token') ||
        normalizedMessage.contains('api key') ||
        normalizedMessage.contains('quota') ||
        normalizedMessage.contains('billing') ||
        normalizedMessage.contains('配额');
    if (tokenProblem) {
      return '智能服务 Token 或配额不可用，请联系开发者';
    }
    if (normalizedCode == 'device_offline') {
      return '当前桌面设备未在线，无法启动智能交互';
    }
    if (statusCode == 429) {
      return '智能服务当前不可用，请稍后重试';
    }
    return rawMessage;
  }

  Future<void> _processConversationStream({
    required http.StreamedResponse response,
    required StreamController<AgentConversationEventItem> controller,
  }) async {
    String? currentEvent;
    StringBuffer? dataBuffer;

    await for (final line in response.stream
        .transform(utf8.decoder)
        .transform(const LineSplitter())) {
      if (line.startsWith(':')) {
        continue;
      }
      if (line.startsWith('event:')) {
        currentEvent = line.substring(6).trim();
        dataBuffer = StringBuffer();
        continue;
      }
      if (line.startsWith('data:')) {
        final dataContent = line.substring(5).trim();
        if (dataBuffer != null) {
          if (dataBuffer.isNotEmpty) dataBuffer.write('\n');
          dataBuffer.write(dataContent);
        }
        continue;
      }
      if (line.isEmpty && currentEvent != null && dataBuffer != null) {
        if (currentEvent == 'conversation_event') {
          try {
            final decoded = jsonDecode(dataBuffer.toString());
            if (decoded is Map<String, dynamic>) {
              final event = AgentConversationEventItem.fromJson(decoded);
              controller.add(event);
              if (event.type == 'closed') {
                await controller.close();
                return;
              }
            }
          } on FormatException {
            // Ignore malformed conversation frames.
          }
        }
        currentEvent = null;
        dataBuffer = null;
      }
    }

    if (!controller.isClosed) {
      await controller.close();
    }
  }

  AgentSessionException _buildResponseException({
    required int statusCode,
    required String responseBody,
    required String fallbackMessage,
  }) {
    try {
      final decoded = jsonDecode(responseBody);
      if (decoded is Map<String, dynamic>) {
        final topLevelMessage = (decoded['message'] as String?)?.trim();
        final topLevelCode = (decoded['code'] as String?)?.trim();
        if (topLevelMessage != null && topLevelMessage.isNotEmpty) {
          return AgentSessionException(
            message: topLevelMessage,
            code: topLevelCode,
            statusCode: statusCode,
          );
        }
        final detail = decoded['detail'];
        if (detail is Map<String, dynamic>) {
          return AgentSessionException(
            message: (detail['message'] as String? ?? fallbackMessage).trim(),
            code: (detail['reason'] as String?)?.trim(),
            statusCode: statusCode,
          );
        }
        if (detail is String && detail.trim().isNotEmpty) {
          return AgentSessionException(
            message: detail.trim(),
            statusCode: statusCode,
          );
        }
      }
    } on FormatException {
      // fall through
    }
    return AgentSessionException(
      message: '$fallbackMessage ($statusCode)',
      statusCode: statusCode,
    );
  }

  Never _throwResponseException({
    required int statusCode,
    required String responseBody,
    required String fallbackMessage,
  }) {
    throw _buildResponseException(
      statusCode: statusCode,
      responseBody: responseBody,
      fallbackMessage: fallbackMessage,
    );
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

  String _newClientEventId(String prefix) {
    return '$prefix-${DateTime.now().microsecondsSinceEpoch}';
  }

  String _resolveTerminalId(String? terminalId) {
    final trimmed = terminalId?.trim();
    if (trimmed != null && trimmed.isNotEmpty) {
      return trimmed;
    }
    return 'terminal-legacy';
  }
}
