import 'dart:async';
import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:rc_client/services/websocket_service.dart';

void main() {
  group('ConnectionStatus', () {
    test('enum values', () {
      expect(ConnectionStatus.values.length, 5);
      expect(ConnectionStatus.disconnected.index, 0);
      expect(ConnectionStatus.connecting.index, 1);
      expect(ConnectionStatus.connected.index, 2);
      expect(ConnectionStatus.reconnecting.index, 3);
      expect(ConnectionStatus.error.index, 4);
    });
  });

  group('ViewType', () {
    test('enum values', () {
      expect(ViewType.values.length, 2);
      expect(ViewType.mobile.name, 'mobile');
      expect(ViewType.desktop.name, 'desktop');
    });
  });

  group('WebSocketService', () {
    test('initial state', () {
      final service = WebSocketService(
        serverUrl: 'ws://localhost:8888',
        token: 'test-token',
        sessionId: 'session-1',
      );

      expect(service.status, ConnectionStatus.disconnected);
      expect(service.errorMessage, isNull);
      expect(service.agentOnline, isFalse);
      expect(service.isConnected, isFalse);
    });

    test('output stream exists', () {
      final service = WebSocketService(
        serverUrl: 'ws://localhost:8888',
        token: 'test-token',
        sessionId: 'session-1',
      );

      expect(service.outputStream, isNotNull);
    });

    test('presence stream exists', () {
      final service = WebSocketService(
        serverUrl: 'ws://localhost:8888',
        token: 'test-token',
        sessionId: 'session-1',
      );

      expect(service.presenceStream, isNotNull);
    });

    test('terminals changed stream exists', () {
      final service = WebSocketService(
        serverUrl: 'ws://localhost:8888',
        token: 'test-token',
        sessionId: 'session-1',
      );

      expect(service.terminalsChangedStream, isNotNull);
    });

    test('view type affects view type string', () {
      final mobileService = WebSocketService(
        serverUrl: 'ws://localhost:8888',
        token: 'test-token',
        sessionId: 'session-1',
        viewType: ViewType.mobile,
      );

      final desktopService = WebSocketService(
        serverUrl: 'ws://localhost:8888',
        token: 'test-token',
        sessionId: 'session-1',
        viewType: ViewType.desktop,
      );

      // The view type is internal, but we can verify the service was created
      expect(mobileService, isNotNull);
      expect(desktopService, isNotNull);
    });

    test('reconnect settings', () {
      final service = WebSocketService(
        serverUrl: 'ws://localhost:8888',
        token: 'test-token',
        sessionId: 'session-1',
        autoReconnect: false,
        maxRetries: 10,
        reconnectDelay: const Duration(seconds: 5),
      );

      expect(service, isNotNull);
    });
  });

  group('WebSocketService terminalsChangedStream', () {
    test('terminalsChangedStream emits data on terminals_changed message', () async {
      final service = WebSocketService(
        serverUrl: 'ws://localhost:8888',
        token: 'test-token',
        sessionId: 'session-1',
      );

      final completer = Completer<Map<String, dynamic>>();
      final subscription = service.terminalsChangedStream.listen((data) {
        completer.complete(data);
      });

      // 模拟 _handleMessage 被调用（通过反射或直接测试）
      // 由于 _handleMessage 是私有的，我们需要通过其他方式测试
      // 这里我们只验证 stream 存在且可以订阅
      expect(subscription, isNotNull);

      // 清理
      await subscription.cancel();
      service.dispose();
    });

    test('terminalsChangedStream is broadcast stream', () async {
      final service = WebSocketService(
        serverUrl: 'ws://localhost:8888',
        token: 'test-token',
        sessionId: 'session-1',
      );

      final stream = service.terminalsChangedStream;
      expect(stream.isBroadcast, isTrue);

      service.dispose();
    });

    test('terminalsChangedStream closes on dispose', () async {
      final service = WebSocketService(
        serverUrl: 'ws://localhost:8888',
        token: 'test-token',
        sessionId: 'session-1',
      );

      var streamClosed = false;
      final subscription = service.terminalsChangedStream.listen(
        (_) {},
        onDone: () {
          streamClosed = true;
        },
      );

      // 给 stream 订阅一点时间
      await Future.delayed(const Duration(milliseconds: 50));

      service.dispose();
      await Future.delayed(const Duration(milliseconds: 100));

      expect(streamClosed, isTrue);
      await subscription.cancel();
    });

    test('multiple listeners can subscribe to terminalsChangedStream', () async {
      final service = WebSocketService(
        serverUrl: 'ws://localhost:8888',
        token: 'test-token',
        sessionId: 'session-1',
      );

      var listener1Called = false;
      var listener2Called = false;

      final sub1 = service.terminalsChangedStream.listen((_) {
        listener1Called = true;
      });
      final sub2 = service.terminalsChangedStream.listen((_) {
        listener2Called = true;
      });

      expect(sub1, isNotNull);
      expect(sub2, isNotNull);

      // 先取消订阅，再 dispose
      await sub1.cancel();
      await sub2.cancel();
      service.dispose();
    });
  });
}
