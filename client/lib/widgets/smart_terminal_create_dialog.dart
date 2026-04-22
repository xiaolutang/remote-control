import 'package:flutter/material.dart';

import '../models/project_context_snapshot.dart';
import '../models/terminal_launch_plan.dart';
import '../services/runtime_selection_controller.dart';

Future<T?> showSmartTerminalCreateDialog<T>({
  required BuildContext context,
  required RuntimeSelectionController controller,
  required Future<T?> Function(TerminalLaunchPlan plan) onCreate,
  Future<void> Function()? onOpenProjectSettings,
  String title = '智能新建终端',
}) {
  return showDialog<T>(
    context: context,
    builder: (context) {
      return _SmartTerminalCreateDialog<T>(
        title: title,
        controller: controller,
        onCreate: onCreate,
        onOpenProjectSettings: onOpenProjectSettings,
      );
    },
  );
}

class _SmartTerminalCreateDialog<T> extends StatefulWidget {
  const _SmartTerminalCreateDialog({
    required this.title,
    required this.controller,
    required this.onCreate,
    this.onOpenProjectSettings,
  });

  final String title;
  final RuntimeSelectionController controller;
  final Future<T?> Function(TerminalLaunchPlan plan) onCreate;
  final Future<void> Function()? onOpenProjectSettings;

  @override
  State<_SmartTerminalCreateDialog<T>> createState() =>
      _SmartTerminalCreateDialogState<T>();
}

