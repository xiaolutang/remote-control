import 'package:flutter_test/flutter_test.dart';

import 'package:rc_client/services/desktop/desktop_agent_http_client.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  group('DesktopAgentHttpClient', () {
    late DesktopAgentHttpClient client;

    setUp(() {
      client = DesktopAgentHttpClient(
        timeout: const Duration(seconds: 2),
        homeDirectory:
            '/tmp/test_home_${DateTime.now().millisecondsSinceEpoch}',
      );
    });

    tearDown(() {
      client.close();
    });

    test('port range contains expected values', () {
      expect(kAgentPortRange, equals([18765, 18766, 18767, 18768, 18769]));
    });

    test('discoverAgent returns null when no agent running', () async {
      // 在没有 Agent 运行的环境中测试
      final result = await client.discoverAgent();
      // 结果取决于是否有 Agent 运行，这里只验证不会抛出异常
      expect(result, anyOf(isNull, isA<LocalAgentStatus>()));
    });

    test('checkHealth returns false for unreachable port', () async {
      final result = await client.checkHealth(19999); // 不太可能被占用的端口
      expect(result, isFalse);
    });

    test('getStatus returns null for unreachable port', () async {
      final result = await client.getStatus(19999);
      expect(result, isNull);
    });

    test('sendStop returns false for unreachable port', () async {
      final result = await client.sendStop(19999);
      expect(result, isFalse);
    });

    test('updateConfig returns false for unreachable port', () async {
      final result =
          await client.updateConfig(19999, keepRunningInBackground: false);
      expect(result, isFalse);
    });

    test('getTerminals returns empty list for unreachable port', () async {
      final result = await client.getTerminals(19999);
      expect(result, isEmpty);
    });
  });

  group('LocalAgentStatus', () {
    test('fromJson parses all fields', () {
      final json = {
        'running': true,
        'pid': 12345,
        'port': 18765,
        'server_url': 'wss://test.example.com',
        'connected': true,
        'session_id': 'session-123',
        'terminals_count': 3,
        'keep_running_in_background': false,
      };

      final status = LocalAgentStatus.fromJson(json);

      expect(status.running, isTrue);
      expect(status.pid, equals(12345));
      expect(status.port, equals(18765));
      expect(status.serverUrl, equals('wss://test.example.com'));
      expect(status.connected, isTrue);
      expect(status.sessionId, equals('session-123'));
      expect(status.terminalsCount, equals(3));
      expect(status.keepRunningInBackground, isFalse);
    });

    test('fromJson handles missing fields with defaults', () {
      final json = <String, dynamic>{};

      final status = LocalAgentStatus.fromJson(json);

      expect(status.running, isFalse);
      expect(status.pid, equals(0));
      expect(status.port, equals(0));
      expect(status.serverUrl, isEmpty);
      expect(status.connected, isFalse);
      expect(status.sessionId, isEmpty);
      expect(status.terminalsCount, isZero);
      expect(status.keepRunningInBackground, isTrue);
    });

    test('creates with all required fields', () {
      const status = LocalAgentStatus(
        running: true,
        pid: 12345,
        port: 18765,
        serverUrl: 'wss://test.example.com',
        connected: true,
        sessionId: 'session-123',
        terminalsCount: 2,
        keepRunningInBackground: true,
      );

      expect(status.running, isTrue);
      expect(status.pid, equals(12345));
      expect(status.port, equals(18765));
      expect(status.serverUrl, equals('wss://test.example.com'));
      expect(status.connected, isTrue);
      expect(status.sessionId, equals('session-123'));
      expect(status.terminalsCount, equals(2));
      expect(status.keepRunningInBackground, isTrue);
    });
  });
}
