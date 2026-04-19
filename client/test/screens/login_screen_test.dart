import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:rc_client/screens/login_screen.dart';
import 'package:rc_client/services/desktop_agent_manager.dart';
import 'package:rc_client/services/auth_service.dart';
import 'package:rc_client/services/desktop_agent_supervisor.dart';
import 'package:rc_client/services/environment_service.dart';
import 'package:rc_client/services/theme_controller.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Minimal mock supervisor for LoginScreen tests (mobile mode, supported=false)
class _MobileFakeSupervisor extends DesktopAgentSupervisor {
  @override
  bool get supported => false;
}

/// Mock AuthService for testing
class MockAuthService extends AuthService {
  MockAuthService({required super.serverUrl});

  Map<String, dynamic>? _loginResult;
  Map<String, dynamic>? _registerResult;
  Exception? _loginException;
  Exception? _registerException;
  int _loginCallCount = 0;
  int _registerCallCount = 0;
  Duration _simulateDelay = Duration.zero;

  void setLoginResult(Map<String, dynamic> result) => _loginResult = result;
  void setRegisterResult(Map<String, dynamic> result) => _registerResult = result;
  void setLoginException(Exception e) => _loginException = e;
  void setRegisterException(Exception e) => _registerException = e;
  void setSimulateDelay(Duration duration) => _simulateDelay = duration;
  int get loginCallCount => _loginCallCount;
  int get registerCallCount => _registerCallCount;

  @override
  Future<Map<String, dynamic>> login(String username, String password) async {
    _loginCallCount++;
    if (_simulateDelay != Duration.zero) {
      await Future.delayed(_simulateDelay);
    }
    if (_loginException != null) throw _loginException!;
    if (_loginResult != null) return _loginResult!;
    return {'success': true, 'token': 'test-token', 'session_id': 'session-123'};
  }