class _SmartTerminalCreateDialogState<T>
    extends State<_SmartTerminalCreateDialog<T>> {
  late final TextEditingController _intentController;
  late final TextEditingController _titleController;
  late final TextEditingController _cwdController;
  late final TextEditingController _commandController;
  late final TextEditingController _postCreateInputController;

  late TerminalLaunchPlan _plan;
  bool _advancedExpanded = false;
  bool _resolvingIntent = false;
  bool _manualConfirmationAccepted = false;
  String? _plannerProvider;
  String? _matchedCandidateId;
  String? _reasoningKind;
  bool _userEditedPlan = false;

  @override
  void initState() {
    super.initState();
    _intentController = TextEditingController();
    _titleController = TextEditingController();
    _cwdController = TextEditingController();
    _commandController = TextEditingController();
    _postCreateInputController = TextEditingController();
    final recommendedPlans = widget.controller.recommendedLaunchPlans;
    _plan = recommendedPlans.isNotEmpty
        ? recommendedPlans.first
        : widget.controller.normalizeLaunchPlan(
            TerminalLaunchPlan(
              tool: TerminalLaunchTool.shell,
              title: 'Shell',
              cwd: '~',
              command: '/bin/bash',
              entryStrategy: TerminalEntryStrategy.directExec,
              postCreateInput: '',
              source: TerminalLaunchPlanSource.recommended,
            ),
          );
    _manualConfirmationAccepted = !_plan.requiresManualConfirmation;
    _resetExplanationForPlan(_plan);
    _syncDraftControllers();
  }

  @override
  void dispose() {
    _intentController.dispose();
    _titleController.dispose();
    _cwdController.dispose();
    _commandController.dispose();
    _postCreateInputController.dispose();
    super.dispose();
  }

  void _syncDraftControllers() {
    _titleController.text = _plan.title;
    _cwdController.text = _plan.cwd;
    _commandController.text = _plan.command;
    _postCreateInputController.text = _plan.postCreateInput;
  }

  void _applyPlan(
    TerminalLaunchPlan plan, {
    bool expandAdvanced = false,
    bool clearIntent = false,
    bool markUserEdited = false,
    String? plannerProvider,
    String? matchedCandidateId,
    String? reasoningKind,
  }) {
    setState(() {
      _plan = widget.controller.normalizeLaunchPlan(plan);
      _advancedExpanded = _advancedExpanded || expandAdvanced;
      _manualConfirmationAccepted = !_plan.requiresManualConfirmation;
      _userEditedPlan = markUserEdited;
      if (plannerProvider != null || matchedCandidateId != null) {
        _plannerProvider = plannerProvider;
        _matchedCandidateId = matchedCandidateId;
        _reasoningKind = reasoningKind;
      } else if (markUserEdited) {
        _matchedCandidateId = _deriveCandidateId(_plan.cwd);
        _reasoningKind = 'user_override';
      } else {
        _resetExplanationForPlan(_plan);
      }
      if (clearIntent) {
        _intentController.clear();
      }
      _syncDraftControllers();
    });
  }

  void _resetExplanationForPlan(TerminalLaunchPlan plan) {
    _plannerProvider = null;
    _matchedCandidateId = _deriveCandidateId(plan.cwd);
    _reasoningKind = switch (plan.source) {
      TerminalLaunchPlanSource.recommended => 'recommended',
      TerminalLaunchPlanSource.intent => 'intent',
      TerminalLaunchPlanSource.custom => 'custom',
    };
    _userEditedPlan = false;
  }

  String? _deriveCandidateId(String? cwd) {
    return _resolveCandidateForCwd(cwd)?.candidateId;
  }

  ProjectContextCandidate? _resolveMatchedCandidate() {
    final matchedId = _matchedCandidateId ?? _deriveCandidateId(_plan.cwd);
    if (matchedId == null) {
      return null;
    }
    return _resolveCandidateById(matchedId);
  }

  void _handleCandidateSelected(ProjectContextCandidate candidate) {
    final draft = _buildDraftPlan();
    _applyPlan(
      draft.copyWith(
        title: TerminalLaunchPlanDefaults.titleFor(draft.tool, candidate.cwd),
        cwd: candidate.cwd,
        confidence: TerminalLaunchConfidence.high,
        requiresManualConfirmation: candidate.requiresConfirmation,
      ),
      expandAdvanced: true,
      markUserEdited: true,
      plannerProvider: _plannerProvider,
      matchedCandidateId: candidate.candidateId,
      reasoningKind: 'candidate_switch',
    );
  }

  bool _requiresManualConfirmationForCwd(String cwd) {
    return widget.controller.requiresManualConfirmationForCwd(
      cwd,
      currentCwd: _plan.cwd,
      currentRequiresManualConfirmation: _plan.requiresManualConfirmation,
    );
  }

  ProjectContextCandidate? _resolveCandidateForCwd(String? cwd) {
    return widget.controller.resolveCandidateForCwd(cwd);
  }

  ProjectContextCandidate? _resolveCandidateById(String matchedId) {
    final candidates =
        widget.controller.projectContextSnapshot?.candidates ?? const [];
    for (final candidate in candidates) {
      if (candidate.candidateId == matchedId) {
        return candidate;
      }
    }
    return null;
  }

  TerminalLaunchPlan _buildDraftPlan() {
    return widget.controller.finalizeLaunchPlan(
      _plan.copyWith(
        title: _titleController.text,
        cwd: _cwdController.text,
        command: _commandController.text,
        entryStrategy: _plan.entryStrategy,
        postCreateInput: _postCreateInputController.text,
        source: _plan.source,
        intent: _intentController.text.trim().isEmpty
            ? _plan.intent
            : _intentController.text.trim(),
        clearIntent: _intentController.text.trim().isEmpty &&
            _plan.source != TerminalLaunchPlanSource.intent,
        confidence: _plan.confidence,
        requiresManualConfirmation:
            _requiresManualConfirmationForCwd(_cwdController.text),
      ),
    );
  }

  Future<void> _handleResolveIntent() async {
    final rawIntent = _intentController.text.trim();
    if (rawIntent.isEmpty) {
      return;
    }
    setState(() {
      _resolvingIntent = true;
    });
    final resolved = await widget.controller.resolveLaunchIntent(
      rawIntent,
    );
    if (!mounted) {
      return;
    }
    setState(() {
      _resolvingIntent = false;
      _plan = resolved.plan;
      _plannerProvider = resolved.provider;
      _matchedCandidateId = resolved.matchedCandidateId;
      _reasoningKind = resolved.reasoningKind;
      _userEditedPlan = false;
      _manualConfirmationAccepted = !_plan.requiresManualConfirmation;
      _syncDraftControllers();
    });
  }

  Future<void> _handleCreate() async {
    final result = await widget.onCreate(_buildDraftPlan());
    if (!mounted || result == null) {
      return;
    }
    Navigator.of(context).pop(result);
  }

  void _handleToolChanged(TerminalLaunchTool tool) {
    final draft = _buildDraftPlan();
    final defaults = TerminalLaunchPlanDefaults.forTool(tool);
    final nextCwd = draft.cwd.trim().isEmpty ? _plan.cwd : draft.cwd.trim();
    _applyPlan(
      draft.copyWith(
        tool: tool,
        title: TerminalLaunchPlanDefaults.titleFor(tool, nextCwd),
        cwd: nextCwd,
        command: defaults.command,
        entryStrategy: defaults.entryStrategy,
        postCreateInput: defaults.postCreateInput,
        source: tool == TerminalLaunchTool.custom
            ? TerminalLaunchPlanSource.custom
            : draft.source,
      ),
      expandAdvanced: true,
      markUserEdited: true,
    );
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: widget.controller,
      builder: (context, _) {
        final creating = widget.controller.creatingTerminal;
        final errorMessage = widget.controller.errorMessage;
        final recommendedPlans = widget.controller.recommendedLaunchPlans;
        final candidates =
            widget.controller.projectContextSnapshot?.candidates ?? const [];
        final draftPlan = _buildDraftPlan();
        final requiresManualConfirmation = draftPlan.requiresManualConfirmation;
        final matchedCandidate = _resolveMatchedCandidate();

        return Dialog(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 560),
            child: Padding(
              padding: const EdgeInsets.all(20),
              child: SingleChildScrollView(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      widget.title,
                      style: Theme.of(context).textTheme.titleLarge,
                    ),
                    const SizedBox(height: 8),
                    Text(
                      '推荐创建、一句话输入和高级配置都走同一条创建链路。',
                      style: Theme.of(context).textTheme.bodyMedium,
                    ),
                    if (widget.onOpenProjectSettings != null) ...[
                      const SizedBox(height: 12),
                      OutlinedButton.icon(
                        key: const Key('smart-create-project-settings'),
                        onPressed: creating
                            ? null
                            : () => widget.onOpenProjectSettings!.call(),
                        icon: const Icon(Icons.folder_open_outlined),
                        label: const Text('项目来源设置'),
                      ),
                    ],
                    const SizedBox(height: 16),
                    Text(
                      '推荐项',
                      style: Theme.of(context).textTheme.titleSmall,
                    ),
                    const SizedBox(height: 8),
                    Wrap(
                      spacing: 8,
                      runSpacing: 8,
                      children: [
                        for (final plan in recommendedPlans)
                          FilledButton.tonalIcon(
                            key: Key(
                              'smart-create-recommend-${TerminalLaunchToolCodec.toJson(plan.tool)}',
                            ),
                            onPressed: creating
                                ? null
                                : () => _applyPlan(
                                      plan,
                                      clearIntent: true,
                                    ),
                            icon: Icon(_toolIcon(plan.tool)),
                            label: Text(_toolLabel(plan.tool)),
                          ),
                        OutlinedButton.icon(
                          key: const Key('smart-create-recommend-custom'),
                          onPressed: creating
                              ? null
                              : () => _handleToolChanged(
                                    TerminalLaunchTool.custom,
                                  ),
                          icon: const Icon(Icons.tune),
                          label: const Text('自定义'),
                        ),
                      ],
                    ),
                    const SizedBox(height: 20),
                    Text(
                      '一句话输入',
                      style: Theme.of(context).textTheme.titleSmall,
                    ),
                    const SizedBox(height: 8),
                    TextField(
                      key: const Key('smart-create-intent-input'),
                      controller: _intentController,
                      decoration: const InputDecoration(
                        hintText: '例如：进入 codex 修一下登录问题',
                        border: OutlineInputBorder(),
                      ),
                      minLines: 1,
                      maxLines: 3,
                    ),
                    const SizedBox(height: 8),
                    FilledButton.icon(
                      key: const Key('smart-create-generate'),
                      onPressed: creating || _resolvingIntent
                          ? null
                          : _handleResolveIntent,
                      icon: _resolvingIntent
                          ? const SizedBox(
                              width: 16,
                              height: 16,
                              child: CircularProgressIndicator(strokeWidth: 2),
                            )
                          : const Icon(Icons.auto_awesome),
                      label: const Text('生成方案'),
                    ),
                    const SizedBox(height: 20),
                    _PlanPreview(
                      plan: draftPlan,
                      candidate: matchedCandidate,
                      plannerProvider: _plannerProvider,
                      reasoningKind: _reasoningKind,
                      userEditedPlan: _userEditedPlan,
                    ),
                    if (candidates.isNotEmpty) ...[
                      const SizedBox(height: 16),
                      Text(
                        '候选项目',
                        style: Theme.of(context).textTheme.titleSmall,
                      ),
                      const SizedBox(height: 8),
                      Wrap(
                        spacing: 8,
                        runSpacing: 8,
                        children: [
                          for (final candidate in candidates)
                            ChoiceChip(
                              key: Key(
                                'smart-create-candidate-${candidate.candidateId}',
                              ),
                              label: Text(candidate.label),
                              selected: matchedCandidate?.candidateId ==
                                  candidate.candidateId,
                              onSelected: creating || _resolvingIntent
                                  ? null
                                  : (_) => _handleCandidateSelected(candidate),
                            ),
                        ],
                      ),
                    ],
                    if (errorMessage != null) ...[
                      const SizedBox(height: 12),
                      Text(
                        errorMessage,
                        style: TextStyle(
                          color: Theme.of(context).colorScheme.error,
                        ),
                      ),
                    ],
                    const SizedBox(height: 12),
                    ListTile(
                      key: const Key('smart-create-advanced'),
                      contentPadding: EdgeInsets.zero,
                      title: const Text('高级配置'),
                      trailing: Icon(
                        _advancedExpanded
                            ? Icons.expand_less
                            : Icons.expand_more,
                      ),
                      onTap: () {
                        setState(() {
                          _advancedExpanded = !_advancedExpanded;
                        });
                      },
                    ),
                    if (_advancedExpanded)
                      Column(
                        children: [
                          DropdownButtonFormField<TerminalLaunchTool>(
                            key: ValueKey<String>(
                              'smart-create-tool-${TerminalLaunchToolCodec.toJson(_plan.tool)}',
                            ),
                            value: _plan.tool,
                            items: TerminalLaunchTool.values
                                .map(
                                  (tool) => DropdownMenuItem(
                                    value: tool,
                                    child: Text(_toolLabel(tool)),
                                  ),
                                )
                                .toList(),
                            onChanged: creating
                                ? null
                                : (value) {
                                    if (value != null) {
                                      _handleToolChanged(value);
                                    }
                                  },
                            decoration: const InputDecoration(labelText: '工具'),
                          ),
                          const SizedBox(height: 12),
                          TextField(
                            key: const Key('smart-create-title'),
                            controller: _titleController,
                            decoration: const InputDecoration(labelText: '标题'),
                            onChanged: (_) {
                              setState(() {
                                _userEditedPlan = true;
                                _reasoningKind = 'user_override';
                              });
                            },
                          ),
                          const SizedBox(height: 12),
                          TextField(
                            key: const Key('smart-create-cwd'),
                            controller: _cwdController,
                            decoration:
                                const InputDecoration(labelText: '工作目录'),
                            onChanged: (_) {
                              final requiresManualConfirmation =
                                  _requiresManualConfirmationForCwd(
                                _cwdController.text,
                              );
                              setState(() {
                                _plan = _plan.copyWith(
                                  requiresManualConfirmation:
                                      requiresManualConfirmation,
                                );
                                _userEditedPlan = true;
                                _reasoningKind = 'user_override';
                                _matchedCandidateId =
                                    _deriveCandidateId(_cwdController.text);
                                if (requiresManualConfirmation &&
                                    _manualConfirmationAccepted) {
                                  _manualConfirmationAccepted = false;
                                }
                              });
                            },
                          ),
                          const SizedBox(height: 12),
                          TextField(
                            key: const Key('smart-create-command'),
                            controller: _commandController,
                            decoration:
                                const InputDecoration(labelText: '启动命令'),
                            onChanged: (_) {
                              setState(() {
                                _userEditedPlan = true;
                                _reasoningKind = 'user_override';
                              });
                            },
                          ),
                          const SizedBox(height: 12),
                          DropdownButtonFormField<TerminalEntryStrategy>(
                            key: ValueKey<String>(
                              'smart-create-entry-strategy-${TerminalEntryStrategyCodec.toJson(_plan.entryStrategy)}',
                            ),
                            value: _plan.entryStrategy,
                            items: TerminalEntryStrategy.values
                                .map(
                                  (strategy) => DropdownMenuItem(
                                    value: strategy,
                                    child: Text(_entryStrategyLabel(strategy)),
                                  ),
                                )
                                .toList(),
                            onChanged: creating
                                ? null
                                : (value) {
                                    if (value == null) {
                                      return;
                                    }
                                    setState(() {
                                      _plan = _plan.copyWith(
                                        entryStrategy: value,
                                      );
                                      _userEditedPlan = true;
                                      _reasoningKind = 'user_override';
                                    });
                                  },
                            decoration:
                                const InputDecoration(labelText: '进入策略'),
                          ),
                          const SizedBox(height: 12),
                          TextField(
                            key: const Key('smart-create-post-create-input'),
                            controller: _postCreateInputController,
                            decoration: const InputDecoration(
                              labelText: '创建后自动输入',
                            ),
                            minLines: 1,
                            maxLines: 3,
                            onChanged: (_) {
                              setState(() {
                                _userEditedPlan = true;
                                _reasoningKind = 'user_override';
                              });
                            },
                          ),
                        ],
                      ),
                    if (requiresManualConfirmation)
                      CheckboxListTile(
                        key: const Key('smart-create-confirm-manual'),
                        value: _manualConfirmationAccepted,
                        contentPadding: EdgeInsets.zero,
                        title: const Text('我已确认工作目录和启动方案'),
                        subtitle: const Text('检测到路径线索不够明确，确认后才允许创建。'),
                        onChanged: creating || _resolvingIntent
                            ? null
                            : (value) {
                                setState(() {
                                  _manualConfirmationAccepted = value ?? false;
                                });
                              },
                      ),
                    const SizedBox(height: 8),
                    Row(
                      mainAxisAlignment: MainAxisAlignment.end,
                      children: [
                        TextButton(
                          key: const Key('smart-create-cancel'),
                          onPressed: creating
                              ? null
                              : () => Navigator.of(context).pop(),
                          child: const Text('取消'),
                        ),
                        const SizedBox(width: 8),
                        FilledButton(
                          key: const Key('smart-create-submit'),
                          onPressed: creating ||
                                  _resolvingIntent ||
                                  (requiresManualConfirmation &&
                                      !_manualConfirmationAccepted)
                              ? null
                              : _handleCreate,
                          child: creating
                              ? const SizedBox(
                                  width: 16,
                                  height: 16,
                                  child:
                                      CircularProgressIndicator(strokeWidth: 2),
                                )
                              : const Text('创建'),
                        ),
                      ],
                    ),
                  ],
                ),
              ),
            ),
          ),
        );
      },
    );
  }

  String _toolLabel(TerminalLaunchTool tool) {
    switch (tool) {
      case TerminalLaunchTool.claudeCode:
        return 'Claude Code';
      case TerminalLaunchTool.codex:
        return 'Codex';
      case TerminalLaunchTool.shell:
        return 'Shell';
      case TerminalLaunchTool.custom:
        return '自定义';
    }
  }

  String _entryStrategyLabel(TerminalEntryStrategy strategy) {
    switch (strategy) {
      case TerminalEntryStrategy.directExec:
        return '直接执行';
      case TerminalEntryStrategy.shellBootstrap:
        return '启动 shell 后注入';
    }
  }

  IconData _toolIcon(TerminalLaunchTool tool) {
    switch (tool) {
      case TerminalLaunchTool.claudeCode:
        return Icons.smart_toy_outlined;
      case TerminalLaunchTool.codex:
        return Icons.code_outlined;
      case TerminalLaunchTool.shell:
        return Icons.terminal_outlined;
      case TerminalLaunchTool.custom:
        return Icons.tune;
    }
  }
}

