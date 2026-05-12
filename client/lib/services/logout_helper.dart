import 'dart:io';

import 'app_logger.dart';
import 'auth_service.dart';
import 'desktop/desktop_agent_manager.dart';
import 'desktop/desktop_startup_terminal_cleanup_service.dart';
import 'environment_service.dart';
import 'terminal_session_manager.dart';

/// 统一退出登录流程
///
/// 先清理服务端终端（需要 token），再三步并行：关闭 Agent + 断开终端 + 清除 token
/// 每步独立 try-catch，任何一步失败不阻塞其余步骤。
///
/// 调用方负责后续的 UI 跳转。
Future<void> performSessionTeardown({
  required DesktopAgentManager agentManager,
  required TerminalSessionManager sessionManager,
  AuthService Function(String serverUrl)? authServiceBuilder,
}) async {
  final serverUrl = EnvironmentService.instance.currentServerUrl;
  final authService =
      authServiceBuilder?.call(serverUrl) ?? AuthService(serverUrl: serverUrl);

  // 在 token 清除前，清理服务端残留终端（与 App 启动行为一致）
  await _cleanupServerTerminals(authService, serverUrl);

  await Future.wait([
    // 关闭 Agent（桌面端，token 失效前）
    // onLogout() 内部已包含 isPlatformSupported 检查和 8s 超时
    () async {
      try {
        await agentManager.onLogout();
      } catch (e) {
        _log.error('Agent 关闭失败: $e');
      }
    }(),
    // 断开终端连接
    () async {
      try {
        await sessionManager.disconnectAll();
      } catch (e) {
        _log.error('断开终端失败: $e');
      }
    }(),
    // 清除 token
    () async {
      try {
        await authService.logout();
      } catch (e) {
        _log.error('清除 token 失败: $e');
      }
    }(),
  ]);
}

final AppLogger _log = AppLogger('performLogout');

/// 清理服务端残留终端，与 App 启动行为对齐。
/// Best-effort，失败不阻塞登出流程。
Future<void> _cleanupServerTerminals(
  AuthService authService,
  String serverUrl,
) async {
  if (!Platform.isMacOS && !Platform.isLinux && !Platform.isWindows) {
    return;
  }
  try {
    final savedSession = await authService.getSavedSession(
      includeRefreshToken: false,
    );
    if (savedSession == null) return;

    final token = savedSession['token'];
    final deviceId = savedSession['session_id'];
    if (token == null || deviceId == null || deviceId.isEmpty) return;

    final cleanupService = DesktopStartupTerminalCleanupService(
      serverUrl: serverUrl,
    );
    await cleanupService.cleanup(
      token: token,
      deviceId: deviceId,
      forceCleanup: true,
    );
  } catch (e) {
    _log.error('服务端终端清理失败: $e');
  }
}
