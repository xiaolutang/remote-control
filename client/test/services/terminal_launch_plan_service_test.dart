import 'dart:convert';
import 'dart:io';

import 'package:rc_client/models/project_context_snapshot.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rc_client/models/project_context_settings.dart';
import 'package:rc_client/models/recent_launch_context.dart';
import 'package:rc_client/models/runtime_terminal.dart';
import 'package:rc_client/models/terminal_launch_plan.dart';
import 'package:rc_client/services/llm_planner_provider.dart';
import 'package:rc_client/services/terminal_launch_plan_service.dart';

void main() {
  group('TerminalLaunchPlanService', () {
    test('prioritizes recent claude context and preserves bootstrap fields',
        () {
      final service = TerminalLaunchPlanService(
        clock: () => DateTime.parse('2026-04-22T04:00:00Z'),
      );
      final recentContext = RecentLaunchContext(
        deviceId: 'dev-1',
        lastTool: TerminalLaunchTool.claudeCode,
        lastCwd: '/Users/demo/project/remote-control',
        lastSuccessfulPlan: const TerminalLaunchPlan(
          tool: TerminalLaunchTool.claudeCode,
          title: 'Claude / remote-control',
          cwd: '/Users/demo/project/remote-control',
          command: '/bin/bash',
          entryStrategy: TerminalEntryStrategy.shellBootstrap,
          postCreateInput: 'claude\n',
          source: TerminalLaunchPlanSource.intent,
          intent: '帮我进入 Claude 看项目',
          confidence: TerminalLaunchConfidence.low,
          requiresManualConfirmation: true,
        ),
        updatedAt: DateTime.parse('2026-04-22T03:59:00Z'),
      );

      final plans = service.buildRecommendedPlans(
        deviceId: 'dev-1',
        terminals: const [],
        recentContext: recentContext,
      );

      expect(
        plans.map((plan) => plan.tool).toList(),
        [
          TerminalLaunchTool.claudeCode,
          TerminalLaunchTool.shell,
          TerminalLaunchTool.codex,
        ],
      );
      expect(plans.first.cwd, '/Users/demo/project/remote-control');
      expect(plans.first.entryStrategy, TerminalEntryStrategy.shellBootstrap);
      expect(plans.first.postCreateInput, 'claude\n');
      expect(plans.first.source, TerminalLaunchPlanSource.recommended);
      expect(plans.first.intent, isNull);
      expect(plans.first.requiresManualConfirmation, isFalse);
    });

    test('falls back to closed terminal cwd when there is no recent context',
        () {
      final service = TerminalLaunchPlanService();
      final plans = service.buildRecommendedPlans(
        deviceId: 'dev-1',
        recentContext: null,
        terminals: [
          RuntimeTerminal(
            terminalId: 'older',
            title: 'Old shell',
            cwd: '/tmp/older',
            command: '/bin/bash',
            status: 'detached',
            views: const {'desktop': 0},
            updatedAt: DateTime.parse('2026-04-22T01:00:00Z'),
          ),
          RuntimeTerminal(
            terminalId: 'closed-new',
            title: 'Closed Claude',
            cwd: '/tmp/worktree',
            command: '/bin/bash',
            status: 'closed',
            views: const {'desktop': 0},
            updatedAt: DateTime.parse('2026-04-22T02:00:00Z'),
          ),
        ],
      );

      expect(plans.first.tool, TerminalLaunchTool.shell);
      expect(plans.first.cwd, '/tmp/worktree');
      expect(plans[1].title, 'Claude / worktree');
      expect(plans[2].postCreateInput, 'codex\n');
    });

    test('ignores recent context from another device', () {
      final service = TerminalLaunchPlanService();
      final recentContext = RecentLaunchContext(
        deviceId: 'dev-2',
        lastTool: TerminalLaunchTool.codex,
        lastCwd: '/tmp/another-device',
        lastSuccessfulPlan: const TerminalLaunchPlan(
          tool: TerminalLaunchTool.codex,
          title: 'Codex / another-device',
          cwd: '/tmp/another-device',
          command: '/bin/bash',
          entryStrategy: TerminalEntryStrategy.shellBootstrap,
          postCreateInput: 'codex\n',
          source: TerminalLaunchPlanSource.recommended,
        ),
        updatedAt: DateTime.parse('2026-04-22T03:00:00Z'),
      );

      final plans = service.buildRecommendedPlans(
        deviceId: 'dev-1',
        terminals: const [],
        recentContext: recentContext,
      );

      expect(plans.first.tool, TerminalLaunchTool.shell);
      expect(plans.first.cwd, '~');
    });

    test('prefers pinned project candidate when recent context is empty', () {
      final service = TerminalLaunchPlanService();

      final plans = service.buildRecommendedPlans(
        deviceId: 'dev-1',
        terminals: const [],
        recentContext: null,
        projectContextSnapshot: DeviceProjectContextSnapshot(
          deviceId: 'dev-1',
          generatedAt: DateTime.parse('2026-04-22T03:00:00Z'),
          candidates: const [
            ProjectContextCandidate(
              candidateId: 'cand-1',
              deviceId: 'dev-1',
              label: 'remote-control',
              cwd: '/Users/demo/project/remote-control',
              source: 'pinned_project',
              toolHints: ['claude_code', 'shell'],
            ),
            ProjectContextCandidate(
              candidateId: 'cand-2',
              deviceId: 'dev-1',
              label: 'tmp',
              cwd: '/tmp',
              source: 'recent_terminal',
              toolHints: ['shell'],
            ),
          ],
        ),
      );

      expect(plans.first.cwd, '/Users/demo/project/remote-control');
      expect(plans.first.tool, TerminalLaunchTool.claudeCode);
    });

    test('ignores project snapshot from another device', () {
      final service = TerminalLaunchPlanService();

      final plans = service.buildRecommendedPlans(
        deviceId: 'dev-1',
        terminals: const [],
        recentContext: null,
        projectContextSnapshot: DeviceProjectContextSnapshot(
          deviceId: 'dev-2',
          generatedAt: DateTime.parse('2026-04-22T03:00:00Z'),
          candidates: const [
            ProjectContextCandidate(
              candidateId: 'cand-1',
              deviceId: 'dev-2',
              label: 'other-device',
              cwd: '/tmp/other-device',
              source: 'pinned_project',
            ),
          ],
        ),
      );

      expect(plans.first.cwd, '~');
      expect(plans.first.tool, TerminalLaunchTool.shell);
    });

    test('buildRecentLaunchContext normalizes missing fields', () {
      final service = TerminalLaunchPlanService(
        clock: () => DateTime.parse('2026-04-22T05:00:00Z'),
      );

      final context = service.buildRecentLaunchContext(
        deviceId: 'dev-1',
        plan: const TerminalLaunchPlan(
          tool: TerminalLaunchTool.codex,
          title: '',
          cwd: '   ',
          command: '',
          entryStrategy: TerminalEntryStrategy.shellBootstrap,
          postCreateInput: '',
          source: TerminalLaunchPlanSource.custom,
        ),
      );

      expect(context.deviceId, 'dev-1');
      expect(context.lastTool, TerminalLaunchTool.codex);
      expect(context.lastCwd, '~');
      expect(context.lastSuccessfulPlan.title, 'Codex');
      expect(context.lastSuccessfulPlan.command, '/bin/bash');
      expect(context.lastSuccessfulPlan.postCreateInput, 'codex\n');
      expect(context.updatedAt, DateTime.parse('2026-04-22T05:00:00Z'));
    });

    test('recommended plans never surface custom as a top-level shortcut', () {
      final service = TerminalLaunchPlanService();
      final recentContext = RecentLaunchContext(
        deviceId: 'dev-1',
        lastTool: TerminalLaunchTool.custom,
        lastCwd: '/Users/demo/project/custom-runner',
        lastSuccessfulPlan: const TerminalLaunchPlan(
          tool: TerminalLaunchTool.custom,
          title: 'Custom Runner',
          cwd: '/Users/demo/project/custom-runner',
          command: '/bin/zsh',
          entryStrategy: TerminalEntryStrategy.directExec,
          postCreateInput: '',
          source: TerminalLaunchPlanSource.custom,
        ),
        updatedAt: DateTime.parse('2026-04-22T05:10:00Z'),
      );

      final plans = service.buildRecommendedPlans(
        deviceId: 'dev-1',
        terminals: const [],
        recentContext: recentContext,
      );

      expect(
        plans.map((plan) => plan.tool).toList(),
        [
          TerminalLaunchTool.shell,
          TerminalLaunchTool.claudeCode,
          TerminalLaunchTool.codex,
        ],
      );
    });

    test('resolveCandidateForCwd stays within selected device snapshot', () {
      final service = TerminalLaunchPlanService();
      final snapshot = DeviceProjectContextSnapshot(
        deviceId: 'dev-1',
        generatedAt: DateTime.parse('2026-04-22T05:20:00Z'),
        candidates: const [
          ProjectContextCandidate(
            candidateId: 'cand-1',
            deviceId: 'dev-1',
            label: 'remote-control',
            cwd: '/Users/demo/project/remote-control',
            source: 'pinned_project',
          ),
        ],
      );

      final matched = service.resolveCandidateForCwd(
        deviceId: 'dev-1',
        projectContextSnapshot: snapshot,
        cwd: '/Users/demo/project/remote-control/client',
      );
      final otherDevice = service.resolveCandidateForCwd(
        deviceId: 'dev-2',
        projectContextSnapshot: snapshot,
        cwd: '/Users/demo/project/remote-control/client',
      );

      expect(matched?.candidateId, 'cand-1');
      expect(otherDevice, isNull);
    });

    test(
        'requiresManualConfirmationForCwd follows candidate and explicit-path rules',
        () {
      final service = TerminalLaunchPlanService();
      final snapshot = DeviceProjectContextSnapshot(
        deviceId: 'dev-1',
        generatedAt: DateTime.parse('2026-04-22T05:30:00Z'),
        candidates: const [
          ProjectContextCandidate(
            candidateId: 'cand-1',
            deviceId: 'dev-1',
            label: 'remote-control',
            cwd: '/Users/demo/project/remote-control',
            source: 'pinned_project',
            requiresConfirmation: true,
          ),
        ],
      );

      expect(
        service.requiresManualConfirmationForCwd(
          cwd: '/Users/demo/project/remote-control/client',
          deviceId: 'dev-1',
          projectContextSnapshot: snapshot,
        ),
        isTrue,
      );
      expect(
        service.requiresManualConfirmationForCwd(
          cwd: '/Users/demo/project/other',
          deviceId: 'dev-1',
          projectContextSnapshot: snapshot,
        ),
        isFalse,
      );
      expect(
        service.requiresManualConfirmationForCwd(
          cwd: 'project/app',
          deviceId: 'dev-1',
          projectContextSnapshot: snapshot,
        ),
        isTrue,
      );
    });

    test('finalizePlan re-enforces manual confirmation guard', () {
      final service = TerminalLaunchPlanService();
      final snapshot = DeviceProjectContextSnapshot(
        deviceId: 'dev-1',
        generatedAt: DateTime.parse('2026-04-22T05:40:00Z'),
      );

      final relativePlan = service.finalizePlan(
        plan: const TerminalLaunchPlan(
          tool: TerminalLaunchTool.shell,
          title: 'Shell',
          cwd: 'project/app',
          command: '/bin/bash',
          entryStrategy: TerminalEntryStrategy.directExec,
          postCreateInput: '',
          source: TerminalLaunchPlanSource.custom,
          requiresManualConfirmation: false,
        ),
        deviceId: 'dev-1',
        projectContextSnapshot: snapshot,
      );
      final explicitPlan = service.finalizePlan(
        plan: const TerminalLaunchPlan(
          tool: TerminalLaunchTool.shell,
          title: 'Shell',
          cwd: '/Users/demo/project/app',
          command: '/bin/bash',
          entryStrategy: TerminalEntryStrategy.directExec,
          postCreateInput: '',
          source: TerminalLaunchPlanSource.custom,
          requiresManualConfirmation: false,
        ),
        deviceId: 'dev-1',
        projectContextSnapshot: snapshot,
      );

      expect(relativePlan.requiresManualConfirmation, isTrue);
      expect(explicitPlan.requiresManualConfirmation, isFalse);
    });

    test('resolves explicit codex intent to codex launch plan', () async {
      final service = TerminalLaunchPlanService();

      final plan = await service.resolvePlanFromIntent(
        intent: '进入 codex 修一下登录问题',
        deviceId: 'dev-1',
        terminals: const [],
        recentContext: null,
      );

      expect(plan.tool, TerminalLaunchTool.codex);
      expect(plan.source, TerminalLaunchPlanSource.intent);
      expect(plan.entryStrategy, TerminalEntryStrategy.shellBootstrap);
      expect(plan.postCreateInput, 'codex\n');
      expect(plan.confidence, TerminalLaunchConfidence.medium);
      expect(plan.requiresManualConfirmation, isFalse);
    });

    test('falls back to recommended shell plan for ambiguous intent', () async {
      final service = TerminalLaunchPlanService();

      final plan = await service.resolvePlanFromIntent(
        intent: '帮我看一下',
        deviceId: 'dev-1',
        terminals: const [],
        recentContext: null,
      );

      expect(plan.tool, TerminalLaunchTool.shell);
      expect(plan.source, TerminalLaunchPlanSource.intent);
      expect(plan.confidence, TerminalLaunchConfidence.low);
      expect(plan.requiresManualConfirmation, isFalse);
    });

    test('marks relative path hints as requiring confirmation', () async {
      final service = TerminalLaunchPlanService();

      final plan = await service.resolvePlanFromIntent(
        intent: '进 claude 到 project/app 看下',
        deviceId: 'dev-1',
        terminals: const [],
        recentContext: null,
      );

      expect(plan.tool, TerminalLaunchTool.claudeCode);
      expect(plan.cwd, 'project/app');
      expect(plan.requiresManualConfirmation, isTrue);
      expect(plan.confidence, TerminalLaunchConfidence.low);
    });

    test('normalizes multiline intent and keeps explicit absolute path',
        () async {
      final service = TerminalLaunchPlanService();

      final plan = await service.resolvePlanFromIntent(
        intent: '进入 CLAUDE\n到 `/Users/demo/project/app` 修复问题',
        deviceId: 'dev-1',
        terminals: const [],
        recentContext: null,
      );

      expect(plan.tool, TerminalLaunchTool.claudeCode);
      expect(plan.cwd, '/Users/demo/project/app');
      expect(plan.intent, '进入 CLAUDE 到 `/Users/demo/project/app` 修复问题');
      expect(plan.requiresManualConfirmation, isFalse);
      expect(plan.confidence, TerminalLaunchConfidence.high);
    });

    test('llm provider accepts candidate-internal cwd', () async {
      final service = TerminalLaunchPlanService(
        llmPlannerProvider: _buildLlmProvider(
          body: {
            'summary': '进入 remote-control/client 并启动 Codex',
            'source': 'intent',
            'reasoning_kind': 'candidate_match',
            'matched_candidate_id': 'cand-1',
            'steps': [
              {
                'id': 'step_1',
                'label': '进入项目目录',
                'command': 'cd /Users/demo/project/remote-control/client',
              },
              {
                'id': 'step_2',
                'label': '启动 Codex',
                'command': 'codex',
              },
            ],
          },
        ),
      );

      final plan = await service.resolvePlanFromIntent(
        intent: '帮我进 codex 看一下 remote-control 的 client',
        deviceId: 'dev-1',
        terminals: const [],
        recentContext: null,
        projectContextSettings: const ProjectContextSettings(
          deviceId: 'dev-1',
          plannerConfig: PlannerRuntimeConfigModel(
            provider: 'llm',
            llmEnabled: true,
          ),
        ),
        projectContextSnapshot: DeviceProjectContextSnapshot(
          deviceId: 'dev-1',
          generatedAt: DateTime.parse('2026-04-22T03:00:00Z'),
          candidates: const [
            ProjectContextCandidate(
              candidateId: 'cand-1',
              deviceId: 'dev-1',
              label: 'remote-control',
              cwd: '/Users/demo/project/remote-control',
              source: 'pinned_project',
              toolHints: ['codex'],
            ),
          ],
        ),
      );

      expect(plan.tool, TerminalLaunchTool.codex);
      expect(plan.cwd, '/Users/demo/project/remote-control/client');
      expect(plan.requiresManualConfirmation, isFalse);
      expect(plan.confidence, TerminalLaunchConfidence.high);
    });

    test('llm provider marks out-of-candidate path for confirmation', () async {
      final service = TerminalLaunchPlanService(
        llmPlannerProvider: _buildLlmProvider(
          body: {
            'summary': '进入 escaped 并启动 Claude',
            'source': 'intent',
            'reasoning_kind': 'candidate_match',
            'matched_candidate_id': 'cand-1',
            'steps': [
              {
                'id': 'step_1',
                'label': '进入临时目录',
                'command': 'cd /tmp/escaped',
              },
              {
                'id': 'step_2',
                'label': '启动 Claude',
                'command': 'claude',
              },
            ],
          },
        ),
      );

      final plan = await service.resolvePlanFromIntent(
        intent: '帮我进入 claude 看 remote-control',
        deviceId: 'dev-1',
        terminals: const [],
        projectContextSettings: const ProjectContextSettings(
          deviceId: 'dev-1',
          plannerConfig: PlannerRuntimeConfigModel(
            provider: 'llm',
            llmEnabled: true,
          ),
        ),
        projectContextSnapshot: DeviceProjectContextSnapshot(
          deviceId: 'dev-1',
          generatedAt: DateTime.parse('2026-04-22T03:00:00Z'),
          candidates: const [
            ProjectContextCandidate(
              candidateId: 'cand-1',
              deviceId: 'dev-1',
              label: 'remote-control',
              cwd: '/Users/demo/project/remote-control',
              source: 'pinned_project',
              toolHints: ['claude_code'],
            ),
          ],
        ),
      );

      expect(plan.tool, TerminalLaunchTool.claudeCode);
      expect(plan.cwd, '/tmp/escaped');
      expect(plan.requiresManualConfirmation, isTrue);
      expect(plan.confidence, TerminalLaunchConfidence.low);
    });

    test('llm provider falls back to local rules on invalid json', () async {
      final service = TerminalLaunchPlanService(
        llmPlannerProvider: _buildLlmProvider(rawContent: '{invalid-json'),
      );

      final plan = await service.resolvePlanFromIntent(
        intent: '进入 codex 修一下登录问题',
        deviceId: 'dev-1',
        terminals: const [],
        projectContextSettings: const ProjectContextSettings(
          deviceId: 'dev-1',
          plannerConfig: PlannerRuntimeConfigModel(
            provider: 'llm',
            llmEnabled: true,
          ),
        ),
        projectContextSnapshot: DeviceProjectContextSnapshot(
          deviceId: 'dev-1',
          generatedAt: DateTime.parse('2026-04-22T03:00:00Z'),
          candidates: const [
            ProjectContextCandidate(
              candidateId: 'cand-1',
              deviceId: 'dev-1',
              label: 'remote-control',
              cwd: '/Users/demo/project/remote-control',
              source: 'pinned_project',
            ),
          ],
        ),
      );

      expect(plan.tool, TerminalLaunchTool.codex);
      expect(plan.cwd, '/Users/demo/project/remote-control');
      expect(plan.requiresManualConfirmation, isFalse);
      expect(plan.confidence, TerminalLaunchConfidence.medium);
    });

    test('llm provider falls back to local rules on empty result', () async {
      final service = TerminalLaunchPlanService(
        llmPlannerProvider: _buildLlmProvider(body: const {}),
      );

      final plan = await service.resolvePlanFromIntent(
        intent: '进入 codex 修一下登录问题',
        deviceId: 'dev-1',
        terminals: const [],
        projectContextSettings: const ProjectContextSettings(
          deviceId: 'dev-1',
          plannerConfig: PlannerRuntimeConfigModel(
            provider: 'llm',
            llmEnabled: true,
          ),
        ),
        projectContextSnapshot: DeviceProjectContextSnapshot(
          deviceId: 'dev-1',
          generatedAt: DateTime.parse('2026-04-22T03:00:00Z'),
          candidates: const [
            ProjectContextCandidate(
              candidateId: 'cand-1',
              deviceId: 'dev-1',
              label: 'remote-control',
              cwd: '/Users/demo/project/remote-control',
              source: 'pinned_project',
            ),
          ],
        ),
      );

      expect(plan.tool, TerminalLaunchTool.codex);
      expect(plan.cwd, '/Users/demo/project/remote-control');
      expect(plan.confidence, TerminalLaunchConfidence.medium);
    });

    test('llm provider falls back to local rules on timeout', () async {
      final service = TerminalLaunchPlanService(
        llmPlannerProvider: _buildLlmProvider(
          body: {
            'summary': '慢速返回',
            'source': 'intent',
            'reasoning_kind': 'candidate_match',
            'steps': [
              {
                'id': 'step_1',
                'label': '进入临时目录',
                'command': 'cd /tmp/slow',
              },
            ],
          },
          delay: const Duration(milliseconds: 40),
          timeout: const Duration(milliseconds: 10),
        ),
      );

      final plan = await service.resolvePlanFromIntent(
        intent: '进入 codex 修一下登录问题',
        deviceId: 'dev-1',
        terminals: const [],
        projectContextSettings: const ProjectContextSettings(
          deviceId: 'dev-1',
          plannerConfig: PlannerRuntimeConfigModel(
            provider: 'llm',
            llmEnabled: true,
          ),
        ),
        projectContextSnapshot: DeviceProjectContextSnapshot(
          deviceId: 'dev-1',
          generatedAt: DateTime.parse('2026-04-22T03:00:00Z'),
          candidates: const [
            ProjectContextCandidate(
              candidateId: 'cand-1',
              deviceId: 'dev-1',
              label: 'remote-control',
              cwd: '/Users/demo/project/remote-control',
              source: 'pinned_project',
            ),
          ],
        ),
      );

      expect(plan.tool, TerminalLaunchTool.codex);
      expect(plan.cwd, '/Users/demo/project/remote-control');
      expect(plan.confidence, TerminalLaunchConfidence.medium);
    });

    test('llm provider only sends candidate summaries and recent context',
        () async {
      late Map<String, dynamic> requestBody;
      final service = TerminalLaunchPlanService(
        llmPlannerProvider: LlmPlannerProvider(
          processRunner: (executable, arguments) async {
            requestBody = _extractPromptPayload(arguments.last);
            return ProcessResult(
              1,
              0,
              jsonEncode({
                'summary': '进入 remote-control 并启动 Codex',
                'source': 'intent',
                'reasoning_kind': 'candidate_match',
                'matched_candidate_id': 'cand-1',
                'steps': [
                  {
                    'id': 'step_1',
                    'label': '进入项目目录',
                    'command': 'cd /Users/demo/project/remote-control',
                  },
                  {
                    'id': 'step_2',
                    'label': '启动 Codex',
                    'command': 'codex',
                  },
                ],
              }),
              '',
            );
          },
        ),
      );

      await service.resolvePlanFromIntent(
        intent: '进入 codex 看当前项目',
        deviceId: 'dev-1',
        terminals: const [
          RuntimeTerminal(
            terminalId: 'term-1',
            title: 'Should not be sent',
            cwd: '/tmp/hidden',
            command: '/bin/bash',
            status: 'attached',
            views: {'desktop': 1},
          ),
        ],
        recentContext: RecentLaunchContext(
          deviceId: 'dev-1',
          lastTool: TerminalLaunchTool.codex,
          lastCwd: '/Users/demo/project/remote-control',
          lastSuccessfulPlan: const TerminalLaunchPlan(
            tool: TerminalLaunchTool.codex,
            title: 'Codex / remote-control',
            cwd: '/Users/demo/project/remote-control',
            command: '/bin/bash',
            entryStrategy: TerminalEntryStrategy.shellBootstrap,
            postCreateInput: 'codex\n',
            source: TerminalLaunchPlanSource.recommended,
          ),
          updatedAt: DateTime.parse('2026-04-22T03:30:00Z'),
        ),
        projectContextSettings: const ProjectContextSettings(
          deviceId: 'dev-1',
          plannerConfig: PlannerRuntimeConfigModel(
            provider: 'llm',
            llmEnabled: true,
          ),
        ),
        projectContextSnapshot: DeviceProjectContextSnapshot(
          deviceId: 'dev-1',
          generatedAt: DateTime.parse('2026-04-22T03:00:00Z'),
          candidates: const [
            ProjectContextCandidate(
              candidateId: 'cand-1',
              deviceId: 'dev-1',
              label: 'remote-control',
              cwd: '/Users/demo/project/remote-control',
              source: 'pinned_project',
              toolHints: ['codex'],
            ),
          ],
        ),
      );

      final userPayload = requestBody;
      expect(
        userPayload.keys.toSet(),
        {'intent', 'recent_context', 'candidates'},
      );
      final candidates = userPayload['candidates'] as List<dynamic>;
      expect(candidates.single, {
        'candidate_id': 'cand-1',
        'label': 'remote-control',
        'cwd': '/Users/demo/project/remote-control',
        'tool_hints': ['codex'],
        'requires_confirmation': false,
      });
      expect(userPayload.containsKey('terminals'), isFalse);
      expect(userPayload.containsKey('approved_scan_roots'), isFalse);
    });
  });
}

LlmPlannerProvider _buildLlmProvider({
  Map<String, dynamic>? body,
  String? rawContent,
  Duration? delay,
  Duration timeout = const Duration(seconds: 4),
}) {
  final responseBody =
      rawContent ?? jsonEncode(body ?? const <String, dynamic>{});
  return LlmPlannerProvider(
    processRunner: (executable, arguments) async {
      if (delay != null) {
        await Future<void>.delayed(delay);
      }
      return ProcessResult(1, 0, responseBody, '');
    },
    timeout: timeout,
  );
}

Map<String, dynamic> _extractPromptPayload(String prompt) {
  final marker = '输入:\n';
  final index = prompt.indexOf(marker);
  if (index < 0) {
    throw StateError('missing input marker in prompt');
  }
  return jsonDecode(prompt.substring(index + marker.length))
      as Map<String, dynamic>;
}
