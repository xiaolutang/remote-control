import 'assistant_plan.dart';
import 'terminal_launch_plan.dart';

class CommandSequenceStep {
  const CommandSequenceStep({
    required this.id,
    required this.label,
    required this.command,
  });

  final String id;
  final String label;
  final String command;

  CommandSequenceStep copyWith({
    String? id,
    String? label,
    String? command,
  }) {
    return CommandSequenceStep(
      id: id ?? this.id,
      label: label ?? this.label,
      command: command ?? this.command,
    );
  }
}

class CommandSequenceDraft {
  const CommandSequenceDraft({
    required this.summary,
    required this.provider,
    required this.tool,
    required this.title,
    required this.cwd,
    required this.shellCommand,
    required this.steps,
    required this.source,
    this.intent,
    this.confidence = TerminalLaunchConfidence.high,
    this.requiresManualConfirmation = false,
    this.assistantConversationId,
    this.assistantMessageId,
  });

  final String summary;
  final String provider;
  final TerminalLaunchTool tool;
  final String title;
  final String cwd;
  final String shellCommand;
  final List<CommandSequenceStep> steps;
  final TerminalLaunchPlanSource source;
  final String? intent;
  final TerminalLaunchConfidence confidence;
  final bool requiresManualConfirmation;
  final String? assistantConversationId;
  final String? assistantMessageId;

  factory CommandSequenceDraft.fromLaunchPlan(
    TerminalLaunchPlan plan, {
    String? provider,
    bool claudeOnly = true,
  }) {
    final normalizedCwd = _normalizeCwd(plan.cwd);
    final effectiveTool = claudeOnly && plan.tool != TerminalLaunchTool.custom
        ? TerminalLaunchTool.claudeCode
        : plan.tool;
    final normalizedTitle = plan.title.trim().isEmpty
        ? TerminalLaunchPlanDefaults.titleFor(effectiveTool, normalizedCwd)
        : plan.title.trim();
    final normalizedShell =
        plan.command.trim().isEmpty ? '/bin/bash' : plan.command.trim();
    final normalizedPostCreateInput = claudeOnly &&
            effectiveTool != plan.tool &&
            plan.tool != TerminalLaunchTool.custom
        ? ''
        : plan.postCreateInput;
    final steps = _buildDefaultSteps(
      tool: effectiveTool,
      cwd: normalizedCwd,
      shellCommand: normalizedShell,
      postCreateInput: normalizedPostCreateInput,
    );
    return CommandSequenceDraft(
      summary: _buildSummary(effectiveTool, normalizedCwd, steps),
      provider: _normalizeProvider(provider),
      tool: effectiveTool,
      title: normalizedTitle,
      cwd: normalizedCwd,
      shellCommand: normalizedShell,
      steps: steps,
      source: plan.source,
      intent: plan.intent,
      confidence: plan.confidence,
      requiresManualConfirmation: plan.requiresManualConfirmation,
      assistantConversationId: null,
      assistantMessageId: null,
    );
  }

  factory CommandSequenceDraft.fromAssistantCommandSequence({
    required String summary,
    required String provider,
    required String source,
    required List<CommandSequenceStep> steps,
    required String? matchedCwd,
    String? matchedLabel,
    String? intent,
    bool needConfirm = true,
    String? conversationId,
    String? messageId,
  }) {
    final normalizedSteps = [
      for (final step in steps)
        if (step.command.trim().isNotEmpty)
          step.copyWith(command: step.command.trim()),
    ];
    final normalizedCwd = _normalizeCwd(
      _deriveCwdFromSteps(normalizedSteps) ?? matchedCwd ?? '~',
    );
    final tool = _inferTool(normalizedSteps);
    final normalizedTitle = (matchedLabel ?? '').trim().isNotEmpty
        ? '${_toolLabel(tool)} / ${matchedLabel!.trim()}'
        : TerminalLaunchPlanDefaults.titleFor(tool, normalizedCwd);
    return CommandSequenceDraft(
      summary: summary.trim().isEmpty
          ? _buildSummary(tool, normalizedCwd, normalizedSteps)
          : summary.trim(),
      provider: _normalizeProvider(provider),
      tool: tool,
      title: normalizedTitle,
      cwd: normalizedCwd,
      shellCommand: '/bin/bash',
      steps: List.unmodifiable(
        normalizedSteps.isEmpty
            ? const [
                CommandSequenceStep(
                  id: 'step_1',
                  label: '启动 Claude',
                  command: 'claude',
                ),
              ]
            : normalizedSteps,
      ),
      source: _sourceFromValue(source),
      intent: intent,
      requiresManualConfirmation: needConfirm,
      assistantConversationId: conversationId,
      assistantMessageId: messageId,
    );
  }

