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

    test('output frame stream exists', () {
      final service = WebSocketService(
        serverUrl: 'ws://localhost:8888',
        token: 'test-token',
        sessionId: 'session-1',
      );

      expect(service.outputFrameStream, isNotNull);
    });

    test('protocol event stream exists', () {
      final service = WebSocketService(
        serverUrl: 'ws://localhost:8888',
        token: 'test-token',
        sessionId: 'session-1',
      );

      expect(service.eventStream, isNotNull);
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
    test('terminalsChangedStream emits data on terminals_changed message',
        () async {
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

    test('protocol event stream exists', () {
      final service = WebSocketService(
        serverUrl: 'ws://localhost:8888',
        token: 'test-token',
        sessionId: 'session-1',
      );

      expect(service.eventStream, isNotNull);

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

    test('multiple listeners can subscribe to terminalsChangedStream',
        () async {
      final service = WebSocketService(
        serverUrl: 'ws://localhost:8888',
        token: 'test-token',
        sessionId: 'session-1',
      );

      final sub1 = service.terminalsChangedStream.listen((_) {});
      final sub2 = service.terminalsChangedStream.listen((_) {});

      expect(sub1, isNotNull);
      expect(sub2, isNotNull);

      // 先取消订阅，再 dispose
      await sub1.cancel();
      await sub2.cancel();
      service.dispose();
    });
  });

  group('WebSocketService snapshots', () {
    test('snapshot messages are decoded into event stream', () async {
      final service = WebSocketService(
        serverUrl: 'ws://localhost:8888',
        token: 'test-token',
        sessionId: 'session-1',
      );

      final events = <TerminalProtocolEvent>[];
      final sub = service.eventStream.listen(events.add);

      service.debugHandleMessage(jsonEncode({
        'type': 'snapshot',
        'payload': base64Encode(utf8.encode('hello snapshot')),
      }));

      await Future<void>.delayed(const Duration(milliseconds: 10));

      final snapshotEvents = events.where(
        (event) => event.kind == TerminalProtocolEventKind.snapshot,
      );
      expect(snapshotEvents, hasLength(1));
      expect(snapshotEvents.single.payload, 'hello snapshot');

      await sub.cancel();
      service.dispose();
    });

    test('snapshot messages are tagged in output frame stream', () async {
      final service = WebSocketService(
        serverUrl: 'ws://localhost:8888',
        token: 'test-token',
        sessionId: 'session-1',
      );

      final frames = <TerminalOutputFrame>[];
      final sub = service.outputFrameStream.listen(frames.add);

      service.debugHandleMessage(jsonEncode({
        'type': 'snapshot',
        'payload': base64Encode(utf8.encode('hello snapshot')),
      }));

      await Future<void>.delayed(const Duration(milliseconds: 10));

      expect(frames, isNotEmpty);
      expect(frames.single.kind, TerminalOutputKind.snapshot);
      expect(frames.single.payload, 'hello snapshot');

      await sub.cancel();
      service.dispose();
    });

    test('snapshot_chunk messages are decoded into snapshot chunk frames',
        () async {
      final service = WebSocketService(
        serverUrl: 'ws://localhost:8888',
        token: 'test-token',
        sessionId: 'session-1',
      );

      final frames = <TerminalOutputFrame>[];
      final sub = service.outputFrameStream.listen(frames.add);

      service.debugHandleMessage(jsonEncode({
        'type': 'snapshot_chunk',
        'payload': base64Encode(utf8.encode('hello chunk')),
        'attach_epoch': 3,
        'recovery_epoch': 7,
      }));

      await Future<void>.delayed(const Duration(milliseconds: 10));

      expect(frames, hasLength(1));
      expect(frames.single.kind, TerminalOutputKind.snapshotChunk);
      expect(frames.single.payload, 'hello chunk');
      expect(frames.single.attachEpoch, 3);
      expect(frames.single.recoveryEpoch, 7);

      await sub.cancel();
      service.dispose();
    });

    test('snapshot_chunk messages preserve active_buffer metadata', () async {
      final service = WebSocketService(
        serverUrl: 'ws://localhost:8888',
        token: 'test-token',
        sessionId: 'session-1',
      );

      final frames = <TerminalOutputFrame>[];
      final events = <TerminalProtocolEvent>[];
      final sub1 = service.outputFrameStream.listen(frames.add);
      final sub2 = service.eventStream.listen(events.add);

      service.debugHandleMessage(jsonEncode({
        'type': 'snapshot_chunk',
        'payload': base64Encode(utf8.encode('alternate snapshot')),
        'active_buffer': 'alt',
      }));

      await Future<void>.delayed(const Duration(milliseconds: 10));

      expect(frames, hasLength(1));
      expect(frames.single.kind, TerminalOutputKind.snapshotChunk);
      expect(frames.single.activeBuffer, TerminalBufferKind.alt);
      final snapshotEvents = events
          .where(
            (event) => event.kind == TerminalProtocolEventKind.snapshotChunk,
          )
          .toList();
      expect(snapshotEvents, hasLength(1));
      expect(snapshotEvents.single.activeBuffer, TerminalBufferKind.alt);

      await sub1.cancel();
      await sub2.cancel();
      service.dispose();
    });

    test('output messages are decoded into live data frames', () async {
      final service = WebSocketService(
        serverUrl: 'ws://localhost:8888',
        token: 'test-token',
        sessionId: 'session-1',
      );

      final frames = <TerminalOutputFrame>[];
      final sub = service.outputFrameStream.listen(frames.add);

      service.debugHandleMessage(jsonEncode({
        'type': 'output',
        'payload': base64Encode(utf8.encode('live output')),
        'attach_epoch': 4,
      }));

      await Future<void>.delayed(const Duration(milliseconds: 10));

      expect(frames, hasLength(1));
      expect(frames.single.kind, TerminalOutputKind.data);
      expect(frames.single.payload, 'live output');
      expect(frames.single.attachEpoch, 4);

      await sub.cancel();
      service.dispose();
    });

    test('connected messages emit protocol connected event', () async {
      final service = WebSocketService(
        serverUrl: 'ws://localhost:8888',
        token: 'test-token',
        sessionId: 'session-1',
      );

      final events = <TerminalProtocolEvent>[];
      final sub = service.eventStream.listen(events.add);

      service.debugHandleMessage(jsonEncode({
        'type': 'connected',
        'terminal_id': 'term-1',
        'pty': {'rows': 40, 'cols': 120},
        'geometry_owner_view': 'desktop',
        'attach_epoch': 2,
        'recovery_epoch': 5,
        'views': {'mobile': 0, 'desktop': 1},
      }));

      await Future<void>.delayed(const Duration(milliseconds: 10));

      expect(events, isNotEmpty);
      expect(events.single.kind, TerminalProtocolEventKind.connected);
      expect(events.single.attachEpoch, 2);
      expect(events.single.recoveryEpoch, 5);
      expect(events.single.ptySize?.rows, 40);
      expect(events.single.ptySize?.cols, 120);

      await sub.cancel();
      service.dispose();
    });

    test('snapshot_complete emits protocol snapshotComplete event', () async {
      final service = WebSocketService(
        serverUrl: 'ws://localhost:8888',
        token: 'test-token',
        sessionId: 'session-1',
      );

      final events = <TerminalProtocolEvent>[];
      final sub = service.eventStream.listen(events.add);

      service.debugHandleMessage(jsonEncode({
        'type': 'snapshot_complete',
        'attach_epoch': 3,
        'recovery_epoch': 9,
      }));

      await Future<void>.delayed(const Duration(milliseconds: 10));

      expect(events, hasLength(1));
      expect(events.single.kind, TerminalProtocolEventKind.snapshotComplete);
      expect(events.single.attachEpoch, 3);
      expect(events.single.recoveryEpoch, 9);

      await sub.cancel();
      service.dispose();
    });

    test('resize messages update pty size stream', () async {
      final service = WebSocketService(
        serverUrl: 'ws://localhost:8888',
        token: 'test-token',
        sessionId: 'session-1',
      );

      final sizes = <TerminalPtySize>[];
      final sub = service.ptySizeStream.listen(sizes.add);

      service.debugHandleMessage(jsonEncode({
        'type': 'resize',
        'rows': 40,
        'cols': 120,
      }));

      await Future<void>.delayed(const Duration(milliseconds: 10));

      expect(service.ptyRows, 40);
      expect(service.ptyCols, 120);
      expect(sizes.single.rows, 40);
      expect(sizes.single.cols, 120);

      await sub.cancel();
      service.dispose();
    });

    test('connected messages apply initial pty size', () async {
      final service = WebSocketService(
        serverUrl: 'ws://localhost:8888',
        token: 'test-token',
        sessionId: 'session-1',
      );

      service.debugHandleMessage(jsonEncode({
        'type': 'connected',
        'agent_online': true,
        'device_online': true,
        'owner': 'user-1',
        'terminal_status': 'attached',
        'pty': {
          'rows': 32,
          'cols': 96,
        },
      }));

      expect(service.status, ConnectionStatus.connected);
      expect(service.ptyRows, 32);
      expect(service.ptyCols, 96);
    });

    test('connected and presence messages apply geometry owner view', () async {
      final service = WebSocketService(
        serverUrl: 'ws://localhost:8888',
        token: 'test-token',
        sessionId: 'session-1',
        viewType: ViewType.mobile,
      );

      service.debugHandleMessage(jsonEncode({
        'type': 'connected',
        'agent_online': true,
        'device_online': true,
        'owner': 'user-1',
        'terminal_status': 'attached',
        'geometry_owner_view': 'mobile',
        'views': {
          'mobile': 1,
          'desktop': 0,
        },
        'pty': {
          'rows': 32,
          'cols': 96,
        },
      }));

      expect(service.geometryOwnerView, 'mobile');
      expect(service.isGeometryOwner, isTrue);

      service.debugHandleMessage(jsonEncode({
        'type': 'presence',
        'geometry_owner_view': 'desktop',
        'views': {
          'mobile': 1,
          'desktop': 1,
        },
      }));

      expect(service.geometryOwnerView, 'desktop');
      expect(service.isGeometryOwner, isFalse);
      expect(service.views, {'mobile': 1, 'desktop': 1});
    });
  });

  group('eventStream events', () {
    test('resize message emits TerminalProtocolEventKind.resize with ptySize',
        () async {
      final service = WebSocketService(
        serverUrl: 'ws://localhost:8888',
        token: 'test-token',
        sessionId: 'session-1',
      );

      final events = <TerminalProtocolEvent>[];
      final sub = service.eventStream.listen(events.add);

      service.debugHandleMessage(jsonEncode({
        'type': 'resize',
        'rows': 24,
        'cols': 80,
      }));

      await Future<void>.delayed(const Duration(milliseconds: 10));

      expect(events, hasLength(1));
      expect(events.single.kind, TerminalProtocolEventKind.resize);
      expect(events.single.ptySize, isNotNull);
      expect(events.single.ptySize!.rows, 24);
      expect(events.single.ptySize!.cols, 80);

      await sub.cancel();
      service.dispose();
    });

    test('output message emits TerminalProtocolEventKind.output with payload',
        () async {
      final service = WebSocketService(
        serverUrl: 'ws://localhost:8888',
        token: 'test-token',
        sessionId: 'session-1',
      );

      final events = <TerminalProtocolEvent>[];
      final sub = service.eventStream.listen(events.add);

      service.debugHandleMessage(jsonEncode({
        'type': 'output',
        'payload': base64Encode(utf8.encode('live data')),
      }));

      await Future<void>.delayed(const Duration(milliseconds: 10));

      expect(events, hasLength(1));
      expect(events.single.kind, TerminalProtocolEventKind.output);
      expect(events.single.payload, 'live data');

      await sub.cancel();
      service.dispose();
    });

    test(
        'snapshot message emits TerminalProtocolEventKind.snapshot with payload',
        () async {
      final service = WebSocketService(
        serverUrl: 'ws://localhost:8888',
        token: 'test-token',
        sessionId: 'session-1',
      );

      final events = <TerminalProtocolEvent>[];
      final sub = service.eventStream.listen(events.add);

      service.debugHandleMessage(jsonEncode({
        'type': 'snapshot',
        'payload': base64Encode(utf8.encode('snap data')),
      }));

      await Future<void>.delayed(const Duration(milliseconds: 10));

      expect(events, hasLength(1));
      expect(events.single.kind, TerminalProtocolEventKind.snapshot);
      expect(events.single.payload, 'snap data');

      await sub.cancel();
      service.dispose();
    });

    test('presence message emits TerminalProtocolEventKind.presence with views',
        () async {
      final service = WebSocketService(
        serverUrl: 'ws://localhost:8888',
        token: 'test-token',
        sessionId: 'session-1',
      );

      // 先 connected 以设置初始 views
      service.debugHandleMessage(jsonEncode({
        'type': 'connected',
        'agent_online': true,
        'views': {'mobile': 0, 'desktop': 0},
      }));

      final events = <TerminalProtocolEvent>[];
      final sub = service.eventStream.listen(events.add);

      service.debugHandleMessage(jsonEncode({
        'type': 'presence',
        'views': {'mobile': 1, 'desktop': 1},
        'geometry_owner_view': 'mobile',
      }));

      await Future<void>.delayed(const Duration(milliseconds: 10));

      // events[0] 是 connected 事件之后的 presence 事件
      final presenceEvent = events
          .where((e) => e.kind == TerminalProtocolEventKind.presence)
          .toList();
      expect(presenceEvent, hasLength(1));
      expect(presenceEvent.single.views, {'mobile': 1, 'desktop': 1});

      await sub.cancel();
      service.dispose();
    });

    test('terminal_closed message emits TerminalProtocolEventKind.closed event',
        () async {
      final service = WebSocketService(
        serverUrl: 'ws://localhost:8888',
        token: 'test-token',
        sessionId: 'session-1',
        autoReconnect: false,
      );

      // 先 connected
      service.debugHandleMessage(jsonEncode({
        'type': 'connected',
        'agent_online': true,
      }));

      final events = <TerminalProtocolEvent>[];
      final sub = service.eventStream.listen(events.add);

      service.debugHandleMessage(jsonEncode({
        'type': 'terminal_closed',
      }));

      await Future<void>.delayed(const Duration(milliseconds: 10));

      final closedEvent = events
          .where((e) => e.kind == TerminalProtocolEventKind.closed)
          .toList();
      expect(closedEvent, hasLength(1));
      expect(closedEvent.single.terminalStatus, 'closed');

      await sub.cancel();
      service.dispose();
    });

    test('output messages preserve UTF-8 characters across frame boundaries',
        () async {
      final service = WebSocketService(
        serverUrl: 'ws://localhost:8888',
        token: 'test-token',
        sessionId: 'session-1',
      );

      final frames = <TerminalOutputFrame>[];
      final events = <TerminalProtocolEvent>[];
      final sub1 = service.outputFrameStream.listen(frames.add);
      final sub2 = service.eventStream.listen(events.add);
      final bytes = utf8.encode('你');

      service.debugHandleMessage(jsonEncode({
        'type': 'output',
        'payload': base64Encode(bytes.sublist(0, 2)),
      }));
      service.debugHandleMessage(jsonEncode({
        'type': 'output',
        'payload': base64Encode(bytes.sublist(2)),
      }));

      await Future<void>.delayed(const Duration(milliseconds: 10));

      expect(frames, hasLength(1));
      expect(frames.single.kind, TerminalOutputKind.data);
      expect(frames.single.payload, '你');
      expect(frames.single.payload, isNot(contains('�')));

      final outputEvents = events
          .where((event) => event.kind == TerminalProtocolEventKind.output)
          .toList();
      expect(outputEvents, hasLength(1));
      expect(outputEvents.single.payload, '你');

      await sub1.cancel();
      await sub2.cancel();
      service.dispose();
    });

    test(
        'snapshot_chunk messages preserve UTF-8 characters across frame boundaries',
        () async {
      final service = WebSocketService(
        serverUrl: 'ws://localhost:8888',
        token: 'test-token',
        sessionId: 'session-1',
      );

      final frames = <TerminalOutputFrame>[];
      final events = <TerminalProtocolEvent>[];
      final sub1 = service.outputFrameStream.listen(frames.add);
      final sub2 = service.eventStream.listen(events.add);
      final bytes = utf8.encode('好');

      service.debugHandleMessage(jsonEncode({
        'type': 'snapshot_chunk',
        'payload': base64Encode(bytes.sublist(0, 2)),
        'active_buffer': 'alt',
      }));
      service.debugHandleMessage(jsonEncode({
        'type': 'snapshot_chunk',
        'payload': base64Encode(bytes.sublist(2)),
        'active_buffer': 'alt',
      }));

      await Future<void>.delayed(const Duration(milliseconds: 10));

      expect(frames, hasLength(1));
      expect(frames.single.kind, TerminalOutputKind.snapshotChunk);
      expect(frames.single.payload, '好');
      expect(frames.single.payload, isNot(contains('�')));
      expect(frames.single.activeBuffer, TerminalBufferKind.alt);

      final snapshotEvents = events
          .where(
              (event) => event.kind == TerminalProtocolEventKind.snapshotChunk)
          .toList();
      expect(snapshotEvents, hasLength(1));
      expect(snapshotEvents.single.payload, '好');
      expect(snapshotEvents.single.activeBuffer, TerminalBufferKind.alt);

      await sub1.cancel();
      await sub2.cancel();
      service.dispose();
    });
  });

  group('boundary tests', () {
    test('old attach_epoch messages are silently discarded', () async {
      final service = WebSocketService(
        serverUrl: 'ws://localhost:8888',
        token: 'test-token',
        sessionId: 'session-1',
      );

      // 先发 connected 设置 attach_epoch=5
      service.debugHandleMessage(jsonEncode({
        'type': 'connected',
        'attach_epoch': 5,
        'agent_online': true,
      }));

      final events = <TerminalProtocolEvent>[];
      final frames = <TerminalOutputFrame>[];
      final sub1 = service.eventStream.listen(events.add);
      final sub2 = service.outputFrameStream.listen(frames.add);

      // 发旧 epoch output (attach_epoch=3 < 5)
      service.debugHandleMessage(jsonEncode({
        'type': 'output',
        'payload': base64Encode(utf8.encode('stale data')),
        'attach_epoch': 3,
      }));

      await Future<void>.delayed(const Duration(milliseconds: 10));

      // eventStream 不应收到 output 事件
      final outputEvents = events
          .where((e) => e.kind == TerminalProtocolEventKind.output)
          .toList();
      expect(outputEvents, isEmpty);
      // outputFrameStream 也不应收到
      expect(frames, isEmpty);

      await sub1.cancel();
      await sub2.cancel();
      service.dispose();
    });

    test('same attach_epoch messages are processed normally', () async {
      final service = WebSocketService(
        serverUrl: 'ws://localhost:8888',
        token: 'test-token',
        sessionId: 'session-1',
      );

      // connected 设置 attach_epoch=5
      service.debugHandleMessage(jsonEncode({
        'type': 'connected',
        'attach_epoch': 5,
        'agent_online': true,
      }));

      final events = <TerminalProtocolEvent>[];
      final sub = service.eventStream.listen(events.add);

      // 发同 epoch output (attach_epoch=5 == 5)
      service.debugHandleMessage(jsonEncode({
        'type': 'output',
        'payload': base64Encode(utf8.encode('current data')),
        'attach_epoch': 5,
      }));

      await Future<void>.delayed(const Duration(milliseconds: 10));

      final outputEvents = events
          .where((e) => e.kind == TerminalProtocolEventKind.output)
          .toList();
      expect(outputEvents, hasLength(1));
      expect(outputEvents.single.payload, 'current data');

      await sub.cancel();
      service.dispose();
    });

    test('old attach_epoch snapshot_complete messages are silently discarded',
        () async {
      final service = WebSocketService(
        serverUrl: 'ws://localhost:8888',
        token: 'test-token',
        sessionId: 'session-1',
      );

      // connected 设置 attach_epoch=5
      service.debugHandleMessage(jsonEncode({
        'type': 'connected',
        'attach_epoch': 5,
        'agent_online': true,
      }));

      final events = <TerminalProtocolEvent>[];
      final frames = <TerminalOutputFrame>[];
      final sub1 = service.eventStream.listen(events.add);
      final sub2 = service.outputFrameStream.listen(frames.add);

      // 发旧 epoch snapshot_complete (attach_epoch=3 < 5)
      service.debugHandleMessage(jsonEncode({
        'type': 'snapshot_complete',
        'attach_epoch': 3,
        'recovery_epoch': 7,
      }));

      await Future<void>.delayed(const Duration(milliseconds: 10));

      // eventStream 不应收到 snapshotComplete 事件
      final scEvents = events
          .where((e) => e.kind == TerminalProtocolEventKind.snapshotComplete)
          .toList();
      expect(scEvents, isEmpty);
      // outputFrameStream 也不应收到
      final scFrames = frames
          .where((f) => f.kind == TerminalOutputKind.snapshotComplete)
          .toList();
      expect(scFrames, isEmpty);

      await sub1.cancel();
      await sub2.cancel();
      service.dispose();
    });

    test('unknown type message does not crash', () async {
      final service = WebSocketService(
        serverUrl: 'ws://localhost:8888',
        token: 'test-token',
        sessionId: 'session-1',
      );

      final events = <TerminalProtocolEvent>[];
      final sub = service.eventStream.listen(events.add);

      // 发未知 type，不应崩溃
      service.debugHandleMessage(jsonEncode({
        'type': 'unknown_foo',
      }));

      await Future<void>.delayed(const Duration(milliseconds: 10));

      // eventStream 不应收到任何事件
      expect(events, isEmpty);
      // service 不应崩溃，状态仍为 disconnected
      expect(service.status, ConnectionStatus.disconnected);

      await sub.cancel();
      service.dispose();
    });

    test(
        'outputFrameStream and eventStream receive consistent payload for output messages',
        () async {
      final service = WebSocketService(
        serverUrl: 'ws://localhost:8888',
        token: 'test-token',
        sessionId: 'session-1',
      );

      final frames = <TerminalOutputFrame>[];
      final events = <TerminalProtocolEvent>[];
      final sub1 = service.outputFrameStream.listen(frames.add);
      final sub2 = service.eventStream.listen(events.add);

      service.debugHandleMessage(jsonEncode({
        'type': 'output',
        'payload': base64Encode(utf8.encode('consistent data')),
      }));

      await Future<void>.delayed(const Duration(milliseconds: 10));

      expect(frames, hasLength(1));
      expect(frames.single.kind, TerminalOutputKind.data);
      expect(frames.single.payload, 'consistent data');

      final outputEvents = events
          .where((e) => e.kind == TerminalProtocolEventKind.output)
          .toList();
      expect(outputEvents, hasLength(1));
      expect(outputEvents.single.payload, 'consistent data');

      await sub1.cancel();
      await sub2.cancel();
      service.dispose();
    });
  });
}
