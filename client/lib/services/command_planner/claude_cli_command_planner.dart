import 'dart:async';
import 'dart:convert';
import 'dart:io';

import '../../models/command_sequence_draft.dart';
import '../../models/project_context_settings.dart';
import '../../models/project_context_snapshot.dart';
import '../../models/terminal_launch_plan.dart';
import 'planner_provider.dart';

typedef ClaudeCliProcessRunner = Future<ProcessResult> Function(
  String executable,
  List<String> arguments,
);

class ClaudeCliCommandPlanner extends PlannerProvider {
  ClaudeCliCommandPlanner({
    ClaudeCliProcessRunner? processRunner,
    this.timeout = const Duration(seconds: 6),
  }) : _processRunner = processRunner ?? _defaultProcessRunner;

  final ClaudeCliProcessRunner _processRunner;
  final Duration timeout;

  @override
  String get provider => 'claude_cli';

  @override
  Future<PlannerResolutionResult?> resolve(
    PlannerResolutionRequest request,
  ) async {
    if (!_isClaudeCliEnabled(request.plannerConfig)) {
      return null;
    }

    final result = await _processRunner(
      'claude',
      ['-p', _buildPrompt(request)],
    ).timeout(timeout);
    if (result.exitCode != 0) {
      return null;
    }

    final content = _extractJsonBlock(result.stdout?.toString());
    if (content == null) {
      return null;
    }
    final decoded = jsonDecode(content);
    if (decoded is! Map<String, dynamic>) {
      return null;
    }
    return _buildResult(request, decoded);
  }

  PlannerResolutionResult? _buildResult(
    PlannerResolutionRequest request,
    Map<String, dynamic> payload,
  ) {
    final rawSteps = payload['steps'];
    if (rawSteps is! List || rawSteps.isEmpty) {
      return null;
    }

    final steps = <CommandSequenceStep>[];
    for (var index = 0; index < rawSteps.length; index++) {
      final item = rawSteps[index];
      if (item is! Map<String, dynamic>) {
        return null;
      }
      final command =
          PlannerIntentUtils.normalizeString(item['command'] as String?);
      if (command == null || _isDangerousCommand(command)) {
        return null;
      }
      steps.add(
        CommandSequenceStep(
          id: PlannerIntentUtils.normalizeString(item['id'] as String?) ??
              'step_${index + 1}',
          label: PlannerIntentUtils.normalizeString(item['label'] as String?) ??
              '步骤 ${index + 1}',
          command: command,
        ),
      );
    }

    final explicitPaths =
        PlannerIntentUtils.extractExplicitPaths(request.normalizedIntent);
    final matchedCandidate = _resolveCandidate(
      request.candidates,
      payload['matched_candidate_id'] as String?,
    );
    final derivedCwd = _deriveCwd(steps, request.fallbackPlan.cwd);
    final tool = _inferTool(steps, request.fallbackPlan.tool);
    final requiresManualConfirmation = _resolveNeedConfirm(
      cwd: derivedCwd,
      explicitPaths: explicitPaths,
      matchedCandidate: matchedCandidate,
      payloadValue: payload['need_confirm'],
    );
    final confidence = requiresManualConfirmation
        ? TerminalLaunchConfidence.low
        : (matchedCandidate != null || explicitPaths.isNotEmpty
            ? TerminalLaunchConfidence.high
            : TerminalLaunchConfidence.medium);
    final normalizedCwd =
        PlannerIntentUtils.normalizeCwd(derivedCwd, defaultCwd: '~');
    final source = _resolveSource(payload['source'] as String?);
    final summary = PlannerIntentUtils.normalizeString(
          payload['summary'] as String?,
        ) ??
        _buildSummary(tool, normalizedCwd);
    final sequence = CommandSequenceDraft(
      summary: summary,
      provider: provider,
      tool: tool,
      title: TerminalLaunchPlanDefaults.titleFor(tool, normalizedCwd),
      cwd: normalizedCwd,
      shellCommand: request.fallbackPlan.command,
      steps: List.unmodifiable(steps),
      source: source,
      intent: request.normalizedIntent,
      confidence: confidence,
      requiresManualConfirmation: requiresManualConfirmation,
    );
    final plan = sequence.toLaunchPlan().copyWith(
          source: source,
          intent: request.normalizedIntent,
          confidence: confidence,
          requiresManualConfirmation: requiresManualConfirmation,
        );
    return PlannerResolutionResult(
      provider: provider,
      plan: plan,
      sequence: sequence,
      reasoningKind: PlannerIntentUtils.normalizeString(
            payload['reasoning_kind'] as String?,
          ) ??
          'claude_cli',
      matchedCandidateId: matchedCandidate?.candidateId ??
          PlannerIntentUtils.candidateIdForCwd(
            request.candidates,
            normalizedCwd,
          ),
    );
  }

  static Future<ProcessResult> _defaultProcessRunner(
    String executable,
    List<String> arguments,
  ) {
    return Process.run(executable, arguments);
  }

  bool _isClaudeCliEnabled(PlannerRuntimeConfigModel config) {
    return config.llmEnabled &&
        (config.provider == provider || config.provider == 'llm');
  }

