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
  static const String _productionIp = '${RC_TEST_SERVER_IP}';

  Future<NetworkDiagnosticReport> run({
    required String serverUrl,
    String? username,
    String? password,
  }) async {
    final httpUrl = _getHttpUrl(serverUrl);
    final uri = Uri.parse(httpUrl);
    final checks = <NetworkDiagnosticCheck>[];

    checks.add(await _dnsLookup(uri.host));
    checks.add(await _domainHealth(uri));
    checks.add(await _domainHealthDirect(uri));

    if (_isProductionHost(uri.host)) {
      checks.add(await _ipHealthWithHost(uri));
      if ((username ?? '').isNotEmpty && (password ?? '').isNotEmpty) {
        checks.add(await _domainLogin(uri, username!, password!));
        checks.add(await _ipLoginWithHost(uri, username, password));
      }
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
    final client = HttpClient()
      ..connectionTimeout = const Duration(seconds: 10);
    if (!useSystemProxy) {
      client.findProxy = (_) => 'DIRECT';
    } else {
      client.findProxy = HttpClient.findProxyFromEnvironment;
    }
    if (trustAllCertificates) {
      client.badCertificateCallback = (_, __, ___) => true;
    }

    try {
      final request = await client.getUrl(uri);
      if (hostHeader != null) {
        request.headers.set(HttpHeaders.hostHeader, hostHeader);
      }
      final response = await request.close();
      final body = await response.transform(SystemEncoding().decoder).join();
      final success = response.statusCode >= 200 && response.statusCode < 300;
      final compactBody =
          body.length > 120 ? '${body.substring(0, 120)}...' : body;
      return NetworkDiagnosticCheck(
        title: title,
        success: success,
        detail: 'HTTP ${response.statusCode} $compactBody',
      );
    } catch (e) {
      return NetworkDiagnosticCheck(
        title: title,
        success: false,
        detail: e.toString(),
      );
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
    final client = HttpClient()
      ..connectionTimeout = const Duration(seconds: 10);
    if (!useSystemProxy) {
      client.findProxy = (_) => 'DIRECT';
    } else {
      client.findProxy = HttpClient.findProxyFromEnvironment;
    }
    if (trustAllCertificates) {
      client.badCertificateCallback = (_, __, ___) => true;
    }

    try {
      final request = await client.postUrl(uri);
      request.headers.set(HttpHeaders.contentTypeHeader, 'application/json');
      if (hostHeader != null) {
        request.headers.set(HttpHeaders.hostHeader, hostHeader);
      }
      request.write(_encodeJson(body));
      final response = await request.close();
      final text = await response.transform(SystemEncoding().decoder).join();
      final success = response.statusCode >= 200 && response.statusCode < 300;
      final compactBody =
          text.length > 120 ? '${text.substring(0, 120)}...' : text;
      return NetworkDiagnosticCheck(
        title: title,
        success: success,
        detail: 'HTTP ${response.statusCode} $compactBody',
      );
    } catch (e) {
      return NetworkDiagnosticCheck(
        title: title,
        success: false,
        detail: e.toString(),
      );
    } finally {
      client.close(force: true);
    }
  }

  String _encodeJson(Map<String, dynamic> body) {
    final entries = body.entries
        .map((e) => '"${e.key}":"${_escapeJson(e.value.toString())}"')
        .join(',');
    return '{$entries}';
  }

  String _escapeJson(String input) {
    return input
        .replaceAll('\\', '\\\\')
        .replaceAll('"', '\\"')
        .replaceAll('\n', '\\n')
        .replaceAll('\r', '\\r');
  }

  bool _isProductionHost(String host) {
    return host == _productionHost || host == _productionSubdomain;
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
