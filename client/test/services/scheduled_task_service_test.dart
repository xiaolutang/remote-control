import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:rc_client/models/scheduled_task.dart';
import 'package:rc_client/services/scheduled_task_service.dart';

import '../mocks/mock_http_client.dart';

void main() {
  group('ScheduledTaskService', () {
    late MockHttpClient mockClient;
    late ScheduledTaskService service;

    setUp(() {
      mockClient = MockHttpClient();
      service = ScheduledTaskService(
        serverUrl: 'ws://localhost:8888',
        client: mockClient,
      );
    });

    group('create', () {
      test('success returns task ID', () async {
        mockClient.enqueueResponse(http.Response(
          jsonEncode({'id': 42, 'status': 'pending'}),
          201,
        ));

        final id = await service.create(
          token: 'test-token',
          sessionId: 'device-1',
          terminalId: 'term-1',
          textContent: 'echo hello\recho world',
          executeAt: '2026-05-14T03:00:00+08:00',
          repeatType: ScheduledTaskRepeatType.daily,
        );

        expect(id, 42);

        final request = mockClient.lastRequest!;
        expect(request.method, 'POST');
        expect(request.url.path, '/api/scheduled-tasks');
        expect(request.headers['Authorization'], 'Bearer test-token');

        final body = jsonDecode(request.body) as Map<String, dynamic>;
        expect(body['session_id'], 'device-1');
        expect(body['terminal_id'], 'term-1');
        expect(body['text_content'], 'echo hello\recho world');
        expect(body['execute_at'], '2026-05-14T03:00:00+08:00');
        expect(body['repeat_type'], 'daily');
      });

      test('200 also treated as success', () async {
        mockClient.enqueueResponse(http.Response(
          jsonEncode({'id': 1, 'status': 'pending'}),
          200,
        ));

        final id = await service.create(
          token: 'tok',
          sessionId: 's',
          terminalId: 't',
          textContent: 'cmd',
          executeAt: '2026-01-01T00:00:00Z',
          repeatType: ScheduledTaskRepeatType.once,
        );

        expect(id, 1);
      });

      test('failure throws ScheduledTaskException', () async {
        mockClient.enqueueResponse(http.Response(
          jsonEncode({'detail': 'Agent is not online'}),
          409,
        ));

        expect(
          () => service.create(
            token: 'tok',
            sessionId: 's',
            terminalId: 't',
            textContent: 'cmd',
            executeAt: '2026-01-01T00:00:00Z',
            repeatType: ScheduledTaskRepeatType.once,
          ),
          throwsA(isA<ScheduledTaskException>().having(
            (e) => e.message,
            'message',
            'Agent is not online',
          )),
        );
      });
    });

    group('list', () {
      test('success returns task list', () async {
        mockClient.enqueueResponse(http.Response(
          jsonEncode({
            'tasks': [
              {
                'id': 1,
                'session_id': 's',
                'terminal_id': 't',
                'text_content': 'cmd',
                'execute_at': '2026-01-01T00:00:00Z',
                'repeat_type': 'once',
                'status': 'pending',
                'created_at': '2026-01-01T00:00:00Z',
                'executed_at': null,
              },
            ],
          }),
          200,
        ));

        final tasks = await service.list(token: 'tok');
        expect(tasks.length, 1);
        expect(tasks[0].id, 1);
        expect(tasks[0].textContent, 'cmd');
      });
    });

    group('delete', () {
      test('204 treated as success', () async {
        mockClient.enqueueResponse(http.Response('', 204));
        await service.delete(token: 'tok', taskId: 1);
        // no exception
      });

      test('non-204 throws', () async {
        mockClient.enqueueResponse(http.Response('{}', 403));
        expect(
          () => service.delete(token: 'tok', taskId: 1),
          throwsA(isA<ScheduledTaskException>()),
        );
      });
    });
  });
}
