import 'dart:convert';
import 'dart:io';

import 'package:path/path.dart' as p;

/// 知识文件信息模型
class KnowledgeInfo {
  const KnowledgeInfo({
    required this.filename,
    required this.enabled,
  });

  final String filename;
  final bool enabled;

  KnowledgeInfo copyWith({bool? enabled}) {
    return KnowledgeInfo(
      filename: filename,
      enabled: enabled ?? this.enabled,
    );
  }
}

/// 直接读写本地 managed-agent 数据目录的知识文件配置服务
///
/// 不依赖 Agent 进程，直接操作文件系统：
/// - user_knowledge/ 目录扫描 .md 文件
/// - knowledge_config.json 管理 disabled 列表
class SkillConfigService {
  SkillConfigService({String? homeDirectory}) : _homeDirectory = homeDirectory;

  final String? _homeDirectory;

  /// 获取 managed-agent 数据目录
  String? getAgentDataDir() {
    final home = _homeDirectory ?? Platform.environment['HOME'];
    if (home == null) return null;
    return p.join(
      home,
      'Library/Application Support/com.aistudio.rcClient/managed-agent',
    );
  }

  /// 读取所有知识文件：扫描 user_knowledge/ 目录 + 读取 knowledge_config.json 获取 disabled 列表
  Future<List<KnowledgeInfo>> loadKnowledge() async {
    final dataDir = getAgentDataDir();
    if (dataDir == null) return [];

    final knowledgeDir = Directory(p.join(dataDir, 'user_knowledge'));
    if (!knowledgeDir.existsSync()) return [];

    final disabledFiles = await _loadDisabledKnowledgeFiles(dataDir);

    final knowledge = <KnowledgeInfo>[];
    await for (final entity in knowledgeDir.list()) {
      if (entity is File && entity.path.endsWith('.md')) {
        final filename = p.basename(entity.path);
        final enabled = !disabledFiles.contains(filename);
        knowledge.add(KnowledgeInfo(filename: filename, enabled: enabled));
      }
    }

    knowledge.sort((a, b) => a.filename.compareTo(b.filename));
    return knowledge;
  }

  /// 切换知识文件启用/禁用：写入 knowledge_config.json
  Future<void> toggleKnowledge(String filename, bool enabled) async {
    final dataDir = getAgentDataDir();
    if (dataDir == null) throw Exception('Agent 数据目录不存在');

    final disabledFiles = await _loadDisabledKnowledgeFiles(dataDir);
    if (enabled) {
      disabledFiles.remove(filename);
    } else {
      disabledFiles.add(filename);
    }
    await _saveDisabledKnowledgeFiles(dataDir, disabledFiles);
  }

  /// 导入知识文件：从外部路径复制 .md 文件到 user_knowledge/ 目录
  Future<void> importKnowledgeFile(String sourcePath) async {
    final dataDir = getAgentDataDir();
    if (dataDir == null) throw Exception('Agent 数据目录不存在');

    final sourceFile = File(sourcePath);
    if (!sourceFile.existsSync()) throw Exception('源文件不存在');

    final filename = p.basename(sourcePath);
    if (!filename.endsWith('.md')) throw Exception('仅支持 .md 文件');

    final knowledgeDir = Directory(p.join(dataDir, 'user_knowledge'));
    if (!knowledgeDir.existsSync()) {
      knowledgeDir.createSync(recursive: true);
    }

    final destPath = p.join(knowledgeDir.path, filename);
    await sourceFile.copy(destPath);
  }

  /// 删除知识文件
  Future<void> deleteKnowledgeFile(String filename) async {
    final dataDir = getAgentDataDir();
    if (dataDir == null) throw Exception('Agent 数据目录不存在');

    final file = File(p.join(dataDir, 'user_knowledge', filename));
    if (file.existsSync()) {
      await file.delete();
    }

    final disabledFiles = await _loadDisabledKnowledgeFiles(dataDir);
    disabledFiles.remove(filename);
    await _saveDisabledKnowledgeFiles(dataDir, disabledFiles);
  }

  /// 读取知识文件内容
  Future<String> readKnowledgeContent(String filename) async {
    final dataDir = getAgentDataDir();
    if (dataDir == null) throw Exception('Agent 数据目录不存在');

    final file = File(p.join(dataDir, 'user_knowledge', filename));
    if (!file.existsSync()) throw Exception('文件不存在');
    return file.readAsString();
  }

  /// 写入知识文件内容
  Future<void> writeKnowledgeContent(String filename, String content) async {
    final dataDir = getAgentDataDir();
    if (dataDir == null) throw Exception('Agent 数据目录不存在');

    final file = File(p.join(dataDir, 'user_knowledge', filename));
    await file.writeAsString(content);
  }

  /// 使用 macOS 原生对话框选择文件（.md）
  Future<String?> pickMarkdownFile() async {
    final result = await Process.run('osascript', [
      '-e',
      'set theFile to choose file of type {"md", "txt"} with prompt "选择知识文件"',
      '-e',
      'return POSIX path of theFile',
    ]);
    if (result.exitCode != 0) return null;
    return (result.stdout as String).trim();
  }

  // ============== 私有方法 ==============

  Future<List<String>> _loadDisabledKnowledgeFiles(String dataDir) async {
    final file = File(p.join(dataDir, 'knowledge_config.json'));
    if (!file.existsSync()) return [];

    try {
      final content = await file.readAsString();
      final json = jsonDecode(content) as Map<String, dynamic>;
      final disabled = json['disabled_files'] as List<dynamic>? ?? [];
      return disabled.cast<String>().toList();
    } catch (_) {
      return [];
    }
  }

  Future<void> _saveDisabledKnowledgeFiles(
    String dataDir,
    List<String> disabledFiles,
  ) async {
    final file = File(p.join(dataDir, 'knowledge_config.json'));
    final json = jsonEncode({'disabled_files': disabledFiles});
    await file.writeAsString(json);
  }
}
