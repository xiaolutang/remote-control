import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:rc_client/services/usage_summary_service.dart';

void main() {
  group('UsageSummaryService', () {
    test('parses dual scope usage summary response', () async {
      final client = MockClient((request) async {
        expect(
          request.url.toString(),
          'http://localhost:8888/api/agent/usage/summary?device_id=device-1',
        );
        return http.Response(
          jsonEncode({
            'device': {
              'total_sessions': 2,
              'total_input_tokens': 120,
              'total_output_tokens': 80,
              'total_tokens': 200,
              'total_requests': 3,
              'latest_model_name': 'deepseek-chat',
            },
            'user': {
              'total_sessions': 5,
              'total_input_tokens': 620,
              'total_output_tokens': 280,
              'total_tokens': 900,
              'total_requests': 11,
              'latest_model_name': 'deepseek-chat',
            },
          }),
          200,
        );
      });
      final service = UsageSummaryService(
        serverUrl: 'ws://localhost:8888',
        client: client,
      );

      final summary = await service.fetchSummary(
        token: 'token',
        deviceId: 'device-1',
      );

      expect(summary.device.totalTokens, 200);
      expect(summary.device.totalRequests, 3);
      expect(summary.user.totalTokens, 900);
      expect(summary.user.latestModelName, 'deepseek-chat');
      expect(summary.terminal, isNull);
    });

    test('defaults missing fields to zero values', () async {
      final client = MockClient((request) async {
        return http.Response(
          jsonEncode({
            'device': {'latest_model_name': 'deepseek-chat'},
            'user': {},
          }),
          200,
        );
      });
      final service = UsageSummaryService(
        serverUrl: 'ws://localhost:8888',
        client: client,
      );

      final summary = await service.fetchSummary(
        token: 'token',
        deviceId: 'device-1',
      );

      expect(summary.device.totalSessions, 0);
      expect(summary.device.totalInputTokens, 0);
      expect(summary.device.totalOutputTokens, 0);
      expect(summary.device.totalTokens, 0);
      expect(summary.device.totalRequests, 0);
      expect(summary.device.latestModelName, 'deepseek-chat');
      expect(summary.user.totalTokens, 0);
      expect(summary.user.latestModelName, '');
    });

    test('sends terminal_id when provided', () async {
      final client = MockClient((request) async {
        expect(
          request.url.toString(),
          'http://localhost:8888/api/agent/usage/summary?device_id=device-1&terminal_id=term-1',
        );
        return http.Response(
          jsonEncode({
            'device': {
              'total_sessions': 2,
              'total_tokens': 200,
              'total_requests': 3,
              'latest_model_name': 'deepseek-chat',
            },
            'user': {
              'total_sessions': 5,
              'total_tokens': 900,
              'total_requests': 11,
              'latest_model_name': 'deepseek-chat',
            },
            'terminal': {
              'total_sessions': 1,
              'total_tokens': 1900,
              'total_requests': 3,
              'latest_model_name': 'deepseek-chat',
            },
          }),
          200,
        );
      });
      final service = UsageSummaryService(
        serverUrl: 'ws://localhost:8888',
        client: client,
      );

      final summary = await service.fetchSummary(
        token: 'token',
        deviceId: 'device-1',
        terminalId: 'term-1',
      );

      expect(summary.device.totalTokens, 200);
      expect(summary.user.totalTokens, 900);
      expect(summary.terminal, isNotNull);
      expect(summary.terminal!.totalTokens, 1900);
      expect(summary.terminal!.totalRequests, 3);
      expect(summary.terminal!.totalSessions, 1);
    });

    test('parses terminal scope as null when not present in response',
        () async {
      final client = MockClient((request) async {
        return http.Response(
          jsonEncode({
            'device': {
              'total_tokens': 200,
              'total_requests': 3,
              'latest_model_name': 'deepseek-chat',
            },
            'user': {
              'total_tokens': 900,
              'total_requests': 11,
              'latest_model_name': 'deepseek-chat',
            },
          }),
          200,
        );
      });
      final service = UsageSummaryService(
        serverUrl: 'ws://localhost:8888',
        client: client,
      );

      final summary = await service.fetchSummary(
        token: 'token',
        deviceId: 'device-1',
      );

      expect(summary.terminal, isNull);
    });

    test('throws UsageSummaryException on non-200 status', () async {
      final client = MockClient((request) async {
        return http.Response(
          jsonEncode({'detail': 'Unauthorized'}),
          401,
        );
      });
      final service = UsageSummaryService(
        serverUrl: 'ws://localhost:8888',
        client: client,
      );

      expect(
        () => service.fetchSummary(
          token: 'bad-token',
          deviceId: 'device-1',
        ),
        throwsA(isA<UsageSummaryException>()),
      );
    });
  });
}