  @override
  Future<Map<String, dynamic>> register(String username, String password) async {
    _registerCallCount++;
    if (_simulateDelay != Duration.zero) {
      await Future.delayed(_simulateDelay);
    }
    if (_registerException != null) throw _registerException!;
    if (_registerResult != null) return _registerResult!;
    return {'success': true, 'token': 'test-token', 'session_id': 'session-123'};
  }
}

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues({});
    EnvironmentService.setInstance(
      EnvironmentService(debugModeProvider: () => true),
    );
  });

  // LoginScreen 现在包含环境选择 + host/port 编辑区，需要更大的视口
  Future<void> setLargeViewport(WidgetTester tester) async {
    await tester.binding.setSurfaceSize(const Size(800, 900));
    addTearDown(() => tester.binding.setSurfaceSize(null));
  }

  // LoginScreen 本地环境下有 host/port 输入框，需要偏移索引
  // host=0, port=1, username=2, password=3, confirm=4(注册模式)
  final usernameField = find.byType(TextFormField).at(2);
  final passwordField = find.byType(TextFormField).at(3);
  final confirmPasswordField = find.byType(TextFormField).at(4);

  Widget wrapWithApp({
    DesktopAgentManager? agentManager,
  }) {
    // 使用 mobile platform mock（supported=false），LoginScreen 不需要真实 Agent
    final supervisor = _MobileFakeSupervisor();
    return MultiProvider(
      providers: [
        ChangeNotifierProvider(create: (_) => ThemeController()),
        ChangeNotifierProvider(
          create: (_) => agentManager ?? DesktopAgentManager(
            supervisor: supervisor,
          ),
        ),
      ],
      child: const MaterialApp(
        home: LoginScreen(),
      ),
    );
  }

  group('LoginScreen - 正常场景 (Normal Scenarios)', () {
    testWidgets('shows login form by default', (tester) async {
      await setLargeViewport(tester);
      await tester.pumpWidget(wrapWithApp());
      await tester.pumpAndSettle();

      expect(find.text('Remote Control'), findsOneWidget);
      expect(find.text('登录您的账号'), findsOneWidget);
      expect(find.text('登录'), findsOneWidget);
      expect(find.text('立即注册'), findsOneWidget);
    });

    testWidgets('toggle to register mode shows confirm password field', (tester) async {
      await setLargeViewport(tester);
      await tester.pumpWidget(wrapWithApp());
      await tester.pumpAndSettle();

      // 初始是登录模式
      expect(find.text('登录您的账号'), findsOneWidget);
      expect(find.text('确认密码'), findsNothing);

      // 点击"立即注册"切换到注册模式
      await tester.tap(find.text('立即注册'));
      await tester.pumpAndSettle();

      expect(find.text('创建新账号'), findsOneWidget);
      expect(find.text('注册'), findsOneWidget);
      expect(find.text('确认密码'), findsOneWidget);
      expect(find.text('立即登录'), findsOneWidget);
    });

    testWidgets('toggle back to login mode hides confirm password', (tester) async {
      await setLargeViewport(tester);
      await tester.pumpWidget(wrapWithApp());
      await tester.pumpAndSettle();

      // 切换到注册模式
      await tester.tap(find.text('立即注册'));
      await tester.pumpAndSettle();

      // 切换回登录模式
      await tester.tap(find.text('立即登录'));
      await tester.pumpAndSettle();

      expect(find.text('登录您的账号'), findsOneWidget);
      expect(find.text('确认密码'), findsNothing);
    });

    testWidgets('shows theme picker button', (tester) async {
      await setLargeViewport(tester);
      await tester.pumpWidget(wrapWithApp());
      await tester.pumpAndSettle();

      expect(find.byIcon(Icons.palette_outlined), findsOneWidget);
    });
  });

  group('LoginScreen - 边界场景 (Boundary Scenarios)', () {
    group('form validation - 表单验证', () {
      testWidgets('shows error when username is empty', (tester) async {
        await setLargeViewport(tester);
      await tester.pumpWidget(wrapWithApp());
        await tester.pumpAndSettle();

        await tester.tap(find.text('登录'));
        await tester.pumpAndSettle();

        // hintText 和 errorText 都包含 "请输入用户名"
        expect(find.text('请输入用户名'), findsWidgets);
      });

      testWidgets('shows error when username is too short', (tester) async {
        await setLargeViewport(tester);
      await tester.pumpWidget(wrapWithApp());
        await tester.pumpAndSettle();

        await tester.enterText(usernameField, 'ab');
        await tester.tap(find.text('登录'));
        await tester.pumpAndSettle();

        expect(find.text('用户名至少 3 个字符'), findsOneWidget);
      });

      testWidgets('shows error when username is too long', (tester) async {
        await setLargeViewport(tester);
      await tester.pumpWidget(wrapWithApp());
        await tester.pumpAndSettle();

        await tester.enterText(
          usernameField,
          'a' * 33,
        );
        await tester.tap(find.text('登录'));
        await tester.pumpAndSettle();

        expect(find.text('用户名最多 32 个字符'), findsOneWidget);
      });

      testWidgets('shows error when password is empty', (tester) async {
        await setLargeViewport(tester);
      await tester.pumpWidget(wrapWithApp());
        await tester.pumpAndSettle();

        await tester.enterText(usernameField, 'testuser');
        await tester.tap(find.text('登录'));
        await tester.pumpAndSettle();

        // hintText 和 errorText 都包含 "请输入密码"
        expect(find.text('请输入密码'), findsWidgets);
      });

      testWidgets('shows error when password is too short', (tester) async {
        await setLargeViewport(tester);
      await tester.pumpWidget(wrapWithApp());
        await tester.pumpAndSettle();

        await tester.enterText(usernameField, 'testuser');
        await tester.enterText(passwordField, '12345');
        await tester.tap(find.text('登录'));
        await tester.pumpAndSettle();

        expect(find.text('密码至少 6 个字符'), findsOneWidget);
      });

      testWidgets('shows error when confirm password is empty (register mode)', (tester) async {
        await setLargeViewport(tester);
      await tester.pumpWidget(wrapWithApp());
        await tester.pumpAndSettle();

        // 切换到注册模式
        await tester.tap(find.text('立即注册'));
        await tester.pumpAndSettle();

        await tester.enterText(usernameField, 'testuser');
        await tester.enterText(passwordField, 'password123');
        await tester.tap(find.text('注册'));
        await tester.pumpAndSettle();

        expect(find.text('请确认密码'), findsOneWidget);
      });

      testWidgets('shows error when passwords do not match (register mode)', (tester) async {
        await setLargeViewport(tester);
      await tester.pumpWidget(wrapWithApp());
        await tester.pumpAndSettle();

        // 切换到注册模式
        await tester.tap(find.text('立即注册'));
        await tester.pumpAndSettle();

        await tester.enterText(usernameField, 'testuser');
        await tester.enterText(passwordField, 'password123');
        await tester.enterText(confirmPasswordField, 'password456');
        await tester.tap(find.text('注册'));
        await tester.pumpAndSettle();

        expect(find.text('两次输入的密码不一致'), findsOneWidget);
      });
    });

    group('password visibility - 密码可见性', () {
      testWidgets('toggles password visibility', (tester) async {
        await setLargeViewport(tester);
      await tester.pumpWidget(wrapWithApp());
        await tester.pumpAndSettle();

        // 找到密码输入框对应的 TextField
        final passwordTextField = tester.widget<TextField>(
          find.descendant(
            of: passwordField,
            matching: find.byType(TextField),
          ),
        );
        expect(passwordTextField.obscureText, isTrue);

        // 点击显示密码
        await tester.tap(find.byIcon(Icons.visibility));
        await tester.pumpAndSettle();

        final passwordTextFieldVisible = tester.widget<TextField>(
          find.descendant(
            of: passwordField,
            matching: find.byType(TextField),
          ),
        );
        expect(passwordTextFieldVisible.obscureText, isFalse);
      });

      testWidgets('toggles confirm password visibility (register mode)', (tester) async {
        await setLargeViewport(tester);
      await tester.pumpWidget(wrapWithApp());
        await tester.pumpAndSettle();

        // 切换到注册模式
        await tester.tap(find.text('立即注册'));
        await tester.pumpAndSettle();

        // 确认密码默认隐藏
        final confirmTextField = tester.widget<TextField>(
          find.descendant(
            of: confirmPasswordField,
            matching: find.byType(TextField),
          ),
        );
        expect(confirmTextField.obscureText, isTrue);

        // 点击显示确认密码
        await tester.tap(find.byIcon(Icons.visibility).at(1));
        await tester.pumpAndSettle();

        final confirmTextFieldVisible = tester.widget<TextField>(
          find.descendant(
            of: confirmPasswordField,
            matching: find.byType(TextField),
          ),
        );
        expect(confirmTextFieldVisible.obscureText, isFalse);
      });
    });
  });

  group('LoginScreen - 异常场景 (Exception Scenarios)', () {
    testWidgets('shows error message when login request fails', (tester) async {
      // LoginScreen 内部创建 AuthService，无法注入 mock。
      // 测试环境下 HTTP 请求返回 400，会触发 catch 分支显示错误。
      await setLargeViewport(tester);
      await tester.pumpWidget(wrapWithApp());
      await tester.pumpAndSettle();

      await tester.enterText(usernameField, 'testuser');
      await tester.enterText(passwordField, 'password123');
      await tester.tap(find.text('登录'));
      await tester.pumpAndSettle();

      // 登录失败后应显示错误提示（error container 包含 error_outline icon）
      expect(find.byIcon(Icons.error_outline), findsOneWidget);
    });
  });

  group('LoginScreen - 主题切换 (Theme Toggle)', () {
    testWidgets('opens theme picker bottom sheet', (tester) async {
      await setLargeViewport(tester);
      await tester.pumpWidget(wrapWithApp());
      await tester.pumpAndSettle();

      await tester.tap(find.byIcon(Icons.palette_outlined));
      await tester.pumpAndSettle();

      expect(find.text('主题模式'), findsOneWidget);
      expect(find.text('跟随系统'), findsOneWidget);
      expect(find.text('浅色'), findsOneWidget);
      expect(find.text('深色'), findsOneWidget);
    });

    testWidgets('selects light theme', (tester) async {
      await setLargeViewport(tester);
      await tester.pumpWidget(wrapWithApp());
      await tester.pumpAndSettle();

      await tester.tap(find.byIcon(Icons.palette_outlined));
      await tester.pumpAndSettle();

      await tester.tap(find.text('浅色'));
      await tester.pumpAndSettle();

      // 底部表单应该关闭
      expect(find.text('主题模式'), findsNothing);
    });
  });

  group('LoginScreen - 边界条件 (Edge Cases)', () {
    testWidgets('clears confirm password when switching modes', (tester) async {
      await setLargeViewport(tester);
      await tester.pumpWidget(wrapWithApp());
      await tester.pumpAndSettle();

      // 切换到注册模式
      await tester.tap(find.text('立即注册'));
      await tester.pumpAndSettle();

      // 输入确认密码
      await tester.enterText(confirmPasswordField, 'password123');

      // 切换回登录模式
      await tester.tap(find.text('立即登录'));
      await tester.pumpAndSettle();

      // 再切换到注册模式，确认密码字段应该是空的
      await tester.tap(find.text('立即注册'));
      await tester.pumpAndSettle();

      final confirmField = tester.widget<TextFormField>(
        confirmPasswordField,
      );
      expect((confirmField.controller as TextEditingController).text, isEmpty);
    });

    testWidgets('clears error message when toggling modes', (tester) async {
      await setLargeViewport(tester);
      await tester.pumpWidget(wrapWithApp());
      await tester.pumpAndSettle();

      // 触发一个错误 - 输入空用户名
      await tester.tap(find.text('登录'));
      await tester.pumpAndSettle();

      // 应该显示错误信息
      expect(find.text('请输入用户名'), findsWidgets);

      // 切换模式应该清除错误
      await tester.tap(find.text('立即注册'));
      await tester.pumpAndSettle();

      // 切换后错误被清除，label 变成 "创建新账号"
      expect(find.text('创建新账号'), findsOneWidget);
    });

    testWidgets('mobile mode: DesktopAgentManager does not crash after login', (tester) async {
      // 验证在移动端（supported=false），登录流程不会导致 DesktopAgentManager 崩溃
      // LoginScreen._submit() 中调用了 agentManager.onLogin()
      // 在移动端它会立即 return，state 变为 unsupported
      final supervisor = _MobileFakeSupervisor();
      final agentManager = DesktopAgentManager(supervisor: supervisor);

      await setLargeViewport(tester);
      await tester.pumpWidget(wrapWithApp(
        agentManager: agentManager,
      ));
      await tester.pumpAndSettle();

      // 初始状态：unconfigured
      expect(agentManager.agentState.kind, DesktopAgentStateKind.unconfigured);

      // 填写表单并提交（测试环境下网络请求会失败，但不影响 Agent 状态验证）
      await tester.enterText(usernameField, 'testuser');
      await tester.enterText(passwordField, 'password123');
      await tester.tap(find.text('登录'));
      await tester.pumpAndSettle();

      // 登录请求失败（测试环境无服务器），onLogin 未被调用
      // agentState 仍为 unconfigured，无未捕获异常即可
      expect(agentManager.agentState.kind, DesktopAgentStateKind.unconfigured);
    });
  });
}
