import 'dart:async';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../models/runtime_device.dart';
import '../../models/runtime_terminal.dart';
import '../../navigation/account_menu_actions.dart';
import '../../services/account_menu_action_handler.dart';
import '../../services/auth_service.dart';
import '../../services/app_logger.dart';
import '../../services/config_service.dart';
import '../../services/desktop/desktop_agent_bootstrap_service.dart';
import '../../services/desktop/desktop_agent_manager.dart';
import '../../services/desktop/desktop_workspace_controller.dart';
import '../../services/environment_service.dart';
import '../../services/logout_helper.dart';
import '../../services/runtime_device_service.dart';
import '../../services/runtime_selection_controller.dart';
import '../../services/terminal_session_manager.dart';
import '../../services/ui_helpers.dart';
import '../../services/websocket_service.dart';
import '../login_screen.dart';
import '../skill_config_screen.dart';
import '../terminal_screen.dart';
import '../../widgets/compact_tab_strip.dart';
import 'terminal_workspace_header_bar.dart';
import 'terminal_workspace_empty_state.dart';

class TerminalWorkspaceScreen extends StatelessWidget {
  const TerminalWorkspaceScreen({
    super.key,
    required this.token,
    this.initialDevices = const <RuntimeDevice>[],
    RuntimeSelectionController? controller,
    DesktopAgentBootstrapService? agentBootstrapService,
  })  : _controller = controller,
        _agentBootstrapService = agentBootstrapService;

  final String token;
  final List<RuntimeDevice> initialDevices;
  final RuntimeSelectionController? _controller;
  final DesktopAgentBootstrapService? _agentBootstrapService;

  @override
  Widget build(BuildContext context) {
    final serverUrl = EnvironmentService.instance.currentServerUrl;
    return ChangeNotifierProvider<RuntimeSelectionController>(
      create: (_) => _controller ??
          RuntimeSelectionController(
            serverUrl: serverUrl,
            token: token,
            runtimeService: RuntimeDeviceService(serverUrl: serverUrl),
            initialDevices: initialDevices,
          )
        ..initialize(),
      child: _TerminalWorkspaceView(
        token: token,
        agentBootstrapService:
            _agentBootstrapService ?? DesktopAgentBootstrapService(),
      ),
    );
  }
}

class _TerminalWorkspaceView extends StatefulWidget {
  const _TerminalWorkspaceView({
    required this.token,
    required this.agentBootstrapService,
  });

  final String token;
  final DesktopAgentBootstrapService agentBootstrapService;

  @override
  State<_TerminalWorkspaceView> createState() => _TerminalWorkspaceViewState();
}

class _TerminalWorkspaceViewState extends State<_TerminalWorkspaceView> {
  late final DesktopWorkspaceController _workspaceController;
  StreamSubscription<Map<String, dynamic>>? _terminalsChangedSubscription;
  WebSocketService? _lastListenedService;
  Timer? _refreshDebounceTimer;
  String? _pendingToastAction;
  String? _pendingToastTerminalId;
  bool _authDialogShowing = false;

  @override
  void initState() {
    super.initState();
    _workspaceController = DesktopWorkspaceController(
      serverUrl: EnvironmentService.instance.currentServerUrl,
      token: widget.token,
      agentBootstrapService: widget.agentBootstrapService,
      configService: ConfigService(),
    );
  }

  @override
  void dispose() {
    _terminalsChangedSubscription?.cancel();
    _cleanupServiceListener();
    _refreshDebounceTimer?.cancel();
    unawaited(_workspaceController.handleViewDispose());
    _workspaceController.dispose();
    super.dispose();
  }

  /// 清理 service 状态监听器
  void _cleanupServiceListener() {
    _terminalsChangedSubscription?.cancel();
    _terminalsChangedSubscription = null;
    _lastListenedService = null;
  }

