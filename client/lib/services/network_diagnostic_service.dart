import 'dart:convert';
import 'dart:io';
import 'package:flutter/foundation.dart';

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

  static const String _productionHost = 'xiaolutang.top';
  static const String _productionSubdomain = 'rc.xiaolutang.top';
  static const String _productionIp = '';

  Future<NetworkDiagnosticReport> run({
    required String serverUrl,
    String? username,
    String? password,
  }) async {
    final httpUrl = _getHttpUrl(serverUrl);
    final uri = Uri.parse(httpUrl);

    // 基础检查：并行执行（DNS + 域名 health x2）
    final baseResults = await Future.wait([
      _dnsLookup(uri.host),
      _domainHealth(uri),
      _domainHealthDirect(uri),
    ]);

    final checks = <NetworkDiagnosticCheck>[...baseResults];

    // 生产环境额外检查：并行执行（IP health + 域名 login + IP login）
    if (_isProductionHost(uri.host)) {
      final prodFutures = <Future<NetworkDiagnosticCheck>>[
        _ipHealthWithHost(uri),
      ];
      if ((username ?? '').isNotEmpty && (password ?? '').isNotEmpty) {
        prodFutures.add(_domainLogin(uri, username!, password!));
        prodFutures.add(_ipLoginWithHost(uri, username, password));
      }
      checks.addAll(await Future.wait(prodFutures));
    }

    final report = NetworkDiagnosticReport(
      serverUrl: serverUrl,
      httpUrl: httpUrl,
      checks: checks,
    );
    _logReport(report);
    return report;
  }

  String _getHttpUrl(String serverUrl) {
    if (serverUrl.startsWith('ws://')) {
      return serverUrl.replaceFirst('ws://', 'http://');
    }
    if (serverUrl.startsWith('wss://')) {
      return serverUrl.replaceFirst('wss://', 'https://');
    }
    return serverUrl;
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

  Future<NetworkDiagnosticCheck> _domainHealth(Uri baseUri) async {
    final uri = baseUri.replace(path: '${baseUri.path}/health');
    return _healthCheck(
      title: '域名 health',
      uri: uri,
      useSystemProxy: true,
      trustAllCertificates: false,
    );
  }

  Future<NetworkDiagnosticCheck> _domainHealthDirect(Uri baseUri) async {
    final uri = baseUri.replace(path: '${baseUri.path}/health');
    return _healthCheck(
      title: '域名 health (DIRECT)',
      uri: uri,
      useSystemProxy: false,
      trustAllCertificates: false,
    );
  }

  Future<NetworkDiagnosticCheck> _ipHealthWithHost(Uri baseUri) async {
    final uri = Uri.parse('https://$_productionIp${baseUri.path}/health');
    return _healthCheck(
      title: 'IP + Host health',
      uri: uri,
      useSystemProxy: false,
      trustAllCertificates: true,
      hostHeader: baseUri.host,
    );
  }

  Future<NetworkDiagnosticCheck> _domainLogin(
    Uri baseUri,
    String username,
    String password,
  ) async {
    final uri = baseUri.replace(path: '${baseUri.path}/api/login');
    return _postJsonCheck(
      title: '域名 login',
      uri: uri,
      useSystemProxy: true,
      trustAllCertificates: false,
      body: {
        'username': username,
        'password': password,
        'view': 'mobile',
      },
    );
  }

  Future<NetworkDiagnosticCheck> _ipLoginWithHost(
    Uri baseUri,
    String username,
    String password,
  ) async {
    final uri = Uri.parse('https://$_productionIp${baseUri.path}/api/login');
    return _postJsonCheck(
      title: 'IP + Host login',
      uri: uri,
      useSystemProxy: false,
      trustAllCertificates: true,
      hostHeader: baseUri.host,
      body: {
        'username': username,
        'password': password,
        'view': 'mobile',
      },
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
      return NetworkDiagnosticCheck(title: title, success: false, detail: e.toString());
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
      return NetworkDiagnosticCheck(title: title, success: false, detail: e.toString());
    } finally {
      client.close(force: true);
    }
  }

  String _encodeJson(Map<String, dynamic> body) {
    return jsonEncode(body);
  }

  bool _isProductionHost(String host) {
    return host == _productionHost || host == _productionSubdomain;
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

  NetworkDiagnosticCheck _buildCheck(String title, int statusCode, String body) {
    final success = statusCode >= 200 && statusCode < 300;
    final compactBody = body.length > 120 ? '${body.substring(0, 120)}...' : body;
    return NetworkDiagnosticCheck(
      title: title,
      success: success,
      detail: 'HTTP $statusCode $compactBody',
    );
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
