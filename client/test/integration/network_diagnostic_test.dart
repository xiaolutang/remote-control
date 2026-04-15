import 'dart:convert';
import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/io_client.dart';
import 'package:http/http.dart' as http;

void main() {
  group('Network diagnostic', () {
    late http.Client trustAllClient;

    setUp(() {
      final httpClient = HttpClient();
      httpClient.badCertificateCallback = (_, __, ___) => true;
      httpClient.connectionTimeout = const Duration(seconds: 10);
      trustAllClient = IOClient(httpClient);
    });

    tearDown(() {
      trustAllClient.close();
    });

    test('1. 域名 HTTPS → health', () async {
      try {
        final r = await trustAllClient.get(Uri.parse('https://xiaolutang.top/rc/health'));
        print('域名 health: ${r.statusCode} ${r.body}');
        expect(r.statusCode, 200);
      } catch (e) {
        print('域名 health FAILED: $e');
        // 预期失败 — DNS 污染
        print('  → DNS 解析到 ${(await InternetAddress.lookup('xiaolutang.top')).first.address}');
      }
    });

    test('2. IP 直连 HTTPS (无 Host 头) → health', () async {
      try {
        final r = await trustAllClient.get(Uri.parse('https://${RC_TEST_SERVER_IP}/rc/health'));
        print('IP health (无Host头): ${r.statusCode} ${r.body}');
        // 预期 404 — Traefik Host 路由不匹配
      } catch (e) {
        print('IP health FAILED: $e');
        rethrow;
      }
    });

    test('3. IP 直连 HTTPS (带 Host 头) → health', () async {
      try {
        final r = await trustAllClient.get(
          Uri.parse('https://${RC_TEST_SERVER_IP}/rc/health'),
          headers: {'Host': 'xiaolutang.top'},
        );
        print('IP health (带Host头): ${r.statusCode} ${r.body}');
        expect(r.statusCode, 200);
      } catch (e) {
        print('IP health (带Host头) FAILED: $e');
        rethrow;
      }
    });

    test('4. IP 直连 HTTPS (带 Host 头) → login', () async {
      try {
        final r = await trustAllClient.post(
          Uri.parse('https://${RC_TEST_SERVER_IP}/rc/api/login'),
          headers: {'Content-Type': 'application/json', 'Host': 'xiaolutang.top'},
          body: jsonEncode({
            'username': 'prod_test',
            'password': 'test123456',
            'view': 'mobile',
          }),
        );
        print('IP login (带Host头): ${r.statusCode} body前100字符=${r.body.substring(0, r.body.length > 100 ? 100 : r.body.length)}');
        expect(r.statusCode, 200);
      } catch (e) {
        print('IP login (带Host头) FAILED: $e');
        rethrow;
      }
    });

    test('4. 域名 HTTPS → login', () async {
      try {
        final r = await trustAllClient.post(
          Uri.parse('https://xiaolutang.top/rc/api/login'),
          headers: {'Content-Type': 'application/json'},
          body: jsonEncode({
            'username': 'prod_test',
            'password': 'test123456',
            'view': 'mobile',
          }),
        );
        print('域名 login: ${r.statusCode} ${r.body}');
        expect(r.statusCode, 200);
      } catch (e) {
        print('域名 login FAILED: $e');
        // 预期失败 — DNS 污染
        print('  → DNS 解析到 ${(await InternetAddress.lookup('xiaolutang.top')).first.address}');
      }
    });

    test('5. 本地 HTTPS → health', () async {
      try {
        final r = await trustAllClient.get(Uri.parse('https://localhost/rc/health'));
        print('本地 health: ${r.statusCode} ${r.body}');
        expect(r.statusCode, 200);
      } catch (e) {
        print('本地 health FAILED: $e');
        rethrow;
      }
    });

    test('6. DNS 解析对比', () async {
      final domainResult = await InternetAddress.lookup('xiaolutang.top');
      for (final addr in domainResult) {
        print('xiaolutang.top → ${addr.address} (${addr.type.name})');
      }

      try {
        final localhost = await InternetAddress.lookup('localhost');
        for (final addr in localhost) {
          print('localhost → ${addr.address} (${addr.type.name})');
        }
      } catch (e) {
        print('localhost lookup FAILED: $e');
      }
    });
  });
}
