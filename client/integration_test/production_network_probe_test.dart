// ignore_for_file: avoid_print

import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:http/io_client.dart';
import 'package:http/http.dart' as http;

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  group('Production network probe', () {
    const domainBase = 'https://rc.xiaolutang.top/rc';
    const ipBase = 'https://${RC_TEST_SERVER_IP}/rc';
    const domainWsBase = 'wss://rc.xiaolutang.top/rc';
    const ipWsBase = 'wss://${RC_TEST_SERVER_IP}/rc';
    const host = 'rc.xiaolutang.top';
    const username = 'prod_test';
    const password = 'test123456';

    late HttpClient rawClient;
    late http.Client httpClient;

    setUp(() {
      rawClient = HttpClient()..connectionTimeout = const Duration(seconds: 10);
      rawClient.badCertificateCallback = (_, __, ___) => true;
      httpClient = IOClient(rawClient);
    });

    tearDown(() {
      httpClient.close();
      rawClient.close(force: true);
    });

    testWidgets('probe domain vs ip+host login paths', (_) async {
      final dns = await InternetAddress.lookup(host);
      print('PROBE dns=$host -> ${dns.map((e) => e.address).join(",")}');

      await _probeHealth(
        label: 'domain-health-http-package',
        client: httpClient,
        uri: Uri.parse('$domainBase/health')
            .replace(queryParameters: {'probe': 'domain-health-http'}),
      );

      await _probeLogin(
        label: 'domain-login-http-package',
        client: httpClient,
        uri: Uri.parse('$domainBase/api/login')
            .replace(queryParameters: {'probe': 'domain-login-http'}),
      );

      await _probeHealthRaw(
        label: 'domain-health-raw-direct',
        uri: Uri.parse('$domainBase/health')
            .replace(queryParameters: {'probe': 'domain-health-raw'}),
        useSystemProxy: false,
      );

      await _probeLoginRaw(
        label: 'domain-login-raw-direct',
        uri: Uri.parse('$domainBase/api/login')
            .replace(queryParameters: {'probe': 'domain-login-raw'}),
        username: username,
        password: password,
        useSystemProxy: false,
      );

      await _probeHealth(
        label: 'ip-host-health-http-package',
        client: httpClient,
        uri: Uri.parse('$ipBase/health')
            .replace(queryParameters: {'probe': 'ip-health-http'}),
        headers: {'Host': host},
      );

      await _probeLogin(
        label: 'ip-host-login-http-package',
        client: httpClient,
        uri: Uri.parse('$ipBase/api/login')
            .replace(queryParameters: {'probe': 'ip-login-http'}),
        headers: {'Host': host},
      );

      await _probeHealthRaw(
        label: 'ip-host-health-raw-direct',
        uri: Uri.parse('$ipBase/health')
            .replace(queryParameters: {'probe': 'ip-health-raw'}),
        hostHeader: host,
        useSystemProxy: false,
      );

      await _probeLoginRaw(
        label: 'ip-host-login-raw-direct',
        uri: Uri.parse('$ipBase/api/login')
            .replace(queryParameters: {'probe': 'ip-login-raw'}),
        username: username,
        password: password,
        hostHeader: host,
        useSystemProxy: false,
      );

      final session = await _loginForWsSession(
        uri: Uri.parse('$ipBase/api/login')
            .replace(queryParameters: {'probe': 'ws-session-login'}),
        hostHeader: host,
        username: username,
        password: password,
      );

      if (session != null) {
        await _probeWebSocket(
          label: 'domain-ws-direct',
          uri: Uri.parse('$domainWsBase/ws/client').replace(
            queryParameters: {
              'session_id': session['session_id']!,
              'view': 'mobile',
              'probe': 'domain-ws',
            },
          ),
          token: session['token']!,
          useSystemProxy: false,
        );

        await _probeWebSocket(
          label: 'ip-host-ws-direct',
          uri: Uri.parse('$ipWsBase/ws/client').replace(
            queryParameters: {
              'session_id': session['session_id']!,
              'view': 'mobile',
              'probe': 'ip-ws',
            },
          ),
          token: session['token']!,
          hostHeader: host,
          useSystemProxy: false,
        );
      } else {
        print('PROBE ws skipped: failed to obtain session token');
      }

      expect(true, isTrue);
    });
  });
}

Future<void> _probeHealth({
  required String label,
  required http.Client client,
  required Uri uri,
  Map<String, String>? headers,
}) async {
  try {
    final response = await client.get(uri, headers: headers);
    print(
        'PROBE $label status=${response.statusCode} body=${_compact(response.body)}');
  } catch (e) {
    print('PROBE $label error=$e');
  }
}

Future<void> _probeLogin({
  required String label,
  required http.Client client,
  required Uri uri,
  Map<String, String>? headers,
}) async {
  try {
    final response = await client.post(
      uri,
      headers: {
        HttpHeaders.contentTypeHeader: 'application/json',
        ...?headers,
      },
      body: jsonEncode({
        'username': 'prod_test',
        'password': 'test123456',
        'view': 'mobile',
      }),
    );
    print(
        'PROBE $label status=${response.statusCode} body=${_compact(response.body)}');
  } catch (e) {
    print('PROBE $label error=$e');
  }
}

