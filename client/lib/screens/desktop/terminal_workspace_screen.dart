import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';

import '../../models/runtime_device.dart';
import '../../models/runtime_terminal.dart';
import '../../navigation/account_menu_actions.dart';
import '../../navigation/account_menu_action_handler.dart';
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
import '../../services/scheduled_task_poller.dart';
import '../../widgets/scheduled_task_badge.dart';
import '../../services/terminal_session_manager.dart';
import '../../widgets/theme_picker_sheet.dart';
import '../../widgets/snack_bar_helper.dart';
import '../../widgets/scheduled_task_list_sheet.dart';
import '../../widgets/schedule_bottom_sheet.dart';
import '../../services/websocket_service.dart';
import '../login_screen.dart';
import '../skill_config_screen.dart';
import '../terminal_screen.dart';
import '../../widgets/terminal_page_indicator.dart';
import '../../widgets/terminal_sidebar.dart';
import 'terminal_actions_mixin.dart';
import 'terminal_workspace_header_bar.dart';
import 'terminal_workspace_empty_state.dart';
import 'workspace_shortcut_intents.dart';

class TerminalWorkspaceScreen extends StatelessWidget {
  const TerminalWorkspaceScreen({
    super.key,
    required this.token,
    this.initialDevices = const <RuntimeDevice>[],
    RuntimeSelectionController? controller,
    DesktopAgentBootstrapService? agentBootstrapService,
    this.platformOverride,
  })  : _controller = controller,
        _agentBootstrapService = agentBootstrapService;

  final String token;
  final List<RuntimeDevice> initialDevices;
  final RuntimeSelectionController? _controller;
  final DesktopAgentBootstrapService? _agentBootstrapService;

  /// Optional platform override for testing.
  /// When null, uses [defaultTargetPlatform].
  final TargetPlatform? platformOverride;

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
        platformOverride: platformOverride,
      ),
    );
  }
}

class _TerminalWorkspaceView extends StatefulWidget {
  const _TerminalWorkspaceView({
    required this.token,
    required this.agentBootstrapService,
    this.platformOverride,
  });

  final String token;
  final DesktopAgentBootstrapService agentBootstrapService;
  final TargetPlatform? platformOverride;

  @override
  State<_TerminalWorkspaceView> createState() => _TerminalWorkspaceViewState();
}

