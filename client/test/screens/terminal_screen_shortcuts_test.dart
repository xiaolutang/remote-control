import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:rc_client/screens/terminal_screen.dart';
import 'package:rc_client/services/environment_service.dart';
import 'package:rc_client/services/terminal_session_manager.dart';
import 'package:rc_client/services/websocket_service.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:xterm/xterm.dart';
import 'dart:io';

import '../mocks/mock_websocket_service.dart';

/// 内置命令增多后"当前项目"section 可能需要滚动才能看到
Future<void> scrollToProjectSection(WidgetTester tester) async {
  final scrollables = find.byType(Scrollable).evaluate().toList();
  if (scrollables.isNotEmpty) {
    await tester.scrollUntilVisible(
      find.text('当前项目'),
      200,
      scrollable: find.byType(Scrollable).last,
    );
    await tester.pumpAndSettle();
  }
}

void main() {
  group('TerminalScreen mobile shortcuts', () {
    late _PreconnectedWebSocketService mockService;

    setUp(() {
      SharedPreferences.setMockInitialValues({});
      EnvironmentService.setInstance(
        EnvironmentService(debugModeProvider: () => true),
      );
      mockService = _PreconnectedWebSocketService()..simulateConnect();
    });

    tearDown(() {
      mockService.dispose();
    });

    Future<void> pumpScreenWithManager(
      WidgetTester tester, {
      required WebSocketService service,
      required TerminalSessionManager sessionManager,
      MediaQueryData? mediaQueryData,
    }) async {
      await tester.pumpWidget(
        MediaQuery(
          data: mediaQueryData ?? const MediaQueryData(size: Size(400, 800)),
          child: MultiProvider(
            providers: [
              ChangeNotifierProvider<TerminalSessionManager>.value(
                value: sessionManager,
              ),
              ChangeNotifierProvider<WebSocketService>.value(value: service),
            ],
            child: const MaterialApp(
              home: TerminalScreen(platformOverride: TargetPlatform.android),
            ),
          ),
        ),
      );
      await tester.pump(const Duration(milliseconds: 150));
    }

    Future<void> pumpScreen(
      WidgetTester tester,
      WebSocketService service,
    ) async {
      await pumpScreenWithManager(
        tester,
        service: service,
        sessionManager: TerminalSessionManager(),
      );
    }

    testWidgets('shows shortcut bar on mobile and sends control payloads',
        (tester) async {
      await pumpScreen(tester, mockService);

      expect(find.text('Ctrl+C'), findsOneWidget);
      expect(find.text('Enter'), findsOneWidget);
      expect(find.text('更多'), findsOneWidget);
      expect(find.text('/help'), findsNothing);

      await tester.tap(find.text('Ctrl+C'));
      await tester.pump();
      await tester.tap(find.text('上一项'));
      await tester.pump();

      expect(mockService.sentMessages, contains('\x03'));
      expect(mockService.sentMessages, contains('\x1b[A'));
    });

    testWidgets('shows TUI selector and shortcut bar together on mobile',
        (tester) async {
      await pumpScreen(tester, mockService);
      mockService.simulateOutput('  1. Option A\n  2. Option B\n');
      await tester.pumpAndSettle();

      expect(find.text('Ctrl+C'), findsOneWidget);
      expect(find.text('1'), findsOneWidget);
      expect(find.text('2'), findsOneWidget);

      await tester.tap(find.text('1'));
      await tester.pump();

      expect(mockService.sentMessages, contains('1'));
    });

    testWidgets('reuses cached Terminal buffer across screen remounts',
        (tester) async {
      final sessionManager = TerminalSessionManager();
      addTearDown(sessionManager.dispose);

      await pumpScreenWithManager(
        tester,
        service: mockService,
        sessionManager: sessionManager,
      );

      mockService.simulateOutput('hello from cached terminal\n');
      await tester.pumpAndSettle();

      final cachedTerminal = sessionManager
          .getRendererAdapter('device-1', 'term-1')
          ?.terminalForView;
      expect(cachedTerminal, isNotNull);
      expect(cachedTerminal!.buffer.lines[0].toString(), contains('hello'));

      await tester.pumpWidget(const SizedBox.shrink());
      await tester.pumpAndSettle();

      final newService = _PreconnectedWebSocketService()..simulateConnect();
      addTearDown(newService.dispose);
      await pumpScreenWithManager(
        tester,
        service: newService,
        sessionManager: sessionManager,
      );

      final reusedTerminal = sessionManager
          .getRendererAdapter('device-1', 'term-1')
          ?.terminalForView;
      expect(identical(reusedTerminal, cachedTerminal), isTrue);
      expect(reusedTerminal!.buffer.lines[0].toString(), contains('hello'));
    });

    testWidgets('keeps shortcut bar above software keyboard on mobile',
        (tester) async {
      final sessionManager = TerminalSessionManager();
      addTearDown(sessionManager.dispose);

      await pumpScreenWithManager(
        tester,
        service: mockService,
        sessionManager: sessionManager,
        mediaQueryData: const MediaQueryData(
          size: Size(400, 800),
          viewInsets: EdgeInsets.only(bottom: 320),
        ),
      );

      final ctrlCBottom = tester.getBottomLeft(find.text('Ctrl+C')).dy;
      expect(ctrlCBottom, lessThan(800 - 320));
    });

    testWidgets(
        'keeps cached terminal receiving output while screen is offstage',
        (tester) async {
      final sessionManager = TerminalSessionManager();
      addTearDown(sessionManager.dispose);

      final serviceA = _PreconnectedWebSocketService(
        terminalId: 'term-1',
      )..simulateConnect();
      final serviceB = _PreconnectedWebSocketService(
        terminalId: 'term-2',
      )..simulateConnect();
      addTearDown(serviceA.dispose);
      addTearDown(serviceB.dispose);

      await pumpScreenWithManager(
        tester,
        service: serviceA,
        sessionManager: sessionManager,
      );
      serviceA.simulateOutput('term-1 visible\n');
      await tester.pumpAndSettle();

      await pumpScreenWithManager(
        tester,
        service: serviceB,
        sessionManager: sessionManager,
      );
      serviceA.simulateOutput('term-1 background\n');
      serviceB.simulateOutput('term-2 visible\n');
      await tester.pumpAndSettle();

      final terminalA = sessionManager
          .getRendererAdapter('device-1', 'term-1')
          ?.terminalForView;
      expect(terminalA, isNotNull);

      final terminalAText = List.generate(
        terminalA!.buffer.lines.length,
        (index) => terminalA.buffer.lines[index].toString(),
      ).join('\n');

      expect(terminalAText, contains('term-1 background'));
    });

    testWidgets('mobile scaffold disables resizeToAvoidBottomInset',
        (tester) async {
      await pumpScreen(tester, mockService);

      final scaffold = tester.widget<Scaffold>(find.byType(Scaffold));
      expect(scaffold.resizeToAvoidBottomInset, isFalse);
    });

    testWidgets('mobile follows shared PTY instead of auto resizing',
        (tester) async {
      mockService.simulatePresence({'mobile': 1, 'desktop': 1});
      mockService.simulateGeometryOwner('desktop');

      await pumpScreen(tester, mockService);

      final terminalView =
          tester.widget<TerminalView>(find.byType(TerminalView));
      expect(terminalView.autoResize, isFalse);
    });

    test(
        'source guard: _onOutput does not rebuild TerminalScreen with setState',
        () async {
      final source =
          await File('lib/screens/terminal_screen.dart').readAsString();
      final onOutputBody = RegExp(
        r'void _onOutput\(String data\) \{([\s\S]*?)\n  \}',
      ).firstMatch(source);

      expect(onOutputBody, isNotNull);
      expect(
        onOutputBody!.group(1),
        isNot(contains('setState(')),
        reason:
            '终端输出重绘应由 xterm/RenderTerminal 和局部 notifier 驱动，不应重建整个 TerminalScreen subtree',
      );
    });

    testWidgets('sends enter and ctrl+l payloads from shortcut bar',
        (tester) async {
      await pumpScreen(tester, mockService);

      await tester.tap(find.text('Ctrl+L'));
      await tester.pump();
      await tester.ensureVisible(find.text('Enter'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Enter'));
      await tester.pump();

      expect(mockService.sentMessages, contains('\x0c'));
      expect(mockService.sentMessages, contains('\r'));
    });

    testWidgets(
        'sends default Claude command pack items and updates smart ordering',
        (tester) async {
      await pumpScreen(tester, mockService);

      await tester.tap(find.text('更多'));
      await tester.pumpAndSettle();

      expect(find.text('快捷命令'), findsOneWidget);
      expect(find.text('Claude Code'), findsOneWidget);
      expect(find.text('/help'), findsOneWidget);
      expect(find.text('/status'), findsOneWidget);
      expect(find.byType(BottomSheet), findsOneWidget);

      await tester.tap(find.text('/compact'));
      await tester.pumpAndSettle();

      expect(mockService.sentMessages, contains('/compact\r'));
      await tester.tap(find.text('更多'));
      await tester.pumpAndSettle();

      final compact = tester.getTopLeft(find.text('/compact'));
      final help = tester.getTopLeft(find.text('/help'));
      expect(compact.dy, lessThanOrEqualTo(help.dy));
    });

    testWidgets('allows managing Claude commands from the shortcut menu',
        (tester) async {
      await pumpScreen(tester, mockService);

      await tester.tap(find.text('更多'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('管理'));
      await tester.pumpAndSettle();

      expect(find.text('管理快捷命令'), findsOneWidget);
      expect(find.text('/help'), findsOneWidget);

      await tester.tap(find.byKey(const Key('shortcut-toggle-claude_help')));
      await tester.pumpAndSettle();

      await tester.tap(find.byKey(const Key('shortcut-settings-close')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('更多'));
      await tester.pumpAndSettle();

      expect(find.text('/help'), findsNothing);
      expect(find.text('/status'), findsOneWidget);

      await tester.tap(find.text('管理'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('恢复默认'));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('shortcut-settings-close')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('更多'));
      await tester.pumpAndSettle();

      expect(find.text('/help'), findsOneWidget);
    });

    testWidgets('allows reordering Claude command items from settings',
        (tester) async {
      await pumpScreen(tester, mockService);

      await tester.tap(find.text('更多'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('管理'));
      await tester.pumpAndSettle();

      await tester.tap(find.byKey(const Key('shortcut-move-down-claude_help')));
      await tester.pumpAndSettle();

      await tester.tap(find.byKey(const Key('shortcut-settings-close')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('更多'));
      await tester.pumpAndSettle();

      final help = tester.getTopLeft(find.text('/help'));
      final status = tester.getTopLeft(find.text('/status'));
      expect(help.dy, greaterThan(status.dy));
    });

    testWidgets('allows creating project commands and sending them from menu',
        (tester) async {
      await pumpScreen(tester, mockService);

      await tester.tap(find.text('更多'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('管理'));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('add-project-command')));
      await tester.pumpAndSettle();

      await tester.enterText(
        find.byKey(const Key('project-command-label-field')),
        '运行测试',
      );
      await tester.enterText(
        find.byKey(const Key('project-command-value-field')),
        'pnpm test',
      );
      await tester.tap(find.byKey(const Key('save-project-command')));
      await tester.pumpAndSettle();

      await tester.tap(find.byKey(const Key('shortcut-settings-close')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('更多'));
      await tester.pumpAndSettle();

      await scrollToProjectSection(tester);

      expect(find.text('当前项目'), findsOneWidget);
      expect(find.text('运行测试'), findsOneWidget);

      await tester.tap(find.text('运行测试'));
      await tester.pumpAndSettle();

      expect(mockService.sentMessages, contains('pnpm test\r'));
    });

    testWidgets(
        'allows switching Claude navigation mode without changing labels',
        (tester) async {
      await pumpScreen(tester, mockService);

      expect(find.text('上一项'), findsOneWidget);
      await tester.tap(find.text('更多'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('管理'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('应用'));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('shortcut-settings-close')));
      await tester.pumpAndSettle();

      expect(find.text('上一项'), findsOneWidget);
      await tester.tap(find.text('上一项'));
      await tester.pump();

      expect(mockService.sentMessages, contains('\x1bOA'));
    });

    testWidgets('uses Claude navigation semantics in mobile labels',
        (tester) async {
      await pumpScreen(tester, mockService);

      expect(find.text('上一项'), findsOneWidget);
      expect(find.text('下一项'), findsOneWidget);
      expect(find.text('Enter'), findsOneWidget);
      expect(find.text('Up'), findsNothing);
      expect(find.text('Down'), findsNothing);
    });

    testWidgets('shows reconnecting state when service is reconnecting',
        (tester) async {
      await pumpScreen(tester, mockService);
      mockService.simulateReconnecting();
      await tester.pump();

      expect(find.textContaining('正在重连'), findsOneWidget);
      expect(find.text('Ctrl+C'), findsOneWidget);
    });

    testWidgets('shows error banner and retry triggers reconnect',
        (tester) async {
      await pumpScreen(tester, mockService);
      final initialConnectCalls = mockService.connectCallCount;

      mockService.simulateError('Connection refused');
      await tester.pump();

      expect(find.text('无法连接到服务器，请检查服务器是否启动'), findsOneWidget);
      expect(find.text('重试'), findsOneWidget);

      await tester.tap(find.text('重试'));
      await tester.pump();

      expect(mockService.connectCallCount, greaterThan(initialConnectCalls));
    });

    testWidgets('sends TUI selection then shortcut in the same session',
        (tester) async {
      await pumpScreen(tester, mockService);
      mockService.simulateOutput('  1. Option A\n');
      await tester.pumpAndSettle();

      await tester.tap(find.text('1'));
      await tester.pump();
      await tester.tap(find.text('Esc'));
      await tester.pump();

      expect(mockService.sentMessages, contains('1'));
      expect(mockService.sentMessages, contains('\x1b'));
    });

    testWidgets('sends new control key payloads from shortcut bar',
        (tester) async {
      await pumpScreen(tester, mockService);

      await tester.ensureVisible(find.text('Ctrl+A'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Ctrl+A'));
      await tester.pump();

      expect(mockService.sentMessages, contains('\x01'));

      await tester.ensureVisible(find.text('Ctrl+U'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Ctrl+U'));
      await tester.pump();

      expect(mockService.sentMessages, contains('\x15'));
    });

    testWidgets('sends new escape sequence key payloads from shortcut bar',
        (tester) async {
      await pumpScreen(tester, mockService);

      await tester.ensureVisible(find.text('Home'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Home'));
      await tester.pump();

      expect(mockService.sentMessages, contains('\x1b[H'));

      await tester.ensureVisible(find.text('End'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('End'));
      await tester.pump();

      expect(mockService.sentMessages, contains('\x1b[F'));
    });

    testWidgets('persists hidden Claude commands across screen rebuilds',
        (tester) async {
      await pumpScreen(tester, mockService);

      await tester.tap(find.text('更多'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('管理'));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('shortcut-toggle-claude_help')));
      await tester.pumpAndSettle();

      await tester.pumpWidget(const SizedBox.shrink());
      await tester.pumpAndSettle();

      final newService = _PreconnectedWebSocketService()..simulateConnect();
      addTearDown(newService.dispose);
      await pumpScreen(tester, newService);

      await tester.tap(find.text('更多'));
      await tester.pumpAndSettle();

      expect(find.text('/help'), findsNothing);
      expect(find.text('/status'), findsOneWidget);
    });

    testWidgets('persists project commands across screen rebuilds',
        (tester) async {
      await pumpScreen(tester, mockService);

      await tester.tap(find.text('更多'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('管理'));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('add-project-command')));
      await tester.pumpAndSettle();
      await tester.enterText(
        find.byKey(const Key('project-command-label-field')),
        '运行测试',
      );
      await tester.enterText(
        find.byKey(const Key('project-command-value-field')),
        'pnpm test',
      );
      await tester.tap(find.byKey(const Key('save-project-command')));
      await tester.pumpAndSettle();

      await tester.pumpWidget(const SizedBox.shrink());
      await tester.pumpAndSettle();

      final newService = _PreconnectedWebSocketService()..simulateConnect();
      addTearDown(newService.dispose);
      await pumpScreen(tester, newService);

      await tester.tap(find.text('更多'));
      await tester.pumpAndSettle();

      // 内置命令增多后"当前项目"section 可能需要滚动才能看到
      await scrollToProjectSection(tester);

      expect(find.text('当前项目'), findsOneWidget);
      expect(find.text('运行测试'), findsOneWidget);
    });

    testWidgets('persists Claude navigation mode across screen rebuilds',
        (tester) async {
      await pumpScreen(tester, mockService);

      await tester.tap(find.text('更多'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('管理'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('应用'));
      await tester.pumpAndSettle();

      await tester.pumpWidget(const SizedBox.shrink());
      await tester.pumpAndSettle();

      final newService = _PreconnectedWebSocketService()..simulateConnect();
      addTearDown(newService.dispose);
      await pumpScreen(tester, newService);

      await tester.tap(find.text('上一项'));
      await tester.pump();

      expect(newService.sentMessages, contains('\x1bOA'));
    });
  });

  group('TerminalScreen desktop shortcuts', () {
    late _PreconnectedWebSocketService mockService;

    setUp(() {
      SharedPreferences.setMockInitialValues({});
      EnvironmentService.setInstance(
        EnvironmentService(debugModeProvider: () => true),
      );
      mockService = _PreconnectedWebSocketService(
        viewType: ViewType.desktop,
      )..simulateConnect();
    });

    tearDown(() {
      mockService.dispose();
    });

    testWidgets('does not show mobile shortcut bar on desktop', (tester) async {
      await tester.pumpWidget(
        MultiProvider(
          providers: [
            ChangeNotifierProvider<TerminalSessionManager>(
              create: (_) => TerminalSessionManager(),
            ),
            ChangeNotifierProvider<WebSocketService>.value(value: mockService),
          ],
          child: const MaterialApp(
            home: TerminalScreen(platformOverride: TargetPlatform.macOS),
          ),
        ),
      );

      await tester.pump(const Duration(milliseconds: 150));

      expect(find.text('Ctrl+L'), findsNothing);
      expect(find.text('Enter'), findsNothing);
      expect(find.text('Paste'), findsNothing);
      expect(find.text('更多'), findsNothing);
    });

    testWidgets('desktop scaffold keeps resizeToAvoidBottomInset enabled',
        (tester) async {
      await tester.pumpWidget(
        MultiProvider(
          providers: [
            ChangeNotifierProvider<TerminalSessionManager>(
              create: (_) => TerminalSessionManager(),
            ),
            ChangeNotifierProvider<WebSocketService>.value(value: mockService),
          ],
          child: const MaterialApp(
            home: TerminalScreen(platformOverride: TargetPlatform.macOS),
          ),
        ),
      );

      await tester.pump(const Duration(milliseconds: 150));

      final scaffold = tester.widget<Scaffold>(find.byType(Scaffold));
      expect(scaffold.resizeToAvoidBottomInset, isTrue);
    });

    testWidgets('desktop follows shared PTY when another viewer is attached',
        (tester) async {
      mockService.simulatePresence({'mobile': 1, 'desktop': 1});
      mockService.simulateGeometryOwner('mobile');

      await tester.pumpWidget(
        MultiProvider(
          providers: [
            ChangeNotifierProvider<TerminalSessionManager>(
              create: (_) => TerminalSessionManager(),
            ),
            ChangeNotifierProvider<WebSocketService>.value(value: mockService),
          ],
          child: const MaterialApp(
            home: TerminalScreen(platformOverride: TargetPlatform.macOS),
          ),
        ),
      );

      await tester.pump(const Duration(milliseconds: 150));

      final terminalView =
          tester.widget<TerminalView>(find.byType(TerminalView));
      expect(terminalView.autoResize, isFalse);
    });

    testWidgets(
        'desktop does not send resize events while following shared PTY',
        (tester) async {
      final sessionManager = TerminalSessionManager();
      addTearDown(sessionManager.dispose);
      mockService.simulatePresence({'mobile': 1, 'desktop': 1});
      mockService.simulateGeometryOwner('mobile');

      await tester.pumpWidget(
        MultiProvider(
          providers: [
            ChangeNotifierProvider<TerminalSessionManager>.value(
              value: sessionManager,
            ),
            ChangeNotifierProvider<WebSocketService>.value(value: mockService),
          ],
          child: const MaterialApp(
            home: TerminalScreen(platformOverride: TargetPlatform.macOS),
          ),
        ),
      );

      await tester.pump(const Duration(milliseconds: 150));

      final terminal = sessionManager
          .getRendererAdapter('device-1', 'term-1')
          ?.terminalForView;
      expect(terminal, isNotNull);

      terminal!.onResize?.call(120, 40, 0, 0);

      expect(mockService.sentMessages, isEmpty);
    });
  });
}

class _PreconnectedWebSocketService extends MockWebSocketService {
  _PreconnectedWebSocketService({
    super.terminalId,
    super.viewType,
  });

  @override
  Future<bool> connect() async {
    connectCallCount++;
    return true;
  }
}