Future<void> _probeHealthRaw({
  required String label,
  required Uri uri,
  required bool useSystemProxy,
  String? hostHeader,
}) async {
  final client = HttpClient()..connectionTimeout = const Duration(seconds: 10);
  client.badCertificateCallback = (_, __, ___) => true;
  client.findProxy =
      useSystemProxy ? HttpClient.findProxyFromEnvironment : (_) => 'DIRECT';
  try {
    final request = await client.getUrl(uri);
    request.persistentConnection = false;
    if (hostHeader != null) {
      request.headers.set(HttpHeaders.hostHeader, hostHeader);
    }
    final response = await request.close();
    final body = await response.transform(SystemEncoding().decoder).join();
    print('PROBE $label status=${response.statusCode} body=${_compact(body)}');
  } catch (e) {
    print('PROBE $label error=$e');
  } finally {
    client.close(force: true);
  }
}

Future<void> _probeLoginRaw({
  required String label,
  required Uri uri,
  required String username,
  required String password,
  required bool useSystemProxy,
  String? hostHeader,
}) async {
  final client = HttpClient()..connectionTimeout = const Duration(seconds: 10);
  client.badCertificateCallback = (_, __, ___) => true;
  client.findProxy =
      useSystemProxy ? HttpClient.findProxyFromEnvironment : (_) => 'DIRECT';
  try {
    final request = await client.postUrl(uri);
    request.persistentConnection = false;
    request.headers.set(HttpHeaders.contentTypeHeader, 'application/json');
    if (hostHeader != null) {
      request.headers.set(HttpHeaders.hostHeader, hostHeader);
    }
    request.write(jsonEncode({
      'username': username,
      'password': password,
      'view': 'mobile',
    }));
    final response = await request.close();
    final body = await response.transform(SystemEncoding().decoder).join();
    print('PROBE $label status=${response.statusCode} body=${_compact(body)}');
  } catch (e) {
    print('PROBE $label error=$e');
  } finally {
    client.close(force: true);
  }
}

String _compact(String text) {
  final normalized = text.replaceAll('\n', ' ');
  if (normalized.length <= 160) {
    return normalized;
  }
  return '${normalized.substring(0, 160)}...';
}

Future<Map<String, String>?> _loginForWsSession({
  required Uri uri,
  required String username,
  required String password,
  String? hostHeader,
}) async {
  final client = HttpClient()..connectionTimeout = const Duration(seconds: 10);
  client.badCertificateCallback = (_, __, ___) => true;
  client.findProxy = (_) => 'DIRECT';
  try {
    final request = await client.postUrl(uri);
    request.persistentConnection = false;
    request.headers.set(HttpHeaders.contentTypeHeader, 'application/json');
    if (hostHeader != null) {
      request.headers.set(HttpHeaders.hostHeader, hostHeader);
    }
    request.write(jsonEncode({
      'username': username,
      'password': password,
      'view': 'mobile',
    }));
    final response = await request.close();
    final body = await response.transform(SystemEncoding().decoder).join();
    if (response.statusCode != 200) {
      print(
        'PROBE ws-session-login status=${response.statusCode} body=${_compact(body)}',
      );
      return null;
    }
    final data = jsonDecode(body) as Map<String, dynamic>;
    final sessionId = data['session_id']?.toString();
    final token = data['token']?.toString();
    if (sessionId == null || token == null) {
      print(
          'PROBE ws-session-login missing session_id/token body=${_compact(body)}');
      return null;
    }
    print('PROBE ws-session-login status=200 session_id=$sessionId');
    return {
      'session_id': sessionId,
      'token': token,
    };
  } catch (e) {
    print('PROBE ws-session-login error=$e');
    return null;
  } finally {
    client.close(force: true);
  }
}

Future<void> _probeWebSocket({
  required String label,
  required Uri uri,
  required String token,
  required bool useSystemProxy,
  String? hostHeader,
}) async {
  final client = HttpClient()..connectionTimeout = const Duration(seconds: 10);
  client.badCertificateCallback = (_, __, ___) => true;
  client.findProxy =
      useSystemProxy ? HttpClient.findProxyFromEnvironment : (_) => 'DIRECT';

  try {
    final socket = await WebSocket.connect(
      uri.toString(),
      headers: hostHeader == null ? null : {HttpHeaders.hostHeader: hostHeader},
      customClient: client,
    ).timeout(const Duration(seconds: 10));

    socket.add(jsonEncode({
      'type': 'auth',
      'token': token,
    }));

    final first = await socket.first.timeout(
      const Duration(seconds: 10),
    );
    print('PROBE $label first=${_compact(first.toString())}');
    await socket.close();
  } catch (e) {
    print('PROBE $label error=$e');
  } finally {
    client.close(force: true);
  }
}
