import 'dart:convert';

import 'package:http/http.dart' as http;

import 'http_client_factory.dart';
import 'server_url_helper.dart';

/// Service 层公共基类，封装 HTTP client、URL 转换和鉴权 headers。
///
/// 子类只需关注业务逻辑，不必重复定义 serverUrl/_client/_httpUrl 和
/// auth headers 等基础设施。
abstract class ApiServiceBase {
  ApiServiceBase({
    required this.serverUrl,
    http.Client? client,
  }) : _client = client ?? HttpClientFactory.create();

  final String serverUrl;
  final http.Client _client;

  /// 暴露给子类的 HTTP client（protected 风格）。
  http.Client get client => _client;

  /// HTTP 基础 URL（ws→http 转换）。
  String get httpUrl => serverUrlToHttpBase(serverUrl);

  /// 带鉴权的 JSON headers（SSE 专用，含 Accept: text/event-stream）。
  Map<String, String> sseHeaders(String token) => {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer $token',
        'Accept': 'text/event-stream',
      };

  /// 带鉴权的 JSON headers。
  Map<String, String> authHeaders(String token) => {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer $token',
      };

  /// 通用错误响应解析。
  ///
  /// 尝试从 JSON body 中提取 `detail` 字段（String 或嵌套的 message）。
  /// 解析失败返回 null，由调用方决定 fallback 逻辑。
  String? readErrorMessage(http.Response response) {
    if (response.body.isEmpty) return null;
    try {
      final data = jsonDecode(response.body) as Map<String, dynamic>;
      final detail = data['detail'];
      if (detail is String && detail.trim().isNotEmpty) {
        return detail.trim();
      }
      if (detail is Map<String, dynamic>) {
        final message = detail['message'];
        if (message is String && message.trim().isNotEmpty) {
          return message.trim();
        }
      }
      return data['detail']?.toString();
    } catch (_) {
      return null;
    }
  }

  /// 释放 HTTP client 资源。
  void dispose() {
    _client.close();
  }
}
