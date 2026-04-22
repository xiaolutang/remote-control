import 'dart:async';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../models/runtime_device.dart';
import '../models/runtime_terminal.dart';
import '../navigation/account_menu_actions.dart';
import '../services/account_menu_action_handler.dart';
import '../services/auth_service.dart';
import '../services/config_service.dart';
import '../services/desktop_agent_bootstrap_service.dart';
import '../services/desktop_agent_manager.dart';
import '../services/desktop_workspace_controller.dart';
import '../services/environment_service.dart';
import '../services/logout_helper.dart';
import '../services/runtime_device_service.dart';
import '../services/runtime_selection_controller.dart';
import '../services/terminal_session_manager.dart';
import '../services/ui_helpers.dart';
import '../services/websocket_service.dart';
import 'login_screen.dart';
import 'terminal_screen.dart';

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
                _WorkspaceHeaderBar(
                  device: device,
                  terminal: workspaceState.selectedTerminal,
                  creatingTerminal: controller.creatingTerminal,
                  desktopAgentState: _workspaceController.desktopAgentState,
                  state: workspaceState,
                  onOpenTerminalMenu: device == null
                      ? null
                      : () => _showTerminalMenu(
                            context,
                            controller,
                            device,
                            terminals,
                            selectedTerminal,
                            _workspaceController.desktopAgentState,
                            context.read<TerminalSessionManager>(),
                          ),
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
                ),
                Expanded(
                  child: _buildBody(
                    context: context,
                    controller: controller,
                    device: device,
                    terminal: workspaceState.selectedTerminal,
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
    required WorkspaceState state,
  }) {
    if (controller.loadingDevices || controller.loadingTerminals) {
      return const Center(child: CircularProgressIndicator());
    }

    if (device == null) {
      return const Center(child: Text('当前没有可用设备'));
    }

    if (state.kind == WorkspaceStateKind.deviceOffline) {
      return _WorkspaceEmptyState(
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
        return const _WorkspaceEmptyState(
          icon: Icons.sync,
          title: '正在启动本机 Agent',
          message: '桌面端正在尝试恢复本机 Agent，成功后即可创建第一个 terminal。',
          loading: true,
        );
      }

      if (state.kind == WorkspaceStateKind.createFailed) {
        return _WorkspaceEmptyState(
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

      return _WorkspaceEmptyState(
        icon: Icons.add_box_outlined,
        title: '创建第一个终端',
        message: state.deviceReady
            ? '当前还没有 terminal，创建后会直接进入新的工作标签页。'
            : '当前本机 Agent 未在线，创建时会先尝试启动本机 Agent，再进入新的工作标签页。',
        actionLabel: state.deviceReady ? '新建终端' : '启动并创建终端',
        actionKey: const Key('workspace-empty-create-action'),
        onAction: () {
          unawaited(_createEmptyTerminal(context, controller));
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
              child: const TerminalScreen(
                embedded: true,
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

    await sessionManager.disconnectTerminal(
      controller.selectedDeviceId,
      terminal.terminalId,
    );
    await controller.closeTerminal(terminal.terminalId);
    if (!mounted) return;
    await _workspaceController.onTerminalClosed(terminal.terminalId);
  }

  Future<void> _createEmptyTerminal(
    BuildContext context,
    RuntimeSelectionController controller,
  ) async {
    final sessionManager = context.read<TerminalSessionManager>();
    final result = await _workspaceController.createTerminal(
      title: '终端',
      cwd: '~',
      command: '/bin/bash',
    );
    if (result == null || !mounted) {
      return;
    }
    // 建立 WebSocket 连接，不注入 postCreateInput
    final service = sessionManager.getOrCreate(
      controller.selectedDeviceId,
      result.terminalId,
      () => controller.buildTerminalService(result),
    );
    await service.connect();
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
                await controller.renameTerminal(
                    terminal.terminalId, titleController.text);
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
      titleController.dispose();
    });
  }

  Future<void> _showTerminalMenu(
    BuildContext context,
    RuntimeSelectionController controller,
    RuntimeDevice device,
    List<RuntimeTerminal> terminals,
    RuntimeTerminal? selectedTerminal,
    DesktopAgentState? desktopAgentState,
    TerminalSessionManager sessionManager,
  ) async {
    // 设备在线状态统一从 RuntimeSelectionController 获取（唯一真实来源）
    // controller 中的 device.agentOnline 已由 WebSocket 连接实时同步
    final agentOnline = device.agentOnline;

    final selectedAction = await showModalBottomSheet<_TerminalMenuAction>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (context) {
        return StatefulBuilder(
          builder: (context, setModalState) {
            final desktopMode = controller.isDesktopPlatform;
            // agentOnline 已在方法开头从 device.agentOnline 获取（唯一真实来源）
            final managedByDesktop = desktopAgentState?.managed ?? false;
            return SafeArea(
              child: Padding(
                padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      '终端菜单',
                      style: Theme.of(context).textTheme.titleMedium?.copyWith(
                            fontWeight: FontWeight.w700,
                          ),
                    ),
                    const SizedBox(height: 8),
                    if (desktopMode) ...[
                      // TODO: 后台保持电脑在线功能暂时屏蔽，开关打开时 agent 仍会被关闭
                      // SwitchListTile.adaptive(
                      //   key: const Key('workspace-keep-agent-running-switch'),
                      //   contentPadding: EdgeInsets.zero,
                      //   title: const Text('后台保持电脑在线'),
                      //   subtitle: Text(
                      //     _workspaceController.keepAgentRunningInBackground
                      //         ? '退出桌面端后保留本机 Agent 继续后台运行'
                      //         : '退出桌面端时同时停止桌面端托管的 Agent',
                      //   ),
                      //   value: _workspaceController.keepAgentRunningInBackground,
                      //   onChanged: (value) {
                      //     setModalState(() {});
                      //     unawaited(_workspaceController.setKeepAgentRunningInBackground(value));
                      //   },
                      // ),
                      ListTile(
                        key: const Key('workspace-menu-agent-action'),
                        enabled: !_workspaceController.desktopActionInFlight &&
                            (managedByDesktop || !agentOnline),
                        contentPadding: EdgeInsets.zero,
                        leading: _workspaceController.desktopActionInFlight
                            ? const SizedBox(
                                width: 20,
                                height: 20,
                                child:
                                    CircularProgressIndicator(strokeWidth: 2),
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
                      const Divider(height: 24),
                    ],
                    ListTile(
                      key: const Key('workspace-menu-create'),
                      enabled: device.canCreateTerminal &&
                          !controller.creatingTerminal,
                      contentPadding: EdgeInsets.zero,
                      leading: controller.creatingTerminal
                          ? const SizedBox(
                              width: 20,
                              height: 20,
                              child: CircularProgressIndicator(strokeWidth: 2),
                            )
                          : const Icon(Icons.add_circle_outline),
                      title: const Text('新建终端'),
                      subtitle: Text(
                        device.canCreateTerminal
                            ? '当前 ${device.activeTerminals}/${device.maxTerminals} 个 terminal'
                            : '电脑离线或已达到 terminal 上限',
                      ),
                      onTap: device.canCreateTerminal &&
                              !controller.creatingTerminal
                          ? () => Navigator.of(context)
                              .pop(const _TerminalMenuAction.create())
                          : null,
                    ),
                    if (selectedTerminal != null) ...[
                      ListTile(
                        key: const Key('workspace-menu-rename'),
                        contentPadding: EdgeInsets.zero,
                        leading: const Icon(Icons.edit_outlined),
                        title: const Text('重命名当前终端'),
                        onTap: () => Navigator.of(context)
                            .pop(const _TerminalMenuAction.rename()),
                      ),
                      ListTile(
                        key: const Key('workspace-menu-close'),
                        enabled: !selectedTerminal.isClosed,
                        contentPadding: EdgeInsets.zero,
                        leading: const Icon(Icons.close),
                        title: const Text('关闭当前终端'),
                        onTap: selectedTerminal.isClosed
                            ? null
                            : () => Navigator.of(context)
                                .pop(const _TerminalMenuAction.close()),
                      ),
                    ],
                    if (agentOnline) ...[
                      const SizedBox(height: 8),
                      Text(
                        '切换终端',
                        style: Theme.of(context).textTheme.titleSmall?.copyWith(
                              fontWeight: FontWeight.w700,
                            ),
                      ),
                      const SizedBox(height: 8),
                      Flexible(
                        child: ConstrainedBox(
                          constraints: const BoxConstraints(maxHeight: 320),
                          child: ListView.separated(
                            shrinkWrap: true,
                            itemCount: terminals.length,
                            separatorBuilder: (_, __) =>
                                const Divider(height: 1),
                            itemBuilder: (context, index) {
                              final terminal = terminals[index];
                              return ListTile(
                                key: Key(
                                    'workspace-menu-terminal-${terminal.terminalId}'),
                                enabled: terminal.canAttach,
                                contentPadding: EdgeInsets.zero,
                                leading: Icon(
                                  terminal.terminalId ==
                                          selectedTerminal?.terminalId
                                      ? Icons.radio_button_checked
                                      : Icons.radio_button_unchecked,
                                  color: terminal.terminalId ==
                                          selectedTerminal?.terminalId
                                      ? Theme.of(context).colorScheme.primary
                                      : null,
                                ),
                                title: Text(terminal.title),
                                subtitle: Text(
                                    '${terminal.cwd} · ${terminal.status}'),
                                onTap: terminal.canAttach
                                    ? () => Navigator.of(context).pop(
                                          _TerminalMenuAction.switchTo(
                                              terminal.terminalId),
                                        )
                                    : null,
                              );
                            },
                          ),
                        ),
                      ),
                    ] else ...[
                      const SizedBox(height: 8),
                      Text(
                        '电脑离线，当前不可切换或连接已有 terminal。',
                        style: Theme.of(context).textTheme.bodySmall?.copyWith(
                              color: Theme.of(context)
                                  .colorScheme
                                  .onSurfaceVariant,
                            ),
                      ),
                    ],
                  ],
                ),
              ),
            );
          },
        );
      },
    );

    if (!mounted || !context.mounted || selectedAction == null) {
      return;
    }
    switch (selectedAction.kind) {
      case _TerminalMenuActionKind.create:
        await _createEmptyTerminal(context, controller);
        break;
      case _TerminalMenuActionKind.rename:
        if (selectedTerminal != null) {
          await _showRenameTerminalDialog(
              context, controller, selectedTerminal);
        }
        break;
      case _TerminalMenuActionKind.close:
        if (selectedTerminal != null) {
          await _confirmCloseTerminal(context, controller, selectedTerminal);
        }
        break;
      case _TerminalMenuActionKind.switchTerminal:
        _workspaceController.selectTerminal(selectedAction.terminalId);
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
    debugPrint(
        '[Workspace] auth error: code=${authError.code} msg=${authError.message}');
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
    await logoutAndNavigate(
      context: context,
      destinationBuilder: (_) => const LoginScreen(),
    );
  }
}

class _WorkspaceHeaderBar extends StatelessWidget {
  const _WorkspaceHeaderBar({
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
              }
            },
            itemBuilder: (context) => buildAccountMenuEntries(),
          ),
        ],
      ),
    );
  }
}

