import 'dart:convert';

import 'package:flutter/widgets.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rc_client/services/terminal_session_manager.dart';
import 'package:rc_client/services/websocket_service.dart';
import 'package:xterm/xterm.dart';

/// 测试用 Mock WebSocketService
/// 不发起真实连接，但可以追踪方法调用
class MockWebSocketService extends WebSocketService {
  int disconnectCallCount = 0;
  int connectCallCount = 0;
  final List<String> sentMessages = [];
  bool _mockConnected = false;
  ConnectionStatus _mockStatus = ConnectionStatus.disconnected;
  int? _mockLastCloseCode;
  String? _mockTerminalStatus;

  /// 控制 connect() 是否抛异常
  bool connectShouldThrow = false;
  String connectErrorMessage = 'Connection failed';

  /// 控制 connect() 是否成功（false = 临时失败，设为 reconnecting）
  bool connectSucceeds = true;

  MockWebSocketService({
    super.serverUrl = 'ws://localhost:8888',
    super.token = 'token',
    super.sessionId = '',
    super.deviceId = 'dev-1',
    super.terminalId = 'term-1',
    super.viewType = ViewType.mobile,
  });

  void setMockConnected(bool value) {
    _mockConnected = value;
    _mockStatus =
        value ? ConnectionStatus.connected : ConnectionStatus.disconnected;
  }

  void setMockStatus(ConnectionStatus status) {
    _mockStatus = status;
    _mockConnected = status == ConnectionStatus.connected;
  }

  void setMockLastCloseCode(int? code) {
    _mockLastCloseCode = code;
  }

  void setMockTerminalStatus(String? status) {
    _mockTerminalStatus = status;
  }

  /// 模拟认证失败（closeCode=4001 + disconnected + notifyListeners）
  void simulateAuthFailed() {
    _mockLastCloseCode = 4001;
    _mockConnected = false;
    _mockStatus = ConnectionStatus.disconnected;
    notifyListeners();
  }

  /// 模拟终端被服务端关闭（terminalStatus=closed + disconnected + notifyListeners）
  void simulateTerminalClosed() {
    _mockTerminalStatus = 'closed';
    _mockConnected = false;
    _mockStatus = ConnectionStatus.disconnected;
    notifyListeners();
  }

  @override
  ConnectionStatus get status => _mockStatus;

  @override
  int? get lastCloseCode => _mockLastCloseCode;

  @override
  String? get terminalStatus => _mockTerminalStatus;

  @override
  bool get isAuthFailed =>
      _mockLastCloseCode == 4001 || _mockLastCloseCode == 4011;

  @override
  bool get isConnected => _mockConnected;

  @override
  Future<void> disconnect({bool notify = true}) async {
    disconnectCallCount++;
    _mockConnected = false;
    _mockStatus = ConnectionStatus.disconnected;
  }

  @override
  Future<bool> connect() async {
    connectCallCount++;
    if (connectShouldThrow) {
      throw Exception(connectErrorMessage);
    }
    if (!connectSucceeds) {
      _mockStatus = ConnectionStatus.reconnecting;
      notifyListeners();
      return false;
    }
    _mockConnected = true;
    _mockStatus = ConnectionStatus.connected;
    return true;
  }

  @override
  void send(String data) {
    sentMessages.add(data);
  }
}

extension _TerminalSessionManagerTestAccess on TerminalSessionManager {
  Terminal testEnsureTerminal(
    String? deviceId,
    String terminalId,
    Terminal Function() create, {
    WebSocketService? service,
  }) {
    return ensureRendererAdapter(
      deviceId,
      terminalId,
      create,
      service: service,
    ).terminalForView;
  }

  Terminal? testTerminal(String? deviceId, String terminalId) {
    return getRendererAdapter(deviceId, terminalId)?.terminalForView;
  }
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  group('TerminalSessionManager', () {
    test('reuses existing terminal session for same device and terminal', () {
      final manager = TerminalSessionManager();
      var createCount = 0;

      WebSocketService build() {
        createCount += 1;
        return WebSocketService(
          serverUrl: 'ws://localhost:8888',
          token: 'token',
          sessionId: '',
          deviceId: 'mbp-01',
          terminalId: 'term-1',
        );
      }

      final first = manager.getOrCreate('mbp-01', 'term-1', build);
      final second = manager.getOrCreate('mbp-01', 'term-1', build);

      expect(identical(first, second), isTrue);
      expect(createCount, 1);

      manager.disconnectAll();
    });

    test('reuses existing Terminal instance for same device and terminal', () {
      final manager = TerminalSessionManager();
      var createCount = 0;

      Terminal build() {
        createCount += 1;
        return Terminal(maxLines: 10000);
      }

      final first = manager.testEnsureTerminal('mbp-01', 'term-1', build);
      first.write('hello');
      final second = manager.testEnsureTerminal('mbp-01', 'term-1', build);

      expect(identical(first, second), isTrue);
      expect(createCount, 1);
      expect(second.buffer.lines[0].toString(), contains('hello'));
    });

    test(
        'replaces cached terminal buffer when snapshot arrives after reconnect',
        () async {
      final manager = TerminalSessionManager();
      final firstService = MockWebSocketService(
        sessionId: 'session-1',
        deviceId: 'mbp-01',
        terminalId: 'term-1',
      );

      final terminal = manager.testEnsureTerminal(
        'mbp-01',
        'term-1',
        () => Terminal(maxLines: 10000),
        service: firstService,
      );

      firstService.debugHandleMessage(jsonEncode({
        'type': 'data',
        'payload': base64Encode(utf8.encode('stale frame')),
      }));
      await Future<void>.delayed(const Duration(milliseconds: 10));
      expect(terminal.buffer.lines[0].toString(), contains('stale frame'));

      final reconnectedService = MockWebSocketService(
        sessionId: 'session-1',
        deviceId: 'mbp-01',
        terminalId: 'term-1',
      );
      manager.bindTerminalOutput('mbp-01', 'term-1', reconnectedService);

      reconnectedService.debugHandleMessage(jsonEncode({
        'type': 'snapshot',
        'payload': base64Encode(utf8.encode('fresh snapshot')),
      }));
      await Future<void>.delayed(const Duration(milliseconds: 10));

      expect(
          terminal.buffer.lines[0].toString(), isNot(contains('stale frame')));
      expect(terminal.buffer.lines[0].toString(), contains('fresh snapshot'));
    });

    test('does not let later snapshot clobber existing live terminal buffer',
        () async {
      final manager = TerminalSessionManager();
      final service = MockWebSocketService(
        sessionId: 'session-1',
        deviceId: 'mbp-01',
        terminalId: 'term-1',
      );

      final terminal = manager.testEnsureTerminal(
        'mbp-01',
        'term-1',
        () => Terminal(maxLines: 10000),
        service: service,
      );

      service.debugHandleMessage(jsonEncode({
        'type': 'data',
        'payload': base64Encode(utf8.encode('codex live frame')),
      }));
      await Future<void>.delayed(const Duration(milliseconds: 10));
      expect(terminal.buffer.lines[0].toString(), contains('codex live frame'));

      service.debugHandleMessage(jsonEncode({
        'type': 'snapshot',
        'payload': base64Encode(utf8.encode('truncated snapshot')),
      }));
      await Future<void>.delayed(const Duration(milliseconds: 10));

      expect(
        terminal.buffer.lines[0].toString(),
        contains('codex live frame'),
      );
      expect(
        terminal.buffer.lines[0].toString(),
        isNot(contains('truncated snapshot')),
      );
    });

    test('applies authoritative remote pty resize to cached terminal',
        () async {
      final manager = TerminalSessionManager();
      final service = MockWebSocketService(
        sessionId: 'session-1',
        deviceId: 'mbp-01',
        terminalId: 'term-1',
      );

      final terminal = manager.testEnsureTerminal(
        'mbp-01',
        'term-1',
        () => Terminal(maxLines: 10000),
        service: service,
      );

      service.debugHandleMessage(jsonEncode({
        'type': 'resize',
        'rows': 36,
        'cols': 110,
      }));
      await Future<void>.delayed(const Duration(milliseconds: 10));

      expect(terminal.viewHeight, 36);
      expect(terminal.viewWidth, 110);
    });

    test('restores alternate snapshot without leaking alt content into main',
        () async {
      final manager = TerminalSessionManager();
      final service = MockWebSocketService(
        sessionId: 'session-1',
        deviceId: 'mbp-01',
        terminalId: 'term-1',
      );

      final terminal = manager.testEnsureTerminal(
        'mbp-01',
        'term-1',
        () => Terminal(maxLines: 10000),
        service: service,
      );

      service.debugHandleMessage(jsonEncode({'type': 'connected'}));
      service.debugHandleMessage(jsonEncode({
        'type': 'snapshot_chunk',
        'payload': base64Encode(utf8.encode('alternate snapshot body')),
        'active_buffer': 'alt',
      }));
      service.debugHandleMessage(jsonEncode({'type': 'snapshot_complete'}));
      service.debugHandleMessage(jsonEncode({
        'type': 'output',
        'payload': base64Encode(
          utf8.encode('\x1b[?1049lrestored shell prompt'),
        ),
      }));

      await Future<void>.delayed(const Duration(milliseconds: 10));

      expect(terminal.isUsingAltBuffer, isFalse);
      expect(
        terminal.mainBuffer.lines[0].toString(),
        contains('restored shell prompt'),
      );
      expect(
        terminal.mainBuffer.lines[0].toString(),
        isNot(contains('alternate snapshot body')),
      );
      expect(
        terminal.altBuffer.lines[0].toString(),
        contains('alternate snapshot body'),
      );
    });
  });