class _PlanPreview extends StatelessWidget {
  const _PlanPreview({
    required this.plan,
    this.candidate,
    this.plannerProvider,
    this.reasoningKind,
    this.userEditedPlan = false,
  });

  final TerminalLaunchPlan plan;
  final ProjectContextCandidate? candidate;
  final String? plannerProvider;
  final String? reasoningKind;
  final bool userEditedPlan;

  @override
  Widget build(BuildContext context) {
    final colorScheme = Theme.of(context).colorScheme;
    final confidenceText = switch (plan.confidence) {
      TerminalLaunchConfidence.high => '高置信度',
      TerminalLaunchConfidence.medium => '中置信度',
      TerminalLaunchConfidence.low => '低置信度',
    };
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: colorScheme.surfaceContainerHighest.withValues(alpha: 0.45),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  '当前方案预览',
                  style: Theme.of(context).textTheme.titleSmall,
                ),
              ),
              Text(
                confidenceText,
                key: const Key('smart-create-preview-confidence'),
                style: Theme.of(context).textTheme.bodySmall,
              ),
            ],
          ),
          const SizedBox(height: 8),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              _MetaChip(
                keyName: 'smart-create-preview-source',
                label: '来源 ${_sourceLabel(plan.source)}',
              ),
              _MetaChip(
                keyName: 'smart-create-preview-provider',
                label: '规划 ${_providerLabel(plannerProvider, plan.source)}',
              ),
              if (candidate != null)
                _MetaChip(
                  keyName: 'smart-create-preview-candidate',
                  label: '候选 ${candidate!.label}',
                ),
              if (candidate != null)
                _MetaChip(
                  keyName: 'smart-create-preview-candidate-source',
                  label: '候选来源 ${_candidateSourceLabel(candidate!.source)}',
                ),
              if (userEditedPlan)
                const _MetaChip(
                  keyName: 'smart-create-preview-user-edited',
                  label: '已手动修改',
                ),
            ],
          ),
          const SizedBox(height: 8),
          Text(
            _previewToolLabel(plan.tool),
            key: const Key('smart-create-preview-tool'),
            style: Theme.of(context).textTheme.titleMedium,
          ),
          const SizedBox(height: 4),
          Text(
            plan.title,
            key: const Key('smart-create-preview-title'),
          ),
          const SizedBox(height: 4),
          Text(
            plan.cwd,
            key: const Key('smart-create-preview-cwd'),
          ),
          const SizedBox(height: 4),
          Text(
            plan.command,
            key: const Key('smart-create-preview-command'),
          ),
          if (plan.requiresManualConfirmation) ...[
            const SizedBox(height: 8),
            Text(
              '检测到了可能的路径线索，请在创建前确认工作目录。',
              key: const Key('smart-create-preview-warning'),
              style: TextStyle(color: colorScheme.error),
            ),
          ] else if (plan.source == TerminalLaunchPlanSource.intent &&
              plan.confidence == TerminalLaunchConfidence.low) ...[
            const SizedBox(height: 8),
            const Text(
              '当前短句不够明确，已回退到默认推荐方案。',
              key: Key('smart-create-preview-fallback'),
            ),
          ],
          if (reasoningKind != null) ...[
            const SizedBox(height: 8),
            Text(
              '解释：${_reasoningLabel(reasoningKind!)}',
              key: const Key('smart-create-preview-reasoning'),
              style: Theme.of(context).textTheme.bodySmall,
            ),
          ],
        ],
      ),
    );
  }

  static String _previewToolLabel(TerminalLaunchTool tool) {
    switch (tool) {
      case TerminalLaunchTool.claudeCode:
        return 'Claude Code';
      case TerminalLaunchTool.codex:
        return 'Codex';
      case TerminalLaunchTool.shell:
        return 'Shell';
      case TerminalLaunchTool.custom:
        return '自定义';
    }
  }

  static String _sourceLabel(TerminalLaunchPlanSource source) {
    switch (source) {
      case TerminalLaunchPlanSource.recommended:
        return '推荐';
      case TerminalLaunchPlanSource.intent:
        return '短句意图';
      case TerminalLaunchPlanSource.custom:
        return '自定义';
    }
  }

  static String _providerLabel(
    String? provider,
    TerminalLaunchPlanSource source,
  ) {
    switch (provider) {
      case 'llm':
        return 'LLM';
      case 'local_rules':
        return '本地规则';
      default:
        return source == TerminalLaunchPlanSource.recommended ? '默认推荐' : '未指定';
    }
  }

  static String _candidateSourceLabel(String source) {
    switch (source) {
      case 'pinned_project':
        return '固定项目';
      case 'recent_terminal':
        return '最近终端';
      case 'recent_launch':
        return '最近启动';
      case 'approved_scan':
        return '授权扫描';
      case 'explicit_input':
        return '显式输入';
      default:
        return source;
    }
  }

  static String _reasoningLabel(String reasoningKind) {
    switch (reasoningKind) {
      case 'candidate_match':
        return '命中候选项目';
      case 'candidate_switch':
        return '已切换候选项目';
      case 'explicit_input':
        return '使用了显式路径';
      case 'tool_and_path_hint':
        return '识别到工具和路径线索';
      case 'tool_hint':
        return '识别到工具线索';
      case 'path_hint':
        return '识别到路径线索';
      case 'fallback':
        return '回退到默认推荐';
      case 'user_override':
        return '用户已手动覆盖';
      case 'recommended':
        return '使用默认推荐';
      case 'intent':
        return '使用短句结果';
      case 'custom':
        return '使用自定义方案';
      default:
        return reasoningKind;
    }
  }
}

class _MetaChip extends StatelessWidget {
  const _MetaChip({
    required this.keyName,
    required this.label,
  });

  final String keyName;
  final String label;

  @override
  Widget build(BuildContext context) {
    return Container(
      key: Key(keyName),
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
      decoration: BoxDecoration(
        color: Theme.of(context)
            .colorScheme
            .surfaceContainerHighest
            .withValues(alpha: 0.7),
        borderRadius: BorderRadius.circular(999),
      ),
      child: Text(
        label,
        style: Theme.of(context).textTheme.bodySmall,
      ),
    );
  }
}