  CommandSequenceDraft copyWith({
    String? summary,
    String? provider,
    TerminalLaunchTool? tool,
    String? title,
    String? cwd,
    String? shellCommand,
    List<CommandSequenceStep>? steps,
    TerminalLaunchPlanSource? source,
    String? intent,
    bool clearIntent = false,
    TerminalLaunchConfidence? confidence,
    bool? requiresManualConfirmation,
    String? assistantConversationId,
    bool clearAssistantConversationId = false,
    String? assistantMessageId,
    bool clearAssistantMessageId = false,
  }) {
    return CommandSequenceDraft(
      summary: summary ?? this.summary,
      provider: provider ?? this.provider,
      tool: tool ?? this.tool,
      title: title ?? this.title,
      cwd: cwd ?? this.cwd,
      shellCommand: shellCommand ?? this.shellCommand,
      steps: steps ?? this.steps,
      source: source ?? this.source,
      intent: clearIntent ? null : (intent ?? this.intent),
      confidence: confidence ?? this.confidence,
      requiresManualConfirmation:
          requiresManualConfirmation ?? this.requiresManualConfirmation,
      assistantConversationId: clearAssistantConversationId
          ? null
          : (assistantConversationId ?? this.assistantConversationId),
      assistantMessageId: clearAssistantMessageId
          ? null
          : (assistantMessageId ?? this.assistantMessageId),
    );
  }

  TerminalLaunchPlan toLaunchPlan() {
    final normalizedCwd = _normalizeCwd(cwd);
    final normalizedShell =
        shellCommand.trim().isEmpty ? '/bin/bash' : shellCommand.trim();
    final normalizedSteps = [
      for (final step in steps)
        if (step.command.trim().isNotEmpty)
          step.copyWith(command: step.command.trim()),
    ];
    final inferredTool = _inferTool(normalizedSteps);
    final compiledPayload = _compileSteps(normalizedSteps);
    return TerminalLaunchPlan(
      tool: inferredTool,
      title: title.trim().isEmpty
          ? TerminalLaunchPlanDefaults.titleFor(inferredTool, normalizedCwd)
          : title.trim(),
      cwd: normalizedCwd,
      command: normalizedShell,
      entryStrategy: compiledPayload.isEmpty
          ? TerminalEntryStrategy.directExec
          : TerminalEntryStrategy.shellBootstrap,
      postCreateInput: compiledPayload,
      source: source,
      intent: intent,
      confidence: confidence,
      requiresManualConfirmation: requiresManualConfirmation,
    );
  }

  AssistantCommandSequence toAssistantCommandSequence() {
    final normalizedSteps = [
      for (final step in steps)
        if (step.command.trim().isNotEmpty)
          step.copyWith(command: step.command.trim()),
    ];
    return AssistantCommandSequence(
      summary: summary.trim().isEmpty
          ? _buildSummary(tool, _normalizeCwd(cwd), normalizedSteps)
          : summary.trim(),
      provider: provider.trim().isEmpty ? 'service_llm' : provider.trim(),
      source: _sourceToValue(source),
      needConfirm: requiresManualConfirmation,
      steps: List.unmodifiable(normalizedSteps),
    );
  }

  static List<CommandSequenceStep> _buildDefaultSteps({
    required TerminalLaunchTool tool,
    required String cwd,
    required String shellCommand,
    required String postCreateInput,
  }) {
    final steps = <CommandSequenceStep>[];
    if (cwd != '~' && cwd != '/') {
      steps.add(
        CommandSequenceStep(
          id: 'step_1',
          label: '进入项目目录',
          command: 'cd $cwd',
        ),
      );
    }

    final launchCommand = _resolveLaunchCommand(
      tool: tool,
      shellCommand: shellCommand,
      postCreateInput: postCreateInput,
    );
    if (launchCommand.isNotEmpty) {
      steps.add(
        CommandSequenceStep(
          id: 'step_${steps.length + 1}',
          label: _launchLabel(tool),
          command: launchCommand,
        ),
      );
    }
    if (steps.isEmpty) {
      steps.add(
        const CommandSequenceStep(
          id: 'step_1',
          label: '启动 Claude Code',
          command: 'claude',
        ),
      );
    }
    return List.unmodifiable(steps);
  }

