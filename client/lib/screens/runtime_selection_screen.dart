import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../models/runtime_device.dart';
import '../models/runtime_terminal.dart';
import '../navigation/account_menu_actions.dart';
import '../services/account_menu_action_handler.dart';
import '../services/runtime_device_service.dart';
import '../services/runtime_selection_controller.dart';
import '../services/terminal_session_manager.dart';
import '../services/ui_helpers.dart';
import '../services/websocket_service.dart';
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
        title: Text(controller.isLocalDeviceSelected ? '本机终端' : '选择设备与终端'),
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
                '${device.activeTerminals}/${device.maxTerminals} terminals',
              ),
              trailing: Text(device.agentOnline ? '可创建终端' : '不可创建'),
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

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 16, 16, 8),
          child: Row(
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      device!.name.isEmpty ? device!.deviceId : device!.name,
                      style: Theme.of(context).textTheme.titleLarge,
                    ),
                    Text(
                      desktopLocalFirst
                          ? (device!.agentOnline
                              ? '本机电脑在线，可直接创建并管理终端'
                              : '本机电脑离线，请先启动或重连 Agent')
                          : (device!.agentOnline
                              ? '电脑在线，可选择现有终端或新建终端'
                              : '电脑离线，当前不可连接或创建新终端'),
                      style: Theme.of(context).textTheme.bodyMedium,
                    ),
                  ],
                ),
              ),
              IconButton(
                key: const Key('edit-device-name'),
                tooltip: '编辑设备名',
                onPressed: () =>
                    _showRenameDeviceDialog(context, controller, device!),
                icon: const Icon(Icons.edit),
              ),
              FilledButton.icon(
                key: const Key('create-terminal'),
                onPressed:
                    device!.canCreateTerminal && !controller.creatingTerminal
                        ? () => _showCreateDialog(context, controller, device!)
                        : null,
                icon: controller.creatingTerminal
                    ? const SizedBox(
                        width: 16,
                        height: 16,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : const Icon(Icons.add),
                label: const Text('新建终端'),
              ),
            ],
          ),
        ),
        if (controller.loadingTerminals)
          const Expanded(child: Center(child: CircularProgressIndicator()))
        else if (controller.terminals.isEmpty)
          const Expanded(child: Center(child: Text('当前设备还没有终端')))
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
                          onPressed: device!.agentOnline && terminal.canAttach
                              ? () =>
                                  _openTerminal(context, controller, terminal)
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
  }

  Future<void> _showCreateDialog(
    BuildContext context,
    RuntimeSelectionController controller,
    RuntimeDevice device,
  ) async {
    final titleController = TextEditingController(
      text: 'Claude / ${device.name.isEmpty ? device.deviceId : device.name}',
    );
    final cwdController = TextEditingController(text: '~');
    final commandController = TextEditingController(text: '/bin/bash');

    final terminal = await showDialog<RuntimeTerminal>(
      context: context,
      builder: (context) {
        return AlertDialog(
          title: const Text('新建终端'),
          content: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                TextField(
                  key: const Key('create-terminal-title'),
                  controller: titleController,
                  decoration: const InputDecoration(labelText: '标题'),
                ),
                TextField(
                  key: const Key('create-terminal-cwd'),
                  controller: cwdController,
                  decoration: const InputDecoration(labelText: '工作目录'),
                ),
                TextField(
                  key: const Key('create-terminal-command'),
                  controller: commandController,
                  decoration: const InputDecoration(labelText: '启动命令'),
                ),
              ],
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(context).pop(),
              child: const Text('取消'),
            ),
            FilledButton(
              key: const Key('create-terminal-submit'),
              onPressed: () async {
                final result = await controller.createTerminal(
                  title: titleController.text.trim(),
                  cwd: cwdController.text.trim(),
                  command: commandController.text.trim(),
                );
                if (!context.mounted) return;
                Navigator.of(context).pop(result);
              },
              child: const Text('创建'),
            ),
          ],
        );
      },
    );

    WidgetsBinding.instance.addPostFrameCallback((_) {
      titleController.dispose();
      cwdController.dispose();
      commandController.dispose();
    });

    if (terminal != null && context.mounted) {
      _openTerminal(context, controller, terminal);
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
    RuntimeTerminal terminal,
  ) async {
    final service = context.read<TerminalSessionManager>().getOrCreate(
          controller.selectedDeviceId,
          terminal.terminalId,
          () => controller.buildTerminalService(terminal),
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
