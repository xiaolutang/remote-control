import '../../models/assistant_plan.dart';
import '../../models/command_sequence_draft.dart';
import '../../models/project_context_settings.dart';
import '../../models/project_context_snapshot.dart';
import '../../models/recent_launch_context.dart';
import '../../models/terminal_launch_plan.dart';

class PlannerResolutionRequest {
  const PlannerResolutionRequest({
    required this.deviceId,
    required this.intent,
    required this.normalizedIntent,
    required this.fallbackPlan,
    required this.candidates,
    required this.plannerConfig,
    this.recentContext,
  });

  final String? deviceId;
  final String intent;
  final String normalizedIntent;
  final TerminalLaunchPlan fallbackPlan;
  final List<ProjectContextCandidate> candidates;
  final PlannerRuntimeConfigModel plannerConfig;
  final RecentLaunchContext? recentContext;
}

class PlannerResolutionResult {
  const PlannerResolutionResult({
    required this.provider,
    required this.plan,
    required this.reasoningKind,
    this.sequence,
    this.matchedCandidateId,
    this.fallbackUsed = false,
    this.fallbackReason,
    this.assistantMessages = const [],
    this.trace = const [],
    this.conversationId,
    this.messageId,
    this.limits,
    this.evaluationContext = const <String, dynamic>{},
  });

  final String provider;
  final TerminalLaunchPlan plan;
  final String reasoningKind;
  final CommandSequenceDraft? sequence;
  final String? matchedCandidateId;
  final bool fallbackUsed;
  final String? fallbackReason;
  final List<AssistantMessage> assistantMessages;
  final List<AssistantTraceItem> trace;
  final String? conversationId;
  final String? messageId;
  final AssistantPlanLimits? limits;
  final Map<String, dynamic> evaluationContext;

  PlannerResolutionResult copyWith({
    String? provider,
    TerminalLaunchPlan? plan,
    String? reasoningKind,
    CommandSequenceDraft? sequence,
    bool clearSequence = false,
    String? matchedCandidateId,
    bool clearMatchedCandidateId = false,
    bool? fallbackUsed,
    String? fallbackReason,
    bool clearFallbackReason = false,
    List<AssistantMessage>? assistantMessages,
    List<AssistantTraceItem>? trace,
    String? conversationId,
    bool clearConversationId = false,
    String? messageId,
    bool clearMessageId = false,
    AssistantPlanLimits? limits,
    bool clearLimits = false,
    Map<String, dynamic>? evaluationContext,
  }) {
    return PlannerResolutionResult(
      provider: provider ?? this.provider,
      plan: plan ?? this.plan,
      reasoningKind: reasoningKind ?? this.reasoningKind,
      sequence: clearSequence ? null : (sequence ?? this.sequence),
      matchedCandidateId: clearMatchedCandidateId
          ? null
          : (matchedCandidateId ?? this.matchedCandidateId),
      fallbackUsed: fallbackUsed ?? this.fallbackUsed,
      fallbackReason:
          clearFallbackReason ? null : (fallbackReason ?? this.fallbackReason),
      assistantMessages: assistantMessages ?? this.assistantMessages,
      trace: trace ?? this.trace,
      conversationId:
          clearConversationId ? null : (conversationId ?? this.conversationId),
      messageId: clearMessageId ? null : (messageId ?? this.messageId),
      limits: clearLimits ? null : (limits ?? this.limits),
      evaluationContext: evaluationContext ?? this.evaluationContext,
    );
  }
}

abstract class PlannerProvider {
  const PlannerProvider();

  String get provider;

  Future<PlannerResolutionResult?> resolve(PlannerResolutionRequest request);
}

class PlannerPathHint {
  const PlannerPathHint({
    required this.cwd,
    required this.requiresManualConfirmation,
  });

  final String? cwd;
  final bool requiresManualConfirmation;
}

class PlannerIntentUtils {
  PlannerIntentUtils._();

  static final RegExp _explicitPathPattern = RegExp(
    r'''(`[^`]+`|"[^"]+"|'[^']+'|~\/[^\s]+|\/[^\s]+|\.\.?\/[^\s]+|[A-Za-z0-9._-]+\/[A-Za-z0-9._\/-]+)''',
  );

  static String? normalizeIntent(String? intent) {
    final trimmed = intent?.trim();
    if (trimmed == null || trimmed.isEmpty) {
      return null;
    }
    final collapsed = trimmed
        .replaceAll(RegExp(r'[\r\n\t]+'), ' ')
        .replaceAll(RegExp(r'\s+'), ' ')
        .trim();
    if (collapsed.isEmpty) {
      return null;
    }
    return collapsed.length <= 280 ? collapsed : collapsed.substring(0, 280);
  }

  static String? normalizeString(String? value) {
    final trimmed = value?.trim();
    if (trimmed == null || trimmed.isEmpty) {
      return null;
    }
    return trimmed;
  }

  static String normalizeCwd(String cwd, {String defaultCwd = '~'}) {
    return normalizeString(cwd) ?? defaultCwd;
  }

