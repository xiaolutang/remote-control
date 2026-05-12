import 'package:flutter_test/flutter_test.dart';
import 'package:rc_client/services/logger_service.dart';

void main() {
  group('LoggerService', () {
    late LoggerService service;

    setUp(() {
      service = LoggerService(
        serverUrl: 'wss://localhost/rc',
        sessionId: 'test-session',
        token: 'test-token',
      );
    });

    tearDown(() async {
      // 先 stop（会 cancel timer + flush），等待完成后再 dispose
      await service.stop();
      service.dispose();
    });

    test('连续写入 100 条日志，notifyListeners 调用次数远少于 100', () async {
      int notifyCount = 0;
      service.addListener(() {
        notifyCount++;
      });

      // 写入 100 条日志（batchSize=10，第 10 条触发 flush）
      for (int i = 0; i < 100; i++) {
        service.info('log message $i');
      }

      // 等待 flush 的异步操作完成
      await service.flush();
      // flush 内部会 await _uploadLogs（网络请求会失败），
      // 等待微任务队列排空
      await Future.delayed(Duration(milliseconds: 100));

      // 验收条件：notifyListeners 调用次数 < 100
      // _log 不再调用 notifyListeners，只有 flush 时才通知
      // 100 条日志 = 10 次 flush，每次 flush 最多 2 次 notify（begin + end）
      expect(notifyCount, lessThan(100));
    });

    test('_log 不直接调用 notifyListeners', () async {
      int notifyCount = 0;
      service.addListener(() {
        notifyCount++;
      });

      // 写入少量日志（不触发 flush，batchSize=10）
      for (int i = 0; i < 5; i++) {
        service.info('log message $i');
      }

      // 等待微任务
      await Future.delayed(Duration(milliseconds: 50));

      // 5 条日志不应触发任何通知（未达到 batchSize，无 flush）
      expect(notifyCount, equals(0));
    });

    test('flush 在状态变化时通知', () async {
      int notifyCount = 0;
      service.addListener(() {
        notifyCount++;
      });

      // 写入一些日志触发 flush
      for (int i = 0; i < 10; i++) {
        service.info('log message $i');
      }

      // 等待 flush 完成
      await service.flush();
      await Future.delayed(Duration(milliseconds: 100));

      // flush 至少通知了状态变化（uploading true -> false）
      expect(notifyCount, greaterThan(0));
    });

    test('pendingCount 反映队列中的日志数', () {
      expect(service.pendingCount, equals(0));

      service.info('msg1');
      expect(service.pendingCount, equals(1));

      service.info('msg2');
      expect(service.pendingCount, equals(2));
    });
  });
}
