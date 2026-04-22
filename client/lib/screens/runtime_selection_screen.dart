import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../models/runtime_device.dart';
import '../models/runtime_terminal.dart';
import '../models/command_sequence_draft.dart';
import '../models/terminal_launch_plan.dart';
import '../navigation/account_menu_actions.dart';
import '../services/account_menu_action_handler.dart';
import '../services/runtime_device_service.dart';
import '../services/terminal_launch_session_service.dart';
import '../services/runtime_selection_controller.dart';
import '../services/terminal_session_manager.dart';
import '../services/ui_helpers.dart';
import '../services/websocket_service.dart';
import '../widgets/smart_terminal_create_dialog.dart';
import 'login_screen.dart';
import 'terminal_screen.dart';

class RuntimeSelectionScreen extends StatelessWidget {
  const RuntimeSelectionScreen({
    super.key,
    required this.serverUrl,
    required this.token,
    RuntimeSelectionController? controller,
  }) : _controller = controller;

  final String serverUrl;
  final String token;
  final RuntimeSelectionController? _controller;

  @override
  Widget build(BuildContext context) {
    return ChangeNotifierProvider<RuntimeSelectionController>(
      create: (_) => _controller ??
          RuntimeSelectionController(
            serverUrl: serverUrl,
            token: token,
            runtimeService: RuntimeDeviceService(serverUrl: serverUrl),
          )
        ..initialize(),
      child: const _RuntimeSelectionView(),
    );
  }
}

class _RuntimeSelectionView extends StatelessWidget {
  const _RuntimeSelectionView();

  @override
  Widget build(BuildContext context) {
    final controller = context.watch<RuntimeSelectionController>();
    final selectedDevice = controller.selectedDevice;

    return Scaffold(
      appBar: AppBar(
        title: Text(controller.isLocalDeviceSelected ? '本机终端' : '远程终端'),
        actions: [
          IconButton(
            tooltip: '刷新',
            onPressed: controller.loadDevices,
            icon: const Icon(Icons.refresh),
          ),
          PopupMenuButton<AccountMenuAction>(
            onSelected: (value) async {
              await handleAccountMenuAction(
                context,
                action: value,
                serverUrl: controller.serverUrl,
                token: controller.token,
                logoutDestinationBuilder: (_) => const LoginScreen(),
                onTheme: () => showThemePickerSheet(context),
              );
            },
            itemBuilder: (context) => buildAccountMenuEntries(),
          ),
        ],
      ),
      body: SafeArea(
        child: controller.loadingDevices
            ? const Center(child: CircularProgressIndicator())
            : Column(
                children: [
                  if (controller.errorMessage != null)
                    MaterialBanner(
                      content: Text(controller.errorMessage!),
                      actions: [
                        TextButton(
                          onPressed: controller.loadDevices,
                          child: const Text('重试'),
                        ),
                      ],
                    ),
                  Expanded(
                    child: LayoutBuilder(
                      builder: (context, constraints) {
                        final isWide = constraints.maxWidth >= 900;
                        final showDesktopLocal =
                            isWide && controller.isLocalDeviceSelected;
                        if (showDesktopLocal) {
                          return _TerminalPanel(
                            controller: controller,
                            device: selectedDevice,
                            desktopLocalFirst: true,
                          );
                        }
                        if (isWide) {
                          return Row(
                            children: [
                              SizedBox(
                                width: 320,
                                child: _DeviceList(
                                  devices: controller.devices,
                                  selectedDeviceId: controller.selectedDeviceId,
                                  onSelect: controller.selectDevice,
                                ),
                              ),
                              const VerticalDivider(width: 1),
                              Expanded(
                                child: _TerminalPanel(
                                  controller: controller,
                                  device: selectedDevice,
                                  desktopLocalFirst: false,
                                ),
                              ),
                            ],
                          );
                        }
                        return Column(
                          children: [
                            SizedBox(
                              height: 180,
                              child: _DeviceList(
                                devices: controller.devices,
                                selectedDeviceId: controller.selectedDeviceId,
                                onSelect: controller.selectDevice,
                                horizontal: true,
                              ),
                            ),
                            const Divider(height: 1),
                            Expanded(
                              child: _TerminalPanel(
                                controller: controller,
                                device: selectedDevice,
                                desktopLocalFirst: false,
                              ),
                            ),
                          ],
                        );
                      },
                    ),
                  ),
                ],
              ),
      ),
    );
  }
}

