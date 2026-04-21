import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';
import 'services/config_service.dart';
import 'services/desktop_agent_exit_bridge.dart';
import 'screens/login_screen.dart';
import 'screens/terminal_workspace_screen.dart';
import 'services/app_startup_coordinator.dart';
import 'services/desktop_agent_manager.dart';
import 'services/environment_service.dart';
import 'services/terminal_session_manager.dart';
import 'services/theme_controller.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  SystemChrome.setEnabledSystemUIMode(SystemUiMode.edgeToEdge);
  await EnvironmentService.initialize();
  final config = await ConfigService().loadConfig();
  await DesktopAgentExitBridge.syncTerminationSnapshot(
    keepRunningInBackground: config.keepAgentRunningInBackground,
  );
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
              statusBarBrightness: isDark ? Brightness.dark : Brightness.light,
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
    final serverUrl = EnvironmentService.instance.currentServerUrl;
    final coordinator = AppStartupCoordinator(serverUrl: serverUrl);
    final result = await coordinator.restore(
      agentManager: context.read<DesktopAgentManager>(),
    );

    if (!mounted) return;

    if (result.destination == AppStartupDestination.workspace &&
        result.token != null) {
      Navigator.pushReplacement(
        context,
        MaterialPageRoute(
          builder: (context) => TerminalWorkspaceScreen(
            token: result.token!,
            initialDevices: result.initialDevices,
          ),
        ),
      );
      return;
    }

    Navigator.pushReplacement(
      context,
      MaterialPageRoute(
        builder: (context) => const LoginScreen(),
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
