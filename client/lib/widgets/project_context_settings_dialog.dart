import 'package:flutter/material.dart';

import '../models/project_context_settings.dart';
import '../services/planner_credentials_service.dart';
import '../services/runtime_selection_controller.dart';

Future<bool?> showProjectContextSettingsDialog({
  required BuildContext context,
  required RuntimeSelectionController controller,
  PlannerCredentialsService? credentialsService,
}) {
  return showDialog<bool>(
    context: context,
    builder: (context) {
      return _ProjectContextSettingsDialog(
        controller: controller,
        credentialsService:
            credentialsService ?? PlannerCredentialsService.shared,
      );
    },
  );
}

class _ProjectContextSettingsDialog extends StatefulWidget {
  const _ProjectContextSettingsDialog({
    required this.controller,
    required this.credentialsService,
  });

  final RuntimeSelectionController controller;
  final PlannerCredentialsService credentialsService;

  @override
  State<_ProjectContextSettingsDialog> createState() =>
      _ProjectContextSettingsDialogState();
}

class _ProjectContextSettingsDialogState
    extends State<_ProjectContextSettingsDialog> {
  final TextEditingController _pinnedLabelController = TextEditingController();
  final TextEditingController _pinnedCwdController = TextEditingController();
  final TextEditingController _scanRootController = TextEditingController();
  final TextEditingController _scanDepthController =
      TextEditingController(text: '2');
  final TextEditingController _apiKeyController = TextEditingController();

  List<PinnedProject> _pinnedProjects = const [];
  List<ApprovedScanRoot> _scanRoots = const [];
  PlannerRuntimeConfigModel _plannerConfig = const PlannerRuntimeConfigModel();
  bool _loading = true;
  bool _saving = false;
  bool _advancedExpanded = false;
  bool _hasStoredApiKey = false;
  String? _errorMessage;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) {
        _load();
      }
    });
  }

  @override
  void dispose() {
    _pinnedLabelController.dispose();
    _pinnedCwdController.dispose();
    _scanRootController.dispose();
    _scanDepthController.dispose();
    _apiKeyController.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    final settings = await widget.controller.loadProjectContextSettings();
    final deviceId = widget.controller.selectedDeviceId;
    final apiKey = deviceId == null
        ? null
        : await widget.credentialsService.readApiKey(deviceId);
    if (!mounted) {
      return;
    }
    setState(() {
      _loading = false;
      _pinnedProjects = settings?.pinnedProjects ?? const [];
      _scanRoots = settings?.approvedScanRoots ?? const [];
      _plannerConfig =
          settings?.plannerConfig ?? const PlannerRuntimeConfigModel();
      _hasStoredApiKey = (apiKey ?? '').isNotEmpty;
      _errorMessage = settings == null ? widget.controller.errorMessage : null;
    });
  }

  void _addPinnedProject() {
    final label = _pinnedLabelController.text.trim();
    final cwd = _pinnedCwdController.text.trim();
    if (cwd.isEmpty) {
      setState(() {
        _errorMessage = '固定项目需要填写工作目录';
      });
      return;
    }
    setState(() {
      _pinnedProjects = [
        ..._pinnedProjects,
        PinnedProject(
          label: label.isEmpty ? _labelFromPath(cwd) : label,
          cwd: cwd,
        ),
      ];
      _pinnedLabelController.clear();
      _pinnedCwdController.clear();
      _errorMessage = null;
    });
  }

  void _addScanRoot() {
    final rootPath = _scanRootController.text.trim();
    final depth = int.tryParse(_scanDepthController.text.trim()) ?? 2;
    if (rootPath.isEmpty) {
      setState(() {
        _errorMessage = '扫描根目录不能为空';
      });
      return;
    }
    setState(() {
      _scanRoots = [
        ..._scanRoots,
        ApprovedScanRoot(
          rootPath: rootPath,
          scanDepth: depth < 1 ? 1 : depth,
          enabled: true,
        ),
      ];
      _scanRootController.clear();
      _scanDepthController.text = '2';
      _errorMessage = null;
    });
  }

  Future<void> _save() async {
    final deviceId = widget.controller.selectedDeviceId;
    if (deviceId == null || deviceId.isEmpty) {
      setState(() {
        _errorMessage = '请先选择设备';
      });
      return;
    }

    final apiKeyInput = _apiKeyController.text.trim();

    setState(() {
      _saving = true;
      _errorMessage = null;
    });
    final saved = await widget.controller.updateProjectContextSettings(
      ProjectContextSettings(
        deviceId: deviceId,
        pinnedProjects: _pinnedProjects,
        approvedScanRoots: _scanRoots,
        plannerConfig: _plannerConfig,
      ),
    );
    if (saved != null && apiKeyInput.isNotEmpty) {
      await widget.credentialsService.saveApiKey(deviceId, apiKeyInput);
      _hasStoredApiKey = true;
    }
    if (!mounted) {
      return;
    }
    setState(() {
      _saving = false;
      _errorMessage = saved == null ? widget.controller.errorMessage : null;
    });
    if (saved != null) {
      Navigator.of(context).pop(true);
    }
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('常用项目'),
      content: SizedBox(
        width: 560,
        child: _loading
            ? const SizedBox(
                height: 220,
                child: Center(child: CircularProgressIndicator()),
              )
            : SingleChildScrollView(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Container(
                      width: double.infinity,
                      padding: const EdgeInsets.all(16),
                      decoration: BoxDecoration(
                        color: Theme.of(context)
                            .colorScheme
                            .surfaceContainerHighest
                            .withValues(alpha: 0.42),
                        borderRadius: BorderRadius.circular(16),
                      ),
                      child: Text(
                        '把你常进入的项目放在这里，智能终端会优先推荐这些目录。',
                        style: Theme.of(context).textTheme.bodyMedium,
                      ),
                    ),
                    const SizedBox(height: 20),
                    _SectionTitle(
                      title: '常用项目',
                      subtitle: '这里越明确，智能推荐越容易一步到位。',
                    ),
                    const SizedBox(height: 8),
                    for (var index = 0; index < _pinnedProjects.length; index++)
                      Card(
                        child: ListTile(
                          key: Key('project-settings-pinned-$index'),
                          title: Text(_pinnedProjects[index].label),
                          subtitle: Text(_pinnedProjects[index].cwd),
                          trailing: IconButton(
                            key: Key('project-settings-pinned-remove-$index'),
                            onPressed: _saving
                                ? null
                                : () {
                                    setState(() {
                                      _pinnedProjects = [
                                        for (var i = 0;
                                            i < _pinnedProjects.length;
                                            i++)
                                          if (i != index) _pinnedProjects[i],
                                      ];
                                    });
                                  },
                            icon: const Icon(Icons.delete_outline),
                          ),
                        ),
                      ),
                    TextField(
                      key: const Key('project-settings-pinned-label'),
                      controller: _pinnedLabelController,
                      decoration: const InputDecoration(labelText: '项目名称'),
                    ),
                    const SizedBox(height: 8),
                    TextField(
                      key: const Key('project-settings-pinned-cwd'),
                      controller: _pinnedCwdController,
                      decoration: const InputDecoration(labelText: '项目目录'),
                    ),
                    const SizedBox(height: 8),
                    OutlinedButton.icon(
                      key: const Key('project-settings-pinned-add'),
                      onPressed: _saving ? null : _addPinnedProject,
                      icon: const Icon(Icons.add),
                      label: const Text('添加常用项目'),
                    ),
                    const SizedBox(height: 20),
                    ListTile(
                      contentPadding: EdgeInsets.zero,
                      title: const Text('高级设置'),
                      subtitle: const Text('只有需要扫描目录或接入 LLM 时再展开。'),
                      trailing: Icon(
                        _advancedExpanded
                            ? Icons.expand_less
                            : Icons.expand_more,
                      ),
                      onTap: _saving
                          ? null
                          : () {
                              setState(() {
                                _advancedExpanded = !_advancedExpanded;
                              });
                            },
                    ),
                    if (_advancedExpanded) ...[
                      const SizedBox(height: 8),
                      _SectionTitle(
                        title: '扫描目录',
                        subtitle: 'Agent 只会在你显式授权的目录范围里扫描项目。',
                      ),
                      const SizedBox(height: 8),
                      for (var index = 0; index < _scanRoots.length; index++)
                        Card(
                          child: CheckboxListTile(
                            key: Key('project-settings-scan-root-$index'),
                            value: _scanRoots[index].enabled,
                            onChanged: _saving
                                ? null
                                : (value) {
                                    setState(() {
                                      _scanRoots = [
                                        for (var i = 0;
                                            i < _scanRoots.length;
                                            i++)
                                          if (i == index)
                                            _scanRoots[i].copyWith(
                                              enabled: value ?? false,
                                            )
                                          else
                                            _scanRoots[i],
                                      ];
                                    });
                                  },
                            title: Text(_scanRoots[index].rootPath),
                            subtitle: Text(
                              '扫描深度 ${_scanRoots[index].scanDepth}',
                            ),
                            secondary: IconButton(
                              key: Key(
                                'project-settings-scan-root-remove-$index',
                              ),
                              onPressed: _saving
                                  ? null
                                  : () {
                                      setState(() {
                                        _scanRoots = [
                                          for (var i = 0;
                                              i < _scanRoots.length;
                                              i++)
                                            if (i != index) _scanRoots[i],
                                        ];
                                      });
                                    },
                              icon: const Icon(Icons.delete_outline),
                            ),
                          ),
                        ),
                      TextField(
                        key: const Key('project-settings-scan-root-path'),
                        controller: _scanRootController,
                        decoration: const InputDecoration(labelText: '根目录'),
                      ),
                      const SizedBox(height: 8),
                      TextField(
                        key: const Key('project-settings-scan-root-depth'),
                        controller: _scanDepthController,
                        decoration: const InputDecoration(labelText: '扫描深度'),
                        keyboardType: TextInputType.number,
                      ),
                      const SizedBox(height: 8),
                      OutlinedButton.icon(
                        key: const Key('project-settings-scan-root-add'),
                        onPressed: _saving ? null : _addScanRoot,
                        icon: const Icon(Icons.add),
                        label: const Text('添加扫描目录'),
                      ),
                      const SizedBox(height: 20),
                      _SectionTitle(
                        title: '智能规划器',
                        subtitle:
                            '默认优先调用服务端 LLM，失败时自动回退 `claude -p` 和本地规则。',
                      ),
                      SwitchListTile(
                        key: const Key('project-settings-planner-enabled'),
                        value: _plannerConfig.llmEnabled,
                        contentPadding: EdgeInsets.zero,
                        onChanged: _saving
                            ? null
                            : (value) {
                                setState(() {
                                  _plannerConfig = _plannerConfig.copyWith(
                                    llmEnabled: value,
                                    provider:
                                        value ? 'claude_cli' : 'local_rules',
                                  );
                                });
                              },
                        title: const Text('启用智能规划'),
                        subtitle: const Text('关闭后，一句话创建只走本地规则。'),
                      ),
                      const SizedBox(height: 8),
                      DropdownButtonFormField<String>(
                        key: const Key('project-settings-endpoint-profile'),
                        value: _plannerConfig.endpointProfile,
                        items: const [
                          DropdownMenuItem(
                            value: 'openai_compatible',
                            child: Text('OpenAI Compatible'),
                          ),
                        ],
                        onChanged: _saving || !_plannerConfig.llmEnabled
                            ? null
                            : (value) {
                                if (value == null) {
                                  return;
                                }
                                setState(() {
                                  _plannerConfig = _plannerConfig.copyWith(
                                    endpointProfile: value,
                                  );
                                });
                              },
                        decoration:
                            const InputDecoration(labelText: 'Endpoint'),
                      ),
                      const SizedBox(height: 8),
                      TextField(
                        key: const Key('project-settings-planner-api-key'),
                        controller: _apiKeyController,
                        decoration: InputDecoration(
                          labelText:
                              _hasStoredApiKey ? '替换 API Key（可选）' : 'API Key（可选）',
                          helperText: _hasStoredApiKey
                              ? '已保存旧密钥；如果服务端已统一配置，这里可以留空。'
                              : '通常由服务端统一配置；只有你要做客户端凭证覆盖时才需要填写。',
                        ),
                        obscureText: true,
                      ),
                    ],
                    if (_errorMessage != null) ...[
                      const SizedBox(height: 12),
                      Text(
                        _errorMessage!,
                        key: const Key('project-settings-error'),
                        style: TextStyle(
                          color: Theme.of(context).colorScheme.error,
                        ),
                      ),
                    ],
                  ],
                ),
              ),
      ),
      actions: [
        TextButton(
          onPressed: _saving ? null : () => Navigator.of(context).pop(),
          child: const Text('取消'),
        ),
        FilledButton(
          key: const Key('project-settings-save'),
          onPressed: _saving ? null : _save,
          child: _saving
              ? const SizedBox(
                  width: 16,
                  height: 16,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              : const Text('保存'),
        ),
      ],
    );
  }

  String _labelFromPath(String path) {
    final normalized = path.trim().replaceAll(RegExp(r'/+$'), '');
    if (normalized.isEmpty) {
      return 'Unnamed Project';
    }
    final segments = normalized.split('/');
    return segments.isEmpty ? normalized : segments.last;
  }
}

class _SectionTitle extends StatelessWidget {
  const _SectionTitle({
    required this.title,
    required this.subtitle,
  });

  final String title;
  final String subtitle;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(title, style: Theme.of(context).textTheme.titleSmall),
        const SizedBox(height: 4),
        Text(subtitle, style: Theme.of(context).textTheme.bodySmall),
      ],
    );
  }
}
