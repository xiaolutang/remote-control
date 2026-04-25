import 'dart:async';

import 'package:flutter/material.dart';

import '../services/desktop_agent_http_client.dart';

/// F089: Agent 技能/知识文件配置面板
class SkillConfigScreen extends StatefulWidget {
  const SkillConfigScreen({
    super.key,
    this.agentPort,
    this.httpClient,
  });

  /// 已知的 Agent HTTP 端口（可选，不传则自动发现）
  final int? agentPort;

  /// 可注入的 HTTP 客户端（测试用）
  final DesktopAgentHttpClient? httpClient;

  @override
  State<SkillConfigScreen> createState() => _SkillConfigScreenState();
}

class _SkillConfigScreenState extends State<SkillConfigScreen>
    with SingleTickerProviderStateMixin {
  late final TabController _tabController;
  late final DesktopAgentHttpClient _httpClient;

  int? _resolvedPort;
  List<SkillItem> _skills = [];
  List<KnowledgeItem> _knowledge = [];
  bool _loading = true;
  String? _errorMessage;
  // 追踪正在切换中的项，避免重复操作
  final Set<String> _togglingSkills = {};
  final Set<String> _togglingKnowledge = {};

  @override
  void initState() {
    super.initState();
    _tabController = TabController(length: 2, vsync: this);
    _httpClient = widget.httpClient ?? DesktopAgentHttpClient();
    unawaited(_loadData());
  }

  @override
  void dispose() {
    _tabController.dispose();
    _httpClient.close();
    super.dispose();
  }

  Future<int?> _resolvePort() async {
    if (_resolvedPort != null) return _resolvedPort;
    if (widget.agentPort != null) {
      _resolvedPort = widget.agentPort;
      return _resolvedPort;
    }
    final status = await _httpClient.discoverAgent();
    if (status != null && status.port > 0) {
      _resolvedPort = status.port;
      return _resolvedPort;
    }
    return null;
  }

  Future<void> _loadData() async {
    setState(() {
      _loading = true;
      _errorMessage = null;
    });

    try {
      final port = await _resolvePort();
      if (port == null) {
        if (!mounted) return;
        setState(() {
          _errorMessage = '未发现本地 Agent，请确认 Agent 已启动';
          _loading = false;
        });
        return;
      }

      final results = await Future.wait([
        _httpClient.getSkills(port),
        _httpClient.getKnowledge(port),
      ]);

      if (!mounted) return;

      setState(() {
        _skills = results[0] as List<SkillItem>;
        _knowledge = results[1] as List<KnowledgeItem>;
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

  Future<void> _toggleSkill(SkillItem skill, bool newValue) async {
    final key = skill.name;
    final port = _resolvedPort;
    if (_togglingSkills.contains(key) || port == null) return;

    setState(() {
      _togglingSkills.add(key);
    });

    // 乐观更新
    final index = _skills.indexWhere((s) => s.name == key);
    if (index == -1) return;
    setState(() {
      _skills[index] = skill.copyWith(enabled: newValue);
    });

    final ok = await _httpClient.toggleSkill(
      port,
      name: key,
      enabled: newValue,
    );

    if (!mounted) return;

    setState(() {
      _togglingSkills.remove(key);
    });

    if (ok) {
      _showRestartHint();
    } else {
      // 回滚
      setState(() {
        _skills[index] = skill;
      });
      _showError('切换失败，请重试');
    }
  }

  Future<void> _toggleKnowledge(KnowledgeItem item, bool newValue) async {
    final key = item.filename;
    final port = _resolvedPort;
    if (_togglingKnowledge.contains(key) || port == null) return;

    setState(() {
      _togglingKnowledge.add(key);
    });

    // 乐观更新
    final index = _knowledge.indexWhere((k) => k.filename == key);
    if (index == -1) return;
    setState(() {
      _knowledge[index] = item.copyWith(enabled: newValue);
    });

    final ok = await _httpClient.toggleKnowledge(
      port,
      filename: key,
      enabled: newValue,
    );

    if (!mounted) return;

    setState(() {
      _togglingKnowledge.remove(key);
    });

    if (ok) {
      _showRestartHint();
    } else {
      // 回滚
      setState(() {
        _knowledge[index] = item;
      });
      _showError('切换失败，请重试');
    }
  }

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

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('技能管理'),
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
    if (_skills.isEmpty) {
      return _buildEmptyState('暂无技能');
    }

    return ListView.builder(
      itemCount: _skills.length,
      itemBuilder: (context, index) {
        final skill = _skills[index];
        final isToggling = _togglingSkills.contains(skill.name);
        return ListTile(
          key: Key('skill-${skill.name}'),
          title: Text(skill.name),
          subtitle: skill.description.isNotEmpty
              ? Text(skill.description, maxLines: 2, overflow: TextOverflow.ellipsis)
              : null,
          trailing: Switch(
            key: Key('skill-switch-${skill.name}'),
            value: skill.enabled,
            onChanged: isToggling
                ? null
                : (value) => unawaited(_toggleSkill(skill, value)),
          ),
        );
      },
    );
  }

  Widget _buildKnowledgeList() {
    if (_knowledge.isEmpty) {
      return _buildEmptyState('暂无知识文件');
    }

    return ListView.builder(
      itemCount: _knowledge.length,
      itemBuilder: (context, index) {
        final item = _knowledge[index];
        final isToggling = _togglingKnowledge.contains(item.filename);
        return ListTile(
          key: Key('knowledge-${item.filename}'),
          title: Text(item.filename),
          trailing: Switch(
            key: Key('knowledge-switch-${item.filename}'),
            value: item.enabled,
            onChanged: isToggling
                ? null
                : (value) => unawaited(_toggleKnowledge(item, value)),
          ),
        );
      },
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
