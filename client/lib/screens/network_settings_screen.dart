import 'package:flutter/material.dart';

import '../models/app_environment.dart';
import '../models/app_environment_presentation.dart';
import '../services/auth_service.dart';
import '../services/environment_service.dart';
import '../services/environment_switch_coordinator.dart';
import '../services/network_diagnostic_service.dart';

class NetworkSettingsScreen extends StatefulWidget {
  const NetworkSettingsScreen({
    super.key,
    this.username,
    this.password,
    this.diagnosticService = const NetworkDiagnosticService(),
    this.switchCoordinator = const EnvironmentSwitchCoordinator(),
  });

  final String? username;
  final String? password;
  final NetworkDiagnosticService diagnosticService;
  final EnvironmentSwitchCoordinator switchCoordinator;

  @override
  State<NetworkSettingsScreen> createState() => _NetworkSettingsScreenState();
}

class _NetworkSettingsScreenState extends State<NetworkSettingsScreen> {
  final _hostController = TextEditingController();
  final _portController = TextEditingController();

  late AppEnvironment _selectedEnvironment;
  late Future<NetworkDiagnosticReport> _reportFuture;

  bool _isBusy = false;

  @override
  void initState() {
    super.initState();
    _selectedEnvironment = EnvironmentService.instance.currentEnvironment;
    _syncHostPortControllers();
    _reportFuture = _loadReport();
  }

  @override
  void dispose() {
    _hostController.dispose();
    _portController.dispose();
    super.dispose();
  }

  Future<NetworkDiagnosticReport> _loadReport() {
    return widget.diagnosticService.run(
      serverUrl: EnvironmentService.instance.currentServerUrl,
      username: widget.username,
      password: widget.password,
      view: currentView,
    );
  }

  void _syncHostPortControllers() {
    final env = EnvironmentService.instance;
    if (_selectedEnvironment == AppEnvironment.direct) {
      _hostController.text = env.directHost;
      _portController.text = env.directPort;
      return;
    }

    _hostController.text = env.localHost;
    _portController.text = env.localPort;
  }

  void _refreshDiagnostics() {
    setState(() {
      _reportFuture = _loadReport();
    });
  }

  void _applyEnvironmentSnapshot({required bool refreshDiagnostics}) {
    _selectedEnvironment = EnvironmentService.instance.currentEnvironment;
    _syncHostPortControllers();
    if (refreshDiagnostics) {
      _reportFuture = _loadReport();
    }
  }

  Future<void> _switchEnvironment(AppEnvironment newEnv) async {
    if (newEnv == _selectedEnvironment || _isBusy) {
      return;
    }

    final previousServerUrl = EnvironmentService.instance.currentServerUrl;
    setState(() => _isBusy = true);
    try {
      await widget.switchCoordinator.switchEnvironment(
        context: context,
        newEnv: newEnv,
      );
      if (!mounted) {
        return;
      }
      final refreshDiagnostics =
          EnvironmentService.instance.currentServerUrl != previousServerUrl;
      setState(() {
        _applyEnvironmentSnapshot(refreshDiagnostics: refreshDiagnostics);
        _isBusy = false;
      });
    } finally {
      if (mounted && _isBusy) {
        setState(() => _isBusy = false);
      }
    }
  }