  group('TerminalSessionManager lifecycle - 正常路径', () {
    late TerminalSessionManager manager;

    MockWebSocketService buildMock({
      String deviceId = 'dev-1',
      String terminalId = 'term-1',
      ViewType viewType = ViewType.mobile,
    }) {
      return MockWebSocketService(
        deviceId: deviceId,
        terminalId: terminalId,
        viewType: viewType,
      );
    }

    setUp(() {
      manager = TerminalSessionManager();
    });

    tearDown(() {
      manager.disconnectAll();
    });

    test('pauseAll 断开所有已连接 service，保留 map 条目', () async {
      final mock1 = buildMock(deviceId: 'dev-1', terminalId: 'term-1');
      final mock2 = buildMock(deviceId: 'dev-2', terminalId: 'term-2');

      manager.getOrCreate('dev-1', 'term-1', () => mock1);
      manager.getOrCreate('dev-2', 'term-2', () => mock2);

      mock1.setMockConnected(true);
      mock2.setMockConnected(true);

      manager.pauseAll();

      expect(mock1.disconnectCallCount, 1);
      expect(mock2.disconnectCallCount, 1);
      expect(manager.get('dev-1', 'term-1'), isNotNull);
      expect(manager.get('dev-2', 'term-2'), isNotNull);
    });

    test('pauseAll 不操作未连接的 service', () async {
      final mock = buildMock();
      manager.getOrCreate('dev-1', 'term-1', () => mock);

      manager.pauseAll();
      expect(mock.disconnectCallCount, 0);
    });

    test('resumeAll 重连暂停前已连接的 service', () async {
      final mock = buildMock();
      manager.getOrCreate('dev-1', 'term-1', () => mock);
      manager.testEnsureTerminal(
        'dev-1',
        'term-1',
        () => Terminal(maxLines: 10000),
      );

      mock.setMockConnected(true);
      manager.pauseAll();
      expect(mock.disconnectCallCount, 1);

      await manager.resumeAll();
      expect(mock.connectCallCount, 1);
    });

    test('手动 disconnect 的 service 不被 resumeAll 重连', () async {
      final mock = buildMock();
      manager.getOrCreate('dev-1', 'term-1', () => mock);

      mock.setMockConnected(true);
      manager.pauseAll();

      await manager.disconnectTerminal('dev-1', 'term-1');
      await manager.resumeAll();

      expect(mock.connectCallCount, 0);
    });

    test('disconnectTerminal 同时清理 cached Terminal', () async {
      final mock = buildMock();
      manager.getOrCreate('dev-1', 'term-1', () => mock);
      manager.testEnsureTerminal(
        'dev-1',
        'term-1',
        () => Terminal(maxLines: 10000),
      );

      await manager.disconnectTerminal('dev-1', 'term-1');

      expect(manager.get('dev-1', 'term-1'), isNull);
      expect(manager.testTerminal('dev-1', 'term-1'), isNull);
    });

    test('pause 后新增的 service 不被 resumeAll 影响', () async {
      manager.pauseAll();

      final newMock = buildMock(deviceId: 'dev-new', terminalId: 'term-new');
      manager.getOrCreate('dev-new', 'term-new', () => newMock);

      await manager.resumeAll();
      expect(newMock.connectCallCount, 0);
    });

    test('连续 pause-resume 不导致重复连接', () async {
      final mock = buildMock();
      manager.getOrCreate('dev-1', 'term-1', () => mock);
      manager.testEnsureTerminal(
        'dev-1',
        'term-1',
        () => Terminal(maxLines: 10000),
      );

      // 第一轮
      mock.setMockConnected(true);
      manager.pauseAll();
      await manager.resumeAll();
      expect(mock.connectCallCount, 1);

      // 第二轮
      mock.setMockConnected(true);
      manager.pauseAll();
      await manager.resumeAll();
      expect(mock.connectCallCount, 2);
    });

    test('pauseAll 混合 connected/disconnected 状态', () async {
      final connected = buildMock(deviceId: 'dev-1', terminalId: 'term-1');
      final disconnected = buildMock(deviceId: 'dev-2', terminalId: 'term-2');

      manager.getOrCreate('dev-1', 'term-1', () => connected);
      manager.getOrCreate('dev-2', 'term-2', () => disconnected);
      manager.testEnsureTerminal(
        'dev-1',
        'term-1',
        () => Terminal(maxLines: 10000),
      );

      connected.setMockConnected(true);

      manager.pauseAll();

      expect(connected.disconnectCallCount, 1);
      expect(disconnected.disconnectCallCount, 0);

      await manager.resumeAll();
      expect(connected.connectCallCount, 1);
      expect(disconnected.connectCallCount, 0);
    });
  });

  group('TerminalSessionManager lifecycle - 边界条件', () {
    late TerminalSessionManager manager;

    MockWebSocketService buildMock({
      String deviceId = 'dev-1',
      String terminalId = 'term-1',
      ViewType viewType = ViewType.mobile,
    }) {
      return MockWebSocketService(
        deviceId: deviceId,
        terminalId: terminalId,
        viewType: viewType,
      );
    }

    setUp(() {
      manager = TerminalSessionManager();
    });

    tearDown(() {
      manager.disconnectAll();
    });

    test('空 manager 调用 pauseAll 不报错', () {
      expect(() => manager.pauseAll(), returnsNormally);
    });

    test('空 manager 调用 resumeAll 不报错', () async {
      await expectLater(manager.resumeAll(), completes);
    });

    test('连续调用 pauseAll 不会累积重复 key', () {
      final mock = buildMock();
      manager.getOrCreate('dev-1', 'term-1', () => mock);

      mock.setMockConnected(true);
      manager.pauseAll();
      manager.pauseAll(); // 第二次 pause 应该重置 _pausedKeys

      // 第二次 pauseAll 时 mock 已经是 disconnected（第一次 pause 断开了）
      // 所以 disconnect 被调用 1 次（只有第一次 pause 时 connected）
      expect(mock.disconnectCallCount, 1);
    });

    test('resumeAll 时 service 已被外部恢复连接则不重复 connect', () async {
      final mock = buildMock();
      manager.getOrCreate('dev-1', 'term-1', () => mock);

      mock.setMockConnected(true);
      manager.pauseAll();

      // 模拟外部已恢复连接（比如 WebSocketService 自身的 autoReconnect）
      mock.setMockConnected(true);

      await manager.resumeAll();

      // service 已经是 connected，resumeAll 不应调用 connect
      expect(mock.connectCallCount, 0);
    });

    test('pauseAll 不操作 connecting 状态的 service', () {
      final mock = buildMock();
      manager.getOrCreate('dev-1', 'term-1', () => mock);

      mock.setMockStatus(ConnectionStatus.connecting);
      manager.pauseAll();

      expect(mock.disconnectCallCount, 0);
    });

    test('pauseAll 不操作 error 状态的 service', () {
      final mock = buildMock();
      manager.getOrCreate('dev-1', 'term-1', () => mock);

      mock.setMockStatus(ConnectionStatus.error);
      manager.pauseAll();

      expect(mock.disconnectCallCount, 0);
    });

    test('pauseAll 不操作 reconnecting 状态的 service', () {
      final mock = buildMock();
      manager.getOrCreate('dev-1', 'term-1', () => mock);

      mock.setMockStatus(ConnectionStatus.reconnecting);
      manager.pauseAll();

      expect(mock.disconnectCallCount, 0);
    });

    test('disconnectAll 后 pauseAll/resumeAll 安全执行', () async {
      final mock = buildMock();
      manager.getOrCreate('dev-1', 'term-1', () => mock);
      mock.setMockConnected(true);
      manager.testEnsureTerminal(
        'dev-1',
        'term-1',
        () => Terminal(maxLines: 10000),
      );

      await manager.disconnectAll();

      // disconnectAll 清空了所有状态
      expect(() => manager.pauseAll(), returnsNormally);
      await expectLater(manager.resumeAll(), completes);
      expect(manager.testTerminal('dev-1', 'term-1'), isNull);
    });

    test('桌面端 pauseAll/resumeAll 安全调用', () async {
      final mgr = TerminalSessionManager();
      mgr.pauseAll();
      await mgr.resumeAll();
      mgr.disconnectAll();
    });

    test('dispose 移除 observer 不报错', () {
      final disposableManager = TerminalSessionManager();
      disposableManager.dispose();
    });
  });

