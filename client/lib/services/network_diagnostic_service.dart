import 'dart:convert';
import 'dart:io';
import 'package:flutter/foundation.dart';
import '../models/server_endpoint_profile.dart';

class NetworkDiagnosticCheck {
  const NetworkDiagnosticCheck({
    required this.title,
    required this.success,
    required this.detail,
  });

  final String title;
  final bool success;
  final String detail;
}

class NetworkDiagnosticReport {
  const NetworkDiagnosticReport({
    required this.serverUrl,
    required this.httpUrl,
    required this.checks,
  });

  final String serverUrl;
  final String httpUrl;
  final List<NetworkDiagnosticCheck> checks;
}

class NetworkDiagnosticService {
  const NetworkDiagnosticService();

  Future<NetworkDiagnosticReport> run({
    required String serverUrl,
    String? username,
    String? password,
    String? view,
  }) async {
    final profile = ServerEndpointProfile.fromServerUrl(serverUrl);
    final trustSelfSigned = profile.shouldTrustSelfSignedCertificates;

    // 基础检查：并行执行（DNS + 健康检查 x2）
    final baseResults = await Future.wait([
      _dnsLookup(profile.host),
      _health(
        title: '健康检查',
        uri: profile.healthUri(),
        useSystemProxy: true,
        trustAllCertificates: trustSelfSigned,
      ),
      _health(
        title: '健康检查 (DIRECT)',
        uri: profile.healthUri(),
        useSystemProxy: false,
        trustAllCertificates: trustSelfSigned,
      ),
    ]);

    final checks = <NetworkDiagnosticCheck>[...baseResults];

    // 网关生产环境额外检查：并行执行（IP + Host health/login）
    if (profile.isProductionGateway) {
      final prodFutures = <Future<NetworkDiagnosticCheck>>[
        _ipHealthWithHost(profile),
      ];
      if ((username ?? '').isNotEmpty && (password ?? '').isNotEmpty) {
        prodFutures.add(
          _login(
            title: '登录接口',
            uri: profile.loginUri(),
            useSystemProxy: true,
            trustAllCertificates: trustSelfSigned,
            username: username!,
            password: password!,
            view: view,
          ),
        );
        prodFutures.add(
          _ipLoginWithHost(profile, username, password, view),
        );
      }
      checks.addAll(await Future.wait(prodFutures));
    }

    final report = NetworkDiagnosticReport(
      serverUrl: serverUrl,
      httpUrl: profile.httpBaseUrl,
      checks: checks,
    );
    _logReport(report);
    return report;
  }

  Future<NetworkDiagnosticCheck> _dnsLookup(String host) async {
    try {
      final addresses = await InternetAddress.lookup(host);
      final rendered = addresses.map((addr) => addr.address).join(', ');
      return NetworkDiagnosticCheck(
        title: 'DNS 解析',
        success: addresses.isNotEmpty,
        detail: rendered.isEmpty ? '未返回地址' : rendered,
      );
    } catch (e) {
      return NetworkDiagnosticCheck(
        title: 'DNS 解析',
        success: false,
        detail: e.toString(),
      );
    }
  }

  Future<NetworkDiagnosticCheck> _health({
    required String title,
    required Uri uri,
    required bool useSystemProxy,
    required bool trustAllCertificates,
    String? hostHeader,
  }) async {
    return _healthCheck(
      title: title,
      uri: uri,
      useSystemProxy: useSystemProxy,
      trustAllCertificates: trustAllCertificates,
      hostHeader: hostHeader,
    );
  }

  Future<NetworkDiagnosticCheck> _ipHealthWithHost(
    ServerEndpointProfile profile,
  ) async {
    final uri = profile.ipFallbackUriFor('health');
    if (uri == null) {
      return const NetworkDiagnosticCheck(
        title: 'IP + Host health',
        success: false,
        detail: '未配置 production fallback IP',
      );
    }
    return _health(
      title: 'IP + Host health',
      uri: uri,
      useSystemProxy: false,
      trustAllCertificates: true,
      hostHeader: profile.host,
    );
  }

  Future<NetworkDiagnosticCheck> _login({
    required String title,
    required Uri uri,
    required bool useSystemProxy,
    required bool trustAllCertificates,
    required String username,
    required String password,
    String? view,
    String? hostHeader,
  }) async {
    final body = <String, dynamic>{
      'username': username,
      'password': password,
    };
    if (view != null && view.isNotEmpty) {
      body['view'] = view;
    }
    return _postJsonCheck(
      title: title,
      uri: uri,
      useSystemProxy: useSystemProxy,
      trustAllCertificates: trustAllCertificates,
      hostHeader: hostHeader,
      body: body,
    );
  }

