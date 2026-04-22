import '../../models/terminal_launch_plan.dart';
import 'planner_provider.dart';

class LocalRulesCommandPlanner extends PlannerProvider {
  const LocalRulesCommandPlanner({
    this.defaultCwd = '~',
  });

  final String defaultCwd;

  @override
  String get provider => 'local_rules';

  @override
  Future<PlannerResolutionResult?> resolve(
    PlannerResolutionRequest request,
  ) async {
    final detectedTool =
        PlannerIntentUtils.detectTool(request.normalizedIntent);
    final pathHint =
        PlannerIntentUtils.extractPathHint(request.normalizedIntent);
    final tool = detectedTool ?? request.fallbackPlan.tool;
    final cwd = pathHint?.cwd ?? request.fallbackPlan.cwd;
    final usesFallback = detectedTool == null && pathHint == null;
    final confidence = PlannerIntentUtils.resolveLocalIntentConfidence(
      hasExplicitTool: detectedTool != null,
      pathHint: pathHint,
      usesFallback: usesFallback,
    );
    final reasoningKind = switch ((detectedTool != null, pathHint != null)) {
      (true, true) => 'tool_and_path_hint',
      (true, false) => 'tool_hint',
      (false, true) => 'path_hint',
      (false, false) => 'fallback',
    };

    final defaults = TerminalLaunchPlanDefaults.forTool(tool);
    final normalizedCwd =
        PlannerIntentUtils.normalizeCwd(cwd, defaultCwd: defaultCwd);
    final plan = TerminalLaunchPlan(
      tool: tool,
      title: TerminalLaunchPlanDefaults.titleFor(tool, normalizedCwd),
      cwd: normalizedCwd,
      command: defaults.command,
      entryStrategy: defaults.entryStrategy,
      postCreateInput: defaults.postCreateInput,
      source: TerminalLaunchPlanSource.intent,
      intent: request.normalizedIntent,
      confidence: confidence,
      requiresManualConfirmation: pathHint?.requiresManualConfirmation ?? false,
    );
    return PlannerResolutionResult(
      provider: provider,
      matchedCandidateId: PlannerIntentUtils.candidateIdForCwd(
        request.candidates,
        normalizedCwd,
      ),
      plan: plan,
      sequence: PlannerIntentUtils.sequenceFromPlan(
        plan,
        provider: provider,
      ),
      reasoningKind: reasoningKind,
    );
  }
}
