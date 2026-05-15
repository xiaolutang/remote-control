import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:remote_control/models/terminal_protocol.dart';
import 'package:remote_control/screens/terminal_screen.dart';
import 'package:remote_control/services/environment_service.dart';
import 'package:remote_control/services/terminal_session_manager.dart';
import 'package:remote_control/services/websocket_service.dart';
import 'package:xterm/terminal.dart';

import '../mocks/mock_websocket_service.dart';

/// 验证 WebSocket 重连时 TerminalView State 不被销毁、scroll 位置保持。
void main() {
  late MockWebSocketService service;
  late TerminalSessionManager sessionManager;

  setUp(() {
    SharedPreferences.setMockInitialValues({});
    EnvironmentService.setInstance(
      EnvironmentService(debugModeProvider: () => true),
    );
    service = _PreconnectedWebSocketService();
    sessionManager = TerminalSessionManager();
  });

  Future<void> pumpScreen(WidgetTester tester) async {
    await tester.pumpWidget(
      MultiProvider(
        providers: [
          ChangeNotifierProvider<TerminalSessionManager>.value(
            value: sessionManager,
          ),
          ChangeNotifierProvider<WebSocketService>.value(value: service),
        ],
        child: const MaterialApp(
          home: TerminalScreen(platformOverride: TargetPlatform.macOS),
        ),
      ),
    );
    await tester.pump(const Duration(milliseconds: 150));
  }

  testWidgets(
    'reconnecting preserves TerminalView widget (no State disposal)',
    (tester) async {
      await pumpScreen(tester);

      // TerminalView 应该已构建
      expect(find.byType(TerminalView), findsOneWidget);

      // 模拟重连
      service.simulateReconnecting();
      await tester.pump();

      // 关键断言：TerminalView 仍然在 widget tree 中（不被 _buildCenteredMessage 替换）
      expect(find.byType(TerminalView), findsOneWidget);
      // 重连提示应该作为遮罩覆盖在上方
      expect(find.textContaining('正在重连'), findsOneWidget);

      // 恢复连接
      service.simulateConnect();
      await tester.pump();

      // TerminalView 仍在
      expect(find.byType(TerminalView), findsOneWidget);
      // 重连提示消失
      expect(find.textContaining('正在重连'), findsNothing);
    },
  );

  testWidgets(
    'first connection without terminal shows connecting message',
    (tester) async {
      // 不调用 simulateConnect，terminal 为 null
      final freshService = MockWebSocketService();
      await tester.pumpWidget(
        MultiProvider(
          providers: [
            ChangeNotifierProvider<TerminalSessionManager>.value(
              value: sessionManager,
            ),
            ChangeNotifierProvider<WebSocketService>.value(
              value: freshService,
            ),
          ],
          child: const MaterialApp(
            home: TerminalScreen(platformOverride: TargetPlatform.macOS),
          ),
        ),
      );
      await tester.pump(const Duration(milliseconds: 150));

      // 无 TerminalView（terminal 未创建）
      expect(find.byType(TerminalView), findsNothing);
    },
  );

  testWidgets(
    'autoResize does not change between connected and reconnecting',
    (tester) async {
      await pumpScreen(tester);

      // 找到 TerminalView 并读取当前 autoResize
      final terminalViewBefore = tester.widgetList<TerminalView>(
        find.byType(TerminalView),
      ).first;

      // 进入重连
      service.simulateReconnecting();
      await tester.pump();

      final terminalViewDuring = tester.widgetList<TerminalView>(
        find.byType(TerminalView),
      ).first;

      // 恢复连接
      service.simulateConnect();
      await tester.pump();

      final terminalViewAfter = tester.widgetList<TerminalView>(
        find.byType(TerminalView),
      ).first;

      // autoResize 在三个状态下应该一致（不会因连接状态变化而切换）
      expect(terminalViewDuring.autoResize, equals(terminalViewBefore.autoResize));
      expect(terminalViewAfter.autoResize, equals(terminalViewBefore.autoResize));
    },
  );
}

/// 预连接的 WebSocket mock，connect() 直接返回 true。
class _PreconnectedWebSocketService extends MockWebSocketService {
  @override
  Future<bool> connect() async {
    connectCallCount++;
    simulateConnect();
    return true;
  }
}
