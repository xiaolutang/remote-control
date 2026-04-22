import '../../models/command_sequence_draft.dart';
import '../../models/terminal_launch_plan.dart';
import 'planner_provider.dart';

class PlannerCoordinator {
  PlannerCoordinator({
    required PlannerProvider claudeCliPlanner,
  }) : _claudeCliPlanner = claudeCliPlanner;

  final PlannerProvider _claudeCliPlanner;

  Future<PlannerResolutionResult> resolve(
    PlannerResolutionRequest request, {
    required PlannerResolutionResult localFallback,
  }) async {
    if (!_shouldUseClaudeCli(request)) {
      return localFallback;
    }

    try {
      final result = await _claudeCliPlanner.resolve(request);
      if (result == null) {
        return _withFallback(localFallback, reason: 'claude_cli_unavailable');
      }
      final sequence = result.sequence;
      if (sequence == null || !_isValidSequence(sequence)) {
        return _withFallback(localFallback, reason: 'claude_cli_invalid');
      }
      return result;
    } catch (_) {
      return _withFallback(localFallback, reason: 'claude_cli_failed');
    }
  }

  bool _shouldUseClaudeCli(PlannerResolutionRequest request) {
    return request.plannerConfig.llmEnabled &&
        (request.plannerConfig.provider == 'claude_cli' ||
            request.plannerConfig.provider == 'llm');
  }

  bool _isValidSequence(CommandSequenceDraft sequence) {
    if (sequence.steps.isEmpty) {
      return false;
    }
    for (final step in sequence.steps) {
      if (step.command.trim().isEmpty) {
        return false;
      }
    }
    return true;
  }

  PlannerResolutionResult _withFallback(
    PlannerResolutionResult localFallback, {
    required String reason,
  }) {
    final fallbackPlan = localFallback.plan.copyWith(
      source: TerminalLaunchPlanSource.intent,
    );
    return localFallback.copyWith(
      plan: fallbackPlan,
      sequence: PlannerIntentUtils.sequenceFromPlan(
        fallbackPlan,
        provider: localFallback.provider,
      ),
      fallbackUsed: true,
      fallbackReason: reason,
      reasoningKind: 'fallback',
    );
  }
}
