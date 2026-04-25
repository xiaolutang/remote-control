import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rc_client/screens/skill_config_screen.dart';
import 'package:rc_client/services/desktop_agent_http_client.dart';

/// Fake DesktopAgentHttpClient 用于测试 SkillConfigScreen
class _FakeDesktopAgentHttpClient extends DesktopAgentHttpClient {
  _FakeDesktopAgentHttpClient({
    this.skillsResult = const [],
    this.knowledgeResult = const [],
    this.toggleSkillResult = true,
    this.toggleKnowledgeResult = true,
    this.discoverResult,
  }) : super(homeDirectory: '/tmp/test_home');

  List<SkillItem> skillsResult;
  List<KnowledgeItem> knowledgeResult;
  bool toggleSkillResult;
  bool toggleKnowledgeResult;
  LocalAgentStatus? discoverResult;

  final List<_ToggleCall> toggleSkillCalls = [];
  final List<_ToggleCall> toggleKnowledgeCalls = [];
  int getSkillsCallCount = 0;
  int getKnowledgeCallCount = 0;

  @override
  Future<List<SkillItem>> getSkills(int port) async {
    getSkillsCallCount++;
    return skillsResult;
  }

  @override
  Future<List<KnowledgeItem>> getKnowledge(int port) async {
    getKnowledgeCallCount++;
    return knowledgeResult;
  }

  @override
  Future<bool> toggleSkill(int port, {required String name, required bool enabled}) async {
    toggleSkillCalls.add(_ToggleCall(key: name, value: enabled));
    final result = toggleSkillResult;
    toggleSkillResult = true; // reset for subsequent calls
    return result;
  }

  @override
  Future<bool> toggleKnowledge(int port, {required String filename, required bool enabled}) async {
    toggleKnowledgeCalls.add(_ToggleCall(key: filename, value: enabled));
    final result = toggleKnowledgeResult;
    toggleKnowledgeResult = true; // reset for subsequent calls
    return result;
  }

  @override
  Future<LocalAgentStatus?> discoverAgent() async {
    return discoverResult;
  }

  @override
  void close() {}
}

