import 'package:flutter/material.dart';

import '../../models/runtime_device.dart';
import '../../models/runtime_terminal.dart';
import '../../navigation/account_menu_actions.dart';
import '../../services/desktop/desktop_agent_manager.dart';
import '../../services/desktop/desktop_workspace_controller.dart';
import '../../widgets/terminal_tab_bar.dart';

/// Desktop-only settings menu actions (workspace local, not shared).
/// Extends standard account menu with Agent management and device editing.
enum _DesktopSettingsAction {
  agentAction,
  editDevice,
  theme,
  knowledgeConfig,
  profile,
  feedback,
  logout,
}

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
    this.isDesktopPlatform = false,
    this.terminals = const [],
    this.selectedTerminalId,
    this.onSwitchTerminal,
    this.onCreateTerminal,
    this.onTabContextMenu,
    this.onAgentAction,
    this.onEditDevice,
    this.desktopActionInFlight = false,
  });

  final RuntimeDevice? device;
  final RuntimeTerminal? terminal;
  final bool creatingTerminal;
  final DesktopAgentState? desktopAgentState;
  final WorkspaceState state;

  /// Whether an Agent start/stop action is currently in-flight.
  /// When true, the Agent action in settings menu is disabled.
  final bool desktopActionInFlight;
  final VoidCallback? onOpenTerminalMenu;
  final VoidCallback? onRefresh;
  final VoidCallback? onTheme;
  final VoidCallback? onProfile;
  final VoidCallback? onFeedback;
  final VoidCallback? onLogout;
  final VoidCallback? onSkillConfig;

  /// Whether the current platform is desktop (macOS/Windows/Linux).
  /// When true, TerminalTabBar replaces the expand_more button and terminal title.
  final bool isDesktopPlatform;

  /// List of all terminal sessions for the tab bar (desktop only).
  final List<RuntimeTerminal> terminals;

  /// ID of the currently selected terminal (desktop only).
  final String? selectedTerminalId;

  /// Callback when user switches terminal via tab bar (desktop only).
  final ValueChanged<String>? onSwitchTerminal;

  /// Callback when user creates a new terminal via tab bar + button (desktop only).
  final VoidCallback? onCreateTerminal;

  /// Callback when user triggers context menu on a terminal tab.
  /// Provides the terminal ID and the tap position for menu placement.
  final void Function(String terminalId, Offset position)? onTabContextMenu;

  /// Callback for Agent start/stop action (desktop only, in settings menu).
  final VoidCallback? onAgentAction;

  /// Callback for device rename action (desktop only, in settings menu).
  final VoidCallback? onEditDevice;

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

    if (isDesktopPlatform) {
      return _buildDesktopLayout(
        context: context,
        colorScheme: colorScheme,
        iconColor: iconColor,
        deviceName: deviceName,
        currentDevice: currentDevice,
        statusText: statusText,
        agentOnline: currentDevice.agentOnline,
        managedByDesktop: managedByDesktop,
      );
    }

    // 移动端布局：expand_more 条件隐藏
    // F004: _showTerminalMenu 不再有终端 CRUD，移动端菜单为空
    // 当 onOpenTerminalMenu 为 null 时不渲染 expand_more 按钮
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
          // 展开菜单按钮（F004: 菜单空化后条件隐藏）
          if (onOpenTerminalMenu != null)
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
          // 设置按钮 - 小菜单（主题 + 个人信息，移动端不含 Agent/设备管理）
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

  /// Desktop layout: two-row layout with status text preserved.
  /// Row 1: [computer icon] [device name] [status text] [menu] [refresh] [settings]
  /// Row 2: [TerminalTabBar (full width)]
  Widget _buildDesktopLayout({
    required BuildContext context,
    required ColorScheme colorScheme,
    required Color iconColor,
    required String deviceName,
    required RuntimeDevice currentDevice,
    required String statusText,
    required bool agentOnline,
    required bool managedByDesktop,
  }) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(12, 8, 12, 0),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          // Row 1: device info + action buttons
          Row(
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
              // 状态文本（保留原有运行态信息）
              Expanded(
                child: Text(
                  statusText,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: Theme.of(context).textTheme.bodySmall?.copyWith(
                        color: colorScheme.onSurfaceVariant,
                      ),
                ),
              ),
              // 菜单按钮（保留用于 Agent 管理、设备编辑等桌面端管理功能）
              IconButton(
                key: const Key('workspace-open-terminal-menu'),
                tooltip: '管理菜单',
                padding: EdgeInsets.zero,
                constraints: const BoxConstraints(minWidth: 36, minHeight: 36),
                onPressed: onOpenTerminalMenu,
                icon: creatingTerminal
                    ? const SizedBox(
                        width: 16,
                        height: 16,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : const Icon(Icons.more_horiz, size: 20),
              ),
              // 刷新按钮
              IconButton(
                tooltip: '刷新',
                padding: EdgeInsets.zero,
                constraints: const BoxConstraints(minWidth: 36, minHeight: 36),
                onPressed: onRefresh,
                icon: const Icon(Icons.refresh, size: 20),
              ),
              // 设置按钮 - 桌面端含 Agent 管理 + 设备编辑（workspace 局部）
              PopupMenuButton<_DesktopSettingsAction>(
                tooltip: '设置',
                padding: EdgeInsets.zero,
                icon: const Icon(Icons.settings_outlined, size: 20),
                onSelected: (value) {
                  switch (value) {
                    case _DesktopSettingsAction.agentAction:
                      onAgentAction?.call();
                      break;
                    case _DesktopSettingsAction.editDevice:
                      onEditDevice?.call();
                      break;
                    case _DesktopSettingsAction.theme:
                      onTheme?.call();
                      break;
                    case _DesktopSettingsAction.knowledgeConfig:
                      onSkillConfig?.call();
                      break;
                    case _DesktopSettingsAction.profile:
                      onProfile?.call();
                      break;
                    case _DesktopSettingsAction.feedback:
                      onFeedback?.call();
                      break;
                    case _DesktopSettingsAction.logout:
                      onLogout?.call();
                      break;
                  }
                },
                itemBuilder: (context) => [
                  // Agent 管理（workspace 局部）
                  // Guard: 与管理菜单一致 — 外部启动的 Agent 不可操作，in-flight 时禁用
                  PopupMenuItem<_DesktopSettingsAction>(
                    key: const Key('workspace-settings-agent-action'),
                    value: _DesktopSettingsAction.agentAction,
                    enabled: !desktopActionInFlight &&
                        (managedByDesktop || !agentOnline),
                    child: Row(
                      children: [
                        desktopActionInFlight
                            ? const SizedBox(
                                width: 20,
                                height: 20,
                                child:
                                    CircularProgressIndicator(strokeWidth: 2),
                              )
                            : Icon(
                                agentOnline
                                    ? Icons.stop_circle_outlined
                                    : Icons.play_circle_outline,
                                size: 20,
                              ),
                        const SizedBox(width: 12),
                        Text(agentOnline
                            ? '停止本机 Agent'
                            : '启动本机 Agent'),
                      ],
                    ),
                  ),
                  // 设备编辑（workspace 局部）
                  const PopupMenuItem<_DesktopSettingsAction>(
                    key: Key('workspace-settings-rename-device'),
                    value: _DesktopSettingsAction.editDevice,
                    child: Row(
                      children: [
                        Icon(Icons.edit_outlined, size: 20),
                        SizedBox(width: 12),
                        Text('编辑设备名称'),
                      ],
                    ),
                  ),
                  const PopupMenuDivider(),
                  // 主题
                  const PopupMenuItem<_DesktopSettingsAction>(
                    value: _DesktopSettingsAction.theme,
                    child: Row(
                      children: [
                        Icon(Icons.palette_outlined, size: 20),
                        SizedBox(width: 12),
                        Text('主题'),
                      ],
                    ),
                  ),
                  // 知识管理
                  if (onSkillConfig != null)
                    const PopupMenuItem<_DesktopSettingsAction>(
                      value: _DesktopSettingsAction.knowledgeConfig,
                      child: Row(
                        children: [
                          Icon(Icons.menu_book_outlined, size: 20),
                          SizedBox(width: 12),
                          Text('知识管理'),
                        ],
                      ),
                    ),
                  const PopupMenuDivider(),
                  // 个人信息
                  const PopupMenuItem<_DesktopSettingsAction>(
                    value: _DesktopSettingsAction.profile,
                    child: Row(
                      children: [
                        Icon(Icons.person_outline, size: 20),
                        SizedBox(width: 12),
                        Text('个人信息'),
                      ],
                    ),
                  ),
                  // 问题反馈
                  const PopupMenuItem<_DesktopSettingsAction>(
                    value: _DesktopSettingsAction.feedback,
                    child: Row(
                      children: [
                        Icon(Icons.feedback_outlined, size: 20),
                        SizedBox(width: 12),
                        Text('问题反馈'),
                      ],
                    ),
                  ),
                  const PopupMenuDivider(),
                  // 退出登录
                  const PopupMenuItem<_DesktopSettingsAction>(
                    value: _DesktopSettingsAction.logout,
                    child: Row(
                      children: [
                        Icon(Icons.logout, size: 20),
                        SizedBox(width: 12),
                        Text('退出登录'),
                      ],
                    ),
                  ),
                ],
              ),
            ],
          ),
          // Row 2: TerminalTabBar
          TerminalTabBar(
            terminals: terminals,
            selectedTerminalId: selectedTerminalId,
            onSwitch: onSwitchTerminal ?? (_) {},
            onCreate: onCreateTerminal ?? () {},
            createDisabled:
                !currentDevice.canCreateTerminal || creatingTerminal,
            onContextMenu: onTabContextMenu,
          ),
        ],
      ),
    );
  }
}