  group('TerminalSessionManager lifecycle - 异常路径', () {
    late TerminalSessionManager manager;

    MockWebSocketService buildMock({
      String deviceId = 'dev-1',
      String terminalId = 'term-1',
      ViewType viewType = ViewType.mobile,
    }) {
      return MockWebSocketService(
        deviceId: deviceId,
        terminalId: terminalId,
        viewType: viewType,
      );
    }

    setUp(() {
      manager = TerminalSessionManager();
    });

    tearDown(() {
      manager.disconnectAll();
    });

    test('resumeAll 中 connect 抛异常不阻塞其他 service', () async {
      final failMock = buildMock(deviceId: 'dev-1', terminalId: 'term-1');
      final okMock = buildMock(deviceId: 'dev-2', terminalId: 'term-2');

      failMock.connectShouldThrow = true;
      failMock.connectErrorMessage = 'token expired';

      manager.getOrCreate('dev-1', 'term-1', () => failMock);
      manager.getOrCreate('dev-2', 'term-2', () => okMock);
      manager.testEnsureTerminal(
        'dev-1',
        'term-1',
        () => Terminal(maxLines: 10000),
      );
      manager.testEnsureTerminal(
        'dev-2',
        'term-2',
        () => Terminal(maxLines: 10000),
      );

      failMock.setMockConnected(true);
      okMock.setMockConnected(true);

      manager.pauseAll();

      // resumeAll 应该继续处理后续 service，即使第一个失败
      await manager.resumeAll();

      // failMock 尝试了 connect 但失败（recoverWithRetry 重试 3 次）
      expect(failMock.connectCallCount, 3);
      // okMock 仍然成功重连
      expect(okMock.connectCallCount, 1);
    });

    test('resumeAll 全部 connect 失败不崩溃', () async {
      final mock = buildMock();
      mock.connectShouldThrow = true;

      manager.getOrCreate('dev-1', 'term-1', () => mock);
      manager.testEnsureTerminal(
        'dev-1',
        'term-1',
        () => Terminal(maxLines: 10000),
      );
      mock.setMockConnected(true);

      manager.pauseAll();

      // 即使全部失败也不应抛出未捕获的异常（recoverWithRetry 重试 3 次）
      await expectLater(manager.resumeAll(), completes);
      expect(mock.connectCallCount, 3);
    });

    // 注意：pauseAll 中 disconnect() 是 fire-and-forget（不 await），
    // async 异常无法被 sync try-catch 捕获（dart 语言限制）。
    // 真实的 WebSocketService.disconnect() 设计上不会抛异常（只做 cancel/close），
    // 所以不测试 pauseAll 的 disconnect 异常场景。
  });

  group('TerminalSessionManager - auth-failed eviction', () {
    late TerminalSessionManager manager;

    MockWebSocketService buildMock({
      String deviceId = 'dev-1',
      String terminalId = 'term-1',
      ViewType viewType = ViewType.mobile,
    }) {
      return MockWebSocketService(
        deviceId: deviceId,
        terminalId: terminalId,
        viewType: viewType,
      );
    }

    setUp(() {
      manager = TerminalSessionManager();
    });

    tearDown(() {
      manager.disconnectAll();
    });

    test('getOrCreate 自动淘汰 closeCode=4001 的缓存服务', () {
      var createCount = 0;
      final mock1 = buildMock();
      mock1.setMockLastCloseCode(4001);

      WebSocketService build() {
        createCount++;
        if (createCount == 1) return mock1;
        return buildMock();
      }

      // 首次创建
      final first = manager.getOrCreate('dev-1', 'term-1', build);
      expect(identical(first, mock1), isTrue);
      expect(createCount, 1);
      final firstTerminal = manager.testEnsureTerminal(
        'dev-1',
        'term-1',
        () => Terminal(maxLines: 10000),
      );

      // 第二次调用：mock1 的 lastCloseCode=4001，应被淘汰并重建，
      // 但 cached terminal 应保留，避免 terminal 切换后内容丢失。
      final second = manager.getOrCreate('dev-1', 'term-1', build);
      expect(identical(second, mock1), isFalse);
      expect(createCount, 2);
      expect(mock1.disconnectCallCount, 1);
      final secondTerminal = manager.testEnsureTerminal(
        'dev-1',
        'term-1',
        () => Terminal(maxLines: 10000),
      );
      expect(identical(firstTerminal, secondTerminal), isTrue);
    });

    test('getOrCreate 自动淘汰 closeCode=4011 的缓存服务', () {
      var createCount = 0;
      final mock1 = buildMock();
      mock1.setMockLastCloseCode(4011);

      WebSocketService build() {
        createCount++;
        if (createCount == 1) return mock1;
        return buildMock();
      }

      final first = manager.getOrCreate('dev-1', 'term-1', build);
      expect(identical(first, mock1), isTrue);

      final second = manager.getOrCreate('dev-1', 'term-1', build);
      expect(identical(second, mock1), isFalse);
      expect(createCount, 2);
    });

    test('getOrCreate 不淘汰正常断开的缓存服务', () {
      var createCount = 0;
      final mock1 = buildMock();
      // lastCloseCode 为 null（正常断开）
      mock1.setMockLastCloseCode(null);

      WebSocketService build() {
        createCount++;
        return mock1;
      }

      final first = manager.getOrCreate('dev-1', 'term-1', build);
      final second = manager.getOrCreate('dev-1', 'term-1', build);

      expect(identical(first, second), isTrue);
      expect(createCount, 1);
    });

    test('getOrCreate 不淘汰 closeCode=4503 的缓存服务', () {
      var createCount = 0;
      final mock1 = buildMock();
      // 4503 = Agent 离线，属于正常断开，应复用
      mock1.setMockLastCloseCode(4503);

      WebSocketService build() {
        createCount++;
        return mock1;
      }

      final first = manager.getOrCreate('dev-1', 'term-1', build);
      final second = manager.getOrCreate('dev-1', 'term-1', build);

      expect(identical(first, second), isTrue);
      expect(createCount, 1);
    });

    test('eviction 时同时清理 _pausedKeys', () async {
      final mock1 = buildMock();
      mock1.setMockConnected(true);
      manager.getOrCreate('dev-1', 'term-1', () => mock1);

      // pauseAll 将 key 加入 _pausedKeys
      manager.pauseAll();

      // 标记为 auth-failed
      mock1.setMockLastCloseCode(4001);

      // getOrCreate 应淘汰并清理 _pausedKeys
      final newService =
          manager.getOrCreate('dev-1', 'term-1', () => buildMock());
      expect(identical(newService, mock1), isFalse);

      // resumeAll 不应尝试重连已被淘汰的 mock1
      await manager.resumeAll();
      expect(mock1.connectCallCount, 0);
    });

    test('eviction 后新服务可正常使用', () async {
      final mock1 = buildMock();
      mock1.setMockLastCloseCode(4001);
      manager.getOrCreate('dev-1', 'term-1', () => mock1);

      final mock2 = buildMock();
      final service = manager.getOrCreate('dev-1', 'term-1', () => mock2);
      expect(identical(service, mock2), isTrue);

      // 新服务可正常连接
      mock2.setMockConnected(true);
      expect(service.isConnected, isTrue);
    });

    test('切换 terminal 前主动断开同 device 同 view 的其他 service', () async {
      final current = buildMock(deviceId: 'dev-1', terminalId: 'term-1');
      final next = buildMock(deviceId: 'dev-1', terminalId: 'term-2');
      final desktop = buildMock(
        deviceId: 'dev-1',
        terminalId: 'term-3',
        viewType: ViewType.desktop,
      );
      final otherDevice = buildMock(deviceId: 'dev-2', terminalId: 'term-4');

      manager.getOrCreate('dev-1', 'term-1', () => current);
      manager.getOrCreate('dev-1', 'term-2', () => next);
      manager.getOrCreate('dev-1', 'term-3', () => desktop);
      manager.getOrCreate('dev-2', 'term-4', () => otherDevice);

      current.setMockConnected(true);
      next.setMockConnected(true);
      desktop.setMockConnected(true);
      otherDevice.setMockConnected(true);

      await manager.deactivateConflictingTerminalSessions(next);

      expect(current.disconnectCallCount, 1);
      expect(next.disconnectCallCount, 0);
      expect(desktop.disconnectCallCount, 0);
      expect(otherDevice.disconnectCallCount, 0);
    });
  });