class _ToggleCall {
  const _ToggleCall({required this.key, required this.value});
  final String key;
  final bool value;
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  group('SkillConfigScreen', () {
    Widget buildScreen({
      _FakeDesktopAgentHttpClient? httpClient,
      int? agentPort,
    }) {
      return MaterialApp(
        home: SkillConfigScreen(
          agentPort: agentPort ?? 18765,
          httpClient: httpClient ?? _FakeDesktopAgentHttpClient(),
        ),
      );
    }

    testWidgets('shows loading indicator then skill list', (tester) async {
      final fakeClient = _FakeDesktopAgentHttpClient(
        skillsResult: [
          const SkillItem(name: 'bash', description: 'Execute bash commands', enabled: true),
          const SkillItem(name: 'python', description: 'Run Python scripts', enabled: false),
        ],
        knowledgeResult: [
          const KnowledgeItem(filename: 'docs.md', enabled: true),
        ],
      );

      await tester.pumpWidget(buildScreen(httpClient: fakeClient));
      expect(find.byType(CircularProgressIndicator), findsOneWidget);

      await tester.pumpAndSettle();

      // Tab 1: Skills
      expect(find.text('bash'), findsOneWidget);
      expect(find.text('Execute bash commands'), findsOneWidget);
      expect(find.text('python'), findsOneWidget);
      expect(find.text('Run Python scripts'), findsOneWidget);

      // Verify switch values
      final bashSwitch = tester.widget<Switch>(
        find.byKey(const Key('skill-switch-bash')),
      );
      expect(bashSwitch.value, isTrue);

      final pythonSwitch = tester.widget<Switch>(
        find.byKey(const Key('skill-switch-python')),
      );
      expect(pythonSwitch.value, isFalse);
    });

    testWidgets('shows knowledge list on second tab', (tester) async {
      final fakeClient = _FakeDesktopAgentHttpClient(
        skillsResult: [],
        knowledgeResult: [
          const KnowledgeItem(filename: 'guide.md', enabled: true),
          const KnowledgeItem(filename: 'api.md', enabled: false),
        ],
      );

      await tester.pumpWidget(buildScreen(httpClient: fakeClient));
      await tester.pumpAndSettle();

      // Switch to knowledge tab
      await tester.tap(find.text('知识文件'));
      await tester.pumpAndSettle();

      expect(find.text('guide.md'), findsOneWidget);
      expect(find.text('api.md'), findsOneWidget);

      final guideSwitch = tester.widget<Switch>(
        find.byKey(const Key('knowledge-switch-guide.md')),
      );
      expect(guideSwitch.value, isTrue);

      final apiSwitch = tester.widget<Switch>(
        find.byKey(const Key('knowledge-switch-api.md')),
      );
      expect(apiSwitch.value, isFalse);
    });

    testWidgets('toggle skill calls API and shows restart hint', (tester) async {
      final fakeClient = _FakeDesktopAgentHttpClient(
        skillsResult: [
          const SkillItem(name: 'bash', description: 'Execute bash', enabled: true),
        ],
        knowledgeResult: [],
      );

      await tester.pumpWidget(buildScreen(httpClient: fakeClient));
      await tester.pumpAndSettle();

      // Toggle bash off
      await tester.tap(find.byKey(const Key('skill-switch-bash')));
      await tester.pumpAndSettle();

      // API call was made
      expect(fakeClient.toggleSkillCalls, hasLength(1));
      expect(fakeClient.toggleSkillCalls.first.key, equals('bash'));
      expect(fakeClient.toggleSkillCalls.first.value, isFalse);

      // Restart hint shown
      expect(find.text('重启 Agent 后生效'), findsOneWidget);
    });

    testWidgets('toggle knowledge calls API and shows restart hint', (tester) async {
      final fakeClient = _FakeDesktopAgentHttpClient(
        skillsResult: [],
        knowledgeResult: [
          const KnowledgeItem(filename: 'notes.md', enabled: false),
        ],
      );

      await tester.pumpWidget(buildScreen(httpClient: fakeClient));
      await tester.pumpAndSettle();

      // Switch to knowledge tab
      await tester.tap(find.text('知识文件'));
      await tester.pumpAndSettle();

      // Toggle notes.md on
      await tester.tap(find.byKey(const Key('knowledge-switch-notes.md')));
      await tester.pumpAndSettle();

      // API call was made
      expect(fakeClient.toggleKnowledgeCalls, hasLength(1));
      expect(fakeClient.toggleKnowledgeCalls.first.key, equals('notes.md'));
      expect(fakeClient.toggleKnowledgeCalls.first.value, isTrue);

      // Restart hint shown
      expect(find.text('重启 Agent 后生效'), findsOneWidget);
    });

    testWidgets('shows empty state when skill list is empty', (tester) async {
      final fakeClient = _FakeDesktopAgentHttpClient(
        skillsResult: [],
        knowledgeResult: [],
      );

      await tester.pumpWidget(buildScreen(httpClient: fakeClient));
      await tester.pumpAndSettle();

      expect(find.text('暂无技能'), findsOneWidget);
    });

    testWidgets('shows empty state when knowledge list is empty', (tester) async {
      final fakeClient = _FakeDesktopAgentHttpClient(
        skillsResult: [],
        knowledgeResult: [],
      );

      await tester.pumpWidget(buildScreen(httpClient: fakeClient));
      await tester.pumpAndSettle();

      // Switch to knowledge tab
      await tester.tap(find.text('知识文件'));
      await tester.pumpAndSettle();

      expect(find.text('暂无知识文件'), findsOneWidget);
    });

    testWidgets('API toggle failure reverts switch and shows error', (tester) async {
      final fakeClient = _FakeDesktopAgentHttpClient(
        skillsResult: [
          const SkillItem(name: 'git', description: 'Git operations', enabled: true),
        ],
        knowledgeResult: [],
        toggleSkillResult: false,
      );

      await tester.pumpWidget(buildScreen(httpClient: fakeClient));
      await tester.pumpAndSettle();

      // Toggle git off - this should fail and revert
      await tester.tap(find.byKey(const Key('skill-switch-git')));
      await tester.pumpAndSettle();

      // API call was made
      expect(fakeClient.toggleSkillCalls, hasLength(1));

      // Switch should revert back to enabled=true
      final gitSwitch = tester.widget<Switch>(
        find.byKey(const Key('skill-switch-git')),
      );
      expect(gitSwitch.value, isTrue);

      // Error message shown
      expect(find.text('切换失败，请重试'), findsOneWidget);
    });

    testWidgets('shows error state when agent is offline', (tester) async {
      // No agentPort provided and discoverAgent returns null
      final fakeClient = _FakeDesktopAgentHttpClient(
        discoverResult: null,
      );

      await tester.pumpWidget(
        MaterialApp(
          home: SkillConfigScreen(
            httpClient: fakeClient,
          ),
        ),
      );
      await tester.pumpAndSettle();

      expect(find.text('未发现本地 Agent，请确认 Agent 已启动'), findsOneWidget);
      expect(find.byKey(const Key('skill-config-retry')), findsOneWidget);
    });

    testWidgets('retry button reloads data', (tester) async {
      final fakeClient = _FakeDesktopAgentHttpClient(
        discoverResult: null,
      );

      await tester.pumpWidget(
        MaterialApp(
          home: SkillConfigScreen(
            httpClient: fakeClient,
          ),
        ),
      );
      await tester.pumpAndSettle();

      // Agent not found
      expect(find.text('未发现本地 Agent，请确认 Agent 已启动'), findsOneWidget);

      // Now make agent discoverable
      fakeClient.discoverResult = const LocalAgentStatus(
        running: true,
        pid: 1,
        port: 18765,
        serverUrl: '',
        connected: true,
        sessionId: '',
        terminalsCount: 0,
        keepRunningInBackground: true,
      );
      fakeClient.skillsResult = [
        const SkillItem(name: 'test-skill', description: 'A test', enabled: true),
      ];

      // Tap retry
      await tester.tap(find.byKey(const Key('skill-config-retry')));
      await tester.pumpAndSettle();

      // Should now show skill
      expect(find.text('test-skill'), findsOneWidget);
    });
  });

