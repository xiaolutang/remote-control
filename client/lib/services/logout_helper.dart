import 'dart:io';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import 'auth_service.dart';
import 'desktop_agent_manager.dart';
import 'environment_service.dart';
import 'terminal_session_manager.dart';

/// 统一退出登录流程
///
/// 三步并行：关闭 Agent + 断开终端 + 清除 token
/// 每步独立 try-catch，任何一步失败不阻塞其余步骤。
///
/// 调用方负责后续的 UI 跳转。
Future<void> performLogout({
  required BuildContext context,
}) async {
  final agentManager = context.read<DesktopAgentManager>();
  final sessionManager = context.read<TerminalSessionManager>();
  final serverUrl = EnvironmentService.instance.currentServerUrl;

  await Future.wait([
    // 关闭 Agent（桌面端，token 失效前）
    // onLogout() 内部已包含 isPlatformSupported 检查和 8s 超时
    () async {
      try {
        await agentManager.onLogout();
      } catch (e) {
        _log('Agent 关闭失败: $e');
      }
    }(),
    // 断开终端连接
    () async {
      try {
        await sessionManager.disconnectAll();
      } catch (e) {
        _log('断开终端失败: $e');
      }
    }(),
    // 清除 token
    () async {
      try {
        await AuthService(serverUrl: serverUrl).logout();
      } catch (e) {
        _log('清除 token 失败: $e');
      }
    }(),
  ]);
}

/// 退出登录后跳转到指定页面
///
/// 封装 performLogout + Navigator.pushAndRemoveUntil 的完整流程。
/// [destinationBuilder] 返回退出后要跳转到的目标页面。
Future<void> logoutAndNavigate({
  required BuildContext context,
  required WidgetBuilder destinationBuilder,
}) async {
  await performLogout(context: context);
  if (!context.mounted) return;
  Navigator.of(context).pushAndRemoveUntil(
    MaterialPageRoute(builder: destinationBuilder),
    (_) => false,
  );
}

void _log(String message) {
  if (Platform.environment.containsKey('FLUTTER_TEST')) return;
  debugPrint('[performLogout] $message');
}
