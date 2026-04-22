import '../models/project_context_settings.dart';
import '../models/project_context_snapshot.dart';
import '../models/recent_launch_context.dart';
import '../models/runtime_terminal.dart';
import '../models/terminal_launch_plan.dart';
import 'llm_planner_provider.dart';
import 'local_rules_planner_provider.dart';
import 'planner_provider.dart';

class TerminalLaunchPlanService {
  TerminalLaunchPlanService({
    this.defaultCwd = '~',
    DateTime Function()? clock,
    PlannerProvider? localRulesPlannerProvider,
    PlannerProvider? llmPlannerProvider,
  })  : _clock = clock ?? _systemClock,
        _localRulesPlannerProvider = localRulesPlannerProvider ??
            LocalRulesPlannerProvider(defaultCwd: defaultCwd),
        _llmPlannerProvider = llmPlannerProvider ?? LlmPlannerProvider();

  final String defaultCwd;
  final DateTime Function() _clock;
  final PlannerProvider _localRulesPlannerProvider;
  final PlannerProvider _llmPlannerProvider;

  List<TerminalLaunchPlan> buildRecommendedPlans({
    required String? deviceId,
    required List<RuntimeTerminal> terminals,
    RecentLaunchContext? recentContext,
    DeviceProjectContextSnapshot? projectContextSnapshot,
  }) {
    final scopedContext = _scopeToDevice(deviceId, recentContext);
    final scopedSnapshot =
        _scopeSnapshotToDevice(deviceId, projectContextSnapshot);
    final candidate = _selectBestCandidate(
      scopedSnapshot?.candidates ?? const [],
      context: scopedContext,
    );
    final cwd = _resolveCwd(terminals, scopedContext, candidate);
    final primaryTool = _resolvePrimaryTool(
      context: scopedContext,
      candidate: candidate,
    );
    final tools = _orderedTools(primaryTool);

    return List.unmodifiable([
      for (var index = 0; index < tools.length; index++)
        _buildPlanForTool(
          tools[index],
          cwd: cwd,
          context: scopedContext,
          isPrimary: index == 0,
          candidate: candidate,
        ),
    ]);
  }

  ProjectContextCandidate? resolveCandidateForCwd({
    required String? deviceId,
    required DeviceProjectContextSnapshot? projectContextSnapshot,
    required String? cwd,
  }) {
    final scopedSnapshot =
        _scopeSnapshotToDevice(deviceId, projectContextSnapshot);
    final matchedId = PlannerIntentUtils.candidateIdForCwd(
      scopedSnapshot?.candidates ?? const [],
      cwd,
    );
    if (matchedId == null) {
      return null;
    }
    for (final candidate in scopedSnapshot?.candidates ?? const []) {
      if (candidate.candidateId == matchedId) {
        return candidate;
      }
    }
    return null;
  }

  bool requiresManualConfirmationForCwd({
    required String cwd,
    required String? deviceId,
    required DeviceProjectContextSnapshot? projectContextSnapshot,
    String? currentCwd,
    bool currentRequiresManualConfirmation = false,
  }) {
    final normalizedCwd = PlannerIntentUtils.normalizeString(cwd);
    if (normalizedCwd == null || normalizedCwd == '~' || normalizedCwd == '/') {
      return false;
    }

    final normalizedCurrentCwd = PlannerIntentUtils.normalizeString(currentCwd);
    if (normalizedCurrentCwd != null &&
        PlannerIntentUtils.samePath(normalizedCwd, normalizedCurrentCwd)) {
      return currentRequiresManualConfirmation;
    }

    final candidate = resolveCandidateForCwd(
      deviceId: deviceId,
      projectContextSnapshot: projectContextSnapshot,
      cwd: normalizedCwd,
    );
    if (candidate != null) {
      return candidate.requiresConfirmation;
    }
    if (PlannerIntentUtils.isExplicitPath(normalizedCwd)) {
      return false;
    }
    return true;
  }

