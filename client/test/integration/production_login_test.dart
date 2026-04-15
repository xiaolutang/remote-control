import 'dart:convert';
import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/io_client.dart';
import 'package:http/http.dart' as http;

void main() {
  group('Production environment integration test', () {
    late http.Client client;

    setUp(() {
      // 模拟 HttpClientFactory.create() — Debug 模式信任自签证书
      final httpClient = HttpClient();
      httpClient.badCertificateCallback = (_, __, ___) => true;
      httpClient.connectionTimeout = const Duration(seconds: 15);
      client = IOClient(httpClient);
    });

    tearDown(() {
      client.close();
    });

    /// 模拟 AuthService._getHttpUrl()
    String getHttpUrl(String wsUrl) {
      if (wsUrl.startsWith('wss://')) {
        return wsUrl.replaceFirst('wss://', 'https://');
      } else if (wsUrl.startsWith('ws://')) {
        return wsUrl.replaceFirst('ws://', 'http://');
      }
      return wsUrl;
    }

    test('Local environment: wss://localhost/rc → login', () async {
      const wsUrl = 'wss://localhost/rc';
      final httpUrl = getHttpUrl(wsUrl);
      expect(httpUrl, 'https://localhost/rc');

      final response = await client.post(
        Uri.parse('$httpUrl/api/login'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({
          'username': 'env_test_user',
          'password': 'test123456',
          'view': 'desktop',
        }),
      );

      print('Local login: status=${response.statusCode} body=${response.body}');
      expect(response.statusCode, 200);

      final data = jsonDecode(response.body) as Map<String, dynamic>;
      expect(data['success'], true);
      expect(data['token'], isNotNull);
      expect(data['session_id'], isNotNull);
    });

    test('Production via IP+Host header: https://111.229.125.161 → login', () async {
      // Traefik 路由绑了 Host(xiaolutang.top)，IP 直连需带 Host 头
      const httpUrl = 'https://111.229.125.161/rc';

      print('Production via IP login URL: $httpUrl/api/login');

      final response = await client.post(
        Uri.parse('$httpUrl/api/login'),
        headers: {
          'Content-Type': 'application/json',
          'Host': 'xiaolutang.top',
        },
        body: jsonEncode({
          'username': 'prod_test',
          'password': 'test123456',
          'view': 'mobile',
        }),
      );

      print('Production via IP login: status=${response.statusCode} body=${response.body}');
      expect(response.statusCode, 200);

      final data = jsonDecode(response.body) as Map<String, dynamic>;
      expect(data['success'], true);
      expect(data['token'], isNotNull);
    });

    test('Production via IP+Host header: register new user', () async {
      const httpUrl = 'https://111.229.125.161/rc';
      final timestamp = DateTime.now().millisecondsSinceEpoch;

      final response = await client.post(
        Uri.parse('$httpUrl/api/register'),
        headers: {
          'Content-Type': 'application/json',
          'Host': 'xiaolutang.top',
        },
        body: jsonEncode({
          'username': 'integ_test_$timestamp',
          'password': 'Test123456',
          'view': 'mobile',
        }),
      );

      print('Production register: status=${response.statusCode} body=${response.body}');
      expect(response.statusCode, 200);

      final data = jsonDecode(response.body) as Map<String, dynamic>;
      expect(data['success'], true);
    });
  });
}
