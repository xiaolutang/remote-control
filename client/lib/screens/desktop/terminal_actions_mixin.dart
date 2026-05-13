import 'dart:async';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../models/runtime_device.dart';
import '../../models/runtime_terminal.dart';
import '../../services/runtime_selection_controller.dart';
import '../../services/terminal_session_manager.dart';
import '../../widgets/rename_dialog_helper.dart';
import '../../widgets/snack_bar_helper.dart';
import '../../services/desktop/desktop_workspace_controller.dart';

// Tab 上下文菜单动作 -- 类型安全枚举替代字符串分发
enum TabContextAction { rename, scheduleSend, close }

/// 终端 CRUD 操作 Mixin
///
/// 封装终端的创建、切换、关闭、重命名和上下文菜单逻辑。
/// 宿主 State 需要提供 [workspaceController] getter
/// 以及 [mounted] 属性（来自 State）。
mixin TerminalActionsMixin<T extends StatefulWidget> on State<T> {
  /// 子类必须提供 DesktopWorkspaceController 实例
  DesktopWorkspaceController get workspaceController;

  /// 可选：定时发送回调，由宿主 State 提供
  void Function(RuntimeTerminal terminal)? get onScheduleSend => null;

  // ---------------------------------------------------------------------------
  // 终端切换
  // ---------------------------------------------------------------------------

  /// 共享的终端切换处理器（消除回调重复）
  void handleSwitchTerminal(String terminalId) {
    workspaceController.selectTerminal(terminalId);
  }

  /// 共享的终端创建入口（桌面端）
  void handleCreateTerminal() {
    final controller = context.read<RuntimeSelectionController>();
    unawaited(createEmptyTerminal(context, controller));
  }

  /// 统一的创建禁用计算
  bool isCreateDisabled(
    RuntimeDevice device,
    RuntimeSelectionController controller,
  ) =>
      !device.canCreateTerminal || controller.creatingTerminal;

  // ---------------------------------------------------------------------------
  // 终端创建
  // ---------------------------------------------------------------------------

  Future<void> createEmptyTerminal(
    BuildContext context,
    RuntimeSelectionController controller, {
    bool snackBarOnError = false,
  }) async {
    final sessionManager = context.read<TerminalSessionManager>();
    final result = await workspaceController.createTerminal(
      title: '终端',
      cwd: '~',
      command: '/bin/bash',
    );
    if (result == null) {
      if (snackBarOnError && mounted) {
        // ignore: use_build_context_synchronously
        showAppSnackBar(context, '创建终端失败');
      }
      return;
    }
    if (!mounted) return;
    // 仅注册 service 到 session manager，不提前 connect。
    // 连接由 TerminalScreen.connectToServer() 发起，
    // 此时 bindTerminalOutput() 已创建 binding subscription，
    // CONNECTED/SNAPSHOT 事件不会因 broadcast stream 无 listener 而丢失。
    sessionManager.getOrCreate(
      controller.selectedDeviceId,
      result.terminalId,
      () => controller.buildTerminalService(result),
    );
    workspaceController.selectTerminal(result.terminalId);
  }

  // ---------------------------------------------------------------------------
  // 终端关闭
  // ---------------------------------------------------------------------------

  Future<void> confirmCloseTerminal(
    BuildContext context,
    RuntimeSelectionController controller,
    RuntimeTerminal terminal,
  ) async {
    final sessionManager = context.read<TerminalSessionManager>();
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('关闭终端'),
        content: Text('关闭后将断开 "${terminal.title}" 的连接，并释放终端名额。'),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(context).pop(true),
            child: const Text('关闭'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;

    final closed = await controller.closeTerminal(terminal.terminalId);
    if (!mounted) return;
    if (closed == null) {
      // API 失败 -> Tab 保留 + SnackBar 错误提示
      // ignore: use_build_context_synchronously
      showAppSnackBar(context, '关闭终端失败');
      return;
    }
    // Resync selection immediately before any async gap.
    // closeTerminal swaps in the closed terminal and notifies listeners,
    // which triggers a rebuild. Without immediate resync, the IndexedStack
    // sees selectedIndex=-1 because the closed terminal is filtered out.
    await workspaceController.onTerminalClosed(terminal.terminalId);
    await sessionManager.disconnectTerminal(
      controller.selectedDeviceId,
      terminal.terminalId,
    );
  }

  // ---------------------------------------------------------------------------
  // 重命名
  // ---------------------------------------------------------------------------

  Future<void> showRenameDeviceDialog(
    BuildContext context,
    RuntimeSelectionController controller,
    RuntimeDevice device,
  ) async {
    await showRenameDialog(
      context: context,
      title: '编辑设备',
      initialValue: device.name.isEmpty ? device.deviceId : device.name,
      labelText: '设备名称',
      inputKey: 'workspace-rename-device-input',
      submitKey: 'workspace-rename-device-submit',
      onConfirm: (newName) async {
        await controller.updateSelectedDevice(name: newName);
        return true;
      },
    );
  }

  Future<void> showRenameTerminalDialog(
    BuildContext context,
    RuntimeSelectionController controller,
    RuntimeTerminal terminal,
  ) async {
    await showRenameDialog(
      context: context,
      title: '编辑终端标题',
      initialValue: terminal.title,
      labelText: '终端标题',
      inputKey: 'workspace-rename-terminal-input',
      submitKey: 'workspace-rename-terminal-submit',
      onConfirm: (newName) async {
        final renamed =
            await controller.renameTerminal(terminal.terminalId, newName);
        if (renamed == null) {
          // 重命名失败 -> 保持对话框 + SnackBar 提示
          if (context.mounted) {
            showAppSnackBar(context, '重命名终端失败');
          }
          return false;
        }
        return true;
      },
    );
  }

  // ---------------------------------------------------------------------------
  // 上下文菜单
  // ---------------------------------------------------------------------------

  /// F004: 桌面端右键 Tab -> PopupMenu（重命名/关闭）
  void showTabContextMenu(
    BuildContext context,
    RuntimeSelectionController controller,
    String terminalId,
    Offset position,
  ) {
    final terminal = findTerminal(controller, terminalId);
    if (terminal == null) return;

    showMenu<TabContextAction>(
      context: context,
      position: RelativeRect.fromLTRB(
        position.dx, position.dy, position.dx + 1, position.dy + 1,
      ),
      items: buildContextMenuItems(context, terminal),
    ).then((value) {
      if (!mounted) return;
      // ignore: use_build_context_synchronously
      handleTabContextAction(context, controller, terminal, value);
    });
  }

  /// F004: 移动端长按 Tab -> BottomSheet（重命名/关闭）
  Future<void> showMobileTabContextMenu(
    BuildContext context,
    RuntimeSelectionController controller,
    String terminalId,
  ) async {
    final terminal = findTerminal(controller, terminalId);
    if (terminal == null) return;

    final selectedAction = await showModalBottomSheet<TabContextAction>(
      context: context,
      showDragHandle: true,
      builder: (context) {
        final theme = Theme.of(context);
        return SafeArea(
          child: Padding(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  terminal.title,
                  style: theme.textTheme.titleMedium?.copyWith(
                        fontWeight: FontWeight.w700,
                      ),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
                const SizedBox(height: 8),
                ListTile(
                  contentPadding: EdgeInsets.zero,
                  leading: const Icon(Icons.edit_outlined),
                  title: const Text('重命名'),
                  onTap: () => Navigator.of(context).pop(TabContextAction.rename),
                ),
                if (onScheduleSend != null)
                  ListTile(
                    contentPadding: EdgeInsets.zero,
                    leading: const Icon(Icons.schedule),
                    title: const Text('定时发送'),
                    onTap: () {
                      Navigator.of(context).pop(TabContextAction.scheduleSend);
                    },
                  ),
                ListTile(
                  key: const Key('tab-context-close'),
                  contentPadding: EdgeInsets.zero,
                  enabled: !terminal.isClosed,
                  leading: Icon(Icons.close,
                      color: terminal.isClosed ? theme.disabledColor : null),
                  title: Text('关闭',
                      style: terminal.isClosed
                          ? TextStyle(color: theme.disabledColor) : null),
                  onTap: terminal.isClosed
                      ? null
                      : () => Navigator.of(context).pop(TabContextAction.close),
                ),
              ],
            ),
          ),
        );
      },
    );

    if (!mounted) return;
    // ignore: use_build_context_synchronously
    handleTabContextAction(context, controller, terminal, selectedAction);
  }

  /// 共享终端查找
  RuntimeTerminal? findTerminal(
    RuntimeSelectionController controller,
    String terminalId,
  ) =>
      controller.terminals.where((t) => t.terminalId == terminalId).firstOrNull;

  /// 桌面端 PopupMenu 菜单项构建
  List<PopupMenuEntry<TabContextAction>> buildContextMenuItems(
    BuildContext context,
    RuntimeTerminal terminal,
  ) {
    final theme = Theme.of(context);
    return [
      const PopupMenuItem<TabContextAction>(
        value: TabContextAction.rename,
        child: Row(children: [
          Icon(Icons.edit_outlined, size: 20),
          SizedBox(width: 12),
          Text('重命名'),
        ]),
      ),
      if (onScheduleSend != null)
        const PopupMenuItem<TabContextAction>(
          value: TabContextAction.scheduleSend,
          child: Row(children: [
            Icon(Icons.schedule, size: 20),
            SizedBox(width: 12),
            Text('定时发送'),
          ]),
        ),
      PopupMenuItem<TabContextAction>(
        key: const Key('tab-context-close'),
        value: TabContextAction.close,
        enabled: !terminal.isClosed,
        child: Row(children: [
          Icon(Icons.close, size: 20,
              color: terminal.isClosed ? theme.disabledColor : null),
          const SizedBox(width: 12),
          Text('关闭',
              style: terminal.isClosed
                  ? TextStyle(color: theme.disabledColor) : null),
        ]),
      ),
    ];
  }

  /// 上下文菜单动作分发
  void handleTabContextAction(
    BuildContext context,
    RuntimeSelectionController controller,
    RuntimeTerminal terminal,
    TabContextAction? action,
  ) {
    if (action == null || !mounted) return;
    switch (action) {
      case TabContextAction.rename:
        unawaited(showRenameTerminalDialog(context, controller, terminal));
      case TabContextAction.scheduleSend:
        onScheduleSend?.call(terminal);
      case TabContextAction.close:
        unawaited(confirmCloseTerminal(context, controller, terminal));
    }
  }
}
