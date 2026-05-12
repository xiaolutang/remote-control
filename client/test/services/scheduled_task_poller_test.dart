import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:rc_client/models/scheduled_task.dart';
import 'package:rc_client/services/scheduled_task_poller.dart';

ScheduledTask _makeTask({
  int id = 1,
  String terminalId = 'term-1',
  String textContent = 'ls -la',
  String executeAt = '2026-05-13T08:30:00Z',
  ScheduledTaskRepeatType repeatType = ScheduledTaskRepeatType.once,
  ScheduledTaskStatus status = ScheduledTaskStatus.pending,
}) {
  return ScheduledTask(
    id: id,
    sessionId: 'sess-1',
    terminalId: terminalId,
    textContent: textContent,
    executeAt: executeAt,
    repeatType: repeatType,
    status: status,
    createdAt: '2026-05-12T10:00:00Z',
  );
}

/// 构建一个 MockClient，按调用次数依次返回预配置的响应。
MockClient _sequencedClient(List<http.Response> responses) {
  var index = 0;
  return MockClient((request) async {
    if (index < responses.length) {
      return responses[index++];
    }
    // 默认返回空列表
    return http.Response(jsonEncode({'tasks': []}), 200);
  });
}

http.Response _listResponse(List<ScheduledTask> tasks) {
  return http.Response(
    jsonEncode({
      'tasks': tasks.map((t) => t.toJson()).toList(),
    }),
    200,
  );
}

http.Response _deleteResponse() => http.Response('', 204);

void main() {
  group('ScheduledTaskPoller', () {
    test('启动轮询后立即加载一次', () async {
      final task = _makeTask();
      final client = _sequencedClient([_listResponse([task])]);
      final poller = ScheduledTaskPoller(
        serverUrl: 'ws://localhost:8888',
        client: client,
      );

      poller.startPolling('test-token', 'sess-1');
      // refresh() 是异步的，等待 microtask 完成
      await Future<void>.delayed(const Duration(milliseconds: 50));

      expect(poller.tasks, hasLength(1));
      expect(poller.tasks.first.id, 1);

      poller.dispose();
    });

    test('刷新返回 pending 任务 → tasks 更新', () async {
      final task = _makeTask();
      final client = _sequencedClient([_listResponse([task])]);
      final poller = ScheduledTaskPoller(
        serverUrl: 'ws://localhost:8888',
        client: client,
      );

      // 手动设置 token/session，然后 refresh
      poller.startPolling('test-token', 'sess-1');
      await Future<void>.delayed(const Duration(milliseconds: 50));

      expect(poller.tasks, hasLength(1));
      expect(poller.tasks.first.textContent, 'ls -la');

      poller.dispose();
    });

    test('pendingTasksForTerminal 按 terminalId 过滤', () async {
      final tasks = [
        _makeTask(id: 1, terminalId: 'term-a'),
        _makeTask(id: 2, terminalId: 'term-b'),
        _makeTask(id: 3, terminalId: 'term-a'),
      ];
      final client = _sequencedClient([_listResponse(tasks)]);
      final poller = ScheduledTaskPoller(
        serverUrl: 'ws://localhost:8888',
        client: client,
      );

      poller.startPolling('test-token', 'sess-1');
      await Future<void>.delayed(const Duration(milliseconds: 50));

      final termATasks = poller.pendingTasksForTerminal('term-a');
      expect(termATasks, hasLength(2));
      expect(termATasks.every((t) => t.terminalId == 'term-a'), isTrue);

      final termBTasks = poller.pendingTasksForTerminal('term-b');
      expect(termBTasks, hasLength(1));

      poller.dispose();
    });

    test('deleteTask 调用 service.delete 后自动刷新', () async {
      final task = _makeTask(id: 42);
      // 第1次: startPolling → refresh → 返回1个任务
      // 第2次: delete → 204
      // 第3次: deleteTask 内部 refresh → 返回空列表
      final client = _sequencedClient([
        _listResponse([task]),
        _deleteResponse(),
        _listResponse([]),
      ]);
      final poller = ScheduledTaskPoller(
        serverUrl: 'ws://localhost:8888',
        client: client,
      );

      poller.startPolling('test-token', 'sess-1');
      await Future<void>.delayed(const Duration(milliseconds: 50));
      expect(poller.tasks, hasLength(1));

      await poller.deleteTask(42);
      expect(poller.tasks, isEmpty);

      poller.dispose();
    });

    test('停止轮询后不再刷新', () async {
      var callCount = 0;
      final client = MockClient((request) async {
        callCount++;
        return _listResponse([]);
      });
      final poller = ScheduledTaskPoller(
        serverUrl: 'ws://localhost:8888',
        client: client,
      );

      poller.startPolling('test-token', 'sess-1');
      await Future<void>.delayed(const Duration(milliseconds: 50));
      expect(callCount, 1); // 首次 refresh

      poller.stopPolling();
      // 等一段时间确认不会再调用
      await Future<void>.delayed(const Duration(milliseconds: 100));
      expect(callCount, 1); // 仍然是1次

      poller.dispose();
    });

    test('refresh 失败静默处理，保持上次结果', () async {
      final task = _makeTask();
      var callCount = 0;
      final client = MockClient((request) async {
        callCount++;
        if (callCount == 1) {
          return _listResponse([task]);
        }
        // 第2次请求返回 500
        return http.Response('Internal Server Error', 500);
      });
      final poller = ScheduledTaskPoller(
        serverUrl: 'ws://localhost:8888',
        client: client,
      );

      poller.startPolling('test-token', 'sess-1');
      await Future<void>.delayed(const Duration(milliseconds: 50));
      expect(poller.tasks, hasLength(1));

      // 手动 refresh，触发失败的请求
      await poller.refresh();
      // 应该保持上次结果
      expect(poller.tasks, hasLength(1));
      expect(poller.isLoading, isFalse);

      poller.dispose();
    });

    test('dispose 取消 Timer', () async {
      final client = MockClient((request) async => _listResponse([]));
      final poller = ScheduledTaskPoller(
        serverUrl: 'ws://localhost:8888',
        client: client,
      );

      poller.startPolling('test-token', 'sess-1');
      await Future<void>.delayed(const Duration(milliseconds: 50));

      // dispose 不应抛出异常
      poller.dispose();

      // dispose 后 poller 已被 dispose，不应再使用
    });

    test('未启动时 refresh 不执行请求', () async {
      var callCount = 0;
      final client = MockClient((request) async {
        callCount++;
        return _listResponse([]);
      });
      final poller = ScheduledTaskPoller(
        serverUrl: 'ws://localhost:8888',
        client: client,
      );

      await poller.refresh();
      expect(callCount, 0);

      poller.dispose();
    });
  });
}
