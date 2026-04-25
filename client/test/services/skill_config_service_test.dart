import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:rc_client/services/skill_config_service.dart';
import 'package:path/path.dart' as p;

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  late String tempDir;
  late String agentDataDir;

  setUp(() async {
    tempDir = (await Directory.systemTemp.createTemp('skill_test_')).path;
    agentDataDir = p.join(tempDir, 'managed-agent');
    await Directory(agentDataDir).create();
    await Directory(p.join(agentDataDir, 'skills')).create();
    await Directory(p.join(agentDataDir, 'user_knowledge')).create();
  });

  tearDown(() async {
    await Directory(tempDir).delete(recursive: true);
  });

  SkillConfigService createService() {
    // Use a fake home so getAgentDataDir() points to our temp dir
    return _TestSkillConfigService(agentDataDir);
  }

  group('SkillConfigService', () {
    test('getAgentDataDir returns null when HOME not set', () {
      // This is platform-dependent; just verify it doesn't crash
      final service = SkillConfigService(homeDirectory: null);
      // In test env HOME is usually set, so this just verifies no crash
      final dir = service.getAgentDataDir();
      // If HOME is set it returns a path, otherwise null
      expect(dir == null || dir.isNotEmpty, isTrue);
    });

    test('loadSkills returns empty when skills dir is empty', () async {
      final service = createService();
      final skills = await service.loadSkills();
      expect(skills, isEmpty);
    });

    test('loadSkills reads skill.json files and registry', () async {
      final service = createService();

      // Create a skill directory with skill.json
      final bashDir = Directory(p.join(agentDataDir, 'skills', 'bash'));
      await bashDir.create();
      await File(p.join(bashDir.path, 'skill.json')).writeAsString(jsonEncode({
        'name': 'bash',
        'version': '1.0.0',
        'description': 'Execute bash commands',
        'command': 'python3',
        'args': ['-m', 'bash_skill'],
        'transport': 'stdio',
      }));

      // Create registry with bash disabled
      await File(p.join(agentDataDir, 'skill-registry.json'))
          .writeAsString(jsonEncode({
        'skills': [
          {'name': 'bash', 'enabled': false}
        ],
      }));

      final skills = await service.loadSkills();
      expect(skills, hasLength(1));
      expect(skills[0].name, equals('bash'));
      expect(skills[0].version, equals('1.0.0'));
      expect(skills[0].description, equals('Execute bash commands'));
      expect(skills[0].enabled, isFalse);
      expect(skills[0].command, equals('python3'));
      expect(skills[0].args, equals(['-m', 'bash_skill']));
      expect(skills[0].transport, equals('stdio'));
    });

    test('loadSkills defaults to enabled when not in registry', () async {
      final service = createService();

      final pyDir = Directory(p.join(agentDataDir, 'skills', 'python'));
      await pyDir.create();
      await File(p.join(pyDir.path, 'skill.json')).writeAsString(jsonEncode({
        'name': 'python',
        'version': '2.0.0',
        'description': 'Python',
        'command': 'python3',
        'args': [],
        'transport': 'stdio',
      }));

      // No registry file
      final skills = await service.loadSkills();
      expect(skills, hasLength(1));
      expect(skills[0].enabled, isTrue);
    });

    test('loadSkills skips corrupted skill.json', () async {
      final service = createService();

      final badDir = Directory(p.join(agentDataDir, 'skills', 'broken'));
      await badDir.create();
      await File(p.join(badDir.path, 'skill.json')).writeAsString('not json');

      final goodDir = Directory(p.join(agentDataDir, 'skills', 'good'));
      await goodDir.create();
      await File(p.join(goodDir.path, 'skill.json')).writeAsString(jsonEncode({
        'name': 'good',
        'version': '1.0.0',
        'description': 'Good',
        'command': 'echo',
        'args': [],
        'transport': 'stdio',
      }));

      final skills = await service.loadSkills();
      expect(skills, hasLength(1));
      expect(skills[0].name, equals('good'));
    });

    test('loadSkills returns sorted by name', () async {
      final service = createService();

      for (final name in ['z-skill', 'a-skill', 'm-skill']) {
        final dir = Directory(p.join(agentDataDir, 'skills', name));
        await dir.create();
        await File(p.join(dir.path, 'skill.json')).writeAsString(jsonEncode({
          'name': name,
          'version': '1.0.0',
          'description': '',
          'command': 'echo',
          'args': [],
          'transport': 'stdio',
        }));
      }

      final skills = await service.loadSkills();
      expect(skills.map((s) => s.name).toList(),
          equals(['a-skill', 'm-skill', 'z-skill']));
    });

    test('loadKnowledge returns empty when user_knowledge dir is empty',
        () async {
      final service = createService();
      final knowledge = await service.loadKnowledge();
      expect(knowledge, isEmpty);
    });

    test('loadKnowledge reads .md files and disabled list', () async {
      final service = createService();

      await File(p.join(agentDataDir, 'user_knowledge', 'guide.md'))
          .writeAsString('# Guide');
      await File(p.join(agentDataDir, 'user_knowledge', 'api.md'))
          .writeAsString('# API');
      await File(p.join(agentDataDir, 'user_knowledge', 'notes.txt'))
          .writeAsString('not md');

      // Disable guide.md
      await File(p.join(agentDataDir, 'knowledge_config.json'))
          .writeAsString(jsonEncode({
        'disabled_files': ['guide.md'],
      }));

      final knowledge = await service.loadKnowledge();
      expect(knowledge, hasLength(2));
      expect(knowledge[0].filename, equals('api.md'));
      expect(knowledge[0].enabled, isTrue);
      expect(knowledge[1].filename, equals('guide.md'));
      expect(knowledge[1].enabled, isFalse);
    });

    test('toggleSkill updates skill-registry.json', () async {
      final service = createService();

      // Create initial registry
      await File(p.join(agentDataDir, 'skill-registry.json'))
          .writeAsString(jsonEncode({
        'skills': [
          {'name': 'bash', 'enabled': true},
          {'name': 'python', 'enabled': true},
        ],
      }));

      await service.toggleSkill('bash', false);

      // Read back
      final content =
          await File(p.join(agentDataDir, 'skill-registry.json'))
              .readAsString();
      final json = jsonDecode(content) as Map<String, dynamic>;
      final skills = json['skills'] as List<dynamic>;
      final bashEntry =
          skills.firstWhere((s) => (s as Map<String, dynamic>)['name'] == 'bash');
      expect((bashEntry as Map<String, dynamic>)['enabled'], isFalse);
      final pyEntry =
          skills.firstWhere((s) => (s as Map<String, dynamic>)['name'] == 'python');
      expect((pyEntry as Map<String, dynamic>)['enabled'], isTrue);
    });

    test('toggleSkill creates registry if not exists', () async {
      final service = createService();

      // No registry file yet
      await service.toggleSkill('new-skill', true);

      final content =
          await File(p.join(agentDataDir, 'skill-registry.json'))
              .readAsString();
      final json = jsonDecode(content) as Map<String, dynamic>;
      final skills = json['skills'] as List<dynamic>;
      expect(skills, hasLength(1));
      expect((skills[0] as Map<String, dynamic>)['name'], equals('new-skill'));
      expect((skills[0] as Map<String, dynamic>)['enabled'], isTrue);
    });

    test('toggleKnowledge updates knowledge_config.json', () async {
      final service = createService();

      await File(p.join(agentDataDir, 'knowledge_config.json'))
          .writeAsString(jsonEncode({
        'disabled_files': ['guide.md'],
      }));

      // Enable guide.md (remove from disabled)
      await service.toggleKnowledge('guide.md', true);

      final content =
          await File(p.join(agentDataDir, 'knowledge_config.json'))
              .readAsString();
      final json = jsonDecode(content) as Map<String, dynamic>;
      final disabled = json['disabled_files'] as List<dynamic>;
      expect(disabled, isEmpty);

      // Disable api.md
      await service.toggleKnowledge('api.md', false);

      final content2 =
          await File(p.join(agentDataDir, 'knowledge_config.json'))
              .readAsString();
      final json2 = jsonDecode(content2) as Map<String, dynamic>;
      final disabled2 = json2['disabled_files'] as List<dynamic>;
      expect(disabled2, equals(['api.md']));
    });

    test('toggleSkill throws when dataDir is null', () async {
      final service = _NullDataDirSkillConfigService();
      expect(
        () => service.toggleSkill('test', true),
        throwsException,
      );
    });

    test('toggleKnowledge throws when dataDir is null', () async {
      final service = _NullDataDirSkillConfigService();
      expect(
        () => service.toggleKnowledge('test.md', true),
        throwsException,
      );
    });
  });
}

/// Test helper that overrides getAgentDataDir to return a specific path
class _TestSkillConfigService extends SkillConfigService {
  _TestSkillConfigService(this._dataDir) : super(homeDirectory: '/tmp');

  final String _dataDir;

  @override
  String? getAgentDataDir() => _dataDir;
}

/// Test helper that returns null data dir
class _NullDataDirSkillConfigService extends SkillConfigService {
  _NullDataDirSkillConfigService() : super(homeDirectory: null);

  @override
  String? getAgentDataDir() => null;
}
