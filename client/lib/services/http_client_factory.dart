import 'dart:io' show HttpClient;
import 'package:flutter/foundation.dart';
import 'package:http/io_client.dart';
import 'package:http/http.dart' as http;

/// HTTP 客户端工厂
///
/// Debug 模式：允许自签证书（本地开发用）
/// Release 模式：严格验证证书（生产环境）
class HttpClientFactory {
  HttpClientFactory._();

  /// 创建 HTTP Client（用于 REST API 请求）
  static http.Client create() {
    final httpClient = HttpClient();
    if (kDebugMode) {
      httpClient.badCertificateCallback = (_, __, ___) => true;
    }
    return IOClient(httpClient);
  }

  /// 创建 HttpClient（用于 WebSocket 连接）
  static HttpClient createRaw() {
    final client = HttpClient();
    if (kDebugMode) {
      client.badCertificateCallback = (_, __, ___) => true;
    }
    return client;
  }
}
