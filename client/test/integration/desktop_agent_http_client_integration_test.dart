import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:rc_client/services/desktop/desktop_agent_http_client.dart';

/// DesktopAgentHttpClient 集成测试
///
/// 启动真实 HttpServer 模拟 Agent HTTP API，
/// 验证 client 的真实 HTTP 通信和 JSON 解析。
void main() {
  group('DesktopAgentHttpClient integration', () {
    late HttpServer server;
    late DesktopAgentHttpClient client;
    late int port;

    setUp(() async {
      server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      port = server.port;
      client = DesktopAgentHttpClient(
        timeout: const Duration(seconds: 5),
        homeDirectory:
            '/tmp/test_home_${DateTime.now().millisecondsSinceEpoch}',
      );
    });

    tearDown(() async {
      client.close();
      await server.close(force: true);
    });

    // ---- health ----

    test('checkHealth returns true for healthy agent', () async {
      server.listen((request) async {
        request.response.statusCode = 200;
        request.response.headers.contentType = ContentType.json;
        request.response.write(jsonEncode({'status': 'ok'}));
        await request.response.close();
      });

      expect(await client.checkHealth(port), isTrue);
    });

    test('checkHealth returns false for wrong status', () async {
      server.listen((request) async {
        request.response.statusCode = 200;
        request.response.headers.contentType = ContentType.json;
        request.response.write(jsonEncode({'status': 'error'}));
        await request.response.close();
      });

      expect(await client.checkHealth(port), isFalse);
    });

    test('checkHealth returns false for 500', () async {
      server.listen((request) async {
        request.response.statusCode = 500;
        await request.response.close();
      });

      expect(await client.checkHealth(port), isFalse);
    });

    // ---- status ----

    test('getStatus parses full agent status', () async {
      server.listen((request) async {
        request.response.statusCode = 200;
        request.response.headers.contentType = ContentType.json;
        request.response.write(jsonEncode({
          'running': true,
          'pid': 12345,
          'port': port,
          'server_url': 'wss://example.com',
          'connected': true,
          'session_id': 'session-abc',
          'terminals_count': 3,
          'keep_running_in_background': true,
        }));
        await request.response.close();
      });

      final status = await client.getStatus(port);
      expect(status, isNotNull);
      expect(status!.running, isTrue);
      expect(status.pid, 12345);
      expect(status.port, port);
      expect(status.connected, isTrue);
      expect(status.terminalsCount, 3);
    });

    test('getStatus returns null for 404', () async {
      server.listen((request) async {
        request.response.statusCode = 404;
        await request.response.close();
      });

      expect(await client.getStatus(port), isNull);
    });

    // ---- stop ----

    test('sendStop returns true when server accepts', () async {
      server.listen((request) async {
        // 消费请求体
        await request.fold<List<int>>(
          <int>[],
          (buffer, chunk) => buffer..addAll(chunk),
        );
        request.response.statusCode = 200;
        request.response.headers.contentType = ContentType.json;
        request.response.write(jsonEncode({'ok': true}));
        await request.response.close();
      });

      expect(await client.sendStop(port, graceTimeout: 10), isTrue);
    });

    test('sendStop returns false for non-ok', () async {
      server.listen((request) async {
        await request.fold<List<int>>(
          <int>[],
          (buffer, chunk) => buffer..addAll(chunk),
        );
        request.response.statusCode = 200;
        request.response.headers.contentType = ContentType.json;
        request.response.write(jsonEncode({'ok': false}));
        await request.response.close();
      });

      expect(await client.sendStop(port), isFalse);
    });

    // ---- config ----

    test('updateConfig returns true when server accepts', () async {
      server.listen((request) async {
        await request.fold<List<int>>(
          <int>[],
          (buffer, chunk) => buffer..addAll(chunk),
        );
        request.response.statusCode = 200;
        request.response.headers.contentType = ContentType.json;
        request.response.write(jsonEncode({'ok': true}));
        await request.response.close();
      });

      expect(
        await client.updateConfig(port, keepRunningInBackground: false),
        isTrue,
      );
    });

    // ---- terminals ----

    test('getTerminals returns parsed list', () async {
      server.listen((request) async {
        request.response.statusCode = 200;
        request.response.headers.contentType = ContentType.json;
        request.response.write(jsonEncode({
          'terminals': [
            {'terminal_id': 't1', 'status': 'attached'},
            {'terminal_id': 't2', 'status': 'detached'},
          ],
        }));
        await request.response.close();
      });

      final terminals = await client.getTerminals(port);
      expect(terminals.length, 2);
      expect(terminals[0]['terminal_id'], 't1');
      expect(terminals[1]['status'], 'detached');
    });

    test('getTerminals returns empty for 500', () async {
      server.listen((request) async {
        request.response.statusCode = 500;
        await request.response.close();
      });

      expect(await client.getTerminals(port), isEmpty);
    });

    // ---- skills ----

    test('getSkills returns parsed skill list', () async {
      server.listen((request) async {
        request.response.statusCode = 200;
        request.response.headers.contentType = ContentType.json;
        request.response.write(jsonEncode({
          'skills': [
            {
              'name': 'claude_code',
              'description': 'Claude Code',
              'enabled': true,
            },
            {'name': 'custom', 'description': 'Custom tool', 'enabled': false},
          ],
        }));
        await request.response.close();
      });

      final skills = await client.getSkills(port);
      expect(skills.length, 2);
      expect(skills[0].name, 'claude_code');
      expect(skills[0].enabled, isTrue);
      expect(skills[1].name, 'custom');
      expect(skills[1].enabled, isFalse);
    });

    // ---- knowledge ----

    test('getKnowledge returns parsed knowledge list', () async {
      server.listen((request) async {
        request.response.statusCode = 200;
        request.response.headers.contentType = ContentType.json;
        request.response.write(jsonEncode({
          'knowledge': [
            {'filename': 'guide.md', 'enabled': true},
            {'filename': 'tips.md', 'enabled': false},
          ],
        }));
        await request.response.close();
      });

      final knowledge = await client.getKnowledge(port);
      expect(knowledge.length, 2);
      expect(knowledge[0].filename, 'guide.md');
      expect(knowledge[0].enabled, isTrue);
      expect(knowledge[1].filename, 'tips.md');
    });

    // ---- state file discovery ----

    test('discoverAgent finds agent via state file', () async {
      server.listen((request) async {
        if (request.uri.path == '/health') {
          request.response.statusCode = 200;
          request.response.headers.contentType = ContentType.json;
          request.response.write(jsonEncode({'status': 'ok'}));
        } else if (request.uri.path == '/status') {
          request.response.statusCode = 200;
          request.response.headers.contentType = ContentType.json;
          request.response.write(jsonEncode({
            'running': true,
            'pid': pid,
            'port': port,
            'server_url': '',
            'connected': false,
            'session_id': '',
            'terminals_count': 0,
            'keep_running_in_background': true,
          }));
        }
        await request.response.close();
      });

      final homeDir =
          '/tmp/test_discover_${DateTime.now().millisecondsSinceEpoch}';
      final stateDir = Directory(
        '$homeDir/Library/Application Support/remote-control',
      );
      await stateDir.create(recursive: true);
      await File('${stateDir.path}/agent-state.json').writeAsString(
        jsonEncode({'pid': pid, 'port': port}),
      );

      final discoverClient = DesktopAgentHttpClient(
        timeout: const Duration(seconds: 5),
        homeDirectory: homeDir,
      );

      try {
        final result = await discoverClient.discoverAgent();
        expect(result, isNotNull);
        expect(result!.running, isTrue);
        expect(result.port, port);
      } finally {
        discoverClient.close();
        await Directory(homeDir).delete(recursive: true);
      }
    });
  });
}
