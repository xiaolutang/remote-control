import 'dart:io' show HttpClient;
import 'package:flutter/foundation.dart';
import 'package:http/io_client.dart';
import 'package:http/http.dart' as http;

/// HTTP 客户端工厂
///
/// 集中管理证书信任和代理配置，所有 HttpClient 创建都应通过本工厂。
class HttpClientFactory {
  HttpClientFactory._();

  /// 创建 HTTP Client（用于 REST API 请求）
  static http.Client create() {
    return IOClient(createRaw());
  }

  /// 创建 HttpClient（用于 WebSocket 连接等需要原始 HttpClient 的场景）
  static HttpClient createRaw() {
    return _configure(HttpClient());
  }

  /// 创建可配置的原始 HttpClient。
  ///
  /// [trustAllCertificates] 为 null 时走 kDebugMode 自动判断；
  /// [useSystemProxy] 为 null 时默认使用系统代理。
  static HttpClient createRawConfigured({
    bool? trustAllCertificates,
    bool? useSystemProxy,
  }) {
    return _configure(
      HttpClient(),
      trustAllCertificates: trustAllCertificates,
      useSystemProxy: useSystemProxy,
    );
  }

  /// 统一配置 HttpClient 的证书和代理。
  static HttpClient _configure(
    HttpClient client, {
    bool? trustAllCertificates,
    bool? useSystemProxy,
  }) {
    final trust = trustAllCertificates ?? kDebugMode;
    if (trust) {
      client.badCertificateCallback = (_, __, ___) => true;
    }
    final useProxy = useSystemProxy ?? true;
    client.findProxy =
        useProxy ? HttpClient.findProxyFromEnvironment : (_) => 'DIRECT';
    return client;
  }
}