  Future<PlannerResolutionResult> resolveIntent({
    required String intent,
    required String? deviceId,
    required List<RuntimeTerminal> terminals,
    RecentLaunchContext? recentContext,
    DeviceProjectContextSnapshot? projectContextSnapshot,
    ProjectContextSettings? projectContextSettings,
  }) async {
    final fallback = buildRecommendedPlans(
      deviceId: deviceId,
      terminals: terminals,
      recentContext: recentContext,
      projectContextSnapshot: projectContextSnapshot,
    ).first;
    final normalizedIntent = PlannerIntentUtils.normalizeIntent(intent);
    if (normalizedIntent == null) {
      return PlannerResolutionResult(
        provider: 'local_rules',
        plan: fallback,
        reasoningKind: 'empty_intent',
      );
    }
    final scopedContext = _scopeToDevice(deviceId, recentContext);
    final scopedSnapshot =
        _scopeSnapshotToDevice(deviceId, projectContextSnapshot);
    final scopedSettings =
        _scopeSettingsToDevice(deviceId, projectContextSettings);
    final localFallback = _buildFallbackIntentPlan(
      fallback: fallback,
      normalizedIntent: normalizedIntent,
    );
    final request = PlannerResolutionRequest(
      deviceId: PlannerIntentUtils.normalizeString(deviceId),
      intent: intent,
      normalizedIntent: normalizedIntent,
      fallbackPlan: fallback,
      candidates: scopedSnapshot?.candidates ?? const [],
      plannerConfig:
          scopedSettings?.plannerConfig ?? const PlannerRuntimeConfigModel(),
      recentContext: scopedContext,
    );

    final localResult = await _localRulesPlannerProvider.resolve(request) ??
        PlannerResolutionResult(
          provider: 'local_rules',
          plan: localFallback,
          reasoningKind: 'fallback',
        );
    final providerResult = await _resolvePreferredProvider(
      request,
      localFallback: localResult,
    );
    return PlannerResolutionResult(
      provider: providerResult.provider,
      matchedCandidateId: providerResult.matchedCandidateId,
      reasoningKind: providerResult.reasoningKind,
      plan: normalizePlan(providerResult.plan),
    );
  }

  Future<TerminalLaunchPlan> resolvePlanFromIntent({
    required String intent,
    required String? deviceId,
    required List<RuntimeTerminal> terminals,
    RecentLaunchContext? recentContext,
    DeviceProjectContextSnapshot? projectContextSnapshot,
    ProjectContextSettings? projectContextSettings,
  }) async {
    final result = await resolveIntent(
      intent: intent,
      deviceId: deviceId,
      terminals: terminals,
      recentContext: recentContext,
      projectContextSnapshot: projectContextSnapshot,
      projectContextSettings: projectContextSettings,
    );
    return result.plan;
  }

  TerminalLaunchPlan normalizePlan(TerminalLaunchPlan plan) {
    final cwd = _normalizeCwd(plan.cwd);
    final defaults = TerminalLaunchPlanDefaults.forTool(plan.tool);
    return plan.copyWith(
      title: plan.title.trim().isEmpty
          ? TerminalLaunchPlanDefaults.titleFor(plan.tool, cwd)
          : plan.title.trim(),
      cwd: cwd,
      command: plan.command.trim().isEmpty ? defaults.command : plan.command,
      entryStrategy: plan.entryStrategy,
      postCreateInput: plan.postCreateInput.isEmpty
          ? defaults.postCreateInput
          : plan.postCreateInput,
      source: plan.source,
      confidence: plan.confidence,
      requiresManualConfirmation: plan.requiresManualConfirmation,
    );
  }

  TerminalLaunchPlan finalizePlan({
    required TerminalLaunchPlan plan,
    required String? deviceId,
    required DeviceProjectContextSnapshot? projectContextSnapshot,
  }) {
    final normalizedPlan = normalizePlan(plan);
    final requiresManualConfirmation =
        normalizedPlan.requiresManualConfirmation ||
            requiresManualConfirmationForCwd(
              cwd: normalizedPlan.cwd,
              deviceId: deviceId,
              projectContextSnapshot: projectContextSnapshot,
            );
    return normalizedPlan.copyWith(
      requiresManualConfirmation: requiresManualConfirmation,
    );
  }

  RecentLaunchContext buildRecentLaunchContext({
    required String deviceId,
    required TerminalLaunchPlan plan,
  }) {
    final normalizedPlan = normalizePlan(plan);

    return RecentLaunchContext(
      deviceId: deviceId,
      lastTool: normalizedPlan.tool,
      lastCwd: normalizedPlan.cwd,
      lastSuccessfulPlan: normalizedPlan,
      updatedAt: _clock(),
    );
  }

