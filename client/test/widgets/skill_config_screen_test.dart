import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rc_client/screens/skill_config_screen.dart';
import 'package:rc_client/services/skill_config_service.dart';

class _FakeSkillConfigService extends SkillConfigService {
  _FakeSkillConfigService({
    this.dataDirResult = '/tmp/test-agent-data',
    List<KnowledgeInfo>? knowledgeResult,
  })  : _knowledgeResult = knowledgeResult ?? [],
        super(homeDirectory: '/tmp/test_home');

  String? dataDirResult;
  List<KnowledgeInfo> _knowledgeResult;

  final List<_ToggleCall> toggleKnowledgeCalls = [];
  int loadKnowledgeCallCount = 0;
  int importKnowledgeCallCount = 0;
  int deleteKnowledgeCallCount = 0;

  bool toggleKnowledgeShouldThrow = false;
  String? pickMarkdownFileResult;
  String knowledgeContentResult = '# test content';

  void setKnowledgeResult(List<KnowledgeInfo> knowledge) {
    _knowledgeResult = knowledge;
  }

  @override
  String? getAgentDataDir() => dataDirResult;

  @override
  Future<List<KnowledgeInfo>> loadKnowledge() async {
    loadKnowledgeCallCount++;
    return _knowledgeResult;
  }

  @override
  Future<void> toggleKnowledge(String filename, bool enabled) async {
    toggleKnowledgeCalls.add(_ToggleCall(key: filename, value: enabled));
    if (toggleKnowledgeShouldThrow) throw Exception('写入失败');
  }

  @override
  Future<String?> pickMarkdownFile() async => pickMarkdownFileResult;

  @override
  Future<void> importKnowledgeFile(String sourcePath) async {
    importKnowledgeCallCount++;
  }

  @override
  Future<void> deleteKnowledgeFile(String filename) async {
    deleteKnowledgeCallCount++;
  }

  @override
  Future<String> readKnowledgeContent(String filename) async =>
      knowledgeContentResult;

  @override
  Future<void> writeKnowledgeContent(String filename, String content) async {}
}

