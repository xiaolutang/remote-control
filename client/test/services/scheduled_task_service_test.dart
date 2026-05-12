import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:rc_client/models/scheduled_task.dart';
import 'package:rc_client/services/scheduled_task_service.dart';

http.Response _utf8Response(String body, int status) =>
    http.Response.bytes(utf8.encode(body), status);

void main() {
  group('ScheduledTaskService', () {
    test('create sends correct URL and body', () async {
      final client = MockClient((request) async {
        expect(request.method, 'POST');
        expect(request.url.toString(),
            'http://localhost:8888/api/scheduled-tasks');
        expect(request.headers['Authorization'], 'Bearer test-token');
        final body = jsonDecode(request.body) as Map<String, dynamic>;
        expect(body['session_id'], 'sess-1');
        expect(body['terminal_id'], 'term-1');
        expect(body['text_content'], 'ls -la');
        expect(body['execute_at'], '2026-05-13T08:00:00Z');
        expect(body['repeat_type'], 'once');
        return http.Response(jsonEncode({'task_id': 42}), 201);
      });

      final service = ScheduledTaskService(
        serverUrl: 'ws://localhost:8888',
        client: client,
      );

      final taskId = await service.create(
        token: 'test-token',
        sessionId: 'sess-1',
        terminalId: 'term-1',
        textContent: 'ls -la',
        executeAt: '2026-05-13T08:00:00Z',
        repeatType: ScheduledTaskRepeatType.once,
      );

      expect(taskId, 42);
    });

    test('list fetches tasks with filter params', () async {
      final client = MockClient((request) async {
        expect(request.method, 'GET');
        expect(request.url.toString(),
            'http://localhost:8888/api/scheduled-tasks?session_id=sess-1&status=pending');
        return http.Response(
          jsonEncode({
            'tasks': [
              {
                'id': 1,
                'session_id': 'sess-1',
                'terminal_id': 'term-1',
                'text_content': 'ls',
                'execute_at': '2026-05-13T08:00:00Z',
                'repeat_type': 'once',
                'status': 'pending',
                'created_at': '2026-05-12T10:00:00Z',
              },
            ],
          }),
          200,
        );
      });

      final service = ScheduledTaskService(
        serverUrl: 'ws://localhost:8888',
        client: client,
      );

      final tasks = await service.list(
        token: 'test-token',
        sessionId: 'sess-1',
        status: 'pending',
      );

      expect(tasks, hasLength(1));
      expect(tasks.first.id, 1);
      expect(tasks.first.sessionId, 'sess-1');
    });

    test('list without filters sends no query params', () async {
      final client = MockClient((request) async {
        expect(request.method, 'GET');
        expect(request.url.toString(),
            'http://localhost:8888/api/scheduled-tasks');
        return http.Response(
          jsonEncode({'tasks': []}),
          200,
        );
      });

      final service = ScheduledTaskService(
        serverUrl: 'ws://localhost:8888',
        client: client,
      );

      final tasks = await service.list(token: 'test-token');
      expect(tasks, isEmpty);
    });

    test('delete sends correct URL and method', () async {
      final client = MockClient((request) async {
        expect(request.method, 'DELETE');
        expect(request.url.toString(),
            'http://localhost:8888/api/scheduled-tasks/42');
        return http.Response('', 204);
      });

      final service = ScheduledTaskService(
        serverUrl: 'ws://localhost:8888',
        client: client,
      );

      await service.delete(token: 'test-token', taskId: 42);
    });

    test('create throws ScheduledTaskException on 409', () async {
      final client = MockClient((request) async {
        return _utf8Response(
          jsonEncode({'detail': '任务时间冲突'}),
          409,
        );
      });

      final service = ScheduledTaskService(
        serverUrl: 'ws://localhost:8888',
        client: client,
      );

      expect(
        () => service.create(
          token: 'test-token',
          sessionId: 's',
          terminalId: 't',
          textContent: 'ls',
          executeAt: '2026-05-13T08:00:00Z',
          repeatType: ScheduledTaskRepeatType.once,
        ),
        throwsA(isA<ScheduledTaskException>().having(
          (e) => e.statusCode,
          'statusCode',
          409,
        )),
      );
    });

    test('create throws ScheduledTaskException on non-JSON error', () async {
      final client = MockClient((request) async {
        return http.Response('Internal Server Error', 500);
      });

      final service = ScheduledTaskService(
        serverUrl: 'ws://localhost:8888',
        client: client,
      );

      expect(
        () => service.create(
          token: 'test-token',
          sessionId: 's',
          terminalId: 't',
          textContent: 'ls',
          executeAt: '2026-05-13T08:00:00Z',
          repeatType: ScheduledTaskRepeatType.once,
        ),
        throwsA(isA<ScheduledTaskException>().having(
          (e) => e.statusCode,
          'statusCode',
          500,
        )),
      );
    });
  });
}