  /// 在终端 WebSocket 连接上监听 terminals_changed 消息
  /// 使用 identical() 避免重复订阅同一个 service 实例
  ///
  /// 注意：设备在线状态 (agentOnline) 由 Server API 维护，不从 WebSocket 同步。
  /// 这符合架构原则："Server 是在线态唯一权威源，客户端不得自行推断"
  void _listenToTerminalsChangedIfNeeded(WebSocketService service) {
    if (identical(_lastListenedService, service)) {
      return;
    }

    // 先清理旧的监听器
    _cleanupServiceListener();

    _lastListenedService = service;
    final controller = context.read<RuntimeSelectionController>();

    _terminalsChangedSubscription =
        service.terminalsChangedStream.listen((data) {
      if (!mounted) return;
      final action = data['action'] as String?;
      final terminalId = data['terminal_id'] as String?;
      if (action == null) return;

      // 防抖：300ms 内的多次事件合并为一次刷新
      _pendingToastAction = action;
      _pendingToastTerminalId = terminalId;
      _refreshDebounceTimer?.cancel();
      _refreshDebounceTimer = Timer(const Duration(milliseconds: 300), () {
        if (!mounted) return;
        final a = _pendingToastAction;
        final t = _pendingToastTerminalId;
        _pendingToastAction = null;
        _pendingToastTerminalId = null;
        if (a != null) {
          unawaited(_refreshWithToast(controller, a, t));
        }
      });
    });
  }

  Future<void> _refreshWithToast(
    RuntimeSelectionController controller,
    String action,
    String? changedTerminalId,
  ) async {
    // 在刷新前，先根据 ID 查找终端标题（刷新后可能已不存在）
    String? terminalTitle;
    if (changedTerminalId != null) {
      // 使用 where + firstOrNull 避免空列表崩溃
      final terminal = controller.terminals
          .where((t) => t.terminalId == changedTerminalId)
          .firstOrNull;
      terminalTitle = terminal?.title;
    }

    // 使用静默模式刷新，避免 UI 闪烁
    await controller.refreshTerminals(silent: true);

    if (!mounted) return;
    final messenger = ScaffoldMessenger.of(context);

    // 根据 action 确定提示文本，未知 action 跳过 toast
    final actionText = switch (action) {
      'created' => '新建',
      'closed' => '关闭',
      _ => null,
    };
    if (actionText == null) return;

    // 清除旧的 SnackBar，避免堆积
    messenger.clearSnackBars();

    final terminalText = terminalTitle ?? '终端';
    messenger.showSnackBar(
      SnackBar(
        content: Text('$terminalText 已在另一端$actionText'),
        duration: const Duration(seconds: 2),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final controller = context.watch<RuntimeSelectionController>();
    _workspaceController.attachRuntimeController(controller);

    // 检测 401 认证错误，弹窗提示并跳转登录页
    final authError = controller.authError;
    if (authError != null && !_authDialogShowing) {
      _authDialogShowing = true;
      // 使用 addPostFrameCallback 避免 build 中直接弹窗
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (!mounted) return;
        _handleAuthError(context, authError);
      });
    }

    return AnimatedBuilder(
      animation: _workspaceController,
      builder: (context, _) {
        final device = controller.selectedDevice;
        final terminals = controller.terminals;
        final workspaceState = _workspaceController.state;
        final selectedTerminal = _workspaceController.selectedTerminal;

        return Scaffold(
          resizeToAvoidBottomInset: controller.isDesktopPlatform,
          body: SafeArea(
            child: Column(
              children: [
                if (controller.errorMessage != null)
                  MaterialBanner(
                    content: Text(controller.errorMessage!),
                    actions: [
                      TextButton(
                        onPressed: _workspaceController.refresh,
                        child: const Text('重试'),
                      ),
                    ],
                  ),
                WorkspaceHeaderBar(
                  device: device,
                  terminal: workspaceState.selectedTerminal,
                  creatingTerminal: controller.creatingTerminal,
                  desktopAgentState: _workspaceController.desktopAgentState,
                  state: workspaceState,
                  onOpenTerminalMenu: device == null
                      ? null
                      : controller.isDesktopPlatform
                          ? () => _showTerminalMenu(
                                context,
                                controller,
                                device,
                                _workspaceController.desktopAgentState,
                              )
                          : null,
                  onRefresh: _workspaceController.refresh,
                  onTheme: () => showThemePickerSheet(context),
                  onProfile: () => _handleAccountAction(
                    context,
                    AccountMenuAction.profile,
                  ),
                  onFeedback: () => _handleAccountAction(
                    context,
                    AccountMenuAction.feedback,
                  ),
                  onLogout: () => _handleAccountAction(
                    context,
                    AccountMenuAction.logout,
                  ),
                  onSkillConfig: () => Navigator.of(context).push(
                    MaterialPageRoute(
                      builder: (_) => const SkillConfigScreen(),
                    ),
                  ),
                  // F002: 桌面端 Tab Bar 集成
                  isDesktopPlatform: controller.isDesktopPlatform,
                  terminals: terminals,
                  selectedTerminalId: selectedTerminal?.terminalId,
                  onSwitchTerminal: (terminalId) {
                    _workspaceController.selectTerminal(terminalId);
                  },
                  onCreateTerminal: () {
                    unawaited(_createEmptyTerminal(context, controller));
                  },
                  // F004: 桌面端右键 Tab 上下文菜单
                  onTabContextMenu: (terminalId, position) {
                    _showTabContextMenu(
                      context,
                      controller,
                      terminalId,
                      position,
                    );
                  },
                  // F004: 桌面端设置菜单 Agent 管理/设备编辑
                  onAgentAction: () {
                    final agentOnline = device?.agentOnline ?? false;
                    if (agentOnline) {
                      unawaited(_handleStopLocalAgent(context));
                    } else {
                      unawaited(_handleStartLocalAgent(context));
                    }
                  },
                  onEditDevice: () {
                    unawaited(_showRenameDeviceDialog(
                        context, controller, device!));
                  },
                  desktopActionInFlight:
                      _workspaceController.desktopActionInFlight,
                ),
                Expanded(
                  child: _buildBody(
                    context: context,
                    controller: controller,
                    device: device,
                    terminal: workspaceState.selectedTerminal,
                    terminals: terminals,
                    state: workspaceState,
                  ),
                ),
              ],
            ),
          ),
        );
      },
    );
  }