  Future<void> _saveHostPort() async {
    if (_isBusy) {
      return;
    }

    final previousServerUrl = EnvironmentService.instance.currentServerUrl;
    setState(() => _isBusy = true);
    try {
      final env = EnvironmentService.instance;
      if (_selectedEnvironment == AppEnvironment.direct) {
        await env.updateDirectHost(_hostController.text);
        await env.updateDirectPort(_portController.text);
      } else {
        await env.updateLocalHost(_hostController.text);
        await env.updateLocalPort(_portController.text);
      }
      if (!mounted) {
        return;
      }
      final refreshDiagnostics =
          EnvironmentService.instance.currentServerUrl != previousServerUrl;
      setState(() {
        _syncHostPortControllers();
        if (refreshDiagnostics) {
          _reportFuture = _loadReport();
        }
        _isBusy = false;
      });
    } finally {
      if (mounted && _isBusy) {
        setState(() => _isBusy = false);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final colorScheme = Theme.of(context).colorScheme;
    final serverUrl = EnvironmentService.instance.currentServerUrl;

    return Scaffold(
      appBar: AppBar(
        title: const Text('网络设置'),
      ),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(20),
          children: [
            _SectionCard(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Icon(_selectedEnvironment.icon,
                          color: colorScheme.primary),
                      const SizedBox(width: 10),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              _selectedEnvironment.title,
                              style: Theme.of(context).textTheme.titleMedium,
                            ),
                            const SizedBox(height: 4),
                            Text(
                              _selectedEnvironment.description,
                              style: Theme.of(context)
                                  .textTheme
                                  .bodyMedium
                                  ?.copyWith(
                                    color: colorScheme.onSurfaceVariant,
                                  ),
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 14),
                  Container(
                    width: double.infinity,
                    padding: const EdgeInsets.all(14),
                    decoration: BoxDecoration(
                      color: colorScheme.surfaceContainerHighest,
                      borderRadius: BorderRadius.circular(16),
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          '当前连接地址',
                          style: Theme.of(context).textTheme.labelLarge,
                        ),
                        const SizedBox(height: 6),
                        SelectableText(serverUrl),
                      ],
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 16),
            _SectionCard(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    '网络连接',
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                  const SizedBox(height: 6),
                  Text(
                    '切换后会自动断开旧连接并重新诊断当前网络。',
                    style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                          color: colorScheme.onSurfaceVariant,
                        ),
                  ),
                  const SizedBox(height: 14),
                  SegmentedButton<AppEnvironment>(
                    segments: [
                      for (final env in AppEnvironment.values)
                        ButtonSegment<AppEnvironment>(
                          value: env,
                          label: Text(env.label),
                          icon: Icon(env.icon),
                        ),
                    ],
                    selected: {_selectedEnvironment},
                    onSelectionChanged: _isBusy
                        ? null
                        : (selected) => _switchEnvironment(selected.first),
                  ),
                  if (_selectedEnvironment == AppEnvironment.local ||
                      _selectedEnvironment == AppEnvironment.direct) ...[
                    const SizedBox(height: 16),
                    Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Expanded(
                          flex: 3,
                          child: TextFormField(
                            controller: _hostController,
                            decoration: InputDecoration(
                              labelText: 'Host',
                              hintText:
                                  _selectedEnvironment == AppEnvironment.direct
                                      ? '服务器 IP'
                                      : 'localhost',
                              prefixIcon: const Icon(Icons.dns_outlined),
                              border: const OutlineInputBorder(),
                            ),
                            enabled: !_isBusy,
                            textInputAction: TextInputAction.next,
                          ),
                        ),
                        const SizedBox(width: 12),
                        Expanded(
                          child: TextFormField(
                            controller: _portController,
                            decoration: const InputDecoration(
                              labelText: '端口',
                              hintText: '8880',
                              prefixIcon: Icon(Icons.numbers_outlined),
                              border: OutlineInputBorder(),
                            ),
                            enabled: !_isBusy,
                            keyboardType: TextInputType.number,
                            textInputAction: TextInputAction.done,
                            onFieldSubmitted: (_) => _saveHostPort(),
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 12),
                    Align(
                      alignment: Alignment.centerRight,
                      child: FilledButton.icon(
                        onPressed: _isBusy ? null : _saveHostPort,
                        icon: const Icon(Icons.save_outlined),
                        label: const Text('保存并重新诊断'),
                      ),
                    ),
                  ],
                ],
              ),
            ),
            const SizedBox(height: 16),
            _SectionCard(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              '连接诊断',
                              style: Theme.of(context).textTheme.titleMedium,
                            ),
                            const SizedBox(height: 6),
                            Text(
                              '进入页面后会自动检查，切换环境后也会自动重新执行。',
                              style: Theme.of(context)
                                  .textTheme
                                  .bodyMedium
                                  ?.copyWith(
                                    color: colorScheme.onSurfaceVariant,
                                  ),
                            ),
                          ],
                        ),
                      ),
                      IconButton(
                        tooltip: '重新检测',
                        onPressed: _isBusy ? null : _refreshDiagnostics,
                        icon: const Icon(Icons.refresh),
                      ),
                    ],
                  ),
                  const SizedBox(height: 12),
                  FutureBuilder<NetworkDiagnosticReport>(
                    future: _reportFuture,
                    builder: (context, snapshot) {
                      if (snapshot.connectionState != ConnectionState.done) {
                        return const _DiagnosticLoadingState();
                      }

                      if (snapshot.hasError) {
                        return _DiagnosticStateCard(
                          icon: Icons.error_outline,
                          iconColor: colorScheme.error,
                          title: '诊断失败',
                          body: snapshot.error.toString(),
                        );
                      }

                      final report = snapshot.data!;
                      return Column(
                        children: [
                          _DiagnosticStateCard(
                            icon: Icons.link_outlined,
                            iconColor: colorScheme.primary,
                            title: 'HTTP 地址',
                            body: report.httpUrl,
                          ),
                          const SizedBox(height: 12),
                          for (var i = 0; i < report.checks.length; i++) ...[
                            _DiagnosticStateCard(
                              icon: report.checks[i].success
                                  ? Icons.check_circle_outline
                                  : Icons.error_outline,
                              iconColor: report.checks[i].success
                                  ? Colors.green
                                  : colorScheme.error,
                              title: report.checks[i].title,
                              body: report.checks[i].detail,
                            ),
                            if (i != report.checks.length - 1)
                              const SizedBox(height: 12),
                          ],
                        ],
                      );
                    },
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _SectionCard extends StatelessWidget {
  const _SectionCard({required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: EdgeInsets.zero,
      child: Padding(
        padding: const EdgeInsets.all(18),
        child: child,
      ),
    );
  }
}

class _DiagnosticLoadingState extends StatelessWidget {
  const _DiagnosticLoadingState();

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(16),
        color: Theme.of(context).colorScheme.surfaceContainerHighest,
      ),
      child: const Row(
        children: [
          SizedBox(
            height: 18,
            width: 18,
            child: CircularProgressIndicator(strokeWidth: 2),
          ),
          SizedBox(width: 12),
          Expanded(child: Text('正在自动诊断当前网络...')),
        ],
      ),
    );
  }
}

class _DiagnosticStateCard extends StatelessWidget {
  const _DiagnosticStateCard({
    required this.icon,
    required this.iconColor,
    required this.title,
    required this.body,
  });

  final IconData icon;
  final Color iconColor;
  final String title;
  final String body;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(16),
        color: Theme.of(context).colorScheme.surfaceContainerHighest,
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, color: iconColor),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  title,
                  style: Theme.of(context).textTheme.titleSmall,
                ),
                const SizedBox(height: 6),
                SelectableText(body),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
