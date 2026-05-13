import 'dart:convert';

import 'api_service_base.dart';
import '../utils/json_helpers.dart' show readIntFromJson, readStringFromJson;

class UsageSummaryException implements Exception {
  const UsageSummaryException({
    required this.message,
    this.statusCode,
  });

  final String message;
  final int? statusCode;

  @override
  String toString() => message;
}

class UsageSummaryScope {
  const UsageSummaryScope({
    required this.totalSessions,
    required this.totalInputTokens,
    required this.totalOutputTokens,
    required this.totalTokens,
    required this.totalRequests,
    required this.latestModelName,
  });

  const UsageSummaryScope.empty()
      : totalSessions = 0,
        totalInputTokens = 0,
        totalOutputTokens = 0,
        totalTokens = 0,
        totalRequests = 0,
        latestModelName = '';

  final int totalSessions;
  final int totalInputTokens;
  final int totalOutputTokens;
  final int totalTokens;
  final int totalRequests;
  final String latestModelName;

  factory UsageSummaryScope.fromJson(Map<String, dynamic>? json) {
    if (json == null) {
      return const UsageSummaryScope.empty();
    }
    return UsageSummaryScope(
      totalSessions: readIntFromJson(json['total_sessions']),
      totalInputTokens: readIntFromJson(json['total_input_tokens']),
      totalOutputTokens: readIntFromJson(json['total_output_tokens']),
      totalTokens: readIntFromJson(json['total_tokens']),
      totalRequests: readIntFromJson(json['total_requests']),
      latestModelName: readStringFromJson(json['latest_model_name']),
    );
  }
}

class UsageSummaryData {
  const UsageSummaryData({
    required this.device,
    required this.user,
    this.terminal,
  });

  const UsageSummaryData.empty()
      : device = const UsageSummaryScope.empty(),
        user = const UsageSummaryScope.empty(),
        terminal = null;

  final UsageSummaryScope device;
  final UsageSummaryScope user;

  /// 终端维度的 usage scope（仅当请求包含 terminal_id 时返回）
  final UsageSummaryScope? terminal;

  factory UsageSummaryData.fromJson(Map<String, dynamic> json) {
    return UsageSummaryData(
      device:
          UsageSummaryScope.fromJson(json['device'] as Map<String, dynamic>?),
      user: UsageSummaryScope.fromJson(json['user'] as Map<String, dynamic>?),
      terminal: json.containsKey('terminal')
          ? UsageSummaryScope.fromJson(
              json['terminal'] as Map<String, dynamic>?)
          : null,
    );
  }
}

class UsageSummaryService extends ApiServiceBase {
  UsageSummaryService({
    required super.serverUrl,
    super.client,
  });

  Future<UsageSummaryData> fetchSummary({
    required String token,
    required String deviceId,
    String? terminalId,
  }) async {
    final queryParams = <String, String>{'device_id': deviceId};
    if (terminalId != null && terminalId.isNotEmpty) {
      queryParams['terminal_id'] = terminalId;
    }
    final uri = Uri.parse('$httpUrl/api/agent/usage/summary').replace(
      queryParameters: queryParams,
    );
    final response = await client.get(
      uri,
      headers: authHeaders(token),
    );
    if (response.statusCode != 200) {
      throw UsageSummaryException(
        message: readErrorMessage(response) ?? '加载 Token 汇总失败 (${response.statusCode})',
        statusCode: response.statusCode,
      );
    }
    final data = jsonDecode(response.body) as Map<String, dynamic>;
    return UsageSummaryData.fromJson(data);
  }
}
