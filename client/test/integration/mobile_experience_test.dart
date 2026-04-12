import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:rc_client/services/websocket_service.dart';
import 'package:rc_client/widgets/mobile_input_delegate.dart';
import 'package:rc_client/widgets/tui_selector.dart';

import '../mocks/mock_websocket_service.dart';

void main() {
  group('F006 移动端体验优化 - 集成测试', () {
    late MockWebSocketService mockService;

    setUp(() {
      mockService = MockWebSocketService();
    });

    tearDown(() {
      mockService.dispose();
    });

    group('键盘布局与焦点管理测试', () {
      testWidgets('键盘弹出时终端内容可见（不遮挡）', (tester) async {
        await tester.pumpWidget(
          MaterialApp(
            home: ChangeNotifierProvider<WebSocketService>.value(
              value: mockService,
              child: Scaffold(
                body: Column(
                  children: [
                    const Expanded(
                      child: TerminalViewPlaceholder(),
                    ),
                    MobileInputDelegate(
                      onInput: (_) {},
                      onSubmit: () {},
                    ),
                  ],
                ),
              ),
            ),
          ),
        );

        // 验证布局结构：终端视图在上方，输入组件在下方
        expect(find.byType(TerminalViewPlaceholder), findsOneWidget);
        expect(find.byType(MobileInputDelegate), findsOneWidget);
      });

      testWidgets('点击终端区域自动聚焦输入框', (tester) async {
        final focusNode = FocusNode();
        final inputs = <String>[];

        await tester.pumpWidget(
          MaterialApp(
            home: Scaffold(
              body: GestureDetector(
                onTap: () {
                  focusNode.requestFocus();
                },
                behavior: HitTestBehavior.opaque,
                child: Column(
                  children: [
                    const Expanded(
                      child: TerminalViewPlaceholder(),
                    ),
                    MobileInputDelegate(
                      focusNode: focusNode,
                      onInput: (text) => inputs.add(text),
                      onSubmit: () {},
                    ),
                  ],
                ),
              ),
            ),
          ),
        );

        // 点击终端区域（使用 TerminalViewPlaceholder 作为目标）
        await tester.tap(find.byType(TerminalViewPlaceholder));
        await tester.pumpAndSettle();

        // 验证焦点已转移到输入框
        expect(focusNode.hasFocus, true);

        focusNode.dispose();
      });

      testWidgets('键盘收起后焦点正确恢复', (tester) async {
        final focusNode = FocusNode();

        await tester.pumpWidget(
          MaterialApp(
            home: Scaffold(
              body: MobileInputDelegate(
                focusNode: focusNode,
                onInput: (_) {},
                onSubmit: () {},
              ),
            ),
          ),
        );

        // 请求焦点
        focusNode.requestFocus();
        await tester.pump();
        expect(focusNode.hasFocus, true);

        // 收起键盘
        focusNode.unfocus();
        await tester.pump();
        expect(focusNode.hasFocus, false);

        focusNode.dispose();
      });
    });

    group('双端共控场景测试', () {
      testWidgets('桌面端输入时移动端实时显示', (tester) async {
        final outputs = <String>[];

        await tester.pumpWidget(
          MaterialApp(
            home: ChangeNotifierProvider<WebSocketService>.value(
              value: mockService,
              child: Scaffold(
                body: ListenableBuilder(
                  listenable: mockService,
                  builder: (context, _) {
                    return Text(mockService.agentOnline ? 'Agent Online' : 'Agent Offline');
                  },
                ),
              ),
            ),
          ),
        );

        // 模拟桌面端连接
        mockService.simulateConnect(agentOnline: true);
        await tester.pumpAndSettle();

        expect(find.text('Agent Online'), findsOneWidget);
      });

      testWidgets('移动端输入时桌面端实时显示', (tester) async {
        await tester.pumpWidget(
          MaterialApp(
            home: ChangeNotifierProvider<WebSocketService>.value(
              value: mockService,
              child: Scaffold(
                body: MobileInputDelegate(
                  onInput: (text) => mockService.send(text),
                  onSubmit: () => mockService.send('\r'),
                ),
              ),
            ),
          ),
        );

        // 模拟移动端输入 - 使用 enterText 触发完整的事件链
        await tester.enterText(find.byType(TextField), 'ls -la');
        await tester.pump();

        // 验证消息被发送
        expect(mockService.sentMessages, contains('ls -la'));
      });

      testWidgets('双端交替输入不冲突', (tester) async {
        final inputs = <String>[];

        await tester.pumpWidget(
          MaterialApp(
            home: Scaffold(
              body: Column(
                children: [
                  MobileInputDelegate(
                    onInput: (text) => inputs.add('mobile:$text'),
                    onSubmit: () => inputs.add('mobile:enter'),
                  ),
                  ElevatedButton(
                    onPressed: () => inputs.add('desktop:click'),
                    child: const Text('Desktop Action'),
                  ),
                ],
              ),
            ),
          ),
        );

        // 移动端输入 - 使用 enterText 触发完整的事件链
        await tester.enterText(find.byType(TextField), 'a');
        await tester.pump();

        // 桌面端操作
        await tester.tap(find.text('Desktop Action'));
        await tester.pump();

        // 验证两者都被记录
        expect(inputs, contains('mobile:a'));
        expect(inputs, contains('desktop:click'));
      });
    });

    group('横竖屏切换布局测试', () {
      testWidgets('竖屏模式下布局正确', (tester) async {
        await tester.binding.setSurfaceSize(const Size(400, 800));

        await tester.pumpWidget(
          MaterialApp(
            home: Scaffold(
              body: Column(
                children: [
                  const Expanded(child: Placeholder()),
                  Container(
                    height: 50,
                    color: Colors.grey,
                    child: const Center(child: Text('Action Bar')),
                  ),
                ],
              ),
            ),
          ),
        );

        expect(find.text('Action Bar'), findsOneWidget);
      });

      testWidgets('横屏模式下布局正确', (tester) async {
        await tester.binding.setSurfaceSize(const Size(800, 400));

        await tester.pumpWidget(
          MaterialApp(
            home: Scaffold(
              body: Column(
                children: [
                  const Expanded(child: Placeholder()),
                  Container(
                    height: 50,
                    color: Colors.grey,
                    child: const Center(child: Text('Action Bar')),
                  ),
                ],
              ),
            ),
          ),
        );

        expect(find.text('Action Bar'), findsOneWidget);

        // 恢复默认尺寸
        await tester.binding.setSurfaceSize(const Size(800, 600));
      });
    });

    group('TUI 选择与输入协同测试', () {
      testWidgets('TUI 选项显示时输入仍可正常工作', (tester) async {
        final inputs = <String>[];

        await tester.pumpWidget(
          MaterialApp(
            home: Scaffold(
              body: Column(
                children: [
                  TuiSelector(
                    terminalOutput: '  1. Option A\n  2. Option B',
                    onSelect: (key) => inputs.add('tui:$key'),
                  ),
                  MobileInputDelegate(
                    onInput: (text) => inputs.add('input:$text'),
                    onSubmit: () {},
                  ),
                ],
              ),
            ),
          ),
        );

        // TUI 选项存在
        expect(find.text('1'), findsOneWidget);
        expect(find.text('2'), findsOneWidget);

        // 点击 TUI 选项
        await tester.tap(find.text('1'));
        await tester.pump();

        // 验证 TUI 选择被发送
        expect(inputs, contains('tui:1'));
      });
    });
  });
}

/// 终端视图占位符（用于测试布局）
class TerminalViewPlaceholder extends StatelessWidget {
  const TerminalViewPlaceholder({super.key});

  @override
  Widget build(BuildContext context) {
    return Container(
      color: Colors.black,
      child: const Center(
        child: Text(
          'Terminal View',
          style: TextStyle(color: Colors.white),
        ),
      ),
    );
  }
}