class _TerminalWorkspaceViewState extends State<_TerminalWorkspaceView>
    with TerminalActionsMixin<_TerminalWorkspaceView> {
  late final DesktopWorkspaceController _workspaceController;
  late final ScheduledTaskPoller _scheduledTaskPoller;
  StreamSubscription<Map<String, dynamic>>? _terminalsChangedSubscription;
  WebSocketService? _lastListenedService;
  Timer? _refreshDebounceTimer;
  String? _pendingToastAction;
  String? _pendingToastTerminalId;
  bool _authDialogShowing = false;
  String? _pollerSessionId;

  @override
  DesktopWorkspaceController get workspaceController => _workspaceController;

  @override
  void Function(RuntimeTerminal terminal)? get onScheduleSend => (terminal) async {
    final device = context.read<RuntimeSelectionController>().selectedDevice;
    if (device == null) return;
    final success = await showScheduleBottomSheet(
      context: context,
      token: widget.token,
      sessionId: device.deviceId,
      terminalId: terminal.terminalId,
      serverUrl: EnvironmentService.instance.currentServerUrl,
    );
    if (success && mounted) {
      _scheduledTaskPoller.refresh();
    }
  };

  @override
  void initState() {
    super.initState();
    _workspaceController = DesktopWorkspaceController(
      serverUrl: EnvironmentService.instance.currentServerUrl,
      token: widget.token,
      agentBootstrapService: widget.agentBootstrapService,
      configService: ConfigService(),
    );
    _scheduledTaskPoller = ScheduledTaskPoller(
      serverUrl: EnvironmentService.instance.currentServerUrl,
    );
  }

  @override
  void dispose() {
    _terminalsChangedSubscription?.cancel();
    _cleanupServiceListener();
    _refreshDebounceTimer?.cancel();
    _scheduledTaskPoller.dispose();
    unawaited(_workspaceController.handleViewDispose());
    _workspaceController.dispose();
    super.dispose();
  }

  /// 清理 service 状态监听器
  void _cleanupServiceListener() {
    _terminalsChangedSubscription?.cancel();
    _terminalsChangedSubscription = null;
    _lastListenedService = null;
    _refreshDebounceTimer?.cancel();
    _refreshDebounceTimer = null;
    _pendingToastAction = null;
    _pendingToastTerminalId = null;
  }

  /// 停止定时任务轮询并重置 session 标记。
  /// 同时清理 service 状态监听器，避免旧 session 的 terminals_changed 回调。
  void _stopScheduledTaskPoller() {
    _cleanupServiceListener();
    if (_pollerSessionId != null) {
      _scheduledTaskPoller.stopPolling();
      _pollerSessionId = null;
    }
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

    // 根据 action 确定提示文本，未知 action 跳过 toast
    final actionText = switch (action) {
      'created' => '新建',
      'closed' => '关闭',
      _ => null,
    };
    if (actionText == null) return;

    // 清除旧的 SnackBar，避免堆积
    final terminalText = terminalTitle ?? '终端';
    showAppSnackBar(context, '$terminalText 已在另一端$actionText');
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

    // F005: 桌面端键盘快捷键 - Shortcuts/Actions 集成
    // 仅 macOS: Cmd+1/2/3 切换可附加终端, Cmd+W 关闭
    final platform = widget.platformOverride ?? defaultTargetPlatform;
    final isMacOSDesktop = controller.isDesktopPlatform &&
        platform == TargetPlatform.macOS;

    return Focus(
      autofocus: false,
      debugLabel: 'workspaceShortcutsFocus',
      child: Shortcuts(
        debugLabel: 'workspaceShortcuts',
        shortcuts: isMacOSDesktop
            ? <ShortcutActivator, Intent>{
                const SingleActivator(LogicalKeyboardKey.digit1, meta: true):
                    const SwitchTerminalIntent(0),
                const SingleActivator(LogicalKeyboardKey.digit2, meta: true):
                    const SwitchTerminalIntent(1),
                const SingleActivator(LogicalKeyboardKey.digit3, meta: true):
                    const SwitchTerminalIntent(2),
                const SingleActivator(LogicalKeyboardKey.keyW, meta: true):
                    const CloseCurrentTerminalIntent(),
              }
            : const <ShortcutActivator, Intent>{},
        child: Actions(
          actions: isMacOSDesktop
              ? <Type, Action<Intent>>{
                  SwitchTerminalIntent: SwitchTerminalAction(
                    onSwitch: (index) {
                      // 仅索引可附加终端（跳过已关闭的），与 Tab 栏行为一致
                      final attachableTerminals = controller.terminals
                          .where((t) => t.canAttach)
                          .toList();
                      if (index < attachableTerminals.length) {
                        _workspaceController
                            .selectTerminal(attachableTerminals[index].terminalId);
                      }
                    },
                  ),
                  CloseCurrentTerminalIntent: CloseCurrentTerminalAction(
                    onClose: () {
                      final selectedTerminal =
                          _workspaceController.selectedTerminal;
                      if (selectedTerminal != null) {
                        unawaited(confirmCloseTerminal(
                          context,
                          controller,
                          selectedTerminal,
                        ));
                      }
                    },
                  ),
                }
              : <Type, Action<Intent>>{},
          child: AnimatedBuilder(
          animation: _workspaceController,
          builder: (context, _) {
            final device = controller.selectedDevice;
            final allTerminals = controller.terminals;
            final terminals = allTerminals.where((t) => !t.isClosed).toList();
            final workspaceState = _workspaceController.state;
            final selectedTerminal = _workspaceController.selectedTerminal;

            return Scaffold(
              key: const Key('workspace-scaffold'),
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
                      // F003: 桌面端单行 Header（无 Tab Bar）
                      isDesktopPlatform: controller.isDesktopPlatform,
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
                        unawaited(showRenameDeviceDialog(
                            context, controller, device!));
                      },
                      desktopActionInFlight:
                          _workspaceController.desktopActionInFlight,
                      onScheduledTasks: () {
                        final t = workspaceState.selectedTerminal;
                        if (t == null) return;
                        ScheduledTaskListSheet.show(
                          context: context,
                          terminalId: t.terminalId,
                          poller: _scheduledTaskPoller,
                          token: widget.token,
                        );
                      },
                    ),
                    // F003: 桌面端用 Row 包裹 Sidebar + Body
                    Expanded(
                      child: controller.isDesktopPlatform
                          ? Row(
                              children: [
                                TerminalSidebar(
                                  terminals: terminals,
                                  selectedTerminalId:
                                      selectedTerminal?.terminalId,
                                  onSwitch: handleSwitchTerminal,
                                  onCreate: handleCreateTerminal,
                                  createDisabled: device == null ||
                                      isCreateDisabled(device, controller),
                                  onContextMenu: (terminalId, position) {
                                    showTabContextMenu(
                                      context,
                                      controller,
                                      terminalId,
                                      position,
                                    );
                                  },
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
                            )
                          : _buildBody(
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
        ),
      ),
      ),
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
    // F008: 当已有终端时不因 loading 状态销毁 IndexedStack（避免 State 重建）
    // 仅在无终端且正在加载时显示 loading
    if ((controller.loadingDevices || controller.loadingTerminals) &&
        terminal == null) {
      _stopScheduledTaskPoller();
      return const Center(child: CircularProgressIndicator());
    }

    if (device == null) {
      _stopScheduledTaskPoller();
      return const Center(child: Text('当前没有可用设备'));
    }

    if (state.kind == WorkspaceStateKind.deviceOffline) {
      _stopScheduledTaskPoller();
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
      _stopScheduledTaskPoller();
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
          unawaited(createEmptyTerminal(
            context,
            controller,
            snackBarOnError: !controller.isDesktopPlatform,
          ));
        },
      );
    }

    // F008: IndexedStack 缓存所有终端的 TerminalScreen，切换时不销毁 State
    final selectedIndex =
        terminals.indexWhere((t) => t.terminalId == terminal.terminalId);

    // 防御：终端列表为空时回退到空状态
    if (terminals.isEmpty) {
      return WorkspaceEmptyState(
        icon: Icons.add_box_outlined,
        title: '创建第一个终端',
        message: '当前还没有 terminal。',
        actionLabel: '新建终端',
        actionKey: const Key('workspace-empty-create-action'),
        onAction: () {
          unawaited(createEmptyTerminal(
            context,
            controller,
            snackBarOnError: !controller.isDesktopPlatform,
          ));
        },
      );
    }

    // 在选中终端的连接上监听跨平台终端变化通知
    final selectedService = context.read<TerminalSessionManager>().getOrCreate(
          controller.selectedDeviceId,
          terminal.terminalId,
          () => controller.buildTerminalService(terminal),
        );
    _listenToTerminalsChangedIfNeeded(selectedService);

    // 启动定时任务轮询（仅在 session 变化时重启，避免 build 中重复调用）
    final deviceId = controller.selectedDeviceId;
    if (deviceId != null && terminal.terminalId.isNotEmpty) {
      if (_pollerSessionId != deviceId) {
        _pollerSessionId = deviceId;
        _scheduledTaskPoller.startPolling(widget.token, deviceId);
      }
    }

    final terminalBody = Column(
      children: [
        // 定时任务 badge：显示当前终端的 pending 任务
        AnimatedBuilder(
          animation: _scheduledTaskPoller,
          builder: (context, _) {
            final pendingTasks = _scheduledTaskPoller
                .pendingTasksForTerminal(terminal.terminalId);
            return ScheduledTaskBadge(
              tasks: pendingTasks,
              onCancel: (taskId) => _scheduledTaskPoller.deleteTask(taskId),
              onViewAll: () {
                final t = terminal;
                ScheduledTaskListSheet.show(
                  context: context,
                  terminalId: t.terminalId,
                  poller: _scheduledTaskPoller,
                  token: widget.token,
                );
              },
            );
          },
        ),
        Expanded(
          child: IndexedStack(
            index: selectedIndex.clamp(0, terminals.length - 1),
            children: [
              for (final t in terminals)
                KeyedSubtree(
                  key: ValueKey<String>(t.terminalId),
                  child: _buildTerminalView(
                    context: context,
                    controller: controller,
                    terminal: t,
                  ),
                ),
            ],
          ),
        ),
        // F006: 移动端 TerminalPageIndicator（32px 页码指示器）
        // 键盘弹出时隐藏，避免与 ShortcutBar 之间产生空白区域
        if (!controller.isDesktopPlatform &&
            MediaQuery.of(context).viewInsets.bottom == 0)
          TerminalPageIndicator(
            terminals: terminals,
            selectedTerminalId: terminal.terminalId,
            onSwitch: handleSwitchTerminal,
            onCreate: () {
              unawaited(createEmptyTerminal(
                context,
                controller,
                snackBarOnError: true,
              ));
            },
            createDisabled: isCreateDisabled(device, controller),
            onContextMenu: (terminalId, position) {
              showMobileTabContextMenu(
                context,
                controller,
                terminalId,
              );
            },
          ),
      ],
    );

    return terminalBody;
  }

  /// Builds a single cached TerminalScreen for [terminal] with its own
  /// WebSocket service provider. Used by IndexedStack to preserve State
  /// across terminal switches (F008).
  Widget _buildTerminalView({
    required BuildContext context,
    required RuntimeSelectionController controller,
    required RuntimeTerminal terminal,
  }) {
    final service = context.read<TerminalSessionManager>().getOrCreate(
          controller.selectedDeviceId,
          terminal.terminalId,
          () => controller.buildTerminalService(terminal),
        );
    return ChangeNotifierProvider<WebSocketService>.value(
      value: service,
      child: TerminalScreen(
        embedded: true,
        onScheduledTaskCreated: () => _scheduledTaskPoller.refresh(),
      ),
    );
  }

  // ---------------------------------------------------------------------------
  // Agent 生命周期
  // ---------------------------------------------------------------------------

  Future<void> _handleStartLocalAgent(BuildContext context) async {
    await _workspaceController.startLocalAgent();
    if (!mounted || _workspaceController.state.deviceReady) {
      return;
    }
    // ignore: use_build_context_synchronously
    showAppSnackBar(context, '本机 Agent 启动失败');
  }

  Future<void> _handleStopLocalAgent(BuildContext context) async {
    final stopped = await _workspaceController.stopLocalAgent();
    if (!mounted || stopped) {
      return;
    }
    // ignore: use_build_context_synchronously
    showAppSnackBar(context, '当前 Agent 不是由桌面端托管，无法从这里停止');
  }

  // ---------------------------------------------------------------------------
  // 管理菜单（桌面端 BottomSheet）
  // ---------------------------------------------------------------------------

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
                    unawaited(showRenameDeviceDialog(
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

  // ---------------------------------------------------------------------------
  // 账户操作 & 认证
  // ---------------------------------------------------------------------------

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
    await performSessionTeardown(
      agentManager: context.read<DesktopAgentManager>(),
      sessionManager: context.read<TerminalSessionManager>(),
    );
    if (!context.mounted) return;
    Navigator.of(context).pushAndRemoveUntil(
      MaterialPageRoute(builder: (_) => const LoginScreen()),
      (_) => false,
    );
  }
}
