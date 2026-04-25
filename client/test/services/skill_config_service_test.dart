import 'dart:convert';
import 'dart:io';

import 'package:path/path.dart' as p;
import 'package:flutter_test/flutter_test.dart';
import 'package:rc_client/services/skill_config_service.dart';

/// 测试用子类，直接指定数据目录
class _TestSkillConfigService extends SkillConfigService {
  _TestSkillConfigService(this._dataDir) : super(homeDirectory: '');

  final String _dataDir;

  @override
  String? getAgentDataDir() => _dataDir;
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  group('SkillConfigService', () {
    late Directory tmpDir;
    late String dataDir;

    setUp(() async {
      tmpDir = await Directory.systemTemp.createTemp('skill_config_test_');
      dataDir = p.join(tmpDir.path, 'managed-agent');
    });

    tearDown(() async {
      await tmpDir.delete(recursive: true);
    });

    group('loadKnowledge', () {
      test('returns empty when knowledge dir is empty', () async {
        await Directory(p.join(dataDir, 'user_knowledge')).create(recursive: true);
        final service = _TestSkillConfigService(dataDir);

        final result = await service.loadKnowledge();
        expect(result, isEmpty);
      });

      test('reads .md files and respects disabled list', () async {
        final dataDir = p.join(tmpDir.path, 'managed-agent');
        final knowledgeDir = p.join(dataDir, 'user_knowledge');
        await Directory(knowledgeDir).create(recursive: true);

        await File(p.join(knowledgeDir, 'guide.md')).writeAsString('# Guide');
        await File(p.join(knowledgeDir, 'notes.md')).writeAsString('# Notes');
        await File(p.join(knowledgeDir, 'readme.txt')).writeAsString('ignored');

        await File(p.join(dataDir, 'knowledge_config.json')).writeAsString(
          jsonEncode({'disabled_files': ['guide.md']}),
        );

        final service = _TestSkillConfigService(dataDir);
        final result = await service.loadKnowledge();

        expect(result.length, equals(2));
        expect(result[0].filename, equals('guide.md'));
        expect(result[0].enabled, isFalse);
        expect(result[1].filename, equals('notes.md'));
        expect(result[1].enabled, isTrue);
      });
    });

    group('toggleKnowledge', () {
      test('disables a knowledge file', () async {
        final dataDir = p.join(tmpDir.path, 'managed-agent');
        await Directory(p.join(dataDir, 'user_knowledge')).create(recursive: true);
        await File(p.join(dataDir, 'knowledge_config.json'))
            .writeAsString('{"disabled_files":[]}');

        final service = _TestSkillConfigService(dataDir);
        await service.toggleKnowledge('guide.md', false);

        final config = jsonDecode(
          await File(p.join(dataDir, 'knowledge_config.json')).readAsString(),
        ) as Map<String, dynamic>;
        expect(config['disabled_files'], contains('guide.md'));
      });

      test('enables a knowledge file', () async {
        final dataDir = p.join(tmpDir.path, 'managed-agent');
        await Directory(p.join(dataDir, 'user_knowledge')).create(recursive: true);
        await File(p.join(dataDir, 'knowledge_config.json')).writeAsString(
          jsonEncode({'disabled_files': ['guide.md']}),
        );

        final service = _TestSkillConfigService(dataDir);
        await service.toggleKnowledge('guide.md', true);

        final config = jsonDecode(
          await File(p.join(dataDir, 'knowledge_config.json')).readAsString(),
        ) as Map<String, dynamic>;
        expect(config['disabled_files'], isNot(contains('guide.md')));
      });
    });

    group('importKnowledgeFile', () {
      test('copies .md file to user_knowledge directory', () async {
        final dataDir = p.join(tmpDir.path, 'managed-agent');
        await Directory(p.join(dataDir, 'user_knowledge')).create(recursive: true);

        final sourceFile = File(p.join(tmpDir.path, 'source.md'));
        await sourceFile.writeAsString('# Source');

        final service = _TestSkillConfigService(dataDir);
        await service.importKnowledgeFile(sourceFile.path);

        final destFile = File(p.join(dataDir, 'user_knowledge', 'source.md'));
        expect(destFile.existsSync(), isTrue);
        expect(await destFile.readAsString(), equals('# Source'));
      });

      test('throws for non-.md files', () async {
        final dataDir = p.join(tmpDir.path, 'managed-agent');
        await Directory(p.join(dataDir, 'user_knowledge')).create(recursive: true);

        final sourceFile = File(p.join(tmpDir.path, 'source.txt'));
        await sourceFile.writeAsString('text');

        final service = _TestSkillConfigService(dataDir);
        expect(
          () => service.importKnowledgeFile(sourceFile.path),
          throwsException,
        );
      });
    });

    group('deleteKnowledgeFile', () {
      test('deletes file and removes from disabled list', () async {
        final dataDir = p.join(tmpDir.path, 'managed-agent');
        final knowledgeDir = p.join(dataDir, 'user_knowledge');
        await Directory(knowledgeDir).create(recursive: true);

        await File(p.join(knowledgeDir, 'guide.md')).writeAsString('# Guide');
        await File(p.join(dataDir, 'knowledge_config.json')).writeAsString(
          jsonEncode({'disabled_files': ['guide.md']}),
        );

        final service = _TestSkillConfigService(dataDir);
        await service.deleteKnowledgeFile('guide.md');

        expect(File(p.join(knowledgeDir, 'guide.md')).existsSync(), isFalse);

        final config = jsonDecode(
          await File(p.join(dataDir, 'knowledge_config.json')).readAsString(),
        ) as Map<String, dynamic>;
        expect(config['disabled_files'], isNot(contains('guide.md')));
      });
    });

    group('readKnowledgeContent / writeKnowledgeContent', () {
      test('reads and writes content', () async {
        final dataDir = p.join(tmpDir.path, 'managed-agent');
        final knowledgeDir = p.join(dataDir, 'user_knowledge');
        await Directory(knowledgeDir).create(recursive: true);

        await File(p.join(knowledgeDir, 'notes.md')).writeAsString('# Old');

        final service = _TestSkillConfigService(dataDir);

        final content = await service.readKnowledgeContent('notes.md');
        expect(content, equals('# Old'));

        await service.writeKnowledgeContent('notes.md', '# New');
        expect(
          await File(p.join(knowledgeDir, 'notes.md')).readAsString(),
          equals('# New'),
        );
      });
    });
  });
}
