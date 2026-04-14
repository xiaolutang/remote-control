import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';
import 'screens/login_screen.dart';
import 'screens/terminal_workspace_screen.dart';
import 'services/auth_service.dart';
import 'services/config_service.dart';
import 'services/desktop_agent_manager.dart';
import 'services/terminal_session_manager.dart';
import 'services/theme_controller.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  SystemChrome.setEnabledSystemUIMode(SystemUiMode.edgeToEdge);
  runApp(const RemoteControlApp());
}

class RemoteControlApp extends StatelessWidget {
  const RemoteControlApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MultiProvider(
      providers: [
        ChangeNotifierProvider(create: (_) => ThemeController()..load()),
        ChangeNotifierProvider(create: (_) => TerminalSessionManager()),
        ChangeNotifierProvider(create: (_) => DesktopAgentManager()),
      ],
      child: const _AppShell(),
    );
  }
}

/// App 壳层 — 监听 App 生命周期，关闭时停止 Agent（桌面端）
class _AppShell extends StatefulWidget {
  const _AppShell();

  @override
  State<_AppShell> createState() => _AppShellState();
}

class _AppShellState extends State<_AppShell> with WidgetsBindingObserver {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.detached) {
      // App 关闭时停止 Agent（桌面端）；fire-and-forget
      final agentManager = context.read<DesktopAgentManager>();
      agentManager.onAppClose();
    }
  }

  @override
  Widget build(BuildContext context) {
    return Consumer<ThemeController>(
      builder: (context, themeController, _) {
        final theme = ThemeData(
          colorScheme: ColorScheme.fromSeed(seedColor: Colors.blue),
          useMaterial3: true,
          appBarTheme: const AppBarTheme(
            backgroundColor: Colors.transparent,
            elevation: 0,
            scrolledUnderElevation: 0,
          ),
        );
        final darkTheme = ThemeData(
          colorScheme: ColorScheme.fromSeed(
            seedColor: Colors.blue,
            brightness: Brightness.dark,
          ),
          useMaterial3: true,
          appBarTheme: const AppBarTheme(
            backgroundColor: Colors.transparent,
            elevation: 0,
            scrolledUnderElevation: 0,
          ),
        );

        return MaterialApp(
          title: 'Remote Control',
          theme: theme,
          darkTheme: darkTheme,
          themeMode: themeController.themeMode,
          builder: (context, child) {
            final activeTheme = Theme.of(context);
            final isDark = activeTheme.brightness == Brightness.dark;
            final overlayStyle = SystemUiOverlayStyle(
              statusBarColor: Colors.transparent,
              systemNavigationBarColor: Colors.transparent,
              systemNavigationBarDividerColor: Colors.transparent,
              statusBarIconBrightness:
                  isDark ? Brightness.light : Brightness.dark,
              statusBarBrightness:
                  isDark ? Brightness.dark : Brightness.light,
              systemNavigationBarIconBrightness:
                  isDark ? Brightness.light : Brightness.dark,
              systemStatusBarContrastEnforced: false,
              systemNavigationBarContrastEnforced: false,
            );

            return AnnotatedRegion<SystemUiOverlayStyle>(
              value: overlayStyle,
              child: child ?? const SizedBox.shrink(),
            );
          },
          home: const SplashPage(),
        );
      },
    );
  }
}

/// 启动页 - 检查自动登录
class SplashPage extends StatefulWidget {
  const SplashPage({super.key});

  @override
  State<SplashPage> createState() => _SplashPageState();
}

class _SplashPageState extends State<SplashPage> {
  @override
  void initState() {
    super.initState();
    _checkAutoLogin();
  }

  Future<void> _checkAutoLogin() async {
    final configService = ConfigService();
    final config = await configService.loadConfig();

    // 检查是否有保存的凭证
    Map<String, String>? credentials;
    final authService = AuthService(serverUrl: config.serverUrl);
    try {
      credentials = await authService.getSavedCredentials();
    } catch (e) {
      // secure storage 读取失败（如 macOS keychain 问题），直接跳登录页
      if (!mounted) return;
      Navigator.pushReplacement(
        context,
        MaterialPageRoute(
          builder: (context) => LoginScreen(serverUrl: config.serverUrl),
        ),
      );
      return;
    }

    if (credentials != null) {
      // 尝试自动登录
      try {
        final result = await authService.login(
          credentials['username']!,
          credentials['password']!,
        );

        if (!mounted) return;

        // 自动登录成功，恢复 Agent（桌面端）
        final token = result['token'] as String;
        final sessionId = result['session_id'] as String?;
        final username = credentials['username']!;

        // 恢复 Agent 生命周期（不阻塞进入首页）
        if (sessionId != null && sessionId.isNotEmpty) {
          try {
            final agentManager = context.read<DesktopAgentManager>();
            await agentManager.onAppStart(
              serverUrl: config.serverUrl,
              token: token,
              username: username,
              deviceId: sessionId,
            ).timeout(
              const Duration(seconds: 15),
              onTimeout: () {
                // Agent 恢复超时，继续进入首页
              },
            );
          } catch (e) {
            // Agent 恢复失败，继续进入首页
          }
        }

        if (!mounted) return;

        // 跳转到终端工作台
        Navigator.pushReplacement(
          context,
          MaterialPageRoute(
            builder: (context) => TerminalWorkspaceScreen(
              serverUrl: config.serverUrl,
              token: token,
            ),
          ),
        );
        return;
      } catch (e) {
        // 自动登录失败，继续显示登录页面
      }
    }

    if (!mounted) return;

    // 显示登录页面
    Navigator.pushReplacement(
      context,
      MaterialPageRoute(
        builder: (context) => LoginScreen(serverUrl: config.serverUrl),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(
              Icons.terminal,
              size: 64,
              color: Theme.of(context).colorScheme.primary,
            ),
            const SizedBox(height: 16),
            const CircularProgressIndicator(),
            const SizedBox(height: 16),
            Text(
              '正在加载...',
              style: Theme.of(context).textTheme.bodyLarge,
            ),
          ],
        ),
      ),
    );
  }
}