  static TerminalLaunchTool? detectTool(String intent) {
    final normalized = intent.toLowerCase();
    final matches = <_ToolMatch>[
      ..._matchKeywords(normalized, TerminalLaunchTool.claudeCode, const [
        'claude code',
        'claude',
      ]),
      ..._matchKeywords(normalized, TerminalLaunchTool.codex, const ['codex']),
      ..._matchKeywords(normalized, TerminalLaunchTool.shell, const [
        'shell',
        'terminal',
        'bash',
        'zsh',
        '终端',
        '命令行',
        '跑命令',
      ]),
    ]..sort((a, b) => a.index.compareTo(b.index));
    if (matches.isEmpty) {
      return null;
    }
    return matches.first.tool;
  }

  static PlannerPathHint? extractPathHint(String intent) {
    for (final match in _explicitPathPattern.allMatches(intent)) {
      final raw = match.group(0);
      final candidate = sanitizePathCandidate(raw);
      if (candidate == null) {
        continue;
      }
      return PlannerPathHint(
        cwd: candidate,
        requiresManualConfirmation: !isExplicitPath(candidate),
      );
    }

    final currentProjectPattern = RegExp(
      r'(当前项目|this project)',
      caseSensitive: false,
    );
    if (currentProjectPattern.hasMatch(intent)) {
      return const PlannerPathHint(
        cwd: null,
        requiresManualConfirmation: false,
      );
    }
    return null;
  }

  static List<String> extractExplicitPaths(String intent) {
    final paths = <String>[];
    for (final match in _explicitPathPattern.allMatches(intent)) {
      final candidate = sanitizePathCandidate(match.group(0));
      if (candidate != null) {
        paths.add(candidate);
      }
    }
    return List.unmodifiable(paths);
  }

  static String? sanitizePathCandidate(String? raw) {
    if (raw == null) {
      return null;
    }
    var candidate = raw.trim();
    if (candidate.startsWith('`') &&
        candidate.endsWith('`') &&
        candidate.length > 1) {
      candidate = candidate.substring(1, candidate.length - 1);
    }
    if (candidate.startsWith('"') &&
        candidate.endsWith('"') &&
        candidate.length > 1) {
      candidate = candidate.substring(1, candidate.length - 1);
    }
    if (candidate.startsWith('\'') &&
        candidate.endsWith('\'') &&
        candidate.length > 1) {
      candidate = candidate.substring(1, candidate.length - 1);
    }
    candidate = candidate.replaceAll(RegExp(r'[),.;:!?]+$'), '');
    return normalizeString(candidate);
  }

  static bool isExplicitPath(String path) {
    return path.startsWith('/') ||
        path.startsWith('~/') ||
        path.startsWith('./') ||
        path.startsWith('../');
  }

  static bool samePath(String left, String right) {
    return _canonicalizePath(left) == _canonicalizePath(right);
  }

  static bool isPathWithin(String child, String parent) {
    final normalizedChild = _canonicalizePath(child);
    final normalizedParent = _canonicalizePath(parent);
    if (normalizedChild == normalizedParent) {
      return true;
    }
    if (normalizedParent == '/') {
      return normalizedChild.startsWith('/');
    }
    return normalizedChild.startsWith('$normalizedParent/');
  }

  static TerminalLaunchConfidence resolveLocalIntentConfidence({
    required bool hasExplicitTool,
    required PlannerPathHint? pathHint,
    required bool usesFallback,
  }) {
    if (pathHint != null && pathHint.requiresManualConfirmation) {
      return TerminalLaunchConfidence.low;
    }
    if (hasExplicitTool && pathHint != null) {
      return TerminalLaunchConfidence.high;
    }
    if (hasExplicitTool) {
      return TerminalLaunchConfidence.medium;
    }
    if (usesFallback) {
      return TerminalLaunchConfidence.low;
    }
    return TerminalLaunchConfidence.medium;
  }

  static String? candidateIdForCwd(
    List<ProjectContextCandidate> candidates,
    String? cwd,
  ) {
    final normalizedCwd = normalizeString(cwd);
    if (normalizedCwd == null) {
      return null;
    }
    ProjectContextCandidate? matched;
    for (final candidate in candidates) {
      if (!isPathWithin(normalizedCwd, candidate.cwd)) {
        continue;
      }
      if (matched == null ||
          _canonicalizePath(candidate.cwd).length >
              _canonicalizePath(matched.cwd).length) {
        matched = candidate;
      }
    }
    return matched?.candidateId;
  }

  static CommandSequenceDraft sequenceFromPlan(
    TerminalLaunchPlan plan, {
    required String provider,
  }) {
    return CommandSequenceDraft.fromLaunchPlan(
      plan,
      provider: provider,
    );
  }

  static String _canonicalizePath(String value) {
    var normalized = value.trim().replaceAll('\\', '/');
    if (normalized.isEmpty) {
      return normalized;
    }
    while (normalized.length > 1 && normalized.endsWith('/')) {
      normalized = normalized.substring(0, normalized.length - 1);
    }
    return normalized;
  }

  static List<_ToolMatch> _matchKeywords(
    String intent,
    TerminalLaunchTool tool,
    List<String> keywords,
  ) {
    final matches = <_ToolMatch>[];
    for (final keyword in keywords) {
      final index = intent.indexOf(keyword);
      if (index >= 0) {
        matches.add(_ToolMatch(tool: tool, index: index));
      }
    }
    return matches;
  }
}

class _ToolMatch {
  const _ToolMatch({
    required this.tool,
    required this.index,
  });

  final TerminalLaunchTool tool;
  final int index;
}
