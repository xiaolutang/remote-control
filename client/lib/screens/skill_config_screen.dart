import 'dart:async';

import 'package:flutter/material.dart';

import '../services/skill_config_service.dart';

/// F089 重写：Agent 技能/知识文件配置面板（直接读写本地文件，不依赖 HTTP API）
class SkillConfigScreen extends StatefulWidget {
  const SkillConfigScreen({
    super.key,
    SkillConfigService? skillConfigService,
  }) : _skillConfigService = skillConfigService;

  final SkillConfigService? _skillConfigService;

  @override
  State<SkillConfigScreen> createState() => _SkillConfigScreenState();
}

class _SkillConfigScreenState extends State<SkillConfigScreen>
    with SingleTickerProviderStateMixin {
  late final TabController _tabController;
  late final SkillConfigService _service;

  List<SkillInfo> _skills = [];
  List<KnowledgeInfo> _knowledge = [];
  bool _loading = true;
  String? _errorMessage;
  bool _noDataDir = false;

  // 追踪正在切换中的项，避免重复操作
  final Set<String> _togglingSkills = {};
  final Set<String> _togglingKnowledge = {};

  // 验证状态：skill name -> verify result
  final Map<String, SkillVerifyResult> _verifyResults = {};
  bool _verifyingAll = false;

  @override
  void initState() {
    super.initState();
    _tabController = TabController(length: 2, vsync: this);
    _service =
        widget._skillConfigService ?? SkillConfigService();
    unawaited(_loadData());
  }

  @override
  void dispose() {
    _tabController.dispose();
    super.dispose();
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

      final results = await Future.wait([
        _service.loadSkills(),
        _service.loadKnowledge(),
      ]);

      if (!mounted) return;

      setState(() {
        _skills = results[0] as List<SkillInfo>;
        _knowledge = results[1] as List<KnowledgeInfo>;
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

  Future<void> _toggleSkill(SkillInfo skill, bool newValue) async {
    final key = skill.name;
    if (_togglingSkills.contains(key)) return;

    setState(() {
      _togglingSkills.add(key);
    });

    // 乐观更新
    final index = _skills.indexWhere((s) => s.name == key);
    if (index == -1) return;
    setState(() {
      _skills[index] = skill.copyWith(enabled: newValue);
    });

    try {
      await _service.toggleSkill(key, newValue);
      if (!mounted) return;
      setState(() {
        _togglingSkills.remove(key);
      });
      _showRestartHint();
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _togglingSkills.remove(key);
        _skills[index] = skill;
      });
      _showError('切换失败：$e');
    }
  }

  Future<void> _toggleKnowledge(KnowledgeInfo item, bool newValue) async {
    final key = item.filename;
    if (_togglingKnowledge.contains(key)) return;

    setState(() {
      _togglingKnowledge.add(key);
    });

    // 乐观更新
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
      _showRestartHint();
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _togglingKnowledge.remove(key);
        _knowledge[index] = item;
      });
      _showError('切换失败：$e');
    }
  }

  Future<void> _verifyAll() async {
    if (_verifyingAll || _skills.isEmpty) return;

    setState(() {
      _verifyingAll = true;
      _verifyResults.clear();
    });

    for (final skill in _skills) {
      final result = await _service.verifySkill(skill);
      if (!mounted) {
        _verifyingAll = false;
        return;
      }
      setState(() {
        _verifyResults[skill.name] = result;
      });
    }

    setState(() {
      _verifyingAll = false;
    });
  }

  // ============== 新增：导入/删除/编辑 ==============

  Future<void> _importKnowledgeFile() async {
    try {
      final sourcePath = await _service.pickMarkdownFile();
      if (sourcePath == null) return; // 用户取消

      await _service.importKnowledgeFile(sourcePath);
      if (!mounted) return;
      _showSuccess('已导入知识文件');
      await _loadData();
    } catch (e) {
      if (!mounted) return;
      _showError('导入失败：$e');
    }
  }

  Future<void> _importSkillDirectory() async {
    try {
      final sourceDir = await _service.pickSkillDirectory();
      if (sourceDir == null) return; // 用户取消

      await _service.importSkillDirectory(sourceDir);
      if (!mounted) return;
      _showSuccess('已导入技能');
      await _loadData();
    } catch (e) {
      if (!mounted) return;
      _showError('导入失败：$e');
    }
  }

  Future<void> _deleteSkill(SkillInfo skill) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('删除技能'),
        content: Text('确定要删除技能「${skill.name}」吗？此操作不可撤销。'),
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
      await _service.deleteSkill(skill.name);
      if (!mounted) return;
      _showSuccess('已删除技能');
      await _loadData();
    } catch (e) {
      if (!mounted) return;
      _showError('删除失败：$e');
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
      _showSuccess('已删除知识文件');
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

  // ============== UI 辅助 ==============

  void _showRestartHint() {
    ScaffoldMessenger.of(context).clearSnackBars();
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(
        content: Text('重启 Agent 后生效'),
        duration: Duration(seconds: 2),
      ),
    );
  }

  void _showError(String message) {
    ScaffoldMessenger.of(context).clearSnackBars();
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(message),
        duration: const Duration(seconds: 2),
      ),
    );
  }

  void _showSuccess(String message) {
    ScaffoldMessenger.of(context).clearSnackBars();
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(message),
        duration: const Duration(seconds: 2),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('技能管理'),
        actions: [
          if (!_loading && _errorMessage == null && !_noDataDir)
            IconButton(
              key: const Key('verify-all-btn'),
              onPressed: _verifyingAll ? null : () => unawaited(_verifyAll()),
              icon: _verifyingAll
                  ? const SizedBox(
                      width: 20,
                      height: 20,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Icon(Icons.verified),
              tooltip: '验证全部',
            ),
        ],
        bottom: TabBar(
          controller: _tabController,
          tabs: const [
            Tab(text: '技能'),
            Tab(text: '知识文件'),
          ],
        ),
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _noDataDir
              ? _buildNoDataDirState()
              : _errorMessage != null
                  ? _buildErrorState()
                  : TabBarView(
                      controller: _tabController,
                      children: [
                        _buildSkillList(),
                        _buildKnowledgeList(),
                      ],
                    ),
    );
  }

  Widget _buildNoDataDirState() {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(
              Icons.folder_off_outlined,
              size: 48,
              color: Theme.of(context).colorScheme.onSurfaceVariant,
            ),
            const SizedBox(height: 16),
            Text(
              '未找到 Agent 配置目录',
              textAlign: TextAlign.center,
              style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                    color: Theme.of(context).colorScheme.onSurfaceVariant,
                  ),
            ),
            const SizedBox(height: 16),
            FilledButton(
              key: const Key('skill-config-retry'),
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
            Icon(
              Icons.error_outline,
              size: 48,
              color: Theme.of(context).colorScheme.error,
            ),
            const SizedBox(height: 16),
            Text(
              _errorMessage!,
              textAlign: TextAlign.center,
              style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                    color: Theme.of(context).colorScheme.onSurfaceVariant,
                  ),
            ),
            const SizedBox(height: 16),
            FilledButton(
              key: const Key('skill-config-retry'),
              onPressed: _loadData,
              child: const Text('重试'),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildSkillList() {
    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
          child: SizedBox(
            width: double.infinity,
            child: OutlinedButton.icon(
              key: const Key('import-skill-btn'),
              onPressed: () => unawaited(_importSkillDirectory()),
              icon: const Icon(Icons.add),
              label: const Text('导入 Skill 目录'),
            ),
          ),
        ),
        Expanded(
          child: _skills.isEmpty
              ? _buildEmptyState('暂无技能，点击上方按钮导入')
              : ListView.builder(
                  itemCount: _skills.length,
                  itemBuilder: (context, index) {
                    final skill = _skills[index];
                    final isToggling = _togglingSkills.contains(skill.name);
                    final verifyResult = _verifyResults[skill.name];
                    return Dismissible(
                      key: Key('skill-dismiss-${skill.name}'),
                      direction: DismissDirection.endToStart,
                      background: Container(
                        color: Theme.of(context).colorScheme.error,
                        alignment: Alignment.centerRight,
                        padding: const EdgeInsets.only(right: 16),
                        child: const Icon(Icons.delete, color: Colors.white),
                      ),
                      confirmDismiss: (_) async {
                        await _deleteSkill(skill);
                        return false; // 手动处理删除
                      },
                      child: ListTile(
                        key: Key('skill-${skill.name}'),
                        title: Row(
                          children: [
                            Text(skill.name),
                            const SizedBox(width: 8),
                            if (skill.version.isNotEmpty)
                              Text(
                                'v${skill.version}',
                                style:
                                    Theme.of(context).textTheme.bodySmall?.copyWith(
                                          color: Theme.of(context)
                                              .colorScheme
                                              .onSurfaceVariant,
                                        ),
                              ),
                            const SizedBox(width: 8),
                            _buildVerifyIcon(verifyResult),
                          ],
                        ),
                        subtitle: skill.description.isNotEmpty
                            ? Text(skill.description,
                                maxLines: 2, overflow: TextOverflow.ellipsis)
                            : null,
                        trailing: Switch(
                          key: Key('skill-switch-${skill.name}'),
                          value: skill.enabled,
                          onChanged: isToggling
                              ? null
                              : (value) => unawaited(_toggleSkill(skill, value)),
                        ),
                      ),
                    );
                  },
                ),
        ),
      ],
    );
  }

  Widget _buildVerifyIcon(SkillVerifyResult? result) {
    if (result == null) return const SizedBox.shrink();

    switch (result.status) {
      case SkillVerifyStatus.ok:
        return const Icon(Icons.check_circle, size: 16, color: Colors.green);
      case SkillVerifyStatus.failed:
        return Tooltip(
          message: result.error ?? '验证失败',
          child: const Icon(Icons.error, size: 16, color: Colors.red),
        );
      case SkillVerifyStatus.timeout:
        return Tooltip(
          message: result.error ?? '超时',
          child:
              const Icon(Icons.access_time, size: 16, color: Colors.orange),
        );
    }
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
              ? _buildEmptyState('暂无知识文件，点击上方按钮导入')
              : ListView.builder(
                  itemCount: _knowledge.length,
                  itemBuilder: (context, index) {
                    final item = _knowledge[index];
                    final isToggling = _togglingKnowledge.contains(item.filename);
                    return Dismissible(
                      key: Key('knowledge-dismiss-${item.filename}'),
                      direction: DismissDirection.endToStart,
                      background: Container(
                        color: Theme.of(context).colorScheme.error,
                        alignment: Alignment.centerRight,
                        padding: const EdgeInsets.only(right: 16),
                        child: const Icon(Icons.delete, color: Colors.white),
                      ),
                      confirmDismiss: (_) async {
                        await _deleteKnowledgeFile(item);
                        return false;
                      },
                      child: ListTile(
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
                      ),
                    );
                  },
                ),
        ),
      ],
    );
  }

  Widget _buildEmptyState(String message) {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(
            Icons.inbox_outlined,
            size: 48,
            color: Theme.of(context).colorScheme.onSurfaceVariant,
          ),
          const SizedBox(height: 16),
          Text(
            message,
            style: Theme.of(context).textTheme.bodyLarge?.copyWith(
                  color: Theme.of(context).colorScheme.onSurfaceVariant,
                ),
          ),
        ],
      ),
    );
  }
}
