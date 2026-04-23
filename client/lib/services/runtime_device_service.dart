import 'dart:convert';

import 'package:http/http.dart' as http;

import '../models/assistant_plan.dart';
import '../models/project_context_settings.dart';
import '../models/project_context_snapshot.dart';
import '../models/runtime_device.dart';
import '../models/runtime_terminal.dart';
import 'auth_service.dart';
import 'http_client_factory.dart';
import 'server_url_helper.dart';

class RuntimeApiException implements Exception {
  RuntimeApiException({
    required this.statusCode,
    required this.message,
    this.reason,
    this.retryAfter,
  });

  final int statusCode;
  final String message;
  final String? reason;
  final int? retryAfter;

  @override
  String toString() => 'Exception: $message';
}

class RuntimeDeviceService {
  RuntimeDeviceService({
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

  /// 处理非 200 响应，对 401 按 error_code 分支抛出 AuthException
  Never _throwError(http.Response response, String defaultMessage) {
    Map<String, dynamic>? data;
    try {
      data = jsonDecode(response.body) as Map<String, dynamic>;
    } on FormatException {
      throw RuntimeApiException(
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
      throw RuntimeApiException(
        statusCode: response.statusCode,
        message: (detail['message'] as String? ?? defaultMessage).trim(),
        reason: (detail['reason'] as String?)?.trim(),
        retryAfter: int.tryParse(response.headers['retry-after'] ?? ''),
      );
    }
    throw RuntimeApiException(
      statusCode: response.statusCode,
      message: (detail as String? ?? defaultMessage).trim(),
      retryAfter: int.tryParse(response.headers['retry-after'] ?? ''),
    );
  }

  Future<List<RuntimeDevice>> listDevices(String token) async {
    final response = await _client.get(
      Uri.parse('$_httpUrl/api/runtime/devices'),
      headers: _headers(token),
    );
    if (response.statusCode != 200) {
      _throwError(response, '加载设备失败');
    }
    final data = jsonDecode(response.body) as Map<String, dynamic>;
    final devices = (data['devices'] as List<dynamic>? ?? const [])
        .whereType<Map<String, dynamic>>()
        .map(RuntimeDevice.fromJson)
        .toList(growable: false);
    return devices;
  }

  Future<List<RuntimeTerminal>> listTerminals(
      String token, String deviceId) async {
    final response = await _client.get(
      Uri.parse('$_httpUrl/api/runtime/devices/$deviceId/terminals'),
      headers: _headers(token),
    );
    if (response.statusCode != 200) {
      _throwError(response, '加载终端失败');
    }
    final data = jsonDecode(response.body) as Map<String, dynamic>;
    return (data['terminals'] as List<dynamic>? ?? const [])
        .whereType<Map<String, dynamic>>()
        .map(RuntimeTerminal.fromJson)
        .toList(growable: false);
  }

  Future<RuntimeTerminal?> getTerminal(
    String token,
    String deviceId,
    String terminalId,
  ) async {
    final terminals = await listTerminals(token, deviceId);
    for (final terminal in terminals) {
      if (terminal.terminalId == terminalId) {
        return terminal;
      }
    }
    return null;
  }

  Future<RuntimeTerminal> createTerminal(
    String token,
    String deviceId, {
    required String title,
    required String cwd,
    required String command,
    Map<String, String> env = const {},
    String? terminalId,
  }) async {
    final resolvedTerminalId =
        terminalId ?? 'term-${DateTime.now().millisecondsSinceEpoch}';
    final response = await _client.post(
      Uri.parse('$_httpUrl/api/runtime/devices/$deviceId/terminals'),
      headers: _headers(token),
      body: jsonEncode({
        'terminal_id': resolvedTerminalId,
        'title': title,
        'cwd': cwd,
        'command': command,
        'env': env,
      }),
    );
    if (response.statusCode != 200) {
      _throwError(response, '创建终端失败');
    }
    final data = jsonDecode(response.body) as Map<String, dynamic>;
    return RuntimeTerminal.fromJson(data);
  }

  Future<RuntimeTerminal> closeTerminal(
    String token,
    String deviceId,
    String terminalId,
  ) async {
    final response = await _client.delete(
      Uri.parse(
          '$_httpUrl/api/runtime/devices/$deviceId/terminals/$terminalId'),
      headers: _headers(token),
    );
    if (response.statusCode != 200) {
      _throwError(response, '关闭终端失败');
    }
    final data = jsonDecode(response.body) as Map<String, dynamic>;
    return RuntimeTerminal.fromJson(data);
  }

  Future<RuntimeDevice> updateDevice(String token, String deviceId,
      {String? name}) async {
    final response = await _client.patch(
      Uri.parse('$_httpUrl/api/runtime/devices/$deviceId'),
      headers: _headers(token),
      body: jsonEncode({
        if (name != null) 'name': name,
      }),
    );
    if (response.statusCode != 200) {
      _throwError(response, '更新设备配置失败');
    }
    final data = jsonDecode(response.body) as Map<String, dynamic>;
    return RuntimeDevice.fromJson(data);
  }

  Future<RuntimeTerminal> updateTerminalTitle(
    String token,
    String deviceId,
    String terminalId,
    String title,
  ) async {
    final response = await _client.patch(
      Uri.parse(
          '$_httpUrl/api/runtime/devices/$deviceId/terminals/$terminalId'),
      headers: _headers(token),
      body: jsonEncode({'title': title}),
    );
    if (response.statusCode != 200) {
      _throwError(response, '更新终端标题失败');
    }
    final data = jsonDecode(response.body) as Map<String, dynamic>;
    return RuntimeTerminal.fromJson(data);
  }

  Future<ProjectContextSettings> getProjectContextSettings(
    String token,
    String deviceId,
  ) async {
    final response = await _client.get(
      Uri.parse(
          '$_httpUrl/api/runtime/devices/$deviceId/project-context/settings'),
      headers: _headers(token),
    );
    if (response.statusCode != 200) {
      _throwError(response, '加载项目来源配置失败');
    }
    final data = jsonDecode(response.body) as Map<String, dynamic>;
    return ProjectContextSettings.fromJson(data);
  }

  Future<ProjectContextSettings> saveProjectContextSettings(
    String token,
    String deviceId,
    ProjectContextSettings settings,
  ) async {
    final response = await _client.put(
      Uri.parse(
          '$_httpUrl/api/runtime/devices/$deviceId/project-context/settings'),
      headers: _headers(token),
      body: jsonEncode({
        'pinned_projects':
            settings.pinnedProjects.map((item) => item.toJson()).toList(),
        'approved_scan_roots':
            settings.approvedScanRoots.map((item) => item.toJson()).toList(),
        'planner_config': settings.plannerConfig.toJson(),
      }),
    );
    if (response.statusCode != 200) {
      _throwError(response, '保存项目来源配置失败');
    }
    final data = jsonDecode(response.body) as Map<String, dynamic>;
    return ProjectContextSettings.fromJson(data);
  }

  Future<DeviceProjectContextSnapshot> getProjectContextSnapshot(
    String token,
    String deviceId,
  ) async {
    final response = await _client.get(
      Uri.parse('$_httpUrl/api/runtime/devices/$deviceId/project-context'),
      headers: _headers(token),
    );
    if (response.statusCode != 200) {
      _throwError(response, '加载项目候选失败');
    }
    final data = jsonDecode(response.body) as Map<String, dynamic>;
    return DeviceProjectContextSnapshot.fromJson(data);
  }

  Future<DeviceProjectContextSnapshot> refreshProjectContextSnapshot(
    String token,
    String deviceId,
  ) async {
    final response = await _client.post(
      Uri.parse(
          '$_httpUrl/api/runtime/devices/$deviceId/project-context:refresh'),
      headers: _headers(token),
    );
    if (response.statusCode != 200) {
      _throwError(response, '刷新项目候选失败');
    }
    final data = jsonDecode(response.body) as Map<String, dynamic>;
    return DeviceProjectContextSnapshot.fromJson(data);
  }

  Future<AssistantPlanResult> createAssistantPlan(
    String token,
    String deviceId, {
    required String intent,
    required String conversationId,
    required String messageId,
    bool allowClaudeCli = true,
    bool allowLocalRules = true,
  }) async {
    final response = await _client.post(
      Uri.parse('$_httpUrl/api/runtime/devices/$deviceId/assistant/plan'),
      headers: _headers(token),
      body: jsonEncode({
        'intent': intent,
        'conversation_id': conversationId,
        'message_id': messageId,
        'fallback_policy': {
          'allow_claude_cli': allowClaudeCli,
          'allow_local_rules': allowLocalRules,
        },
      }),
    );
    if (response.statusCode != 200) {
      _throwError(response, '智能规划失败');
    }
    final data = jsonDecode(response.body) as Map<String, dynamic>;
    return AssistantPlanResult.fromJson(data);
  }

  Future<AssistantPlanResult> createAssistantPlanStream(
    String token,
    String deviceId, {
    required String intent,
    required String conversationId,
    required String messageId,
    bool allowClaudeCli = true,
    bool allowLocalRules = true,
    void Function(AssistantPlanProgressEvent event)? onProgress,
  }) async {
    final request = http.Request(
      'POST',
      Uri.parse(
          '$_httpUrl/api/runtime/devices/$deviceId/assistant/plan/stream'),
    )
      ..headers.addAll(_headers(token))
      ..body = jsonEncode({
        'intent': intent,
        'conversation_id': conversationId,
        'message_id': messageId,
        'fallback_policy': {
          'allow_claude_cli': allowClaudeCli,
          'allow_local_rules': allowLocalRules,
        },
      });

    final response = await _client.send(request);
    if (response.statusCode != 200) {
      final body = await response.stream.bytesToString();
      _throwError(
        http.Response(
          body,
          response.statusCode,
          headers: response.headers,
          request: request,
        ),
        '智能规划失败',
      );
    }

    AssistantPlanResult? result;
    await for (final line in response.stream
        .transform(utf8.decoder)
        .transform(const LineSplitter())) {
      final trimmed = line.trim();
      if (trimmed.isEmpty) {
        continue;
      }
      final data = jsonDecode(trimmed) as Map<String, dynamic>;
      final event = AssistantPlanProgressEvent.fromJson(data);
      switch (event.type) {
        case 'assistant_message':
        case 'assistant_delta':
        case 'trace':
        case 'trace_item':
        case 'tool_call':
        case 'tool_result':
        case 'status':
        case 'status_update':
          onProgress?.call(event);
          break;
        case 'error':
          throw RuntimeApiException(
            statusCode: 502,
            message: event.message ?? '智能规划流执行失败',
            reason: event.reason,
            retryAfter: event.retryAfter,
          );
        case 'result':
          result = event.result;
          break;
        default:
          break;
      }
    }

    if (result != null) {
      return result;
    }
    throw RuntimeApiException(
      statusCode: 502,
      message: '智能规划流未返回最终结果',
    );
  }

  Future<void> reportAssistantExecution(
    String token,
    String deviceId, {
    required String conversationId,
    required String messageId,
    String? terminalId,
    required String executionStatus,
    String? failedStepId,
    String? outputSummary,
    required AssistantCommandSequence commandSequence,
  }) async {
    final response = await _client.post(
      Uri.parse(
        '$_httpUrl/api/runtime/devices/$deviceId/assistant/executions/report',
      ),
      headers: _headers(token),
      body: jsonEncode({
        'conversation_id': conversationId,
        'message_id': messageId,
        'terminal_id': terminalId,
        'execution_status': executionStatus,
        'failed_step_id': failedStepId,
        'output_summary': outputSummary,
        'command_sequence': commandSequence.toJson(),
      }),
    );
    if (response.statusCode != 200) {
      _throwError(response, '同步执行结果失败');
    }
  }

  void dispose() {
    _client.close();
  }
}
