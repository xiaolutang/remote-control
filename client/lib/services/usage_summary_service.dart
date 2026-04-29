import 'dart:convert';

import 'package:http/http.dart' as http;

import 'http_client_factory.dart';
import 'server_url_helper.dart';

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
      totalSessions: _readInt(json['total_sessions']),
      totalInputTokens: _readInt(json['total_input_tokens']),
      totalOutputTokens: _readInt(json['total_output_tokens']),
      totalTokens: _readInt(json['total_tokens']),
      totalRequests: _readInt(json['total_requests']),
      latestModelName: (json['latest_model_name'] as String? ?? '').trim(),
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

class UsageSummaryService {
  UsageSummaryService({
    required this.serverUrl,
    http.Client? client,
  }) : _client = client ?? HttpClientFactory.create();

  final String serverUrl;
  final http.Client _client;

  String get _httpUrl => serverUrlToHttpBase(serverUrl);

  Future<UsageSummaryData> fetchSummary({
    required String token,
    required String deviceId,
    String? terminalId,
  }) async {
    final queryParams = <String, String>{'device_id': deviceId};
    if (terminalId != null && terminalId.isNotEmpty) {
      queryParams['terminal_id'] = terminalId;
    }
    final uri = Uri.parse('$_httpUrl/api/agent/usage/summary').replace(
      queryParameters: queryParams,
    );
    final response = await _client.get(
      uri,
      headers: {
        'Authorization': 'Bearer $token',
        'Content-Type': 'application/json',
      },
    );
    if (response.statusCode != 200) {
      throw UsageSummaryException(
        message: _readErrorMessage(response, '加载 Token 汇总失败'),
        statusCode: response.statusCode,
      );
    }
    final data = jsonDecode(response.body) as Map<String, dynamic>;
    return UsageSummaryData.fromJson(data);
  }

  String _readErrorMessage(http.Response response, String fallback) {
    try {
      final data = jsonDecode(response.body) as Map<String, dynamic>;
      final detail = data['detail'];
      if (detail is String && detail.trim().isNotEmpty) {
        return detail.trim();
      }
      if (detail is Map<String, dynamic>) {
        final message = (detail['message'] as String? ?? '').trim();
        if (message.isNotEmpty) {
          return message;
        }
      }
    } on FormatException {
      return '$fallback (${response.statusCode})';
    }
    return '$fallback (${response.statusCode})';
  }
}

int _readInt(Object? value) {
  if (value is int) {
    return value;
  }
  if (value is num) {
    return value.toInt();
  }
  if (value is String) {
    return int.tryParse(value) ?? 0;
  }
  return 0;
}
