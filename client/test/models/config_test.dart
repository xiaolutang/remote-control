import 'package:flutter_test/flutter_test.dart';
import 'package:rc_client/models/config.dart';
import 'package:rc_client/models/project_context_snapshot.dart';
import 'package:rc_client/models/recent_launch_context.dart';
import 'package:rc_client/models/shortcut_item.dart';
import 'package:rc_client/models/terminal_launch_plan.dart';
import 'package:rc_client/models/terminal_shortcut.dart';

void main() {
  group('AppConfig', () {
    test('default values', () {
      const config = AppConfig();
      // serverUrl 默认为空，由 EnvironmentService 动态提供
      expect(config.serverUrl, isEmpty);
      expect(config.sessionId, '');
      expect(config.token, isNull);
      expect(config.autoReconnect, isTrue);
      expect(config.maxRetries, 5);
      expect(config.themeMode, AppThemeMode.system);
      expect(config.claudeNavigationMode, ClaudeNavigationMode.standard);
      expect(config.desktopExitPolicy, DesktopExitPolicy.stopAgentOnExit);
      expect(config.keepAgentRunningInBackground, isFalse);
      expect(config.desktopAgentWorkdir, isEmpty);
    });

    test('custom values', () {
      final config = AppConfig(
        serverUrl: 'ws://localhost:8080',
        sessionId: 'session-123',
        token: 'token-abc',
        autoReconnect: false,
        maxRetries: 10,
        themeMode: AppThemeMode.dark,
        claudeNavigationMode: ClaudeNavigationMode.application,
        keepAgentRunningInBackground: false,
        desktopAgentWorkdir: '/tmp/agent',
      );
      expect(config.serverUrl, 'ws://localhost:8080');
      expect(config.sessionId, 'session-123');
      expect(config.token, 'token-abc');
      expect(config.autoReconnect, isFalse);
      expect(config.maxRetries, 10);
      expect(config.themeMode, AppThemeMode.dark);
      expect(config.claudeNavigationMode, ClaudeNavigationMode.application);
      expect(config.desktopExitPolicy, DesktopExitPolicy.stopAgentOnExit);
      expect(config.keepAgentRunningInBackground, isFalse);
      expect(config.desktopAgentWorkdir, '/tmp/agent');
    });

    test('toJson and fromJson', () {
      final config = AppConfig(
        serverUrl: 'ws://localhost:8080',
        sessionId: 'session-123',
        token: 'token-abc',
        autoReconnect: false,
        maxRetries: 3,
        themeMode: AppThemeMode.light,
        claudeNavigationMode: ClaudeNavigationMode.application,
        keepAgentRunningInBackground: false,
        desktopAgentWorkdir: '/tmp/agent',
        shortcutItems: [
          ShortcutItem(
            id: 'claude_help',
            label: '/help',
            source: ShortcutItemSource.builtin,
            section: ShortcutItemSection.smart,
            action: TerminalShortcutAction(
              type: TerminalShortcutActionType.sendText,
              value: '/help\r',
            ),
          ),
        ],
        projectShortcutItems: {
          'project-a': [
            ShortcutItem(
              id: 'project_test',
              label: 'pnpm test',
              source: ShortcutItemSource.project,
              section: ShortcutItemSection.smart,
              action: TerminalShortcutAction(
                type: TerminalShortcutActionType.sendText,
                value: 'pnpm test\r',
              ),
              scope: ShortcutItemScope.project,
            ),
          ],
        },
        recentLaunchContexts: {
          'dev-1': RecentLaunchContext(
            deviceId: 'dev-1',
            lastTool: TerminalLaunchTool.claudeCode,
            lastCwd: '/tmp/agent',
            lastSuccessfulPlan: TerminalLaunchPlan(
              tool: TerminalLaunchTool.claudeCode,
              title: 'Claude / agent',
              cwd: '/tmp/agent',
              command: '/bin/bash',
              entryStrategy: TerminalEntryStrategy.shellBootstrap,
              postCreateInput: 'claude\n',
              source: TerminalLaunchPlanSource.recommended,
            ),
            updatedAt: DateTime.parse('2026-04-22T03:00:00Z'),
          ),
        },
        projectContextSnapshots: {
          'dev-1': DeviceProjectContextSnapshot(
            deviceId: 'dev-1',
            generatedAt: DateTime.parse('2026-04-22T03:05:00Z'),
            candidates: const [
              ProjectContextCandidate(
                candidateId: 'cand-1',
                deviceId: 'dev-1',
                label: 'remote-control',
                cwd: '/tmp/agent',
                source: 'pinned_project',
                toolHints: ['claude_code'],
              ),
            ],
          ),
        },
      );

      final json = config.toJson();
      // serverUrl 不再参与持久化
      expect(json.containsKey('serverUrl'), isFalse);
      expect(json['sessionId'], 'session-123');
      expect(json['token'], 'token-abc');
      expect(json['autoReconnect'], false);
      expect(json['maxRetries'], 3);
      expect(json['themeMode'], AppThemeMode.light.name);
      expect(
        json['claudeNavigationMode'],
        ClaudeNavigationMode.application.name,
      );
      expect(
        json['desktopExitPolicy'],
        DesktopExitPolicy.stopAgentOnExit.name,
      );
      expect(json['desktopAgentWorkdir'], '/tmp/agent');
      expect((json['shortcutItems'] as List).length, 1);
      expect(
        ((json['projectShortcutItems'] as Map<String, dynamic>)['project-a']
                as List)
            .length,
        1,
      );
      expect(
        (json['recentLaunchContexts'] as Map<String, dynamic>)
            .containsKey('dev-1'),
        isTrue,
      );
      expect(
        (json['projectContextSnapshots'] as Map<String, dynamic>)
            .containsKey('dev-1'),
        isTrue,
      );

      final restored = AppConfig.fromJson(json, serverUrl: config.serverUrl);
      expect(restored.serverUrl, config.serverUrl);
      expect(restored.sessionId, config.sessionId);
      expect(restored.token, config.token);
      expect(restored.autoReconnect, config.autoReconnect);
      expect(restored.maxRetries, config.maxRetries);
      expect(restored.themeMode, config.themeMode);
      expect(restored.claudeNavigationMode, config.claudeNavigationMode);
      expect(
        restored.keepAgentRunningInBackground,
        config.keepAgentRunningInBackground,
      );
      expect(restored.desktopAgentWorkdir, config.desktopAgentWorkdir);
      expect(restored.shortcutItems.single.id, 'claude_help');
      expect(restored.projectShortcutItems['project-a']!.single.id,
          'project_test');
      expect(
        restored.recentLaunchContexts['dev-1']!.lastTool,
        TerminalLaunchTool.claudeCode,
      );
      expect(
        restored
            .recentLaunchContexts['dev-1']!.lastSuccessfulPlan.postCreateInput,
        'claude\n',
      );
      expect(
        restored.projectContextSnapshots['dev-1']!.candidates.single.label,
        'remote-control',
      );
    });

    test('fromJson degrades unknown recent launch tool safely', () {
      final config = AppConfig.fromJson({
        'recentLaunchContexts': {
          'dev-1': {
            'device_id': 'dev-1',
            'last_tool': 'unknown',
            'last_cwd': '/tmp/work',
            'last_successful_plan': {
              'tool': 'codex',
              'title': '',
              'cwd': '/tmp/work',
              'command': '',
              'entry_strategy': 'unknown',
              'post_create_input': '',
              'source': 'unknown',
            },
            'updated_at': 'invalid',
          },
        },
      });

      final context = config.recentLaunchContexts['dev-1']!;
      expect(context.lastTool, TerminalLaunchTool.codex);
      expect(
        context.lastSuccessfulPlan.entryStrategy,
        TerminalEntryStrategy.shellBootstrap,
      );
      expect(context.lastSuccessfulPlan.command, '/bin/bash');
      expect(context.lastSuccessfulPlan.title, 'Codex / work');
      expect(context.updatedAt, DateTime.fromMillisecondsSinceEpoch(0));
    });

    test('fromJson handles missing fields', () {
      final json = <String, dynamic>{};
      final config = AppConfig.fromJson(json);
      // serverUrl 默认为空，由 EnvironmentService 动态提供
      expect(config.serverUrl, isEmpty);
      expect(config.sessionId, '');
      expect(config.token, isNull);
      expect(config.autoReconnect, isTrue);
      expect(config.themeMode, AppThemeMode.system);
      expect(config.claudeNavigationMode, ClaudeNavigationMode.standard);
      expect(config.desktopExitPolicy, DesktopExitPolicy.stopAgentOnExit);
      expect(config.keepAgentRunningInBackground, isFalse);
      expect(config.desktopAgentWorkdir, isEmpty);
    });

    test('copyWith', () {
      const original = AppConfig(
        serverUrl: 'ws://localhost:8080',
        sessionId: 'session-123',
      );

      final updated = original.copyWith(
        token: 'new-token',
        maxRetries: 10,
        themeMode: AppThemeMode.dark,
        claudeNavigationMode: ClaudeNavigationMode.application,
        desktopExitPolicy: DesktopExitPolicy.stopAgentOnExit,
        desktopAgentWorkdir: '/tmp/agent',
      );

      expect(updated.serverUrl, 'ws://localhost:8080');
      expect(updated.sessionId, 'session-123');
      expect(updated.token, 'new-token');
      expect(updated.maxRetries, 10);
      expect(updated.themeMode, AppThemeMode.dark);
      expect(updated.claudeNavigationMode, ClaudeNavigationMode.application);
      expect(updated.desktopExitPolicy, DesktopExitPolicy.stopAgentOnExit);
      expect(updated.keepAgentRunningInBackground, isFalse);
      expect(updated.desktopAgentWorkdir, '/tmp/agent');
    });
  });
}
