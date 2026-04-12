import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rc_client/services/terminal_session_manager.dart';
import 'package:rc_client/services/websocket_service.dart';

/// 测试用 Mock WebSocketService
/// 不发起真实连接，但可以追踪方法调用
class MockWebSocketService extends WebSocketService {
  int disconnectCallCount = 0;
  int connectCallCount = 0;
  bool _mockConnected = false;
  ConnectionStatus _mockStatus = ConnectionStatus.disconnected;
  int? _mockLastCloseCode;

  /// 控制 connect() 是否抛异常
  bool connectShouldThrow = false;
  String connectErrorMessage = 'Connection failed';

  MockWebSocketService({
    super.serverUrl = 'ws://localhost:8888',
    super.token = 'token',
    super.sessionId = '',
    super.deviceId = 'dev-1',
    super.terminalId = 'term-1',
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

  @override
  ConnectionStatus get status => _mockStatus;

  @override
  int? get lastCloseCode => _mockLastCloseCode;

  @override
  bool get isAuthFailed => _mockLastCloseCode == 4001 || _mockLastCloseCode == 4011;

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
    _mockConnected = true;
    _mockStatus = ConnectionStatus.connected;
    return true;
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
  });

  group('TerminalSessionManager lifecycle - 正常路径', () {
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

      await manager.disconnectAll();

      // disconnectAll 清空了所有状态
      expect(() => manager.pauseAll(), returnsNormally);
      await expectLater(manager.resumeAll(), completes);
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

    test('resumeAll 中 connect 抛异常不阻塞其他 service', () async {
      final failMock = buildMock(deviceId: 'dev-1', terminalId: 'term-1');
      final okMock = buildMock(deviceId: 'dev-2', terminalId: 'term-2');

      failMock.connectShouldThrow = true;
      failMock.connectErrorMessage = 'token expired';

      manager.getOrCreate('dev-1', 'term-1', () => failMock);
      manager.getOrCreate('dev-2', 'term-2', () => okMock);

      failMock.setMockConnected(true);
      okMock.setMockConnected(true);

      manager.pauseAll();

      // resumeAll 应该继续处理后续 service，即使第一个失败
      await manager.resumeAll();

      // failMock 尝试了 connect 但失败
      expect(failMock.connectCallCount, 1);
      // okMock 仍然成功重连
      expect(okMock.connectCallCount, 1);
    });

    test('resumeAll 全部 connect 失败不崩溃', () async {
      final mock = buildMock();
      mock.connectShouldThrow = true;

      manager.getOrCreate('dev-1', 'term-1', () => mock);
      mock.setMockConnected(true);

      manager.pauseAll();

      // 即使全部失败也不应抛出未捕获的异常
      await expectLater(manager.resumeAll(), completes);
      expect(mock.connectCallCount, 1);
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

      // 第二次调用：mock1 的 lastCloseCode=4001，应被淘汰并重建
      final second = manager.getOrCreate('dev-1', 'term-1', build);
      expect(identical(second, mock1), isFalse);
      expect(createCount, 2);
      expect(mock1.disconnectCallCount, 1);
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
      final newService = manager.getOrCreate('dev-1', 'term-1', () => buildMock());
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

    test('didChangeAppLifecycleState(resumed) 触发 resumeAll（通过直接调用验证）', () async {
      final mock = buildMock();
      manager.getOrCreate('dev-1', 'term-1', () => mock);
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
}