  group('TerminalSessionManager lifecycle - 集成测试', () {
    late TerminalSessionManager manager;

    MockWebSocketService buildMock({
      String deviceId = 'dev-1',
      String terminalId = 'term-1',
    }) {
      return MockWebSocketService(
        deviceId: deviceId,
        terminalId: terminalId,
      );
    }

    setUp(() {
      manager = TerminalSessionManager();
    });

    tearDown(() {
      manager.disconnectAll();
    });

    test('didChangeAppLifecycleState(paused) 触发 pauseAll', () async {
      final mock = buildMock();
      manager.getOrCreate('dev-1', 'term-1', () => mock);
      mock.setMockConnected(true);

      // 模拟 App 进入后台
      manager.didChangeAppLifecycleState(AppLifecycleState.paused);

      expect(mock.disconnectCallCount, 1);
      expect(manager.get('dev-1', 'term-1'), isNotNull);
    });

    test('didChangeAppLifecycleState(inactive) 触发 pauseAll', () async {
      final mock = buildMock();
      manager.getOrCreate('dev-1', 'term-1', () => mock);
      mock.setMockConnected(true);

      manager.didChangeAppLifecycleState(AppLifecycleState.inactive);

      expect(mock.disconnectCallCount, 1);
    });

    test('didChangeAppLifecycleState(resumed) 触发 resumeAll（通过直接调用验证）',
        () async {
      final mock = buildMock();
      manager.getOrCreate('dev-1', 'term-1', () => mock);
      manager.testEnsureTerminal(
        'dev-1',
        'term-1',
        () => Terminal(maxLines: 10000),
      );
      mock.setMockConnected(true);

      // 先通过 lifecycle 回调暂停
      manager.didChangeAppLifecycleState(AppLifecycleState.paused);
      expect(mock.disconnectCallCount, 1);

      // resumed 回调内部调用 resumeAll() 是 fire-and-forget，
      // 所以直接调用 resumeAll() 来验证完整链路
      await manager.resumeAll();
      expect(mock.connectCallCount, 1);
    });

    test('完整后台-前台周期：paused → resumed', () async {
      final mock1 = buildMock(deviceId: 'dev-1', terminalId: 'term-1');
      final mock2 = buildMock(deviceId: 'dev-2', terminalId: 'term-2');

      manager.getOrCreate('dev-1', 'term-1', () => mock1);
      manager.getOrCreate('dev-2', 'term-2', () => mock2);
      manager.testEnsureTerminal(
        'dev-1',
        'term-1',
        () => Terminal(maxLines: 10000),
      );
      manager.testEnsureTerminal(
        'dev-2',
        'term-2',
        () => Terminal(maxLines: 10000),
      );

      mock1.setMockConnected(true);
      mock2.setMockConnected(true);

      // 进入后台
      manager.didChangeAppLifecycleState(AppLifecycleState.paused);

      expect(mock1.disconnectCallCount, 1);
      expect(mock2.disconnectCallCount, 1);
      expect(mock1.connectCallCount, 0);
      expect(mock2.connectCallCount, 0);
      // map 条目保留
      expect(manager.get('dev-1', 'term-1'), same(mock1));
      expect(manager.get('dev-2', 'term-2'), same(mock2));

      // 回到前台（resumeAll 是异步的，直接调用来验证链路）
      await manager.resumeAll();

      expect(mock1.connectCallCount, 1);
      expect(mock2.connectCallCount, 1);
    });

    test('detached 状态不触发任何操作', () async {
      final mock = buildMock();
      manager.getOrCreate('dev-1', 'term-1', () => mock);
      mock.setMockConnected(true);

      manager.didChangeAppLifecycleState(AppLifecycleState.detached);

      expect(mock.disconnectCallCount, 0);
      expect(mock.connectCallCount, 0);
    });

    test('notifyListeners 在 disconnectAll 时被调用', () async {
      final mock = buildMock();
      manager.getOrCreate('dev-1', 'term-1', () => mock);
      mock.setMockConnected(true);

      int notifyCount = 0;
      manager.addListener(() => notifyCount++);

      await manager.disconnectAll();

      expect(notifyCount, 1);
    });

    test('多次 pause-resume 周期稳定性', () async {
      final mock = buildMock();
      manager.getOrCreate('dev-1', 'term-1', () => mock);
      manager.testEnsureTerminal(
        'dev-1',
        'term-1',
        () => Terminal(maxLines: 10000),
      );

      for (int i = 0; i < 5; i++) {
        mock.setMockConnected(true);
        manager.didChangeAppLifecycleState(AppLifecycleState.paused);
        // resumeAll 直接调用以确保异步完成
        await manager.resumeAll();
      }

      // 每轮 pause 断开一次，每轮 resume 重连一次
      expect(mock.disconnectCallCount, 5);
      expect(mock.connectCallCount, 5);
    });
  });

  // ─── F072: Coordinator 状态机测试 ─────────────────────────────

