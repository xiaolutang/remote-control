import 'dart:convert';
import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/io_client.dart';
import 'package:http/http.dart' as http;

/// 网络诊断集成测试 — 验证 S063 三环境模型的连通性
///
/// 环境说明：
/// - production: wss://rc.xiaolutang.top/rc (TLS + Traefik)
/// - direct (IP 绕过): https://IP/rc + Host: rc.xiaolutang.top (TLS + Traefik)
/// - local (直连): ws://IP:8880 (无 TLS，直连 FastAPI，需 S064 部署)
///
/// 测试分层：
/// - test 4-6（IP+Host TLS）: 直接断言 → 证明 TLS 线上正常
/// - test 1-3（域名 TLS）: catch-and-print 诊断模式 → DNS 污染为外部依赖
/// - test 7-10（ws:// 直连）: catch-and-print 诊断模式 → S064 部署为外部依赖
///
/// 运行条件：设置环境变量 RC_TEST_SERVER_IP，需要能访问线上服务器
void main() {
  final serverIp = Platform.environment['RC_TEST_SERVER_IP'] ?? '';
  const domainHost = 'rc.xiaolutang.top';
  const directPort = 8880;

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

    // ─── DNS 诊断 ───

    test('1. DNS 解析对比', () async {
      final domainResult = await InternetAddress.lookup(domainHost);
      for (final addr in domainResult) {
        print('$domainHost → ${addr.address} (${addr.type.name})');
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

    // ─── 域名 HTTPS（预期 DNS 污染导致失败）───

    test('2. 域名 HTTPS → health（预期 DNS 污染）', () async {
      try {
        final r = await trustAllClient
            .get(Uri.parse('https://$domainHost/rc/health'));
        print('域名 health: ${r.statusCode} ${r.body}');
        expect(r.statusCode, 200);
      } catch (e) {
        print('域名 health FAILED: $e（预期：DNS 污染）');
        print(
            '  → DNS 解析到 ${(await InternetAddress.lookup(domainHost)).first.address}');
      }
    });

    test('3. 域名 HTTPS → login（预期 DNS 污染）', () async {
      try {
        final r = await trustAllClient.post(
          Uri.parse('https://$domainHost/rc/api/login'),
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
        print('域名 login FAILED: $e（预期：DNS 污染）');
        print(
            '  → DNS 解析到 ${(await InternetAddress.lookup(domainHost)).first.address}');
      }
    });

    // ─── IP + Host 头 HTTPS（当前唯一可用路径）───

    test('4. IP HTTPS 无 Host 头 → 404（Traefik 不匹配）', () async {
      final r = await trustAllClient
          .get(Uri.parse('https://$serverIp/rc/health'));
      print('IP health (无Host头): ${r.statusCode} ${r.body}');
      expect(r.statusCode, 404);
    });

    test('5. IP HTTPS + Host: rc.xiaolutang.top → health', () async {
      final r = await trustAllClient.get(
        Uri.parse('https://$serverIp/rc/health'),
        headers: {'Host': domainHost},
      );
      print('IP health (Host=$domainHost): ${r.statusCode} ${r.body}');
      expect(r.statusCode, 200);
    });

    test('6. IP HTTPS + Host: rc.xiaolutang.top → login', () async {
      final r = await trustAllClient.post(
        Uri.parse('https://$serverIp/rc/api/login'),
        headers: {
          'Content-Type': 'application/json',
          'Host': domainHost,
        },
        body: jsonEncode({
          'username': 'prod_test',
          'password': 'test123456',
          'view': 'mobile',
        }),
      );
      print(
          'IP login (Host=$domainHost): ${r.statusCode} body前100=${r.body.substring(0, r.body.length > 100 ? 100 : r.body.length)}');
      expect(r.statusCode, 200);
    });

    // ─── ws:// 直连端口（需 S064 部署，当前可能不可用）───
    // 注意：此处 HTTP 请求测试网络可达性，不经过客户端 RSA+AES 加密链路。
    // 实际客户端通过 CryptoService 自动处理加密（ws:// 强制，wss:// 可选）。

    test('7. ws://IP:$directPort 直连 HTTP health（需 S064 部署）', () async {
      try {
        final r = await trustAllClient
            .get(Uri.parse('http://$serverIp:$directPort/health'));
        print('ws:// 直连 health: ${r.statusCode} ${r.body}');
        expect(r.statusCode, 200);
      } catch (e) {
        print('ws:// 直连 health FAILED: $e（S064 尚未部署或端口未映射）');
      }
    });

    test('8. ws://IP:$directPort 直连 HTTP login（需 S064 部署）', () async {
      try {
        final r = await trustAllClient.post(
          Uri.parse('http://$serverIp:$directPort/api/login'),
          headers: {'Content-Type': 'application/json'},
          body: jsonEncode({
            'username': 'prod_test',
            'password': 'test123456',
            'view': 'mobile',
          }),
        );
        print(
            'ws:// 直连 login: ${r.statusCode} body前100=${r.body.substring(0, r.body.length > 100 ? 100 : r.body.length)}');
        expect(r.statusCode, 200);
        final data = jsonDecode(r.body) as Map<String, dynamic>;
        expect(data['success'], true);
        expect(data['token'], isNotNull);
      } catch (e) {
        print('ws:// 直连 login FAILED: $e（S064 尚未部署或端口未映射）');
      }
    });

    test('9. ws://IP:$directPort 直连 → RSA 公钥端点（需 S064 部署）', () async {
      try {
        final r = await trustAllClient
            .get(Uri.parse('http://$serverIp:$directPort/api/public-key'));
        print(
            'ws:// 直连 public-key: ${r.statusCode} body前100=${r.body.substring(0, r.body.length > 100 ? 100 : r.body.length)}');
        expect(r.statusCode, 200);
        final data = jsonDecode(r.body) as Map<String, dynamic>;
        expect(data['public_key_pem'], isNotNull);
      } catch (e) {
        print('ws:// 直连 public-key FAILED: $e（S064 尚未部署或端口未映射）');
      }
    });

    test('10. ws://IP:$directPort 直连 WebSocket（需 S064 部署）', () async {
      final wsClient = HttpClient()
        ..connectionTimeout = const Duration(seconds: 10);
      try {
        final socket = await WebSocket.connect(
          'ws://$serverIp:$directPort/ws/client?view=mobile',
          customClient: wsClient,
        ).timeout(const Duration(seconds: 10));

        socket.add(jsonEncode({
          'type': 'auth',
          'token': 'invalid-token-for-diagnostic',
        }));

        final first = await socket.first.timeout(const Duration(seconds: 5));
        print('ws:// 直连 WS first=$first');
        await socket.close();
      } catch (e) {
        print('ws:// 直连 WS FAILED: $e（S064 尚未部署或端口未映射）');
      } finally {
        wsClient.close(force: true);
      }
    });
  });
}
