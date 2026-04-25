import 'dart:async';

import 'package:flutter/material.dart';

import '../services/skill_config_service.dart';

/// 知识文件配置面板（直接读写本地文件，不依赖 Agent 进程）
class SkillConfigScreen extends StatefulWidget {
  const SkillConfigScreen({
    super.key,
    SkillConfigService? skillConfigService,
  }) : _skillConfigService = skillConfigService;

  final SkillConfigService? _skillConfigService;

  @override
  State<SkillConfigScreen> createState() => _SkillConfigScreenState();
}

class _SkillConfigScreenState extends State<SkillConfigScreen> {
  late final SkillConfigService _service;

  List<KnowledgeInfo> _knowledge = [];
  bool _loading = true;
  String? _errorMessage;
  bool _noDataDir = false;

  final Set<String> _togglingKnowledge = {};

  @override
  void initState() {
    super.initState();
    _service = widget._skillConfigService ?? SkillConfigService();
    unawaited(_loadData());
  }

  Future<void> _loadData() async {
    setState(() {
      _loading = true;
      _errorMessage = null;
      _noDataDir = false;
    });

    try {
      final dataDir = _service.getAgentDataDir();
      if (dataDir == null) {
        if (!mounted) return;
        setState(() {
          _noDataDir = true;
          _loading = false;
        });
        return;
      }

      final knowledge = await _service.loadKnowledge();
      if (!mounted) return;

      setState(() {
        _knowledge = knowledge;
        _loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _errorMessage = '加载失败：$e';
        _loading = false;
      });
    }
  }