  group('Coordinator 状态机', () {
    late TerminalSessionManager manager;

    MockWebSocketService buildMock({
      String deviceId = 'dev-1',
      String terminalId = 'term-1',
    }) {
      return MockWebSocketService(
        deviceId: deviceId,
        terminalId: terminalId,
      );
    }

    setUp(() {
      manager = TerminalSessionManager();
    });

    tearDown(() {
      manager.disconnectAll();
    });

    test('idle -> connecting -> recovering -> live 完整路径', () async {
      final mock = buildMock();
      manager.getOrCreate('dev-1', 'term-1', () => mock);

      final terminal = manager.testEnsureTerminal(
        'dev-1',
        'term-1',
        () => Terminal(maxLines: 10000),
        service: mock,
      );
      expect(terminal, isNotNull);

      // 初始状态为 idle
      expect(manager.getTerminalState('dev-1', 'term-1'),
          TerminalSessionState.idle);

      // connectTerminal: idle -> connecting
      await manager.connectTerminal('dev-1', 'term-1');
      expect(manager.getTerminalState('dev-1', 'term-1'),
          TerminalSessionState.connecting);

      // 模拟 connected 事件：connecting -> recovering
      mock.debugHandleMessage(jsonEncode({'type': 'connected'}));
      await Future<void>.delayed(const Duration(milliseconds: 10));
      expect(manager.getTerminalState('dev-1', 'term-1'),
          TerminalSessionState.recovering);

      // 模拟 snapshot
      mock.debugHandleMessage(jsonEncode({
        'type': 'snapshot',
        'payload': base64Encode(utf8.encode('snapshot data')),
      }));
      await Future<void>.delayed(const Duration(milliseconds: 10));

      // 仍然是 recovering
      expect(manager.getTerminalState('dev-1', 'term-1'),
          TerminalSessionState.recovering);

      // snapshot_complete: recovering -> live
      mock.debugHandleMessage(jsonEncode({'type': 'snapshot_complete'}));
      await Future<void>.delayed(const Duration(milliseconds: 10));
      expect(manager.getTerminalState('dev-1', 'term-1'),
          TerminalSessionState.live);
    });

    test('switch 只切 active，不改变 sessionState', () async {
      final mock1 = buildMock(deviceId: 'dev-1', terminalId: 'term-1');
      final mock2 = buildMock(deviceId: 'dev-1', terminalId: 'term-2');

      manager.getOrCreate('dev-1', 'term-1', () => mock1);
      manager.getOrCreate('dev-1', 'term-2', () => mock2);

      manager.testEnsureTerminal(
        'dev-1',
        'term-1',
        () => Terminal(maxLines: 10000),
      );
      manager.testEnsureTerminal(
        'dev-1',
        'term-2',
        () => Terminal(maxLines: 10000),
      );

      // 手动将 term-1 推进到 connecting 状态
      await manager.connectTerminal('dev-1', 'term-1');
      final term1State = manager.getTerminalState('dev-1', 'term-1');
      expect(term1State, TerminalSessionState.connecting);

      // switch 到 term-2
      manager.switchTerminal('dev-1', 'term-2');
      expect(manager.activeTerminalKeyForTest, 'dev-1::term-2');

      // term-1 的状态不变
      expect(manager.getTerminalState('dev-1', 'term-1'),
          TerminalSessionState.connecting);
      // term-2 仍是 idle
      expect(manager.getTerminalState('dev-1', 'term-2'),
          TerminalSessionState.idle);
    });

    test('reconnect 进入 recovering 再到 live', () async {
      final mock = buildMock();
      manager.getOrCreate('dev-1', 'term-1', () => mock);

      manager.testEnsureTerminal(
        'dev-1',
        'term-1',
        () => Terminal(maxLines: 10000),
        service: mock,
      );

      // 先走到 live
      await manager.connectTerminal('dev-1', 'term-1');
      mock.debugHandleMessage(jsonEncode({'type': 'connected'}));
      await Future<void>.delayed(const Duration(milliseconds: 10));
      mock.debugHandleMessage(jsonEncode({'type': 'snapshot_complete'}));
      await Future<void>.delayed(const Duration(milliseconds: 10));
      expect(manager.getTerminalState('dev-1', 'term-1'),
          TerminalSessionState.live);

      // recoverTerminal: live -> reconnecting -> recovering
      manager.recoverTerminal('dev-1', 'term-1');
      expect(manager.getTerminalState('dev-1', 'term-1'),
          TerminalSessionState.recovering);

      // snapshot_complete: recovering -> live
      mock.debugHandleMessage(jsonEncode({'type': 'snapshot_complete'}));
      await Future<void>.delayed(const Duration(milliseconds: 10));
      expect(manager.getTerminalState('dev-1', 'term-1'),
          TerminalSessionState.live);
    });

    test('snapshot_complete 前的 live output 缓冲不直接写入', () async {
      final mock = buildMock();
      manager.getOrCreate('dev-1', 'term-1', () => mock);

      final terminal = manager.testEnsureTerminal(
        'dev-1',
        'term-1',
        () => Terminal(maxLines: 10000),
        service: mock,
      );

      // 先将状态推到 connecting
      await manager.connectTerminal('dev-1', 'term-1');
      expect(manager.getTerminalState('dev-1', 'term-1'),
          TerminalSessionState.connecting);

      // connected 事件触发 beginRecovery：connecting -> recovering
      mock.debugHandleMessage(jsonEncode({'type': 'connected'}));
      await Future<void>.delayed(const Duration(milliseconds: 10));
      expect(manager.getTerminalState('dev-1', 'term-1'),
          TerminalSessionState.recovering);

      // 在 recovering 期间收到 live data，应被缓冲而非直接写入
      mock.debugHandleMessage(jsonEncode({
        'type': 'data',
        'payload': base64Encode(utf8.encode('live data during recovery')),
      }));
      await Future<void>.delayed(const Duration(milliseconds: 10));

      // snapshot_complete 后，缓冲数据应该被 flush
      mock.debugHandleMessage(jsonEncode({'type': 'snapshot_complete'}));
      await Future<void>.delayed(const Duration(milliseconds: 10));

      expect(manager.getTerminalState('dev-1', 'term-1'),
          TerminalSessionState.live);
      // 缓冲的 live data 应该在 finishRecovery 后写入 terminal
      expect(
        terminal.buffer.lines[0].toString(),
        contains('live data during recovery'),
      );
    });

    test('create 失败时 coordinator 进入 error 状态', () async {
      // 不创建 session，connectTerminal 应进入 error
      manager.testEnsureTerminal(
        'dev-1',
        'term-1',
        () => Terminal(maxLines: 10000),
      );

      // 没有 session，connectTerminal 应将状态设为 error
      await manager.connectTerminal('dev-1', 'term-1');
      expect(manager.getTerminalState('dev-1', 'term-1'),
          TerminalSessionState.error);
    });

    test('connect 抛异常时 coordinator 进入 error 状态', () async {
      final mock = buildMock();
      mock.connectShouldThrow = true;
      manager.getOrCreate('dev-1', 'term-1', () => mock);

      manager.testEnsureTerminal(
        'dev-1',
        'term-1',
        () => Terminal(maxLines: 10000),
      );

      await manager.connectTerminal('dev-1', 'term-1');
      expect(manager.getTerminalState('dev-1', 'term-1'),
          TerminalSessionState.error);
    });

    test('获取 terminal 状态和监听状态变化', () async {
      final mock = buildMock();
      manager.getOrCreate('dev-1', 'term-1', () => mock);

      manager.testEnsureTerminal(
        'dev-1',
        'term-1',
        () => Terminal(maxLines: 10000),
      );

      // 初始状态
      expect(manager.getTerminalState('dev-1', 'term-1'),
          TerminalSessionState.idle);

      // 不存在的 terminal 返回 idle
      expect(manager.getTerminalState('dev-1', 'term-999'),
          TerminalSessionState.idle);

      // 获取 listenable 并监听变化
      final listenable = manager.getTerminalStateListenable('dev-1', 'term-1');
      expect(listenable, isNotNull);

      final states = <TerminalSessionState>[];
      listenable!.addListener(() {
        states.add(listenable.value);
      });

      // connectTerminal 触发状态变化
      await manager.connectTerminal('dev-1', 'term-1');
      expect(states, contains(TerminalSessionState.connecting));
    });

    test('不存在的 terminal 调用 connectTerminal 不报错', () async {
      // 不应该抛异常
      await expectLater(
        manager.connectTerminal('dev-999', 'term-999'),
        completes,
      );
    });

    test('不存在的 terminal 调用 recoverTerminal 不报错', () {
      expect(
        () => manager.recoverTerminal('dev-999', 'term-999'),
        returnsNormally,
      );
    });

    test('不存在的 terminal 调用 switchTerminal 不报错', () {
      expect(
        () => manager.switchTerminal('dev-999', 'term-999'),
        returnsNormally,
      );
    });

    test('不存在的 terminal 的 listenable 为 null', () {
      expect(
        manager.getTerminalStateListenable('dev-999', 'term-999'),
        isNull,
      );
    });

    // ─── F072: 状态机转换缺口修复测试 ───────────────────────────

    test('idle bind 已连接 service 直接进入 live', () async {
      final mock = buildMock();
      mock.setMockConnected(true);
      manager.getOrCreate('dev-1', 'term-1', () => mock);

      // 初始状态为 idle
      expect(manager.getTerminalState('dev-1', 'term-1'),
          TerminalSessionState.idle);

      // 已经 connected 的现有 transport 只是晚绑定到 UI/coordinator，
      // 不应伪造 recovering，否则会无期限等待 snapshot_complete。
      manager.testEnsureTerminal(
        'dev-1',
        'term-1',
        () => Terminal(maxLines: 10000),
        service: mock,
      );

      // idle -> live
      expect(manager.getTerminalState('dev-1', 'term-1'),
          TerminalSessionState.live);
    });

    test('live rebind 到已连接新 service 保持 live', () async {
      final mock = buildMock();
      manager.getOrCreate('dev-1', 'term-1', () => mock);

      manager.testEnsureTerminal(
        'dev-1',
        'term-1',
        () => Terminal(maxLines: 10000),
        service: mock,
      );

      // 先完成一次完整的 connect -> live 周期
      await manager.connectTerminal('dev-1', 'term-1');
      mock.debugHandleMessage(jsonEncode({'type': 'connected'}));
      await Future<void>.delayed(const Duration(milliseconds: 10));
      mock.debugHandleMessage(jsonEncode({'type': 'snapshot_complete'}));
      await Future<void>.delayed(const Duration(milliseconds: 10));
      expect(manager.getTerminalState('dev-1', 'term-1'),
          TerminalSessionState.live);

      // 用一个新的 service 进行 rebind
      final newMock = buildMock();
      newMock.setMockConnected(true);
      manager.bindTerminalOutput('dev-1', 'term-1', newMock);

      // 已经 live 的 replacement service 不应凭空触发 recovering
      expect(manager.getTerminalState('dev-1', 'term-1'),
          TerminalSessionState.live);
    });

    test('bindTerminalOutput 将 terminal onOutput 路由到当前 service', () {
      final mock = buildMock();
      manager.getOrCreate('dev-1', 'term-1', () => mock);

      final terminal = manager.testEnsureTerminal(
        'dev-1',
        'term-1',
        () => Terminal(maxLines: 10000),
        service: mock,
      );

      terminal.write('\x1b[6n');

      expect(mock.sentMessages, contains('\x1b[1;1R'));
    });

    test('rebind 后 terminal onOutput 切换到新 service', () {
      final mock = buildMock();
      manager.getOrCreate('dev-1', 'term-1', () => mock);

      final terminal = manager.testEnsureTerminal(
        'dev-1',
        'term-1',
        () => Terminal(maxLines: 10000),
        service: mock,
      );

      terminal.setCursor(1, 1);
      terminal.write('\x1b[6n');
      expect(mock.sentMessages, contains('\x1b[2;2R'));
      mock.sentMessages.clear();

      final newMock = buildMock();
      newMock.setMockConnected(true);
      manager.bindTerminalOutput('dev-1', 'term-1', newMock);

      terminal.setCursor(4, 3);
      terminal.write('\x1b[6n');

      expect(mock.sentMessages, isEmpty);
      expect(newMock.sentMessages, contains('\x1b[4;5R'));
    });

    test('Ctrl+C 后 shell prompt 到来时丢弃迟到的终端自动应答', () async {
      final mock = buildMock();
      manager.getOrCreate('dev-1', 'term-1', () => mock);

      final terminal = manager.testEnsureTerminal(
        'dev-1',
        'term-1',
        () => Terminal(maxLines: 10000),
        service: mock,
      );

      terminal.onOutput?.call('\x03');
      terminal.write('\x1b[c');

      expect(mock.sentMessages, contains('\x03'));
      expect(mock.sentMessages, isNot(contains('\x1b[?1;2c')));

      mock.debugHandleMessage(jsonEncode({
        'type': 'output',
        'payload': base64Encode(utf8.encode('bash-3.2\$ ')),
      }));
      await Future<void>.delayed(const Duration(milliseconds: 20));

      expect(mock.sentMessages, isNot(contains('\x1b[?1;2c')));
    });

    test('Ctrl+C 后若未退出则延迟放行终端自动应答', () async {
      final mock = buildMock();
      manager.getOrCreate('dev-1', 'term-1', () => mock);

      final terminal = manager.testEnsureTerminal(
        'dev-1',
        'term-1',
        () => Terminal(maxLines: 10000),
        service: mock,
      );

      terminal.onOutput?.call('\x03');
      terminal.write('\x1b[c');

      expect(mock.sentMessages, contains('\x03'));
      expect(mock.sentMessages, isNot(contains('\x1b[?1;2c')));

      await Future<void>.delayed(const Duration(milliseconds: 450));

      expect(mock.sentMessages, contains('\x1b[?1;2c'));
    });

    test('recovery 窗口内的终端自动应答被丢弃，不在稍后补发', () async {
      final mock = buildMock();
      manager.getOrCreate('dev-1', 'term-1', () => mock);

      final terminal = manager.testEnsureTerminal(
        'dev-1',
        'term-1',
        () => Terminal(maxLines: 10000),
        service: mock,
      );

      await manager.connectTerminal('dev-1', 'term-1');
      mock.debugHandleMessage(jsonEncode({'type': 'connected'}));
      await Future<void>.delayed(const Duration(milliseconds: 20));

      terminal.write('\x1b[c');
      expect(mock.sentMessages, isNot(contains('\x1b[?1;2c')));

      await Future<void>.delayed(const Duration(milliseconds: 2200));
      expect(mock.sentMessages, isNot(contains('\x1b[?1;2c')));
    });

    test('idle bind 已连接 service 直接消费 live output', () async {
      final mock = buildMock();
      mock.setMockConnected(true);
      manager.getOrCreate('dev-1', 'term-1', () => mock);

      final terminal = manager.testEnsureTerminal(
        'dev-1',
        'term-1',
        () => Terminal(maxLines: 10000),
        service: mock,
      );

      // idle -> live
      expect(manager.getTerminalState('dev-1', 'term-1'),
          TerminalSessionState.live);

      // 直接到达 live output，不应被错误缓冲
      mock.debugHandleMessage(jsonEncode({
        'type': 'output',
        'payload': base64Encode(utf8.encode('live output')),
      }));
      await Future<void>.delayed(const Duration(milliseconds: 10));

      expect(manager.getTerminalState('dev-1', 'term-1'),
          TerminalSessionState.live);
      expect(
        terminal.buffer.lines[0].toString(),
        contains('live output'),
      );
    });

    // ─── F074: statusListener + connect() 永久失败区分 ────────

    test('connect 临时失败不设 error（autoReconnect 可恢复）', () async {
      final mock = buildMock();
      mock.connectSucceeds = false; // connect 返回 false，状态为 reconnecting
      manager.getOrCreate('dev-1', 'term-1', () => mock);

      manager.testEnsureTerminal(
        'dev-1',
        'term-1',
        () => Terminal(maxLines: 10000),
        service: mock,
      );

      await manager.connectTerminal('dev-1', 'term-1');

      // 临时失败：不应设为 error
      final state = manager.getTerminalState('dev-1', 'term-1');
      expect(state, isNot(equals(TerminalSessionState.error)));
    });

    test('connect auth_failed 时 statusListener 收敛到 error', () async {
      final mock = buildMock();
      manager.getOrCreate('dev-1', 'term-1', () => mock);

      manager.testEnsureTerminal(
        'dev-1',
        'term-1',
        () => Terminal(maxLines: 10000),
        service: mock,
      );

      // 先连接成功 + connected 事件进入 recovering
      await manager.connectTerminal('dev-1', 'term-1');
      mock.debugHandleMessage(jsonEncode({'type': 'connected'}));
      await Future<void>.delayed(const Duration(milliseconds: 10));
      expect(
        manager.getTerminalState('dev-1', 'term-1'),
        TerminalSessionState.recovering,
      );

      // 模拟 auth_failed 断线
      mock.simulateAuthFailed();

      // statusListener 应将 recovering 收敛到 error
      expect(
        manager.getTerminalState('dev-1', 'term-1'),
        TerminalSessionState.error,
      );
    });

    test('terminal_closed 时 statusListener 收敛到 error', () async {
      final mock = buildMock();
      manager.getOrCreate('dev-1', 'term-1', () => mock);

      manager.testEnsureTerminal(
        'dev-1',
        'term-1',
        () => Terminal(maxLines: 10000),
        service: mock,
      );

      // 先连接成功 + connected 事件进入 recovering
      await manager.connectTerminal('dev-1', 'term-1');
      mock.debugHandleMessage(jsonEncode({'type': 'connected'}));
      await Future<void>.delayed(const Duration(milliseconds: 10));

      // 模拟终端被关闭
      mock.simulateTerminalClosed();

      // statusListener 应收敛到 error
      expect(
        manager.getTerminalState('dev-1', 'term-1'),
        TerminalSessionState.error,
      );
    });

    test('error 状态下新 service 的 connected 可推进到 recovering', () async {
      final mock = buildMock();
      manager.getOrCreate('dev-1', 'term-1', () => mock);

      manager.testEnsureTerminal(
        'dev-1',
        'term-1',
        () => Terminal(maxLines: 10000),
        service: mock,
      );

      // 先连接成功 + connected 事件进入 recovering
      await manager.connectTerminal('dev-1', 'term-1');
      mock.debugHandleMessage(jsonEncode({'type': 'connected'}));
      await Future<void>.delayed(const Duration(milliseconds: 10));

      // 模拟 auth_failed 进入 error（旧 service 不可复用）
      mock.simulateAuthFailed();
      expect(
        manager.getTerminalState('dev-1', 'term-1'),
        TerminalSessionState.error,
      );

      // 生产路径：用新 service 替换旧的 auth_failed service
      final newMock = buildMock();
      manager.getOrCreate('dev-1', 'term-1', () => newMock);
      manager.bindTerminalOutput('dev-1', 'term-1', newMock);

      // 新 service connected 事件推进到 recovering
      newMock.debugHandleMessage(jsonEncode({'type': 'connected'}));
      await Future<void>.delayed(const Duration(milliseconds: 10));

      // error → recovering 应该合法
      expect(
        manager.getTerminalState('dev-1', 'term-1'),
        TerminalSessionState.recovering,
      );
    });

    test('connecting 状态下 auth_failed 时 statusListener 收敛到 error', () async {
      final mock = buildMock();
      manager.getOrCreate('dev-1', 'term-1', () => mock);

      manager.testEnsureTerminal(
        'dev-1',
        'term-1',
        () => Terminal(maxLines: 10000),
        service: mock,
      );

      // connectTerminal 进入 connecting（尚未收到 connected 事件）
      await manager.connectTerminal('dev-1', 'term-1');
      expect(
        manager.getTerminalState('dev-1', 'term-1'),
        TerminalSessionState.connecting,
      );

      // 在 connected 事件到达前，直接发生 auth_failed
      mock.simulateAuthFailed();

      // connecting → error 应该通过 statusListener 收敛
      expect(
        manager.getTerminalState('dev-1', 'term-1'),
        TerminalSessionState.error,
      );
    });
  });