  Widget _buildBody({
    required BuildContext context,
    required RuntimeSelectionController controller,
    required RuntimeDevice? device,
    required RuntimeTerminal? terminal,
    required List<RuntimeTerminal> terminals,
    required WorkspaceState state,
  }) {
    if (controller.loadingDevices || controller.loadingTerminals) {
      return const Center(child: CircularProgressIndicator());
    }

    if (device == null) {
      return const Center(child: Text('当前没有可用设备'));
    }

    if (state.kind == WorkspaceStateKind.deviceOffline) {
      return WorkspaceEmptyState(
        icon: Icons.computer_outlined,
        title: '电脑离线',
        message: '当前电脑不可创建或承载 terminal，请先启动或重连本机 Agent。',
        actionLabel: '刷新状态',
        actionKey: const Key('workspace-empty-refresh-action'),
        onAction: () {
          unawaited(controller.loadDevices());
        },
      );
    }

    if (terminal == null) {
      if (state.kind == WorkspaceStateKind.bootstrappingAgent) {
        return const WorkspaceEmptyState(
          icon: Icons.sync,
          title: '正在启动本机 Agent',
          message: '桌面端正在尝试恢复本机 Agent，成功后即可创建第一个 terminal。',
          loading: true,
        );
      }

      if (state.kind == WorkspaceStateKind.createFailed) {
        return WorkspaceEmptyState(
          icon: Icons.error_outline,
          title: '启动本机 Agent 失败',
          message: '当前还没有 terminal。请重试启动本机 Agent，成功后即可创建第一个 terminal。',
          actionLabel: '重试启动',
          actionKey: const Key('workspace-empty-retry-start'),
          onAction: () {
            unawaited(_workspaceController.startLocalAgent());
          },
        );
      }

      return WorkspaceEmptyState(
        icon: Icons.add_box_outlined,
        title: '创建第一个终端',
        message: state.deviceReady
            ? '当前还没有 terminal，创建后会直接进入新的工作标签页。'
            : '当前本机 Agent 未在线，创建时会先尝试启动本机 Agent，再进入新的工作标签页。',
        actionLabel: state.deviceReady ? '新建终端' : '启动并创建终端',
        actionKey: const Key('workspace-empty-create-action'),
        onAction: () {
          unawaited(_createEmptyTerminal(
            context,
            controller,
            snackBarOnError: !controller.isDesktopPlatform,
          ));
        },
      );
    }

    final service = context.read<TerminalSessionManager>().getOrCreate(
          controller.selectedDeviceId,
          terminal.terminalId,
          () => controller.buildTerminalService(terminal),
        );

    // 在现有终端连接上监听跨平台终端变化通知
    _listenToTerminalsChangedIfNeeded(service);

    return Column(
      children: [
        Expanded(
          child: ChangeNotifierProvider<WebSocketService>.value(
            value: service,
            child: KeyedSubtree(
              key: ValueKey<String>(terminal.terminalId),
              child: TerminalScreen(
                embedded: true,
                bottomChrome: controller.isDesktopPlatform
                    ? null
                    : CompactTabStrip(
                        terminals: terminals,
                        selectedTerminalId: terminal?.terminalId,
                        onSwitch: (terminalId) {
                          _workspaceController.selectTerminal(terminalId);
                        },
                        onCreate: () {
                          unawaited(_createEmptyTerminal(
                            context,
                            controller,
                            snackBarOnError: true,
                          ));
                        },
                        // F004: 移动端长按 Tab 上下文菜单
                        onLongPress: (terminalId) {
                          _showMobileTabContextMenu(
                            context,
                            controller,
                            terminalId,
                          );
                        },
                        // 设备在线但达到上限或创建中时禁用；设备离线时 CompactTabStrip 不会渲染
                        // （_buildBody 在 deviceOffline 分支返回 WorkspaceEmptyState）
                        createDisabled: !device.canCreateTerminal ||
                            controller.creatingTerminal,
                      ),
              ),
            ),
          ),
        ),
      ],
    );
  }