class _WorkspaceEmptyState extends StatelessWidget {
  const _WorkspaceEmptyState({
    required this.icon,
    required this.title,
    required this.message,
    this.actionLabel,
    this.actionKey,
    this.onAction,
    this.loading = false,
  });

  final IconData icon;
  final String title;
  final String message;
  final String? actionLabel;
  final Key? actionKey;
  final VoidCallback? onAction;
  final bool loading;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 360),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(icon,
                  size: 48, color: Theme.of(context).colorScheme.primary),
              const SizedBox(height: 16),
              Text(
                title,
                style: Theme.of(context).textTheme.titleLarge?.copyWith(
                      fontWeight: FontWeight.w700,
                    ),
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: 8),
              Text(
                message,
                style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                      color: Theme.of(context).colorScheme.onSurfaceVariant,
                    ),
                textAlign: TextAlign.center,
              ),
              if (loading) ...[
                const SizedBox(height: 24),
                const CircularProgressIndicator(),
              ] else if (actionLabel != null && onAction != null) ...[
                const SizedBox(height: 16),
                FilledButton(
                  key: actionKey,
                  onPressed: onAction,
                  child: Text(actionLabel!),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

enum _TerminalMenuActionKind { create, rename, close, switchTerminal }

class _TerminalMenuAction {
  const _TerminalMenuAction._(this.kind, [this.terminalId]);

  const _TerminalMenuAction.create() : this._(_TerminalMenuActionKind.create);
  const _TerminalMenuAction.rename() : this._(_TerminalMenuActionKind.rename);
  const _TerminalMenuAction.close() : this._(_TerminalMenuActionKind.close);
  const _TerminalMenuAction.switchTo(String terminalId)
      : this._(_TerminalMenuActionKind.switchTerminal, terminalId);

  final _TerminalMenuActionKind kind;
  final String? terminalId;
}