class _DeviceList extends StatelessWidget {
  const _DeviceList({
    required this.devices,
    required this.selectedDeviceId,
    required this.onSelect,
    this.horizontal = false,
  });

  final List<RuntimeDevice> devices;
  final String? selectedDeviceId;
  final ValueChanged<String> onSelect;
  final bool horizontal;

  @override
  Widget build(BuildContext context) {
    if (devices.isEmpty) {
      return const Center(child: Text('当前没有可用设备'));
    }

    final list = ListView.separated(
      padding: const EdgeInsets.all(16),
      scrollDirection: horizontal ? Axis.horizontal : Axis.vertical,
      itemCount: devices.length,
      separatorBuilder: (_, __) =>
          SizedBox(width: horizontal ? 12 : 0, height: horizontal ? 0 : 12),
      itemBuilder: (context, index) {
        final device = devices[index];
        final selected = device.deviceId == selectedDeviceId;
        return SizedBox(
          width: horizontal ? 280 : null,
          child: Card(
            color: selected
                ? Theme.of(context).colorScheme.primaryContainer
                : null,
            child: ListTile(
              key: Key('device-${device.deviceId}'),
              selected: selected,
              leading: Icon(
                device.agentOnline ? Icons.computer : Icons.computer_outlined,
                color: device.agentOnline
                    ? Colors.green
                    : Theme.of(context).colorScheme.outline,
              ),
              title: Text(device.name.isEmpty ? device.deviceId : device.name),
              subtitle: Text(
                device.agentOnline
                    ? '${device.activeTerminals}/${device.maxTerminals} 个终端可用'
                    : '设备离线，暂时不能创建终端',
              ),
              trailing: Text(device.agentOnline ? '在线' : '离线'),
              onTap: () => onSelect(device.deviceId),
            ),
          ),
        );
      },
    );

    return horizontal ? list : Material(child: list);
  }
}

class _TerminalPanel extends StatelessWidget {
  const _TerminalPanel({
    required this.controller,
    required this.device,
    required this.desktopLocalFirst,
  });

  final RuntimeSelectionController controller;
  final RuntimeDevice? device;
  final bool desktopLocalFirst;