  Future<void> _confirmCloseTerminal(
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

    final closed =
        await controller.closeTerminal(terminal.terminalId);
    if (!mounted) return;
    if (closed == null) {
      // API 失败 → Tab 保留 + SnackBar 错误提示
      ScaffoldMessenger.of(context).clearSnackBars();
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('关闭终端失败'),
          duration: Duration(seconds: 2),
        ),
      );
      return;
    }
    await sessionManager.disconnectTerminal(
      controller.selectedDeviceId,
      terminal.terminalId,
    );
    if (!mounted) return;
    await _workspaceController.onTerminalClosed(terminal.terminalId);
  }

  Future<void> _createEmptyTerminal(
    BuildContext context,
    RuntimeSelectionController controller, {
    bool snackBarOnError = false,
  }) async {
    final sessionManager = context.read<TerminalSessionManager>();
    final result = await _workspaceController.createTerminal(
      title: '终端',
      cwd: '~',
      command: '/bin/bash',
    );
    if (result == null) {
      if (snackBarOnError && mounted) {
        ScaffoldMessenger.of(context).clearSnackBars();
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('创建终端失败'),
            duration: Duration(seconds: 2),
          ),
        );
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
    _workspaceController.selectTerminal(result.terminalId);
  }

  Future<void> _showRenameDeviceDialog(
    BuildContext context,
    RuntimeSelectionController controller,
    RuntimeDevice device,
  ) async {
    final nameController = TextEditingController(
      text: device.name.isEmpty ? device.deviceId : device.name,
    );

    await showDialog<void>(
      context: context,
      builder: (context) {
        return AlertDialog(
          title: const Text('编辑设备'),
          content: SingleChildScrollView(
            child: TextField(
              key: const Key('workspace-rename-device-input'),
              controller: nameController,
              decoration: const InputDecoration(labelText: '设备名称'),
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(context).pop(),
              child: const Text('取消'),
            ),
            FilledButton(
              key: const Key('workspace-rename-device-submit'),
              onPressed: () async {
                await controller.updateSelectedDevice(
                  name: nameController.text,
                );
                if (!context.mounted) return;
                Navigator.of(context).pop();
              },
              child: const Text('保存'),
            ),
          ],
        );
      },
    );

    WidgetsBinding.instance.addPostFrameCallback((_) {
      nameController.dispose();
    });
  }

  Future<void> _showRenameTerminalDialog(
    BuildContext context,
    RuntimeSelectionController controller,
    RuntimeTerminal terminal,
  ) async {
    final titleController = TextEditingController(text: terminal.title);

    await showDialog<void>(
      context: context,
      builder: (context) {
        return AlertDialog(
          title: const Text('编辑终端标题'),
          content: SingleChildScrollView(
            child: TextField(
              key: const Key('workspace-rename-terminal-input'),
              controller: titleController,
              decoration: const InputDecoration(labelText: '终端标题'),
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(context).pop(),
              child: const Text('取消'),
            ),
            FilledButton(
              key: const Key('workspace-rename-terminal-submit'),
              onPressed: () async {
                final renamed = await controller.renameTerminal(
                    terminal.terminalId, titleController.text);
                if (!context.mounted) return;
                if (renamed == null) {
                  // 重命名失败 → 保持对话框 + SnackBar 提示
                  ScaffoldMessenger.of(context).clearSnackBars();
                  ScaffoldMessenger.of(context).showSnackBar(
                    const SnackBar(
                      content: Text('重命名终端失败'),
                      duration: Duration(seconds: 2),
                    ),
                  );
                  return;
                }
                Navigator.of(context).pop();
              },
              child: const Text('保存'),
            ),
          ],
        );
      },
    );

    WidgetsBinding.instance.addPostFrameCallback((_) {
      titleController.dispose();
    });
  }

  Future<void> _showTerminalMenu(
    BuildContext context,
    RuntimeSelectionController controller,
    RuntimeDevice device,
    DesktopAgentState? desktopAgentState,
  ) async {
    // F004: 菜单瘦身 - 仅保留桌面端管理功能（Agent 管理 + 设备编辑）
    // 终端 CRUD（创建/重命名/关闭/切换）已移至 Tab 上下文菜单
    final agentOnline = device.agentOnline;
    final managedByDesktop = desktopAgentState?.managed ?? false;

    await showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (context) {
        return SafeArea(
          child: Padding(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  '管理菜单',
                  style: Theme.of(context).textTheme.titleMedium?.copyWith(
                        fontWeight: FontWeight.w700,
                      ),
                ),
                const SizedBox(height: 8),
                ListTile(
                  key: const Key('workspace-menu-agent-action'),
                  enabled: !_workspaceController.desktopActionInFlight &&
                      (managedByDesktop || !agentOnline),
                  contentPadding: EdgeInsets.zero,
                  leading: _workspaceController.desktopActionInFlight
                      ? const SizedBox(
                          width: 20,
                          height: 20,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : Icon(agentOnline
                          ? Icons.stop_circle_outlined
                          : Icons.play_circle_outline),
                  title: Text(agentOnline ? '停止本机 Agent' : '启动本机 Agent'),
                  subtitle: Text(
                    agentOnline
                        ? (managedByDesktop
                            ? '当前 Agent 由桌面端托管'
                            : '当前 Agent 由外部方式启动，桌面端不会误杀')
                        : '启动后当前电脑即可创建并承载 terminal',
                  ),
                  onTap: !_workspaceController.desktopActionInFlight &&
                          (managedByDesktop || !agentOnline)
                      ? () {
                          Navigator.of(context).pop();
                          if (agentOnline) {
                            unawaited(_handleStopLocalAgent(context));
                          } else {
                            unawaited(_handleStartLocalAgent(context));
                          }
                        }
                      : null,
                ),
                ListTile(
                  key: const Key('workspace-menu-rename-device'),
                  contentPadding: EdgeInsets.zero,
                  leading: const Icon(Icons.edit_outlined),
                  title: const Text('编辑设备名称'),
                  onTap: () {
                    Navigator.of(context).pop();
                    unawaited(_showRenameDeviceDialog(
                        context, controller, device));
                  },
                ),
              ],
            ),
          ),
        );
      },
    );
  }

  /// F004: 桌面端右键 Tab → PopupMenu（重命名/关闭）
  void _showTabContextMenu(
    BuildContext context,
    RuntimeSelectionController controller,
    String terminalId,
    Offset position,
  ) {
    final terminal = controller.terminals
        .where((t) => t.terminalId == terminalId)
        .firstOrNull;
    if (terminal == null) return;

    final overlay = Overlay.of(context);
    showMenu<String>(
      context: context,
      position: RelativeRect.fromLTRB(
        position.dx,
        position.dy,
        position.dx + 1,
        position.dy + 1,
      ),
      items: [
        PopupMenuItem<String>(
          value: 'rename',
          child: Row(
            children: const [
              Icon(Icons.edit_outlined, size: 20),
              SizedBox(width: 12),
              Text('重命名'),
            ],
          ),
        ),
        PopupMenuItem<String>(
          key: const Key('tab-context-close'),
          value: 'close',
          enabled: !terminal.isClosed,
          child: Row(
            children: [
              Icon(Icons.close, size: 20,
                  color: terminal.isClosed
                      ? Theme.of(context).disabledColor
                      : null),
              const SizedBox(width: 12),
              Text('关闭',
                  style: terminal.isClosed
                      ? TextStyle(color: Theme.of(context).disabledColor)
                      : null),
            ],
          ),
        ),
      ],
    ).then((value) {
      if (value == null) return;
      switch (value) {
        case 'rename':
          unawaited(_showRenameTerminalDialog(
              context, controller, terminal));
          break;
        case 'close':
          unawaited(_confirmCloseTerminal(
              context, controller, terminal));
          break;
      }
    });
  }

  /// F004: 移动端长按 Tab → BottomSheet（重命名/关闭）
  Future<void> _showMobileTabContextMenu(
    BuildContext context,
    RuntimeSelectionController controller,
    String terminalId,
  ) async {
    final terminal = controller.terminals
        .where((t) => t.terminalId == terminalId)
        .firstOrNull;
    if (terminal == null) return;

    final selectedAction = await showModalBottomSheet<String>(
      context: context,
      showDragHandle: true,
      builder: (context) {
        return SafeArea(
          child: Padding(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  terminal.title,
                  style: Theme.of(context).textTheme.titleMedium?.copyWith(
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
                  onTap: () => Navigator.of(context).pop('rename'),
                ),
                ListTile(
                  key: const Key('tab-context-close'),
                  contentPadding: EdgeInsets.zero,
                  enabled: !terminal.isClosed,
                  leading: Icon(Icons.close,
                      color: terminal.isClosed
                          ? Theme.of(context).disabledColor
                          : null),
                  title: Text('关闭',
                      style: terminal.isClosed
                          ? TextStyle(
                              color: Theme.of(context).disabledColor)
                          : null),
                  onTap: terminal.isClosed
                      ? null
                      : () => Navigator.of(context).pop('close'),
                ),
              ],
            ),
          ),
        );
      },
    );

    if (!mounted || selectedAction == null) return;
    switch (selectedAction) {
      case 'rename':
        await _showRenameTerminalDialog(context, controller, terminal);
        break;
      case 'close':
        await _confirmCloseTerminal(context, controller, terminal);
        break;
    }
  }

  Future<void> _handleStartLocalAgent(BuildContext context) async {
    final messenger = ScaffoldMessenger.of(context);
    await _workspaceController.startLocalAgent();
    if (!mounted || _workspaceController.state.deviceReady) {
      return;
    }
    messenger.showSnackBar(
      const SnackBar(content: Text('本机 Agent 启动失败')),
    );
  }

  Future<void> _handleStopLocalAgent(BuildContext context) async {
    final messenger = ScaffoldMessenger.of(context);
    final stopped = await _workspaceController.stopLocalAgent();
    if (!mounted || stopped) {
      return;
    }
    messenger.showSnackBar(
      const SnackBar(content: Text('当前 Agent 不是由桌面端托管，无法从这里停止')),
    );
  }

  Future<void> _handleAccountAction(
    BuildContext context,
    AccountMenuAction action,
  ) async {
    final serverUrl = EnvironmentService.instance.currentServerUrl;
    await handleAccountMenuAction(
      context,
      action: action,
      serverUrl: serverUrl,
      token: widget.token,
      logoutDestinationBuilder: (_) => const LoginScreen(),
      onTheme: () => showThemePickerSheet(context),
    );
  }

  /// 处理 401 认证错误：弹窗提示 -> 清除 token -> 跳转登录页
  Future<void> _handleAuthError(
    BuildContext context,
    AuthException authError,
  ) async {
    AppLogger('Workspace').error('auth error: code=${authError.code} msg=${authError.message}');
    final isReplaced = authError.code == AuthErrorCode.tokenReplaced;
    final title = isReplaced ? '您已在其他设备登录' : '登录已过期';
    final message = isReplaced ? '您的账号已在其他设备登录，当前设备已被迫下线。' : '您的登录凭证已过期，请重新登录。';

    await showDialog<void>(
      context: context,
      barrierDismissible: false,
      builder: (context) => AlertDialog(
        title: Text(title),
        content: Text(message),
        actions: [
          FilledButton(
            onPressed: () => Navigator.of(context).pop(),
            child: const Text('确定'),
          ),
        ],
      ),
    );

    if (!context.mounted) return;
    await performSessionTeardown(context: context);
    if (!context.mounted) return;
    Navigator.of(context).pushAndRemoveUntil(
      MaterialPageRoute(builder: (_) => const LoginScreen()),
      (_) => false,
    );
  }
}