  // ─── F073: RendererAdapter 测试 ────────────────────────────────

  group('RendererAdapter', () {
    test('applySnapshot 清空旧 buffer 并写入新数据', () {
      final terminal = Terminal(maxLines: 10000);
      final adapter = RendererAdapter(terminal);

      // 先写入一些旧数据
      adapter.applyLiveOutput('old data line 1\nold data line 2');
      expect(terminal.buffer.lines[0].toString(), contains('old data line 1'));

      // applySnapshot 应清空旧 buffer 并写入新数据
      adapter.applySnapshot('new snapshot data');
      expect(
        terminal.buffer.lines[0].toString(),
        contains('new snapshot data'),
      );
      expect(
        terminal.buffer.lines[0].toString(),
        isNot(contains('old data')),
      );
      // outputText 也应只包含新数据
      expect(adapter.outputText.value, contains('new snapshot data'));
      expect(adapter.outputText.value, isNot(contains('old data')));
    });

    test('applySnapshot 可按 activeBuffer 恢复到 alternate buffer', () {
      final terminal = Terminal(maxLines: 10000);
      final adapter = RendererAdapter(terminal);

      adapter.applyLiveOutput('main buffer data');
      expect(terminal.mainBuffer.lines[0].toString(), contains('main buffer'));

      adapter.applySnapshot(
        'alternate snapshot',
        activeBuffer: TerminalBufferKind.alt,
      );

      expect(terminal.isUsingAltBuffer, isTrue);
      expect(terminal.altBuffer.lines[0].toString(), contains('alternate'));
      expect(
        terminal.mainBuffer.lines[0].toString(),
        isNot(contains('alternate')),
      );
    });

    test('applyLiveOutput 追加数据不清空', () {
      final terminal = Terminal(maxLines: 10000);
      final adapter = RendererAdapter(terminal);

      adapter.applyLiveOutput('first line\n');
      adapter.applyLiveOutput('second line\n');

      expect(adapter.outputText.value, contains('first line'));
      expect(adapter.outputText.value, contains('second line'));
    });

    test('resize 调整 terminal 尺寸', () {
      final terminal = Terminal(maxLines: 10000);
      final adapter = RendererAdapter(terminal);

      adapter.resize(120, 40);
      expect(terminal.viewWidth, 120);
      expect(terminal.viewHeight, 40);
    });

    test('resize 忽略无效尺寸', () {
      final terminal = Terminal(maxLines: 10000);
      final adapter = RendererAdapter(terminal);

      adapter.resize(120, 40);
      expect(terminal.viewWidth, 120);
      expect(terminal.viewHeight, 40);

      // 零值不应改变尺寸
      adapter.resize(0, 0);
      expect(terminal.viewWidth, 120);
      expect(terminal.viewHeight, 40);

      // 负值不应改变尺寸
      adapter.resize(-1, -1);
      expect(terminal.viewWidth, 120);
      expect(terminal.viewHeight, 40);
    });

    test('resize 不触发 onResize 回调', () {
      final terminal = Terminal(maxLines: 10000);
      final adapter = RendererAdapter(terminal);

      var resizeCallbackCount = 0;
      terminal.onResize = (cols, rows, pixelWidth, pixelHeight) {
        resizeCallbackCount++;
      };

      adapter.resize(120, 40);
      expect(resizeCallbackCount, 0);
    });

    test('reset 清空所有 buffer', () {
      final terminal = Terminal(maxLines: 10000);
      final adapter = RendererAdapter(terminal);

      adapter.applyLiveOutput('some data that will be cleared');
      expect(adapter.outputText.value, isNotEmpty);

      adapter.reset();
      expect(adapter.outputText.value, isEmpty);
    });

    test('dispose 后 outputText 不再更新', () {
      final terminal = Terminal(maxLines: 10000);
      final adapter = RendererAdapter(terminal);

      adapter.applyLiveOutput('before dispose');
      expect(adapter.outputText.value, contains('before dispose'));

      // 记录 terminal 当前内容
      final bufferContentBefore = terminal.buffer.lines[0].toString();

      adapter.dispose();
      expect(adapter.isDisposed, true);

      // F073 fix: dispose 后 applyLiveOutput 静默返回，不操作 terminal
      adapter.applyLiveOutput('after dispose');
      // terminal buffer 不应被 post-dispose 调用修改
      expect(
        terminal.buffer.lines[0].toString(),
        equals(bufferContentBefore),
      );
    });

    test('outputText 不超过 maxBufferLines', () {
      final terminal = Terminal(maxLines: 10000);
      final adapter = RendererAdapter(terminal);

      // 写入超过 50 行（_maxBufferLines）
      for (int i = 0; i < 60; i++) {
        adapter.applyLiveOutput('line $i\n');
      }

      final lines = adapter.outputText.value.split('\n');
      // 应只保留最后 50 行
      expect(lines.length, lessThanOrEqualTo(50));
      // 最早的行已被淘汰
      expect(adapter.outputText.value, isNot(contains('line 0')));
      // 最新的行保留
      expect(adapter.outputText.value, contains('line 59'));
    });

    test('检测到 claude 退出尾巴后清理旧界面，仅保留 resume 和 prompt', () {
      final terminal = Terminal(maxLines: 10000);
      final adapter = RendererAdapter(terminal);

      adapter.applyLiveOutput(
        'old help line 1\r\n'
        'old help line 2\r\n'
        'Resume this session with:\r\n'
        'claude --resume session-123\r\n'
        'bash-3.2\$ ',
      );

      final bufferText = terminal.buffer.getText();
      expect(bufferText, contains('Resume this session with:'));
      expect(bufferText, contains('claude --resume session-123'));
      expect(bufferText, contains('bash-3.2\$'));
      expect(bufferText, isNot(contains('old help line 1')));
      expect(bufferText, isNot(contains('old help line 2')));
      expect(adapter.outputText.value, isNot(contains('old help line 1')));
    });

    test('检测到 prompt 后仍残留旧内容时，继续收敛为 resume 和 prompt', () {
      final terminal = Terminal(maxLines: 10000);
      final adapter = RendererAdapter(terminal);

      adapter.applyLiveOutput(
        'Resume this session with:\r\n'
        'claude --resume session-456\r\n'
        'bash-3.2\$ \r\n'
        'stale claude help line\r\n'
        'stale claude footer',
      );

      final bufferText = terminal.buffer.getText();
      expect(bufferText, contains('Resume this session with:'));
      expect(bufferText, contains('claude --resume session-456'));
      expect(bufferText, contains('bash-3.2\$'));
      expect(bufferText, isNot(contains('stale claude help line')));
      expect(bufferText, isNot(contains('stale claude footer')));
      expect(adapter.outputText.value, isNot(contains('stale claude help line')));
    });

    test('退出清理时保留前面的 shell 历史，不把 prompt 顶到第一行', () {
      final terminal = Terminal(maxLines: 10000);
      final adapter = RendererAdapter(terminal);

      adapter.applyLiveOutput(
        'bash-3.2\$ cd project/ai_rules/\r\n'
        'bash-3.2\$ claude\r\n'
        'stale claude help line\r\n'
        'Resume this session with:\r\n'
        'claude --resume session-789\r\n'
        'bash-3.2\$ ',
      );

      final bufferText = terminal.buffer.getText();
      expect(bufferText, contains('bash-3.2\$ cd project/ai_rules/'));
      expect(bufferText, contains('bash-3.2\$ claude'));
      expect(bufferText, contains('Resume this session with:'));
      expect(bufferText, contains('claude --resume session-789'));
      expect(bufferText, contains('bash-3.2\$'));
      expect(bufferText, isNot(contains('stale claude help line')));
    });

    test('prompt 已经恢复后，只保留该 prompt 之前的 shell 历史', () {
      final terminal = Terminal(maxLines: 10000);
      final adapter = RendererAdapter(terminal);

      adapter.applyLiveOutput(
        'bash-3.2\$ cd project/ai_rules/\r\n'
        'bash-3.2\$ \r\n'
        'Resume this session with:\r\n'
        'claude --resume session-999\r\n'
        'Claude Code v2.1.76\r\n'
        '~/project/ai_rules',
      );

      final bufferText = terminal.buffer.getText();
      expect(bufferText, contains('bash-3.2\$ cd project/ai_rules/'));
      expect(bufferText, contains('bash-3.2\$'));
      expect(bufferText, isNot(contains('Resume this session with:')));
      expect(bufferText, isNot(contains('claude --resume session-999')));
      expect(bufferText, isNot(contains('Claude Code v2.1.76')));
    });

    test('顶部 prompt + 下方 stale claude block 时，将 prompt 收敛回历史末尾', () {
      final terminal = Terminal(maxLines: 10000);
      final adapter = RendererAdapter(terminal);

      adapter.applyLiveOutput(
        'bash-3.2\$ \r\n'
        'The default interactive shell is now zsh.\r\n'
        'To update your account to use zsh, please run `chsh -s /bin/zsh`.\r\n'
        'bash-3.2\$ pwd\r\n'
        '/Users/tangxiaolu\r\n'
        'bash-3.2\$ cd project/ai_rules/\r\n'
        'bash-3.2\$ pwd\r\n'
        '/Users/tangxiaolu/project/ai_rules\r\n'
        'bash-3.2\$ claude\r\n'
        'Claude Code v2.1.76\r\n'
        'glm-5.1 · API Usage Billing\r\n'
        '~/project/ai_rules',
      );

      final bufferText = terminal.buffer.getText();
      final trimmedLines = bufferText
          .split('\n')
          .map((line) => line.trimRight())
          .where((line) => line.isNotEmpty)
          .toList(growable: false);

      expect(trimmedLines.first, 'The default interactive shell is now zsh.');
      expect(trimmedLines, contains('bash-3.2\$ claude'));
      expect(trimmedLines.last, 'bash-3.2\$');
      expect(bufferText, isNot(contains('Claude Code v2.1.76')));
      expect(bufferText, isNot(contains('glm-5.1 · API Usage Billing')));
      expect(bufferText, isNot(contains('~/project/ai_rules')));
    });

    test('检测到 codex 退出尾巴后清理旧界面，并保留前面的 shell 历史', () {
      final terminal = Terminal(maxLines: 10000);
      final adapter = RendererAdapter(terminal);

      adapter.applyLiveOutput(
        'bash-3.2\$ pwd\r\n'
        '/Users/tangxiaolu/project/remote-control\r\n'
        'bash-3.2\$ codex\r\n'
        'stale codex helper line\r\n'
        'To continue this session, run codex resume abc123\r\n'
        'bash-3.2\$ ',
      );

      final bufferText = terminal.buffer.getText();
      expect(bufferText, contains('bash-3.2\$ pwd'));
      expect(bufferText, contains('/Users/tangxiaolu/project/remote-control'));
      expect(bufferText, contains('bash-3.2\$ codex'));
      expect(
        bufferText,
        contains('To continue this session, run codex resume abc123'),
      );
      expect(bufferText, contains('bash-3.2\$'));
      expect(bufferText, isNot(contains('stale codex helper line')));
    });

    test('顶部 prompt + 下方 stale codex block 时，将 prompt 收敛回历史末尾', () {
      final terminal = Terminal(maxLines: 10000);
      final adapter = RendererAdapter(terminal);

      adapter.applyLiveOutput(
        'bash-3.2\$ \r\n'
        'bash-3.2\$ pwd\r\n'
        '/Users/tangxiaolu/project/remote-control\r\n'
        'bash-3.2\$ codex\r\n'
        'OpenAI Codex v0.1.0\r\n'
        'model: gpt-5.4\r\n'
        '~/project/remote-control',
      );

      final bufferText = terminal.buffer.getText();
      final trimmedLines = bufferText
          .split('\n')
          .map((line) => line.trimRight())
          .where((line) => line.isNotEmpty)
          .toList(growable: false);

      expect(trimmedLines, contains('bash-3.2\$ codex'));
      expect(trimmedLines.last, 'bash-3.2\$');
      expect(bufferText, isNot(contains('OpenAI Codex v0.1.0')));
      expect(bufferText, isNot(contains('model: gpt-5.4')));
      expect(bufferText, isNot(contains('~/project/remote-control')));
    });

    test('普通 shell prompt 输出不触发 claude/codex 退出清理', () {
      final terminal = Terminal(maxLines: 10000);
      final adapter = RendererAdapter(terminal);

      adapter.applyLiveOutput('regular output\r\nbash-3.2\$ ');

      final bufferText = terminal.buffer.getText();
      expect(bufferText, contains('regular output'));
      expect(bufferText, contains('bash-3.2\$'));
    });
  });