  @override
  Widget build(BuildContext context) {
    if (device == null) {
      return const Center(child: Text('请选择一台设备'));
    }

    return LayoutBuilder(
      builder: (context, panelConstraints) {
        final compactHeader = panelConstraints.maxHeight < 320;
        final header = Padding(
          padding: EdgeInsets.fromLTRB(
            compactHeader ? 12 : 16,
            compactHeader ? 12 : 16,
            compactHeader ? 12 : 16,
            compactHeader ? 6 : 8,
          ),
          child: Container(
            padding: EdgeInsets.all(compactHeader ? 12 : 16),
            decoration: BoxDecoration(
              color: Theme.of(context)
                  .colorScheme
                  .surfaceContainerHighest
                  .withValues(alpha: 0.42),
              borderRadius: BorderRadius.circular(20),
            ),
            child: compactHeader
                ? Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          Expanded(
                            child: Text(
                              device!.name.isEmpty
                                  ? device!.deviceId
                                  : device!.name,
                              style: Theme.of(context).textTheme.titleMedium,
                            ),
                          ),
                          IconButton(
                            key: const Key('edit-device-name'),
                            tooltip: '编辑设备名',
                            onPressed: () => _showRenameDeviceDialog(
                              context,
                              controller,
                              device!,
                            ),
                            icon: const Icon(Icons.edit),
                          ),
                        ],
                      ),
                      const SizedBox(height: 4),
                      Text(
                        device!.agentOnline
                            ? '设备在线，可直接新建智能终端。'
                            : '设备离线，暂时不能创建新终端。',
                        style: Theme.of(context).textTheme.bodySmall,
                      ),
                      const SizedBox(height: 8),
                      FilledButton.icon(
                        key: const Key('create-terminal'),
                        onPressed: device!.canCreateTerminal &&
                                !controller.creatingTerminal
                            ? () => _showCreateDialog(
                                  context,
                                  controller,
                                  device!,
                                )
                            : null,
                        icon: controller.creatingTerminal
                            ? const SizedBox(
                                width: 16,
                                height: 16,
                                child:
                                    CircularProgressIndicator(strokeWidth: 2),
                              )
                            : const Icon(Icons.auto_awesome),
                        label: const Text('新建智能终端'),
                      ),
                    ],
                  )
                : Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              device!.name.isEmpty
                                  ? device!.deviceId
                                  : device!.name,
                              style: Theme.of(context).textTheme.titleLarge,
                            ),
                            const SizedBox(height: 6),
                            Text(
                              desktopLocalFirst
                                  ? (device!.agentOnline
                                      ? '这台本机已经在线。直接说出你要进入哪个项目、用什么工具即可。'
                                      : '这台本机当前离线。先让 Agent 连上来，再创建终端。')
                                  : (device!.agentOnline
                                      ? '设备在线。推荐直接使用“新建智能终端”，一句话描述你要做什么。'
                                      : '设备当前离线，只能查看已有信息，暂时不能创建新终端。'),
                              style: Theme.of(context).textTheme.bodyMedium,
                            ),
                            const SizedBox(height: 12),
                            Wrap(
                              spacing: 8,
                              runSpacing: 8,
                              children: [
                                _StatusPill(
                                  icon: device!.agentOnline
                                      ? Icons.cloud_done_outlined
                                      : Icons.cloud_off_outlined,
                                  label: device!.agentOnline ? '设备在线' : '设备离线',
                                ),
                                _StatusPill(
                                  icon: Icons.terminal_outlined,
                                  label:
                                      '${device!.activeTerminals}/${device!.maxTerminals} 个终端',
                                ),
                                if (device!.hostname.isNotEmpty)
                                  _StatusPill(
                                    icon: Icons.dns_outlined,
                                    label: device!.hostname,
                                  ),
                              ],
                            ),
                          ],
                        ),
                      ),
                      const SizedBox(width: 12),
                      Column(
                        crossAxisAlignment: CrossAxisAlignment.end,
                        children: [
                          IconButton(
                            key: const Key('edit-device-name'),
                            tooltip: '编辑设备名',
                            onPressed: () => _showRenameDeviceDialog(
                              context,
                              controller,
                              device!,
                            ),
                            icon: const Icon(Icons.edit),
                          ),
                          const SizedBox(height: 8),
                          FilledButton.icon(
                            key: const Key('create-terminal'),
                            onPressed: device!.canCreateTerminal &&
                                    !controller.creatingTerminal
                                ? () => _showCreateDialog(
                                      context,
                                      controller,
                                      device!,
                                    )
                                : null,
                            icon: controller.creatingTerminal
                                ? const SizedBox(
                                    width: 16,
                                    height: 16,
                                    child: CircularProgressIndicator(
                                      strokeWidth: 2,
                                    ),
                                  )
                                : const Icon(Icons.auto_awesome),
                            label: const Text('新建智能终端'),
                          ),
                        ],
                      ),
                    ],
                  ),
          ),
        );

        if (controller.terminals.isEmpty && !controller.loadingTerminals) {
          final compactEmpty = panelConstraints.maxHeight < 420;
          final outerPadding = compactEmpty ? 12.0 : 24.0;
          final innerPadding = compactEmpty ? 12.0 : 24.0;
          final iconSize = compactEmpty ? 24.0 : 36.0;
          final titleGap = compactEmpty ? 8.0 : 16.0;
          final bodyGap = compactEmpty ? 4.0 : 8.0;

          return SingleChildScrollView(
            child: ConstrainedBox(
              constraints:
                  BoxConstraints(minHeight: panelConstraints.maxHeight),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  header,
                  Padding(
                    padding: EdgeInsets.all(outerPadding),
                    child: Center(
                      child: ConstrainedBox(
                        constraints: const BoxConstraints(maxWidth: 520),
                        child: Container(
                          padding: EdgeInsets.all(innerPadding),
                          decoration: BoxDecoration(
                            borderRadius: BorderRadius.circular(24),
                            border: Border.all(
                              color: Theme.of(context)
                                  .colorScheme
                                  .outlineVariant
                                  .withValues(alpha: 0.7),
                            ),
                          ),
                          child: Column(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              Icon(
                                Icons.auto_awesome_outlined,
                                size: iconSize,
                                color: Theme.of(context).colorScheme.primary,
                              ),
                              SizedBox(height: titleGap),
                              Text(
                                '还没有终端',
                                style: Theme.of(context).textTheme.titleLarge,
                              ),
                              SizedBox(height: bodyGap),
                              Text(
                                device!.agentOnline
                                    ? '先点“新建智能终端”，再用一句话描述你要做什么。'
                                    : '这台设备暂时离线，等它重新在线后就可以创建终端。',
                                textAlign: TextAlign.center,
                                style: Theme.of(context).textTheme.bodyMedium,
                              ),
                            ],
                          ),
                        ),
                      ),
                    ),
                  ),
                ],
              ),
            ),
          );
        }

        return Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            header,
            if (controller.loadingTerminals)
              const Expanded(child: Center(child: CircularProgressIndicator()))
            else
              Expanded(
                child: ListView.separated(
                  padding: const EdgeInsets.all(16),
                  itemCount: controller.terminals.length,
                  separatorBuilder: (_, __) => const SizedBox(height: 12),
                  itemBuilder: (context, index) {
                    final terminal = controller.terminals[index];
                    return Card(
                      child: ListTile(
                        key: Key('terminal-${terminal.terminalId}'),
                        title: Text(terminal.title),
                        subtitle: Text(
                          '${terminal.cwd}\n${terminal.command}\n${_statusLabel(terminal)}',
                        ),
                        isThreeLine: true,
                        trailing: Row(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            IconButton(
                              key: Key('edit-terminal-${terminal.terminalId}'),
                              tooltip: '编辑终端标题',
                              onPressed: () => _showRenameTerminalDialog(
                                context,
                                controller,
                                terminal,
                              ),
                              icon: const Icon(Icons.edit_outlined),
                            ),
                            IconButton(
                              key: Key('close-terminal-${terminal.terminalId}'),
                              tooltip: '关闭终端',
                              onPressed: terminal.isClosed
                                  ? null
                                  : () async {
                                      await context
                                          .read<TerminalSessionManager>()
                                          .disconnectTerminal(
                                            device!.deviceId,
                                            terminal.terminalId,
                                          );
                                      await controller
                                          .closeTerminal(terminal.terminalId);
                                    },
                              icon: const Icon(Icons.close),
                            ),
                            FilledButton(
                              onPressed:
                                  device!.agentOnline && terminal.canAttach
                                      ? () => _openTerminal(
                                            context,
                                            controller,
                                            terminal,
                                          )
                                      : null,
                              child: const Text('连接'),
                            ),
                          ],
                        ),
                      ),
                    );
                  },
                ),
              ),
          ],
        );
      },
    );
  }

  Future<void> _showCreateDialog(
    BuildContext context,
    RuntimeSelectionController controller,
    RuntimeDevice device,
  ) async {
    TerminalLaunchPlan? createdPlan;
    CommandSequenceDraft? createdDraft;
    var launchSessionPrepared = false;
    final terminal = await showSmartTerminalCreateDialog<RuntimeTerminal>(
      context: context,
      controller: controller,
      title: '新建智能终端',
      onCreate: (
        CommandSequenceDraft draft,
        Future<void> Function(SmartTerminalExecutionEvent event) reportEvent,
      ) async {
        final plan = draft.toLaunchPlan();
        final normalizedPlan = controller.finalizeLaunchPlan(plan);
        await reportEvent(
          const SmartTerminalExecutionEvent(
            title: '创建终端',
            message: '正在为这条命令序列创建新的终端会话。',
          ),
        );
        final result = await controller.createTerminal(
          title: normalizedPlan.title,
          cwd: normalizedPlan.cwd,
          command: normalizedPlan.command,
        );
        if (result == null) {
          await reportEvent(
            SmartTerminalExecutionEvent(
              title: '创建终端',
              message: controller.errorMessage ?? '终端创建失败，请稍后重试。',
              status: 'error',
            ),
          );
          return null;
        }
        createdPlan = normalizedPlan;
        createdDraft = draft;
        await controller.rememberSuccessfulLaunchPlan(normalizedPlan);
        await reportEvent(
          SmartTerminalExecutionEvent(
            title: '创建终端',
            message: '终端 ${result.title} 已创建，准备建立连接。',
            status: 'success',
          ),
        );
        await reportEvent(
          const SmartTerminalExecutionEvent(
            title: '连接终端',
            message: '正在连接终端并准备注入启动命令。',
          ),
        );
        final prepared =
            await const TerminalLaunchSessionService().prepareConnectedSession(
          sessionManager: context.read<TerminalSessionManager>(),
          deviceId: controller.selectedDeviceId,
          terminalId: result.terminalId,
          serviceFactory: () => controller.buildTerminalService(result),
          plan: normalizedPlan,
          onBootstrapDispatched: () async {
            await reportEvent(
              const SmartTerminalExecutionEvent(
                title: '发送命令',
                message: '命令序列已发送到终端，正在同步执行结果。',
                status: 'success',
              ),
            );
            await controller.reportAssistantExecution(
              draft: draft,
              executionStatus: 'succeeded',
              terminalId: result.terminalId,
              outputSummary: '终端已创建，并已发送命令序列',
            );
            await reportEvent(
              const SmartTerminalExecutionEvent(
                title: '执行状态',
                message: '执行结果已同步到服务端记忆，进入终端后可继续操作。',
                status: 'success',
              ),
            );
          },
        );
        launchSessionPrepared = prepared.bootstrapPrepared;
        if (!prepared.connected) {
          await reportEvent(
            const SmartTerminalExecutionEvent(
              title: '连接终端',
              message: '终端已创建，但连接尚未完成；进入终端页后会继续连接。',
              status: 'warning',
            ),
          );
        } else if ((prepared.observedOutputSummary ?? '').isNotEmpty) {
          await reportEvent(
            SmartTerminalExecutionEvent(
              title: '终端输出',
              message: '已收到终端首段输出：${prepared.observedOutputSummary}',
              status: 'success',
            ),
          );
        }
        return result;
      },
    );

    if (terminal != null && context.mounted) {
      _openTerminal(
        context,
        controller,
        terminal,
        launchPlan: launchSessionPrepared ? null : createdPlan,
        launchDraft: launchSessionPrepared ? null : createdDraft,
      );
    }
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
              key: const Key('rename-device-input'),
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
              key: const Key('rename-device-submit'),
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
              key: const Key('rename-terminal-input'),
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
              key: const Key('rename-terminal-submit'),
              onPressed: () async {
                await controller.renameTerminal(
                  terminal.terminalId,
                  titleController.text,
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
      titleController.dispose();
    });
  }

  Future<void> _openTerminal(
    BuildContext context,
    RuntimeSelectionController controller,
    RuntimeTerminal terminal, {
    TerminalLaunchPlan? launchPlan,
    CommandSequenceDraft? launchDraft,
  }) async {
    final service = const TerminalLaunchSessionService().ensureSession(
      sessionManager: context.read<TerminalSessionManager>(),
      deviceId: controller.selectedDeviceId,
      terminalId: terminal.terminalId,
      serviceFactory: () => controller.buildTerminalService(terminal),
      plan: launchPlan,
      onBootstrapDispatched: launchDraft == null
          ? null
          : () => controller.reportAssistantExecution(
                draft: launchDraft,
                executionStatus: 'succeeded',
                terminalId: terminal.terminalId,
                outputSummary: '终端已创建，并已发送命令序列',
              ),
    );
    await Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => ChangeNotifierProvider<WebSocketService>.value(
          value: service,
          child: const TerminalScreen(),
        ),
      ),
    );
    if (!context.mounted) {
      return;
    }
    await controller.loadDevices();
  }

  String _statusLabel(RuntimeTerminal terminal) {
    final viewCount =
        terminal.views.values.fold<int>(0, (sum, value) => sum + value);
    final reason = terminal.disconnectReason;
    final reasonText = reason == null || reason.isEmpty ? '' : ' · $reason';
    return '状态: ${terminal.status} · 连接数: $viewCount$reasonText';
  }
}

class _StatusPill extends StatelessWidget {
  const _StatusPill({
    required this.icon,
    required this.label,
  });

  final IconData icon;
  final String label;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.surface.withValues(alpha: 0.75),
        borderRadius: BorderRadius.circular(999),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 16),
          const SizedBox(width: 6),
          Text(label),
        ],
      ),
    );
  }
}
