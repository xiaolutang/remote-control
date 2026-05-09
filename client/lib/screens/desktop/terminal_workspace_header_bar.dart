import 'package:flutter/material.dart';

import '../../models/runtime_device.dart';
import '../../models/runtime_terminal.dart';
import '../../navigation/account_menu_actions.dart';
import '../../services/desktop/desktop_agent_manager.dart';
import '../../services/desktop/desktop_workspace_controller.dart';

class WorkspaceHeaderBar extends StatelessWidget {
  const WorkspaceHeaderBar({
    super.key,
    required this.device,
    required this.terminal,
    required this.creatingTerminal,
    required this.desktopAgentState,
    required this.state,
    required this.onOpenTerminalMenu,
    required this.onRefresh,
    required this.onTheme,
    required this.onProfile,
    required this.onFeedback,
    required this.onLogout,
    this.onSkillConfig,
  });

  final RuntimeDevice? device;
  final RuntimeTerminal? terminal;
  final bool creatingTerminal;
  final DesktopAgentState? desktopAgentState;
  final WorkspaceState state;
  final VoidCallback? onOpenTerminalMenu;
  final VoidCallback? onRefresh;
  final VoidCallback? onTheme;
  final VoidCallback? onProfile;
  final VoidCallback? onFeedback;
  final VoidCallback? onLogout;
  final VoidCallback? onSkillConfig;

  @override
  Widget build(BuildContext context) {
    final currentDevice = device;
    if (currentDevice == null) {
      return const SizedBox.shrink();
    }
    final colorScheme = Theme.of(context).colorScheme;
    final iconColor =
        state.deviceReady ? Colors.green.shade600 : colorScheme.error;
    final managedByDesktop = desktopAgentState?.managed ?? false;
    final deviceName = currentDevice.name.isEmpty
        ? currentDevice.deviceId
        : currentDevice.name;
    final terminalTitle = terminal?.title ?? '当前没有打开的终端';
    final statusText = switch (state.kind) {
      WorkspaceStateKind.bootstrappingAgent => '正在启动本机 Agent',
      WorkspaceStateKind.createFailed => '本机 Agent 启动失败，请重试',
      WorkspaceStateKind.readyToCreateFirstTerminal =>
        state.deviceReady ? '' : '将先启动本机 Agent',
      WorkspaceStateKind.deviceOffline => '电脑离线',
      WorkspaceStateKind.readyWithTerminal => managedByDesktop
          ? '${currentDevice.activeTerminals}/${currentDevice.maxTerminals} terminals · Agent 托管中'
          : '${currentDevice.activeTerminals}/${currentDevice.maxTerminals} terminals',
      WorkspaceStateKind.createInProgress => '正在创建 terminal',
    };

    // 紧凑布局：将设备名、编辑和展开按钮放在同一行
    return Padding(
      padding: const EdgeInsets.fromLTRB(12, 8, 12, 6),
      child: Row(
        children: [
          Icon(
            state.deviceReady ? Icons.computer : Icons.computer_outlined,
            size: 18,
            color: iconColor,
          ),
          const SizedBox(width: 8),
          // 设备名
          ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 120),
            child: Text(
              deviceName,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: Theme.of(context).textTheme.titleSmall?.copyWith(
                    fontWeight: FontWeight.w600,
                  ),
            ),
          ),
          const SizedBox(width: 8),
          // 终端标题 + 状态（有终端时合并显示，无终端时只显示状态）
          Expanded(
            child: Text(
              terminal != null ? '$terminalTitle · $statusText' : statusText,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                    color: colorScheme.onSurfaceVariant,
                  ),
            ),
          ),
          // 展开菜单按钮
          IconButton(
            key: const Key('workspace-open-terminal-menu'),
            tooltip: '终端菜单',
            padding: EdgeInsets.zero,
            constraints: const BoxConstraints(minWidth: 36, minHeight: 36),
            onPressed: onOpenTerminalMenu,
            icon: creatingTerminal
                ? const SizedBox(
                    width: 16,
                    height: 16,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Icon(Icons.expand_more, size: 20),
          ),
          // 刷新按钮
          IconButton(
            tooltip: '刷新',
            padding: EdgeInsets.zero,
            constraints: const BoxConstraints(minWidth: 36, minHeight: 36),
            onPressed: onRefresh,
            icon: const Icon(Icons.refresh, size: 20),
          ),
          // 设置按钮 - 小菜单（主题 + 个人信息）
          PopupMenuButton<AccountMenuAction>(
            tooltip: '设置',
            padding: EdgeInsets.zero,
            icon: const Icon(Icons.settings_outlined, size: 20),
            onSelected: (value) {
              switch (value) {
                case AccountMenuAction.theme:
                  onTheme?.call();
                  break;
                case AccountMenuAction.profile:
                  onProfile?.call();
                  break;
                case AccountMenuAction.feedback:
                  onFeedback?.call();
                  break;
                case AccountMenuAction.logout:
                  onLogout?.call();
                  break;
                case AccountMenuAction.knowledgeConfig:
                  onSkillConfig?.call();
                  break;
              }
            },
            itemBuilder: (context) => buildAccountMenuEntries(
              includeKnowledgeConfig: true,
            ),
          ),
        ],
      ),
    );
  }
}