  // ─── F073: getRendererAdapter 集成测试 ────────────────────────

  group('getRendererAdapter', () {
    late TerminalSessionManager manager;

    setUp(() {
      manager = TerminalSessionManager();
    });

    tearDown(() {
      manager.disconnectAll();
    });

    test('返回已创建 terminal 的 RendererAdapter', () {
      manager.testEnsureTerminal(
        'dev-1',
        'term-1',
        () => Terminal(maxLines: 10000),
      );

      final adapter = manager.getRendererAdapter('dev-1', 'term-1');
      expect(adapter, isNotNull);
    });

    test('不存在的 terminal 返回 null', () {
      final adapter = manager.getRendererAdapter('dev-1', 'term-999');
      expect(adapter, isNull);
    });

    test('通过 adapter 写入数据反映到 outputText', () {
      manager.testEnsureTerminal(
        'dev-1',
        'term-1',
        () => Terminal(maxLines: 10000),
      );

      final adapter = manager.getRendererAdapter('dev-1', 'term-1');
      adapter!.applyLiveOutput('via adapter\n');

      // 通过 RendererAdapter 的 outputText 验证（不依赖 terminal.buffer）
      expect(adapter.outputText.value, contains('via adapter'));
    });
  });

  // ─── F072: 多 terminal active transport 测试 ──────────────────

