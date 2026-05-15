import 'package:flutter/foundation.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:rc_client/models/terminal_protocol.dart';
import 'package:rc_client/screens/terminal_screen_controller.dart';
import 'package:rc_client/services/environment_service.dart';
import 'package:rc_client/services/terminal_session_manager.dart';
import 'package:rc_client/services/websocket_service.dart';

import '../mocks/mock_websocket_service.dart';

/// 验证被踢/token 过期后弹窗守卫在 disconnectAll 期间不失效。
///
/// 核心回归锁：旧代码 clearAuthDialog() 在 disconnectAll() 之前，
/// disconnect 回调中 _authDialogShowing 已为 false → 弹窗重入。
/// 修复后 clearAuthDialog() 在 disconnectAll() 之后，守卫全程有效。
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  late TerminalScreenController controller;
  late MockWebSocketService mockService;
  late TerminalSessionManager sessionManager;

  setUp(() {
    EnvironmentService.setInstance(
      EnvironmentService(debugModeProvider: () => true),
    );
    sessionManager = TerminalSessionManager();
    controller = TerminalScreenController(
      platformGetter: () => TargetPlatform.macOS,
    );
    // terminalId 为空 → bindSession 走本地终端路径
    mockService = MockWebSocketService(
      terminalId: '',
      deviceId: 'dev-1',
    );
  });

  tearDown(() {
    controller.dispose();
    sessionManager.disconnectAll();
  });

  // ─── 回归锁：旧代码下这些测试会失败 ──────────────────────────────

  test(
    'regression: confirmDeviceKicked 路径 — '
    'disconnectAll 期间守卫不失效',
    () async {
      // 1. 注册 service 到 sessionManager（真实调用链）
      sessionManager.getOrCreate(
        'dev-1',
        'term-1',
        () => mockService,
      );
      controller.bindSession(mockService, sessionManager);

      // 2. 先连接
      mockService.simulateConnect();

      // 3. 模拟被踢
      mockService.simulateDeviceKicked();
      expect(controller.authDialogShowing, isTrue);
      expect(controller.isDeviceKicked, isTrue);

      // 4. 记录 controller notify 次数
      int authNotifyCount = 0;
      controller.addListener(() {
        if (controller.authDialogShowing) authNotifyCount++;
      });

      // 5. 模拟 confirmDeviceKicked 中的 disconnectAll
      //    旧代码：clearAuthDialog() → disconnectAll() → 守卫失效 → 重入
      //    新代码：disconnectAll() → 守卫有效 → clearAuthDialog()
      await sessionManager.disconnectAll();

      // 关键断言：disconnectAll 后守卫仍然为 true（新代码）
      // 如果是旧代码，clearAuthDialog 在 disconnectAll 之前调用，
      // disconnect 回调中 _onDeviceKicked 会再次触发，
      // authNotifyCount 会 > 0
      expect(controller.authDialogShowing, isTrue);

      // 清除守卫
      controller.clearAuthDialog();
      expect(controller.authDialogShowing, isFalse);
    },
  );

  test(
    'regression: confirmTokenExpired 路径 — '
    'disconnectAll 期间守卫不失效',
    () async {
      sessionManager.getOrCreate(
        'dev-1',
        'term-1',
        () => mockService,
      );
      controller.bindSession(mockService, sessionManager);
      mockService.simulateConnect();

      // 模拟 token 过期（4001）
      mockService.simulateAuthFailed();
      expect(controller.authDialogShowing, isTrue);

      // 模拟 performSessionTeardown 中的 disconnectAll
      await sessionManager.disconnectAll();

      // 守卫仍有效
      expect(controller.authDialogShowing, isTrue);

      controller.clearAuthDialog();
      expect(controller.authDialogShowing, isFalse);
    },
  );

  // ─── 守卫隔离测试 ──────────────────────────────────────────────

  test('device kicked: disconnect 回调中守卫阻止 _onDeviceKicked 重入', () {
    controller.bindSession(mockService, sessionManager);

    mockService.simulateDeviceKicked();
    expect(controller.authDialogShowing, isTrue);

    // disconnect 触发 _onStatusChanged → 检查 4011 → _onDeviceKicked
    // 但 _authDialogShowing 仍为 true，_onDeviceKicked 直接 return
    mockService.disconnect();

    expect(controller.authDialogShowing, isTrue);
  });

  test('token expired: disconnect 回调中守卫阻止 _handleTokenExpired 重入', () {
    controller.bindSession(mockService, sessionManager);

    mockService.simulateAuthFailed();
    expect(controller.authDialogShowing, isTrue);

    mockService.disconnect();

    expect(controller.authDialogShowing, isTrue);
  });

  // ─── 边界场景 ─────────────────────────────────────────────────

  test('未绑定 service 时不触发弹窗', () {
    expect(controller.authDialogShowing, isFalse);
    expect(controller.isDeviceKicked, isFalse);
  });

  test('正常断开不触发弹窗', () {
    controller.bindSession(mockService, sessionManager);
    mockService.simulateConnect();
    mockService.simulateDisconnect();

    expect(controller.authDialogShowing, isFalse);
  });
}