  TerminalLaunchPlan _buildPlanForTool(
    TerminalLaunchTool tool, {
    required String cwd,
    required RecentLaunchContext? context,
    required bool isPrimary,
    required ProjectContextCandidate? candidate,
  }) {
    final defaults = TerminalLaunchPlanDefaults.forTool(tool);
    final recentPlan = context?.lastSuccessfulPlan;
    if (recentPlan != null && recentPlan.tool == tool) {
      final recentCwd = PlannerIntentUtils.normalizeString(recentPlan.cwd);
      return recentPlan.copyWith(
        title: recentPlan.title.trim().isEmpty
            ? TerminalLaunchPlanDefaults.titleFor(tool, cwd)
            : recentPlan.title.trim(),
        cwd: recentCwd ?? cwd,
        command: recentPlan.command.trim().isEmpty
            ? defaults.command
            : recentPlan.command,
        entryStrategy: recentPlan.entryStrategy,
        postCreateInput: recentPlan.postCreateInput.isEmpty
            ? defaults.postCreateInput
            : recentPlan.postCreateInput,
        source: TerminalLaunchPlanSource.recommended,
        clearIntent: true,
        confidence: TerminalLaunchConfidence.high,
        requiresManualConfirmation: false,
      );
    }

    return TerminalLaunchPlan(
      tool: tool,
      title: TerminalLaunchPlanDefaults.titleFor(tool, cwd),
      cwd: cwd,
      command: defaults.command,
      entryStrategy: defaults.entryStrategy,
      postCreateInput: defaults.postCreateInput,
      source: TerminalLaunchPlanSource.recommended,
      confidence: isPrimary
          ? TerminalLaunchConfidence.high
          : TerminalLaunchConfidence.medium,
      requiresManualConfirmation: candidate?.requiresConfirmation ?? false,
    );
  }

  RecentLaunchContext? _scopeToDevice(
    String? deviceId,
    RecentLaunchContext? recentContext,
  ) {
    final normalizedDeviceId = PlannerIntentUtils.normalizeString(deviceId);
    if (normalizedDeviceId == null || recentContext == null) {
      return null;
    }
    if (recentContext.deviceId != normalizedDeviceId) {
      return null;
    }
    return recentContext;
  }

  String _resolveCwd(
    List<RuntimeTerminal> terminals,
    RecentLaunchContext? recentContext,
    ProjectContextCandidate? candidate,
  ) {
    final recentPlanCwd = PlannerIntentUtils.normalizeString(
        recentContext?.lastSuccessfulPlan.cwd);
    if (recentPlanCwd != null) {
      return recentPlanCwd;
    }
    final recentCwd =
        PlannerIntentUtils.normalizeString(recentContext?.lastCwd);
    if (recentCwd != null) {
      return recentCwd;
    }
    final candidateCwd = PlannerIntentUtils.normalizeString(candidate?.cwd);
    if (candidateCwd != null) {
      return candidateCwd;
    }

    final terminal = _recentTerminalWithCwd(terminals);
    final terminalCwd = PlannerIntentUtils.normalizeString(terminal?.cwd);
    if (terminalCwd != null) {
      return terminalCwd;
    }
    return defaultCwd;
  }

  RuntimeTerminal? _recentTerminalWithCwd(List<RuntimeTerminal> terminals) {
    RuntimeTerminal? best;
    for (final terminal in terminals) {
      if (PlannerIntentUtils.normalizeString(terminal.cwd) == null) {
        continue;
      }
      if (best == null) {
        best = terminal;
        continue;
      }
      final currentUpdated = terminal.updatedAt;
      final bestUpdated = best.updatedAt;
      if (currentUpdated != null && bestUpdated != null) {
        if (currentUpdated.isAfter(bestUpdated)) {
          best = terminal;
        }
        continue;
      }
      if (currentUpdated != null && bestUpdated == null) {
        best = terminal;
      }
    }
    return best;
  }

  List<TerminalLaunchTool> _orderedTools(TerminalLaunchTool primaryTool) {
    final effectivePrimaryTool = primaryTool == TerminalLaunchTool.custom
        ? TerminalLaunchTool.shell
        : primaryTool;
    final remaining = <TerminalLaunchTool>[
      TerminalLaunchTool.shell,
      TerminalLaunchTool.claudeCode,
      TerminalLaunchTool.codex,
    ]..remove(effectivePrimaryTool);
    return [effectivePrimaryTool, ...remaining];
  }