  group('多 terminal active transport', () {
    late TerminalSessionManager manager;

    MockWebSocketService buildMock({
      String deviceId = 'dev-1',
      String terminalId = 'term-1',
    }) {
      return MockWebSocketService(
        deviceId: deviceId,
        terminalId: terminalId,
      );
    }

    setUp(() {
      manager = TerminalSessionManager();
    });

    tearDown(() {
      manager.disconnectAll();
    });

    test('创建新 terminal 后 active transport 切到新 terminal', () async {
      manager.testEnsureTerminal(
        'dev-1',
        'term-1',
        () => Terminal(maxLines: 10000),
      );
      expect(manager.activeTerminalKeyForTest, 'dev-1::term-1');

      manager.testEnsureTerminal(
        'dev-1',
        'term-2',
        () => Terminal(maxLines: 10000),
      );
      expect(manager.activeTerminalKeyForTest, 'dev-1::term-2');
    });

    test('同时只有一个 active terminal', () async {
      manager.testEnsureTerminal(
        'dev-1',
        'term-1',
        () => Terminal(maxLines: 10000),
      );
      manager.testEnsureTerminal(
        'dev-1',
        'term-2',
        () => Terminal(maxLines: 10000),
      );
      manager.testEnsureTerminal(
        'dev-1',
        'term-3',
        () => Terminal(maxLines: 10000),
      );

      // 最后一个创建的 terminal 是 active
      expect(manager.activeTerminalKeyForTest, 'dev-1::term-3');

      // switch 到 term-1
      manager.switchTerminal('dev-1', 'term-1');
      expect(manager.activeTerminalKeyForTest, 'dev-1::term-1');
    });

    test('切回旧 terminal 时 terminal 实例和 buffer 保留', () async {
      final mock1 = buildMock(deviceId: 'dev-1', terminalId: 'term-1');
      final mock2 = buildMock(deviceId: 'dev-1', terminalId: 'term-2');

      manager.getOrCreate('dev-1', 'term-1', () => mock1);
      manager.getOrCreate('dev-1', 'term-2', () => mock2);

      final term1 = manager.testEnsureTerminal(
        'dev-1',
        'term-1',
        () => Terminal(maxLines: 10000),
        service: mock1,
      );

      // 写入数据到 term-1
      term1.write('hello term-1');
      await Future<void>.delayed(const Duration(milliseconds: 10));

      // 切到 term-2
      manager.testEnsureTerminal(
        'dev-1',
        'term-2',
        () => Terminal(maxLines: 10000),
        service: mock2,
      );
      expect(manager.activeTerminalKeyForTest, 'dev-1::term-2');

      // 切回 term-1
      manager.switchTerminal('dev-1', 'term-1');
      expect(manager.activeTerminalKeyForTest, 'dev-1::term-1');

      // term-1 的实例和数据应该保留
      final term1Again = manager.testTerminal('dev-1', 'term-1');
      expect(identical(term1, term1Again), isTrue);
      expect(term1Again!.buffer.lines[0].toString(), contains('hello term-1'));
    });

    test('disconnect active terminal 后 activeTerminalKey 清空', () async {
      manager.testEnsureTerminal(
        'dev-1',
        'term-1',
        () => Terminal(maxLines: 10000),
      );
      expect(manager.activeTerminalKeyForTest, 'dev-1::term-1');

      await manager.disconnectTerminal('dev-1', 'term-1');
      expect(manager.activeTerminalKeyForTest, isNull);
    });

    test('disconnect 非活跃终端不影响 activeTerminalKey', () async {
      manager.testEnsureTerminal(
        'dev-1',
        'term-1',
        () => Terminal(maxLines: 10000),
      );
      manager.testEnsureTerminal(
        'dev-1',
        'term-2',
        () => Terminal(maxLines: 10000),
      );
      expect(manager.activeTerminalKeyForTest, 'dev-1::term-2');

      await manager.disconnectTerminal('dev-1', 'term-1');
      expect(manager.activeTerminalKeyForTest, 'dev-1::term-2');
    });

    test('disconnectAll 清空 activeTerminalKey', () async {
      manager.testEnsureTerminal(
        'dev-1',
        'term-1',
        () => Terminal(maxLines: 10000),
      );
      expect(manager.activeTerminalKeyForTest, 'dev-1::term-1');

      await manager.disconnectAll();
      expect(manager.activeTerminalKeyForTest, isNull);
    });

    test('switchTerminal 不存在的 terminal 不改变 active', () async {
      manager.testEnsureTerminal(
        'dev-1',
        'term-1',
        () => Terminal(maxLines: 10000),
      );
      expect(manager.activeTerminalKeyForTest, 'dev-1::term-1');

      // 尝试 switch 到不存在的 terminal
      manager.switchTerminal('dev-1', 'term-999');
      expect(manager.activeTerminalKeyForTest, 'dev-1::term-1');
    });
  });
}