  Future<NetworkDiagnosticCheck> _ipLoginWithHost(
    ServerEndpointProfile profile,
    String username,
    String password,
    String? view,
  ) async {
    final uri = profile.ipFallbackUriFor('api/login');
    if (uri == null) {
      return const NetworkDiagnosticCheck(
        title: 'IP + Host login',
        success: false,
        detail: '未配置 production fallback IP',
      );
    }
    return _login(
      title: 'IP + Host login',
      uri: uri,
      useSystemProxy: false,
      trustAllCertificates: true,
      hostHeader: profile.host,
      username: username,
      password: password,
      view: view,
    );
  }

  Future<NetworkDiagnosticCheck> _healthCheck({
    required String title,
    required Uri uri,
    required bool useSystemProxy,
    required bool trustAllCertificates,
    String? hostHeader,
  }) async {
    final client = _createClient(useSystemProxy, trustAllCertificates);
    try {
      final request = await client.getUrl(uri);
      if (hostHeader != null) {
        request.headers.set(HttpHeaders.hostHeader, hostHeader);
      }
      final response = await request.close();
      final body = await response.transform(SystemEncoding().decoder).join();
      return _buildCheck(title, response.statusCode, body);
    } catch (e) {
      return NetworkDiagnosticCheck(
          title: title, success: false, detail: e.toString());
    } finally {
      client.close(force: true);
    }
  }

  Future<NetworkDiagnosticCheck> _postJsonCheck({
    required String title,
    required Uri uri,
    required bool useSystemProxy,
    required bool trustAllCertificates,
    required Map<String, dynamic> body,
    String? hostHeader,
  }) async {
    final client = _createClient(useSystemProxy, trustAllCertificates);
    try {
      final request = await client.postUrl(uri);
      request.headers.set(HttpHeaders.contentTypeHeader, 'application/json');
      if (hostHeader != null) {
        request.headers.set(HttpHeaders.hostHeader, hostHeader);
      }
      request.write(_encodeJson(body));
      final response = await request.close();
      final text = await response.transform(SystemEncoding().decoder).join();
      return _buildCheck(title, response.statusCode, text);
    } catch (e) {
      return NetworkDiagnosticCheck(
          title: title, success: false, detail: e.toString());
    } finally {
      client.close(force: true);
    }
  }

  String _encodeJson(Map<String, dynamic> body) {
    return jsonEncode(body);
  }

  HttpClient _createClient(bool useSystemProxy, bool trustAllCertificates) {
    final client = HttpClient()
      ..connectionTimeout = const Duration(seconds: 10);
    client.findProxy =
        useSystemProxy ? HttpClient.findProxyFromEnvironment : (_) => 'DIRECT';
    if (trustAllCertificates) {
      client.badCertificateCallback = (_, __, ___) => true;
    }
    return client;
  }

  NetworkDiagnosticCheck _buildCheck(
      String title, int statusCode, String body) {
    final success = _isSuccessfulResponse(statusCode, body);
    final compactBody =
        body.length > 120 ? '${body.substring(0, 120)}...' : body;
    return NetworkDiagnosticCheck(
      title: title,
      success: success,
      detail: 'HTTP $statusCode $compactBody',
    );
  }

  bool _isSuccessfulResponse(int statusCode, String body) {
    if (statusCode < 200 || statusCode >= 300) {
      return false;
    }

    final trimmed = body.trim();
    if (!trimmed.startsWith('{') || !trimmed.endsWith('}')) {
      return true;
    }

    try {
      final decoded = jsonDecode(trimmed);
      if (decoded is! Map<String, dynamic>) {
        return true;
      }
      final success = decoded['success'];
      if (success is bool) {
        return success;
      }
      final status = decoded['status'];
      if (status is String) {
        return status.toLowerCase() == 'ok';
      }
      final msg = decoded['msg'];
      if (msg is String && msg.toUpperCase().contains('NOT_FOUND')) {
        return false;
      }
    } catch (_) {
      return true;
    }

    return true;
  }

  void _logReport(NetworkDiagnosticReport report) {
    debugPrint('[NetworkDiagnostic] serverUrl=${report.serverUrl}');
    debugPrint('[NetworkDiagnostic] httpUrl=${report.httpUrl}');
    for (final check in report.checks) {
      debugPrint(
        '[NetworkDiagnostic] ${check.title} success=${check.success} detail=${check.detail}',
      );
    }
  }
}