class _ToggleCall {
  const _ToggleCall({required this.key, required this.value});
  final String key;
  final bool value;
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  group('SkillConfigScreen', () {
    Widget buildScreen({_FakeSkillConfigService? service}) {
      return MaterialApp(
        home: SkillConfigScreen(
          skillConfigService: service ?? _FakeSkillConfigService(),
        ),
      );
    }

    testWidgets('shows knowledge list', (tester) async {
      final fakeService = _FakeSkillConfigService(
        knowledgeResult: [
          const KnowledgeInfo(filename: 'guide.md', enabled: true),
          const KnowledgeInfo(filename: 'api.md', enabled: false),
        ],
      );

      await tester.pumpWidget(buildScreen(service: fakeService));
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

    testWidgets('toggle knowledge shows new-terminal hint', (tester) async {
      final fakeService = _FakeSkillConfigService(
        knowledgeResult: [
          const KnowledgeInfo(filename: 'notes.md', enabled: false),
        ],
      );

      await tester.pumpWidget(buildScreen(service: fakeService));
      await tester.pumpAndSettle();

      await tester.tap(find.byKey(const Key('knowledge-switch-notes.md')));
      await tester.pumpAndSettle();

      expect(fakeService.toggleKnowledgeCalls, hasLength(1));
      expect(fakeService.toggleKnowledgeCalls.first.key, equals('notes.md'));
      expect(fakeService.toggleKnowledgeCalls.first.value, isTrue);
      expect(find.text('新建终端后生效'), findsOneWidget);
    });

    testWidgets('shows empty state when knowledge list is empty',
        (tester) async {
      await tester.pumpWidget(buildScreen());
      await tester.pumpAndSettle();

      expect(find.text('暂无知识文件，点击上方按钮导入'), findsOneWidget);
    });

    testWidgets('toggle failure reverts switch and shows error', (tester) async {
      final fakeService = _FakeSkillConfigService(
        knowledgeResult: [
          const KnowledgeInfo(filename: 'notes.md', enabled: true),
        ],
      );
      fakeService.toggleKnowledgeShouldThrow = true;

      await tester.pumpWidget(buildScreen(service: fakeService));
      await tester.pumpAndSettle();

      await tester.tap(find.byKey(const Key('knowledge-switch-notes.md')));
      await tester.pumpAndSettle();

      final switchWidget = tester.widget<Switch>(
        find.byKey(const Key('knowledge-switch-notes.md')),
      );
      expect(switchWidget.value, isTrue);
      expect(find.textContaining('切换失败'), findsOneWidget);
    });

    testWidgets('shows no-data-dir state', (tester) async {
      final fakeService = _FakeSkillConfigService();
      fakeService.dataDirResult = null;

      await tester.pumpWidget(buildScreen(service: fakeService));
      await tester.pumpAndSettle();

      expect(find.text('未找到 Agent 配置目录'), findsOneWidget);
    });

    testWidgets('retry button reloads data', (tester) async {
      final fakeService = _FakeSkillConfigService();
      fakeService.dataDirResult = null;

      await tester.pumpWidget(buildScreen(service: fakeService));
      await tester.pumpAndSettle();

      expect(find.text('未找到 Agent 配置目录'), findsOneWidget);

      fakeService.dataDirResult = '/tmp/test-agent-data';
      fakeService.setKnowledgeResult([
        const KnowledgeInfo(filename: 'test.md', enabled: true),
      ]);

      await tester.tap(find.byKey(const Key('knowledge-config-retry')));
      await tester.pumpAndSettle();

      expect(find.text('test.md'), findsOneWidget);
    });

    testWidgets('import knowledge button triggers pick and import',
        (tester) async {
      final fakeService = _FakeSkillConfigService();
      fakeService.pickMarkdownFileResult = '/tmp/guide.md';

      await tester.pumpWidget(buildScreen(service: fakeService));
      await tester.pumpAndSettle();

      await tester.tap(find.byKey(const Key('import-knowledge-btn')));
      await tester.pumpAndSettle();

      expect(fakeService.importKnowledgeCallCount, equals(1));
      expect(find.text('已导入知识文件'), findsOneWidget);
    });

    testWidgets('import cancelled does not call import', (tester) async {
      final fakeService = _FakeSkillConfigService();

      await tester.pumpWidget(buildScreen(service: fakeService));
      await tester.pumpAndSettle();

      await tester.tap(find.byKey(const Key('import-knowledge-btn')));
      await tester.pumpAndSettle();

      expect(fakeService.importKnowledgeCallCount, equals(0));
    });

    testWidgets('edit knowledge shows editor dialog', (tester) async {
      final fakeService = _FakeSkillConfigService(
        knowledgeResult: [
          const KnowledgeInfo(filename: 'notes.md', enabled: true),
        ],
      );

      await tester.pumpWidget(buildScreen(service: fakeService));
      await tester.pumpAndSettle();

      await tester.tap(find.byKey(const Key('knowledge-edit-notes.md')));
      await tester.pumpAndSettle();

      expect(find.byKey(const Key('knowledge-editor')), findsOneWidget);
      expect(find.byKey(const Key('knowledge-save-btn')), findsOneWidget);
    });

    testWidgets('delete knowledge shows confirmation dialog', (tester) async {
      final fakeService = _FakeSkillConfigService(
        knowledgeResult: [
          const KnowledgeInfo(filename: 'old.md', enabled: true),
        ],
      );

      await tester.pumpWidget(buildScreen(service: fakeService));
      await tester.pumpAndSettle();

      await tester.tap(find.byKey(const Key('knowledge-delete-old.md')));
      await tester.pumpAndSettle();

      expect(find.text('删除知识文件'), findsOneWidget);
    });
  });

  group('KnowledgeInfo', () {
    test('copyWith works', () {
      const info = KnowledgeInfo(filename: 'test.md', enabled: false);
      final copied = info.copyWith(enabled: true);
      expect(copied.filename, equals('test.md'));
      expect(copied.enabled, isTrue);
    });
  });
}
