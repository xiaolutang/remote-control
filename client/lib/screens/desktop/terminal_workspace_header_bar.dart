import 'package:flutter/material.dart';

import '../../models/runtime_device.dart';
import '../../models/runtime_terminal.dart';
import '../../navigation/account_menu_actions.dart';
import '../../services/desktop/desktop_agent_manager.dart';
import '../../services/desktop/desktop_workspace_controller.dart';

/// Desktop-only settings menu actions (workspace local, not shared).
/// Extends standard account menu with Agent management and device editing.
enum _DesktopSettingsAction {
  agentAction,
  editDevice,
  scheduleSend,
  scheduledTasks,
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
    this.onAgentAction,
    this.onEditDevice,
    this.desktopActionInFlight = false,
    this.onScheduledTasks,
    this.onScheduleSend,
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
  /// When true, desktop layout is used (single-row header without tab bar).
  final bool isDesktopPlatform;

  /// Callback for Agent start/stop action (desktop only, in settings menu).
  final VoidCallback? onAgentAction;

  /// Callback for device rename action (desktop only, in settings menu).
  final VoidCallback? onEditDevice;

  /// Callback for viewing scheduled tasks for the current terminal.
  final VoidCallback? onScheduledTasks;

  /// Callback for scheduling a new task for the current terminal.
  final VoidCallback? onScheduleSend;

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
          ..._buildDeviceInfoRow(
            context: context,
            iconColor: iconColor,
            deviceName: deviceName,
            statusText: terminal != null ? '$terminalTitle · $statusText' : statusText,
            colorScheme: colorScheme,
            deviceReady: state.deviceReady,
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
                case AccountMenuAction.profile:
                  onProfile?.call();
                case AccountMenuAction.feedback:
                  onFeedback?.call();
                case AccountMenuAction.logout:
                  onLogout?.call();
                case AccountMenuAction.knowledgeConfig:
                  onSkillConfig?.call();
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

  /// Shared device info row: [computer icon] [device name] [status text].
  /// Used by both mobile and desktop layouts to avoid duplication.
  List<Widget> _buildDeviceInfoRow({
    required BuildContext context,
    required Color iconColor,
    required String deviceName,
    required String statusText,
    required ColorScheme colorScheme,
    required bool deviceReady,
  }) {
    return [
      Icon(
        deviceReady ? Icons.computer : Icons.computer_outlined,
        size: 18,
        color: iconColor,
      ),
      const SizedBox(width: 8),
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
    ];
  }

  /// Desktop layout: single-row layout with status text preserved.
  /// Row: [computer icon] [device name] [status text] [menu] [refresh] [settings]
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
      child: Row(
        children: [
          ..._buildDeviceInfoRow(
            context: context,
            iconColor: iconColor,
            deviceName: deviceName,
            statusText: statusText,
            colorScheme: colorScheme,
            deviceReady: state.deviceReady,
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
                case _DesktopSettingsAction.editDevice:
                  onEditDevice?.call();
                case _DesktopSettingsAction.scheduleSend:
                  onScheduleSend?.call();
                case _DesktopSettingsAction.scheduledTasks:
                  onScheduledTasks?.call();
                case _DesktopSettingsAction.theme:
                  onTheme?.call();
                case _DesktopSettingsAction.knowledgeConfig:
                  onSkillConfig?.call();
                case _DesktopSettingsAction.profile:
                  onProfile?.call();
                case _DesktopSettingsAction.feedback:
                  onFeedback?.call();
                case _DesktopSettingsAction.logout:
                  onLogout?.call();
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
              // 定时发送
              if (onScheduleSend != null)
                PopupMenuItem<_DesktopSettingsAction>(
                  key: const Key('workspace-settings-schedule-send'),
                  value: _DesktopSettingsAction.scheduleSend,
                  enabled: terminal != null,
                  child: const Row(
                    children: [
                      Icon(Icons.schedule_send, size: 20),
                      SizedBox(width: 12),
                      Text('定时发送'),
                    ],
                  ),
                ),
              // 定时任务列表
              if (onScheduledTasks != null)
                PopupMenuItem<_DesktopSettingsAction>(
                  key: const Key('workspace-settings-scheduled-tasks'),
                  value: _DesktopSettingsAction.scheduledTasks,
                  enabled: terminal != null,
                  child: const Row(
                    children: [
                      Icon(Icons.schedule, size: 20),
                      SizedBox(width: 12),
                      Text('定时任务'),
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
    );
  }
}