  String _buildPrompt(PlannerResolutionRequest request) {
    final payload = <String, dynamic>{
      'intent': request.normalizedIntent,
      'recent_context': request.recentContext == null
          ? null
          : {
              'last_tool': TerminalLaunchToolCodec.toJson(
                request.recentContext!.lastTool,
              ),
              'last_cwd': request.recentContext!.lastCwd,
              'last_successful_plan':
                  request.recentContext!.lastSuccessfulPlan.toJson(),
            },
      'candidates': [
        for (final candidate in request.candidates)
          {
            'candidate_id': candidate.candidateId,
            'label': candidate.label,
            'cwd': candidate.cwd,
            'tool_hints': candidate.toolHints,
            'requires_confirmation': candidate.requiresConfirmation,
          },
      ],
    };
    return '''
你是一个受约束的终端命令规划器。只返回 JSON，不要 markdown。
输出 schema:
{
  "summary": "string",
  "source": "intent",
  "need_confirm": true,
  "reasoning_kind": "string",
  "matched_candidate_id": "string|null",
  "steps": [
    {"id": "step_1", "label": "说明", "command": "单条 shell 命令"}
  ]
}
约束:
- 只输出用户确认后可在同一个 shell 会话中顺序执行的命令
- 不要执行危险命令，不要删除文件，不要 sudo，不要联网下载安装
- 路径只能来自候选 cwd、用户输入中的显式路径，或用 pwd/find/cd 这类可解释命令去发现
- 当前产品只进入 Claude，请优先以 claude 作为最后一步
输入:
${jsonEncode(payload)}
''';
  }

  String? _extractJsonBlock(String? raw) {
    final normalized = PlannerIntentUtils.normalizeString(raw);
    if (normalized == null) {
      return null;
    }
    if (normalized.startsWith('{') && normalized.endsWith('}')) {
      return normalized;
    }
    final fenced =
        RegExp(r'```(?:json)?\s*(\{[\s\S]*\})\s*```').firstMatch(normalized);
    if (fenced != null) {
      return fenced.group(1);
    }
    final start = normalized.indexOf('{');
    final end = normalized.lastIndexOf('}');
    if (start >= 0 && end > start) {
      return normalized.substring(start, end + 1);
    }
    return null;
  }

  bool _isDangerousCommand(String command) {
    final normalized = command.toLowerCase();
    const blockedPatterns = [
      'rm -rf /',
      'sudo ',
      'shutdown',
      'reboot',
      'mkfs',
      'dd if=',
      ':(){',
    ];
    for (final pattern in blockedPatterns) {
      if (normalized.contains(pattern)) {
        return true;
      }
    }
    return false;
  }

  ProjectContextCandidate? _resolveCandidate(
    List<ProjectContextCandidate> candidates,
    String? candidateId,
  ) {
    final normalizedId = PlannerIntentUtils.normalizeString(candidateId);
    if (normalizedId == null) {
      return null;
    }
    for (final candidate in candidates) {
      if (candidate.candidateId == normalizedId) {
        return candidate;
      }
    }
    return null;
  }

  String _deriveCwd(List<CommandSequenceStep> steps, String fallbackCwd) {
    for (var index = steps.length - 1; index >= 0; index--) {
      final command = steps[index].command.trim();
      if (!command.startsWith('cd ')) {
        continue;
      }
      final next = command.substring(3).trim();
      if (next.isNotEmpty) {
        return next;
      }
    }
    return fallbackCwd;
  }

  TerminalLaunchTool _inferTool(
    List<CommandSequenceStep> steps,
    TerminalLaunchTool fallbackTool,
  ) {
    for (var index = steps.length - 1; index >= 0; index--) {
      final command = steps[index].command.trim().toLowerCase();
      if (command == 'claude') {
        return TerminalLaunchTool.claudeCode;
      }
      if (command == 'codex') {
        return TerminalLaunchTool.codex;
      }
    }
    return fallbackTool;
  }

  bool _resolveNeedConfirm({
    required String cwd,
    required List<String> explicitPaths,
    required ProjectContextCandidate? matchedCandidate,
    required Object? payloadValue,
  }) {
    final payloadFlag = payloadValue as bool?;
    if (payloadFlag == true) {
      return true;
    }
    if (matchedCandidate != null &&
        PlannerIntentUtils.isPathWithin(cwd, matchedCandidate.cwd)) {
      return matchedCandidate.requiresConfirmation;
    }
    if (matchedCandidate != null) {
      return true;
    }
    for (final path in explicitPaths) {
      if (PlannerIntentUtils.samePath(cwd, path)) {
        return !PlannerIntentUtils.isExplicitPath(path);
      }
    }
    return !PlannerIntentUtils.isExplicitPath(cwd);
  }

  TerminalLaunchPlanSource _resolveSource(String? raw) {
    switch (raw) {
      case 'custom':
        return TerminalLaunchPlanSource.custom;
      case 'recommended':
        return TerminalLaunchPlanSource.recommended;
      case 'intent':
      default:
        return TerminalLaunchPlanSource.intent;
    }
  }

  String _buildSummary(TerminalLaunchTool tool, String cwd) {
    final target = TerminalLaunchPlanDefaults.titleFor(tool, cwd);
    return '创建终端后执行 $target';
  }
}
