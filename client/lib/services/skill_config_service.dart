import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:path/path.dart' as p;

/// Skill 信息模型
class SkillInfo {
  const SkillInfo({
    required this.name,
    required this.description,
    required this.version,
    required this.enabled,
    required this.command,
    required this.args,
    required this.transport,
  });

  final String name;
  final String description;
  final String version;
  final bool enabled;
  final String command;
  final List<String> args;
  final String transport;

  SkillInfo copyWith({bool? enabled}) {
    return SkillInfo(
      name: name,
      description: description,
      version: version,
      enabled: enabled ?? this.enabled,
      command: command,
      args: args,
      transport: transport,
    );
  }
}

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

/// 验证状态枚举
enum SkillVerifyStatus { ok, failed, timeout }

/// 验证结果
class SkillVerifyResult {
  const SkillVerifyResult({
    required this.status,
    this.error,
    this.tools,
  });

  final SkillVerifyStatus status;
  final String? error;
  final List<String>? tools;
}

/// F089 重写：直接读写本地 managed-agent 数据目录的 Skill 配置服务
///
/// 不依赖 Agent HTTP API，直接操作文件系统：
/// - skills/ 目录扫描 skill.json
/// - skill-registry.json 管理 enabled 状态
/// - user_knowledge/ 目录扫描 .md 文件
/// - knowledge_config.json 管理 disabled 列表
/// - MCP stdio 验证
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

  /// 读取所有 skills：扫描 skills/ 目录 + 读取 skill-registry.json 获取 enabled 状态
  Future<List<SkillInfo>> loadSkills() async {
    final dataDir = getAgentDataDir();
    if (dataDir == null) return [];

    final skillsDir = Directory(p.join(dataDir, 'skills'));
    if (!skillsDir.existsSync()) return [];

    // 读取 registry 获取 enabled 状态
    final registry = await _loadSkillRegistry(dataDir);

    final skills = <SkillInfo>[];
    await for (final entity in skillsDir.list()) {
      if (entity is Directory) {
        final skillJsonFile = File(p.join(entity.path, 'skill.json'));
        if (skillJsonFile.existsSync()) {
          try {
            final content = await skillJsonFile.readAsString();
            final json = jsonDecode(content) as Map<String, dynamic>;
            final name = json['name'] as String? ?? '';
            final enabled = registry[name] ?? true;
            skills.add(SkillInfo(
              name: name,
              description: json['description'] as String? ?? '',
              version: json['version'] as String? ?? '',
              enabled: enabled,
              command: json['command'] as String? ?? '',
              args: (json['args'] as List<dynamic>?)
                      ?.cast<String>()
                      .toList() ??
                  [],
              transport: json['transport'] as String? ?? 'stdio',
            ));
          } catch (_) {
            // 跳过损坏的 skill.json
          }
        }
      }
    }

    skills.sort((a, b) => a.name.compareTo(b.name));
    return skills;
  }

  /// 读取所有知识文件：扫描 user_knowledge/ 目录 + 读取 knowledge_config.json 获取 disabled 列表
  Future<List<KnowledgeInfo>> loadKnowledge() async {
    final dataDir = getAgentDataDir();
    if (dataDir == null) return [];

    final knowledgeDir = Directory(p.join(dataDir, 'user_knowledge'));
    if (!knowledgeDir.existsSync()) return [];

    // 读取 disabled 列表
    final disabledFiles = await _loadDisabledKnowledgeFiles(dataDir);

    final knowledge = <KnowledgeInfo>[];
    await for (final entity in knowledgeDir.list()) {
      if (entity is File && entity.path.endsWith('.md')) {
        final filename = p.basename(entity.path);
        final enabled = !disabledFiles.contains(filename);
        knowledge.add(KnowledgeInfo(
          filename: filename,
          enabled: enabled,
        ));
      }
    }

    knowledge.sort((a, b) => a.filename.compareTo(b.filename));
    return knowledge;
  }

  /// 切换 skill 启用/禁用：写入 skill-registry.json
  Future<void> toggleSkill(String name, bool enabled) async {
    final dataDir = getAgentDataDir();
    if (dataDir == null) throw Exception('Agent 数据目录不存在');

    final registry = await _loadSkillRegistry(dataDir);
    registry[name] = enabled;
    await _saveSkillRegistry(dataDir, registry);
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

  /// 验证单个 skill：启动 command + args，发送 MCP initialize + tools/list 请求
  Future<SkillVerifyResult> verifySkill(SkillInfo skill) async {
    Process? process;
    try {
      process = await Process.start(
        skill.command,
        skill.args,
      );

      // 发送 initialize 请求
      final initResult = await _sendMcpRequest(
        process,
        1,
        'initialize',
        {
          'protocolVersion': '2024-11-05',
          'capabilities': <String, dynamic>{},
          'clientInfo': {'name': 'rc-client', 'version': '1.0.0'},
        },
        const Duration(seconds: 10),
      );

      if (initResult == null) {
        process.kill();
        return const SkillVerifyResult(
          status: SkillVerifyStatus.timeout,
          error: 'initialize 超时',
        );
      }

      // 发送 tools/list 请求
      final toolsResult = await _sendMcpRequest(
        process,
        2,
        'tools/list',
        <String, dynamic>{},
        const Duration(seconds: 10),
      );

      process.kill();

      if (toolsResult == null) {
        return const SkillVerifyResult(
          status: SkillVerifyStatus.timeout,
          error: 'tools/list 超时',
        );
      }

      final tools = <String>[];
      final resultTools = toolsResult['tools'] as List<dynamic>?;
      if (resultTools != null) {
        for (final tool in resultTools) {
          final name = (tool as Map<String, dynamic>)['name'] as String?;
          if (name != null) tools.add(name);
        }
      }

      return SkillVerifyResult(
        status: SkillVerifyStatus.ok,
        tools: tools,
      );
    } catch (e) {
      process?.kill();
      return SkillVerifyResult(
        status: SkillVerifyStatus.failed,
        error: e.toString(),
      );
    }
  }

  // ============== 私有方法 ==============

  /// 读取 skill-registry.json，返回 {name: enabled} map
  Future<Map<String, bool>> _loadSkillRegistry(String dataDir) async {
    final file = File(p.join(dataDir, 'skill-registry.json'));
    if (!file.existsSync()) return {};

    try {
      final content = await file.readAsString();
      final json = jsonDecode(content) as Map<String, dynamic>;
      final skills = json['skills'] as List<dynamic>? ?? [];
      final result = <String, bool>{};
      for (final s in skills) {
        final map = s as Map<String, dynamic>;
        final name = map['name'] as String?;
        final enabled = map['enabled'] as bool?;
        if (name != null && enabled != null) {
          result[name] = enabled;
        }
      }
      return result;
    } catch (_) {
      return {};
    }
  }

  /// 保存 skill-registry.json
  Future<void> _saveSkillRegistry(
    String dataDir,
    Map<String, bool> registry,
  ) async {
    final file = File(p.join(dataDir, 'skill-registry.json'));
    final skills = registry.entries
        .map((e) => {'name': e.key, 'enabled': e.value})
        .toList();
    final json = jsonEncode({'skills': skills});
    await file.writeAsString(json);
  }

  /// 读取 knowledge_config.json，返回 disabled_files 列表
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

  /// 保存 knowledge_config.json
  Future<void> _saveDisabledKnowledgeFiles(
    String dataDir,
    List<String> disabledFiles,
  ) async {
    final file = File(p.join(dataDir, 'knowledge_config.json'));
    final json = jsonEncode({'disabled_files': disabledFiles});
    await file.writeAsString(json);
  }

  /// 发送 MCP JSON-RPC 请求（LSP Content-Length 格式）并读取响应
  Future<Map<String, dynamic>?> _sendMcpRequest(
    Process process,
    int id,
    String method,
    Map<String, dynamic> params,
    Duration timeout,
  ) async {
    final request = jsonEncode({
      'jsonrpc': '2.0',
      'id': id,
      'method': method,
      'params': params,
    });

    final header = 'Content-Length: ${request.length}\r\n\r\n';
    process.stdin.write(header + request);

    try {
      final response = await _readMcpResponse(process.stdout, timeout);
      if (response == null) return null;

      final json = jsonDecode(response) as Map<String, dynamic>;
      return json['result'] as Map<String, dynamic>?;
    } catch (_) {
      return null;
    }
  }

  /// 从 stdout 读取 MCP 响应（解析 LSP Content-Length header）
  Future<String?> _readMcpResponse(
    Stream<List<int>> stdout,
    Duration timeout,
  ) async {
    final completer = Completer<String?>();
    final buffer = <int>[];
    late StreamSubscription<List<int>> subscription;

    subscription = stdout.listen(
      (data) {
        buffer.addAll(data);

        final result = _tryParseMcpMessage(buffer);
        if (result != null) {
          subscription.cancel();
          if (!completer.isCompleted) {
            completer.complete(result);
          }
        }
      },
      onError: (e) {
        subscription.cancel();
        if (!completer.isCompleted) {
          completer.complete(null);
        }
      },
      onDone: () {
        if (!completer.isCompleted) {
          completer.complete(null);
        }
      },
    );

    return completer.future.timeout(timeout, onTimeout: () {
      subscription.cancel();
      return null;
    });
  }

  /// 尝试从 buffer 解析 MCP 消息
  static String? _tryParseMcpMessage(List<int> buffer) {
    final headerEnd = _findSequence(buffer, '\r\n\r\n'.codeUnits);
    if (headerEnd == -1) return null;

    final headerStr = String.fromCharCodes(buffer.sublist(0, headerEnd));
    final contentLengthMatch =
        RegExp(r'Content-Length:\s*(\d+)').firstMatch(headerStr);
    if (contentLengthMatch == null) return null;

    final contentLength = int.parse(contentLengthMatch.group(1)!);
    final bodyStart = headerEnd + 4; // \r\n\r\n
    if (buffer.length < bodyStart + contentLength) return null;

    return String.fromCharCodes(
      buffer.sublist(bodyStart, bodyStart + contentLength),
    );
  }

  /// 在 buffer 中查找子序列的位置
  static int _findSequence(List<int> buffer, List<int> sequence) {
    for (var i = 0; i <= buffer.length - sequence.length; i++) {
      var found = true;
      for (var j = 0; j < sequence.length; j++) {
        if (buffer[i + j] != sequence[j]) {
          found = false;
          break;
        }
      }
      if (found) return i;
    }
    return -1;
  }
}