  static String? _deriveCwdFromSteps(List<CommandSequenceStep> steps) {
    for (final step in steps) {
      final command = step.command.trim();
      if (!command.startsWith('cd ')) {
        continue;
      }
      final candidate = command.substring(3).trim();
      if (candidate.isNotEmpty) {
        return candidate;
      }
    }
    return null;
  }

  static String _resolveLaunchCommand({
    required TerminalLaunchTool tool,
    required String shellCommand,
    required String postCreateInput,
  }) {
    final bootstrap = postCreateInput.trim();
    if (bootstrap.isNotEmpty) {
      return bootstrap;
    }
    switch (tool) {
      case TerminalLaunchTool.claudeCode:
        return 'claude';
      case TerminalLaunchTool.codex:
        return 'codex';
      case TerminalLaunchTool.shell:
        return '';
      case TerminalLaunchTool.custom:
        final normalizedShell = shellCommand.trim();
        if (normalizedShell == '/bin/bash' || normalizedShell == '/bin/zsh') {
          return '';
        }
        return normalizedShell;
    }
  }

  static TerminalLaunchPlanSource _sourceFromValue(String value) {
    switch (value.trim()) {
      case 'recommended':
        return TerminalLaunchPlanSource.recommended;
      case 'custom':
        return TerminalLaunchPlanSource.custom;
      case 'intent':
      default:
        return TerminalLaunchPlanSource.intent;
    }
  }

  static String _sourceToValue(TerminalLaunchPlanSource source) {
    switch (source) {
      case TerminalLaunchPlanSource.recommended:
        return 'recommended';
      case TerminalLaunchPlanSource.custom:
        return 'custom';
      case TerminalLaunchPlanSource.intent:
        return 'intent';
    }
  }

  static String _toolLabel(TerminalLaunchTool tool) {
    switch (tool) {
      case TerminalLaunchTool.claudeCode:
        return 'Claude';
      case TerminalLaunchTool.codex:
        return 'Codex';
      case TerminalLaunchTool.shell:
        return 'Shell';
      case TerminalLaunchTool.custom:
        return 'Custom';
    }
  }

  static String _buildSummary(
    TerminalLaunchTool tool,
    String cwd,
    List<CommandSequenceStep> steps,
  ) {
    final target = TerminalLaunchPlanDefaults.titleFor(tool, cwd);
    if (steps.length <= 1) {
      return '创建终端后执行 $target';
    }
    return '创建终端后进入 ${_basename(cwd) ?? "目标目录"} 并启动${_toolLabel(tool)}';
  }

  static String _compileSteps(List<CommandSequenceStep> steps) {
    if (steps.isEmpty) {
      return '';
    }
    final buffer = StringBuffer();
    if (steps.length > 1) {
      buffer.writeln('set -e');
    }
    for (final step in steps) {
      final command = step.command.trim();
      if (command.isEmpty) {
        continue;
      }
      buffer.writeln(command);
    }
    return buffer.toString();
  }

  static TerminalLaunchTool _inferTool(List<CommandSequenceStep> steps) {
    for (var index = steps.length - 1; index >= 0; index--) {
      final command = steps[index].command.trim().toLowerCase();
      if (command == 'claude') {
        return TerminalLaunchTool.claudeCode;
      }
      if (command == 'codex') {
        return TerminalLaunchTool.codex;
      }
    }
    return TerminalLaunchTool.custom;
  }

  static String _normalizeProvider(String? provider) {
    switch (provider) {
      case 'llm':
        return 'claude_cli';
      case 'claude_cli':
      case 'local_rules':
        return provider!;
      default:
        return 'local_rules';
    }
  }

  static String _normalizeCwd(String raw) {
    final trimmed = raw.trim();
    if (trimmed.isEmpty) {
      return '~';
    }
    return trimmed;
  }

  static String _launchLabel(TerminalLaunchTool tool) {
    switch (tool) {
      case TerminalLaunchTool.claudeCode:
        return '启动 Claude Code';
      case TerminalLaunchTool.codex:
        return '启动 Codex';
      case TerminalLaunchTool.shell:
        return '打开终端';
      case TerminalLaunchTool.custom:
        return '执行命令';
    }
  }

  static String? _basename(String cwd) {
    final normalized = cwd.trim();
    if (normalized.isEmpty || normalized == '~' || normalized == '/') {
      return null;
    }
    final stripped = normalized.endsWith('/')
        ? normalized.substring(0, normalized.length - 1)
        : normalized;
    final parts = stripped.split('/');
    for (var index = parts.length - 1; index >= 0; index--) {
      final candidate = parts[index].trim();
      if (candidate.isNotEmpty && candidate != '~') {
        return candidate;
      }
    }
    return null;
  }
}