  Future<void> _toggleKnowledge(KnowledgeInfo item, bool newValue) async {
    final key = item.filename;
    if (_togglingKnowledge.contains(key)) return;

    setState(() {
      _togglingKnowledge.add(key);
    });

    final index = _knowledge.indexWhere((k) => k.filename == key);
    if (index == -1) return;
    setState(() {
      _knowledge[index] = item.copyWith(enabled: newValue);
    });

    try {
      await _service.toggleKnowledge(key, newValue);
      if (!mounted) return;
      setState(() {
        _togglingKnowledge.remove(key);
      });
      _showHint('新建终端后生效');
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _togglingKnowledge.remove(key);
        _knowledge[index] = item;
      });
      _showError('切换失败：$e');
    }
  }

  Future<void> _importKnowledgeFile() async {
    try {
      final sourcePath = await _service.pickMarkdownFile();
      if (sourcePath == null) return;

      await _service.importKnowledgeFile(sourcePath);
      if (!mounted) return;
      _showSuccess('已导入知识文件');
      await _loadData();
    } catch (e) {
      if (!mounted) return;
      _showError('导入失败：$e');
    }
  }

  Future<void> _deleteKnowledgeFile(KnowledgeInfo item) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('删除知识文件'),
        content: Text('确定要删除「${item.filename}」吗？此操作不可撤销。'),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(false),
            child: const Text('取消'),
          ),
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(true),
            child: Text(
              '删除',
              style: TextStyle(color: Theme.of(ctx).colorScheme.error),
            ),
          ),
        ],
      ),
    );

    if (confirmed != true || !mounted) return;

    try {
      await _service.deleteKnowledgeFile(item.filename);
      if (!mounted) return;
      _showSuccess('已删除');
      await _loadData();
    } catch (e) {
      if (!mounted) return;
      _showError('删除失败：$e');
    }
  }

  Future<void> _editKnowledgeFile(KnowledgeInfo item) async {
    try {
      final content = await _service.readKnowledgeContent(item.filename);
      if (!mounted) return;

      final controller = TextEditingController(text: content);
      final saved = await showDialog<bool>(
        context: context,
        builder: (ctx) => AlertDialog(
          title: Text(item.filename),
          content: SizedBox(
            width: 500,
            height: 400,
            child: TextField(
              key: const Key('knowledge-editor'),
              controller: controller,
              maxLines: null,
              expands: true,
              decoration: const InputDecoration(
                border: OutlineInputBorder(),
                hintText: '编辑内容...',
              ),
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(ctx).pop(false),
              child: const Text('取消'),
            ),
            FilledButton(
              key: const Key('knowledge-save-btn'),
              onPressed: () => Navigator.of(ctx).pop(true),
              child: const Text('保存'),
            ),
          ],
        ),
      );

      if (saved != true || !mounted) return;
      await _service.writeKnowledgeContent(item.filename, controller.text);
      _showSuccess('已保存');
    } catch (e) {
      if (!mounted) return;
      _showError('编辑失败：$e');
    }
  }

  void _showHint(String message) {
    ScaffoldMessenger.of(context).clearSnackBars();
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(message), duration: const Duration(seconds: 2)),
    );
  }

  void _showError(String message) {
    ScaffoldMessenger.of(context).clearSnackBars();
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(message), duration: const Duration(seconds: 2)),
    );
  }

  void _showSuccess(String message) {
    ScaffoldMessenger.of(context).clearSnackBars();
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(message), duration: const Duration(seconds: 2)),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('知识管理')),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _noDataDir
              ? _buildNoDataDirState()
              : _errorMessage != null
                  ? _buildErrorState()
                  : _buildKnowledgeList(),
    );
  }

  Widget _buildNoDataDirState() {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.folder_off_outlined, size: 48,
                color: Theme.of(context).colorScheme.onSurfaceVariant),
            const SizedBox(height: 16),
            Text('未找到 Agent 配置目录',
                textAlign: TextAlign.center,
                style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                    color: Theme.of(context).colorScheme.onSurfaceVariant)),
            const SizedBox(height: 16),
            FilledButton(
              key: const Key('knowledge-config-retry'),
              onPressed: _loadData,
              child: const Text('重试'),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildErrorState() {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.error_outline, size: 48,
                color: Theme.of(context).colorScheme.error),
            const SizedBox(height: 16),
            Text(_errorMessage!,
                textAlign: TextAlign.center,
                style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                    color: Theme.of(context).colorScheme.onSurfaceVariant)),
            const SizedBox(height: 16),
            FilledButton(
              key: const Key('knowledge-config-retry'),
              onPressed: _loadData,
              child: const Text('重试'),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildKnowledgeList() {
    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
          child: SizedBox(
            width: double.infinity,
            child: OutlinedButton.icon(
              key: const Key('import-knowledge-btn'),
              onPressed: () => unawaited(_importKnowledgeFile()),
              icon: const Icon(Icons.add),
              label: const Text('导入 .md 文件'),
            ),
          ),
        ),
        Expanded(
          child: _knowledge.isEmpty
              ? Center(
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Icon(Icons.menu_book_outlined, size: 48,
                          color: Theme.of(context).colorScheme.onSurfaceVariant),
                      const SizedBox(height: 16),
                      Text('暂无知识文件，点击上方按钮导入',
                          style: Theme.of(context).textTheme.bodyLarge?.copyWith(
                              color: Theme.of(context).colorScheme.onSurfaceVariant)),
                    ],
                  ),
                )
              : ListView.builder(
                  itemCount: _knowledge.length,
                  itemBuilder: (context, index) {
                    final item = _knowledge[index];
                    final isToggling = _togglingKnowledge.contains(item.filename);
                    return ListTile(
                      key: Key('knowledge-${item.filename}'),
                      title: Text(item.filename),
                      trailing: Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          IconButton(
                            key: Key('knowledge-edit-${item.filename}'),
                            icon: const Icon(Icons.edit_outlined, size: 20),
                            tooltip: '编辑',
                            onPressed: () =>
                                unawaited(_editKnowledgeFile(item)),
                          ),
                          IconButton(
                            key: Key('knowledge-delete-${item.filename}'),
                            icon: Icon(Icons.delete_outline, size: 20,
                                color: Theme.of(context).colorScheme.error),
                            tooltip: '删除',
                            onPressed: () =>
                                unawaited(_deleteKnowledgeFile(item)),
                          ),
                          Switch(
                            key: Key('knowledge-switch-${item.filename}'),
                            value: item.enabled,
                            onChanged: isToggling
                                ? null
                                : (value) =>
                                    unawaited(_toggleKnowledge(item, value)),
                          ),
                        ],
                      ),
                    );
                  },
                ),
        ),
      ],
    );
  }
}
