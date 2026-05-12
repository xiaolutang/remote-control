import 'package:flutter_test/flutter_test.dart';
import 'package:rc_client/models/scheduled_task.dart';

void main() {
  group('ScheduledTask', () {
    test('fromJson parses full JSON correctly', () {
      final json = {
        'id': 42,
        'session_id': 'sess-1',
        'terminal_id': 'term-1',
        'text_content': 'ls -la\r\n',
        'execute_at': '2026-05-13T08:00:00Z',
        'repeat_type': 'daily',
        'status': 'pending',
        'created_at': '2026-05-12T10:00:00Z',
        'executed_at': null,
      };

      final task = ScheduledTask.fromJson(json);

      expect(task.id, 42);
      expect(task.sessionId, 'sess-1');
      expect(task.terminalId, 'term-1');
      expect(task.textContent, 'ls -la\r\n');
      expect(task.executeAt, '2026-05-13T08:00:00Z');
      expect(task.repeatType, ScheduledTaskRepeatType.daily);
      expect(task.status, ScheduledTaskStatus.pending);
      expect(task.createdAt, '2026-05-12T10:00:00Z');
      expect(task.executedAt, isNull);
    });

    test('fromJson uses defaults for missing optional fields', () {
      final json = {
        'id': 1,
        'session_id': 'sess-2',
        'terminal_id': 'term-2',
        'text_content': 'echo hello',
        'execute_at': '2026-05-13T08:00:00Z',
        'created_at': '2026-05-12T10:00:00Z',
      };

      final task = ScheduledTask.fromJson(json);

      expect(task.repeatType, ScheduledTaskRepeatType.once);
      expect(task.status, ScheduledTaskStatus.pending);
      expect(task.executedAt, isNull);
    });

    test('fromJson preserves raw text content with control characters', () {
      final json = {
        'id': 1,
        'session_id': 's',
        'terminal_id': 't',
        'text_content': 'cd /tmp\t&& ls\r',
        'execute_at': '2026-05-13T08:00:00Z',
        'created_at': '2026-05-12T10:00:00Z',
      };

      final task = ScheduledTask.fromJson(json);

      // readRawStringFromJson should NOT trim control characters
      expect(task.textContent, 'cd /tmp\t&& ls\r');
    });

    test('toJson round-trips correctly', () {
      final task = ScheduledTask(
        id: 10,
        sessionId: 'sess-3',
        terminalId: 'term-3',
        textContent: 'pwd',
        executeAt: '2026-05-14T09:00:00Z',
        repeatType: ScheduledTaskRepeatType.once,
        status: ScheduledTaskStatus.executed,
        createdAt: '2026-05-12T10:00:00Z',
        executedAt: '2026-05-14T09:00:01Z',
      );

      final json = task.toJson();
      final restored = ScheduledTask.fromJson(json);

      expect(restored.id, task.id);
      expect(restored.sessionId, task.sessionId);
      expect(restored.terminalId, task.terminalId);
      expect(restored.textContent, task.textContent);
      expect(restored.executeAt, task.executeAt);
      expect(restored.repeatType, task.repeatType);
      expect(restored.status, task.status);
      expect(restored.createdAt, task.createdAt);
      expect(restored.executedAt, task.executedAt);
    });

    test('copyWith overrides specified fields', () {
      final original = ScheduledTask(
        id: 1,
        sessionId: 's',
        terminalId: 't',
        textContent: 'ls',
        executeAt: '2026-05-13T08:00:00Z',
        repeatType: ScheduledTaskRepeatType.once,
        status: ScheduledTaskStatus.pending,
        createdAt: '2026-05-12T10:00:00Z',
      );

      final copied = original.copyWith(
        status: ScheduledTaskStatus.executed,
        executedAt: '2026-05-13T08:00:01Z',
      );

      expect(copied.id, original.id);
      expect(copied.sessionId, original.sessionId);
      expect(copied.textContent, original.textContent);
      expect(copied.status, ScheduledTaskStatus.executed);
      expect(copied.executedAt, '2026-05-13T08:00:01Z');
    });
  });
}