  group('SkillItem', () {
    test('fromJson parses all fields', () {
      final json = {
        'name': 'bash',
        'description': 'Execute bash commands',
        'enabled': true,
      };
      final item = SkillItem.fromJson(json);
      expect(item.name, equals('bash'));
      expect(item.description, equals('Execute bash commands'));
      expect(item.enabled, isTrue);
    });

    test('fromJson handles missing fields with defaults', () {
      final item = SkillItem.fromJson({});
      expect(item.name, equals(''));
      expect(item.description, equals(''));
      expect(item.enabled, isFalse);
    });

    test('copyWith works', () {
      const item = SkillItem(name: 'test', description: 'desc', enabled: true);
      final copied = item.copyWith(enabled: false);
      expect(copied.name, equals('test'));
      expect(copied.description, equals('desc'));
      expect(copied.enabled, isFalse);
    });
  });

  group('KnowledgeItem', () {
    test('fromJson parses all fields', () {
      final json = {
        'filename': 'docs.md',
        'enabled': true,
      };
      final item = KnowledgeItem.fromJson(json);
      expect(item.filename, equals('docs.md'));
      expect(item.enabled, isTrue);
    });

    test('fromJson handles missing fields with defaults', () {
      final item = KnowledgeItem.fromJson({});
      expect(item.filename, equals(''));
      expect(item.enabled, isFalse);
    });

    test('copyWith works', () {
      const item = KnowledgeItem(filename: 'test.md', enabled: false);
      final copied = item.copyWith(enabled: true);
      expect(copied.filename, equals('test.md'));
      expect(copied.enabled, isTrue);
    });
  });
}