  DeviceProjectContextSnapshot? _scopeSnapshotToDevice(
    String? deviceId,
    DeviceProjectContextSnapshot? snapshot,
  ) {
    final normalizedDeviceId = PlannerIntentUtils.normalizeString(deviceId);
    if (normalizedDeviceId == null || snapshot == null) {
      return null;
    }
    if (snapshot.deviceId != normalizedDeviceId) {
      return null;
    }
    return snapshot;
  }

  ProjectContextSettings? _scopeSettingsToDevice(
    String? deviceId,
    ProjectContextSettings? settings,
  ) {
    final normalizedDeviceId = PlannerIntentUtils.normalizeString(deviceId);
    if (normalizedDeviceId == null || settings == null) {
      return null;
    }
    if (settings.deviceId != normalizedDeviceId) {
      return null;
    }
    return settings;
  }

  ProjectContextCandidate? _selectBestCandidate(
    List<ProjectContextCandidate> candidates, {
    required RecentLaunchContext? context,
  }) {
    if (candidates.isEmpty) {
      return null;
    }
    ProjectContextCandidate? best;
    var bestScore = -1;
    for (final candidate in candidates) {
      final score = _candidateScore(candidate, context);
      if (best == null || score > bestScore) {
        best = candidate;
        bestScore = score;
      }
    }
    return best;
  }

  int _candidateScore(
    ProjectContextCandidate candidate,
    RecentLaunchContext? context,
  ) {
    var score = switch (candidate.source) {
      'pinned_project' => 400,
      'recent_terminal' => 300,
      'approved_scan' => 200,
      _ => 100,
    };
    final lastPlanCwd =
        PlannerIntentUtils.normalizeString(context?.lastSuccessfulPlan.cwd);
    final lastCwd = PlannerIntentUtils.normalizeString(context?.lastCwd);
    if (lastPlanCwd != null && lastPlanCwd == candidate.cwd) {
      score += 100;
    }
    if (lastCwd != null && lastCwd == candidate.cwd) {
      score += 40;
    }
    if (context != null &&
        candidate.toolHints.contains(_toolHintFor(context.lastTool))) {
      score += 20;
    }
    final timestamp = candidate.updatedAt ?? candidate.lastUsedAt;
    if (timestamp != null) {
      score += timestamp.millisecondsSinceEpoch ~/ 1000000;
    }
    return score;
  }

  TerminalLaunchTool _resolvePrimaryTool({
    required RecentLaunchContext? context,
    required ProjectContextCandidate? candidate,
  }) {
    final contextTool = context?.lastSuccessfulPlan.tool ?? context?.lastTool;
    if (contextTool != null) {
      return contextTool;
    }
    for (final hint in candidate?.toolHints ?? const <String>[]) {
      switch (hint) {
        case 'claude_code':
          return TerminalLaunchTool.claudeCode;
        case 'codex':
          return TerminalLaunchTool.codex;
        case 'shell':
          return TerminalLaunchTool.shell;
      }
    }
    return TerminalLaunchTool.shell;
  }

  String _toolHintFor(TerminalLaunchTool tool) {
    switch (tool) {
      case TerminalLaunchTool.claudeCode:
        return 'claude_code';
      case TerminalLaunchTool.codex:
        return 'codex';
      case TerminalLaunchTool.shell:
      case TerminalLaunchTool.custom:
        return 'shell';
    }
  }

  String _normalizeCwd(String cwd) {
    return PlannerIntentUtils.normalizeCwd(cwd, defaultCwd: defaultCwd);
  }

  static DateTime _systemClock() => DateTime.now();

  Future<PlannerResolutionResult> _resolvePreferredProvider(
    PlannerResolutionRequest request, {
    required PlannerResolutionResult localFallback,
  }) async {
    if (request.plannerConfig.provider != 'llm' ||
        !request.plannerConfig.llmEnabled) {
      return localFallback;
    }
    try {
      return await _llmPlannerProvider.resolve(request) ?? localFallback;
    } catch (_) {
      return localFallback;
    }
  }

  TerminalLaunchPlan _buildFallbackIntentPlan({
    required TerminalLaunchPlan fallback,
    required String normalizedIntent,
  }) {
    return fallback.copyWith(
      source: TerminalLaunchPlanSource.intent,
      intent: normalizedIntent,
      confidence: TerminalLaunchConfidence.low,
      requiresManualConfirmation: false,
    );
  }
}
