import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

import '../models/project_context_snapshot.dart';
import '../models/terminal_launch_plan.dart';
import 'http_client_factory.dart';
import 'planner_credentials_service.dart';
import 'planner_provider.dart';

class LlmPlannerProvider extends PlannerProvider {
  LlmPlannerProvider({
    PlannerCredentialsService? credentialsService,
    http.Client? client,
    this.timeout = const Duration(seconds: 4),
    Uri Function(String endpointProfile)? endpointResolver,
    String? model,
  })  : _credentialsService =
            credentialsService ?? PlannerCredentialsService.shared,
        _client = client ?? HttpClientFactory.create(),
        _endpointResolver = endpointResolver ?? _defaultEndpointResolver,
        _model = model ?? _defaultModel;

  static const String _plannerBaseUrl = String.fromEnvironment(
    'PLANNER_API_BASE_URL',
    defaultValue: 'https://api.openai.com/v1',
  );
  static const String _defaultModel = String.fromEnvironment(
    'PLANNER_MODEL',
    defaultValue: 'gpt-4o-mini',
  );

  final PlannerCredentialsService _credentialsService;
  final http.Client _client;
  final Duration timeout;
  final Uri Function(String endpointProfile) _endpointResolver;
  final String _model;

  @override
  String get provider => 'llm';

  @override
  Future<PlannerResolutionResult?> resolve(
    PlannerResolutionRequest request,
  ) async {
    final deviceId = request.deviceId;
    if (deviceId == null || deviceId.isEmpty) {
      return null;
    }
    if (!request.plannerConfig.llmEnabled ||
        request.plannerConfig.provider != provider) {
      return null;
    }
    final apiKey = await _credentialsService.readApiKey(deviceId);
    if ((apiKey ?? '').trim().isEmpty) {
      return null;
    }
    if (request.candidates.isEmpty) {
      return null;
    }

    final response = await _client
        .post(
          _endpointResolver(request.plannerConfig.endpointProfile),
          headers: {
            'Authorization': 'Bearer ${apiKey!.trim()}',
            'Content-Type': 'application/json',
          },
          body: jsonEncode({
            'model': _model,
            'temperature': 0,
            'response_format': const {'type': 'json_object'},
            'messages': [
              {
                'role': 'system',
                'content': '''
You are a constrained terminal planner.
Return JSON only.
Choose only from provided candidates or an explicit user path already present in the intent.
Schema: {"tool":"claude_code|codex|shell","matched_candidate_id":"string|null","cwd":"string|null","reasoning_kind":"candidate_match|explicit_input"}.
''',
              },
              {
                'role': 'user',
                'content': jsonEncode({
                  'intent': request.normalizedIntent,
                  'recent_context': request.recentContext == null
                      ? null
                      : {
                          'last_tool': TerminalLaunchToolCodec.toJson(
                            request.recentContext!.lastTool,
                          ),
                          'last_cwd': request.recentContext!.lastCwd,
                          'last_successful_plan': request
                              .recentContext!.lastSuccessfulPlan
                              .toJson(),
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
                }),
              },
            ],
          }),
        )
        .timeout(timeout);

    if (response.statusCode < 200 || response.statusCode >= 300) {
      return null;
    }

    final payload = jsonDecode(response.body);
    if (payload is! Map<String, dynamic>) {
      return null;
    }
    final choices = payload['choices'];
    if (choices is! List || choices.isEmpty) {
      return null;
    }
    final firstChoice = choices.first;
    if (firstChoice is! Map<String, dynamic>) {
      return null;
    }
    final message = firstChoice['message'];
    if (message is! Map<String, dynamic>) {
      return null;
    }
    final content = _extractMessageContent(message['content']);
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
    final tool = TerminalLaunchToolCodec.fromJson(
          payload['tool'] as String?,
        ) ??
        request.fallbackPlan.tool;
    final matchedCandidate = _candidateById(
      request.candidates,
      payload['matched_candidate_id'] as String?,
    );
    final returnedCwd =
        PlannerIntentUtils.normalizeString(payload['cwd'] as String?);
    final explicitPaths =
        PlannerIntentUtils.extractExplicitPaths(request.normalizedIntent);

    var resolvedCwd = matchedCandidate?.cwd;
    var matchedCandidateId = matchedCandidate?.candidateId;
    var requiresManualConfirmation =
        matchedCandidate?.requiresConfirmation ?? false;
    var reasoningKind = PlannerIntentUtils.normalizeString(
          payload['reasoning_kind'] as String?,
        ) ??
        (matchedCandidate != null ? 'candidate_match' : 'explicit_input');
    var confidence = matchedCandidate != null
        ? TerminalLaunchConfidence.high
        : TerminalLaunchConfidence.medium;

    if (returnedCwd != null) {
      if (matchedCandidate != null &&
          PlannerIntentUtils.isPathWithin(returnedCwd, matchedCandidate.cwd)) {
        resolvedCwd = returnedCwd;
      } else if (_matchesExplicitPath(returnedCwd, explicitPaths)) {
        resolvedCwd = returnedCwd;
        matchedCandidateId = null;
        reasoningKind = 'explicit_input';
        confidence = PlannerIntentUtils.isExplicitPath(returnedCwd)
            ? TerminalLaunchConfidence.high
            : TerminalLaunchConfidence.medium;
        requiresManualConfirmation =
            !PlannerIntentUtils.isExplicitPath(returnedCwd);
      } else {
        resolvedCwd = returnedCwd;
        matchedCandidateId = null;
        reasoningKind = 'manual_confirmation';
        confidence = TerminalLaunchConfidence.low;
        requiresManualConfirmation = true;
      }
    }

    if (PlannerIntentUtils.normalizeString(resolvedCwd) == null) {
      return null;
    }

    final defaults = TerminalLaunchPlanDefaults.forTool(tool);
    return PlannerResolutionResult(
      provider: provider,
      matchedCandidateId: matchedCandidateId,
      reasoningKind: reasoningKind,
      plan: TerminalLaunchPlan(
        tool: tool,
        title: TerminalLaunchPlanDefaults.titleFor(tool, resolvedCwd!),
        cwd: resolvedCwd,
        command: defaults.command,
        entryStrategy: defaults.entryStrategy,
        postCreateInput: defaults.postCreateInput,
        source: TerminalLaunchPlanSource.intent,
        intent: request.normalizedIntent,
        confidence: confidence,
        requiresManualConfirmation: requiresManualConfirmation,
      ),
    );
  }

  ProjectContextCandidate? _candidateById(
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

  bool _matchesExplicitPath(String returnedCwd, List<String> explicitPaths) {
    for (final path in explicitPaths) {
      if (PlannerIntentUtils.samePath(returnedCwd, path)) {
        return true;
      }
    }
    return false;
  }

  String? _extractMessageContent(Object? rawContent) {
    if (rawContent is String) {
      final normalized = PlannerIntentUtils.normalizeString(rawContent);
      return normalized;
    }
    if (rawContent is List) {
      final buffer = StringBuffer();
      for (final item in rawContent) {
        if (item is! Map<String, dynamic>) {
          continue;
        }
        final text = item['text'] as String?;
        if (text != null) {
          buffer.write(text);
        }
      }
      return PlannerIntentUtils.normalizeString(buffer.toString());
    }
    return null;
  }

  static Uri _defaultEndpointResolver(String endpointProfile) {
    switch (endpointProfile) {
      case 'openai_compatible':
      default:
        return Uri.parse('$_plannerBaseUrl/chat/completions');
    }
  }
}
