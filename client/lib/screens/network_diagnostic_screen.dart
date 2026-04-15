import 'package:flutter/material.dart';

import '../services/network_diagnostic_service.dart';

class NetworkDiagnosticScreen extends StatefulWidget {
  const NetworkDiagnosticScreen({
    super.key,
    required this.serverUrl,
    this.username,
    this.password,
  });

  final String serverUrl;
  final String? username;
  final String? password;

  @override
  State<NetworkDiagnosticScreen> createState() =>
      _NetworkDiagnosticScreenState();
}

class _NetworkDiagnosticScreenState extends State<NetworkDiagnosticScreen> {
  late Future<NetworkDiagnosticReport> _reportFuture;

  @override
  void initState() {
    super.initState();
    _reportFuture = _loadReport();
  }

  Future<NetworkDiagnosticReport> _loadReport() {
    return const NetworkDiagnosticService().run(
      serverUrl: widget.serverUrl,
      username: widget.username,
      password: widget.password,
    );
  }

  void _rerun() {
    setState(() {
      _reportFuture = _loadReport();
    });
  }

  @override
  Widget build(BuildContext context) {
    final colorScheme = Theme.of(context).colorScheme;

    return Scaffold(
      appBar: AppBar(
        title: const Text('网络诊断'),
        actions: [
          IconButton(
            tooltip: '重新检测',
            onPressed: _rerun,
            icon: const Icon(Icons.refresh),
          ),
        ],
      ),
      body: FutureBuilder<NetworkDiagnosticReport>(
        future: _reportFuture,
        builder: (context, snapshot) {
          if (snapshot.connectionState != ConnectionState.done) {
            return const Center(child: CircularProgressIndicator());
          }

          if (snapshot.hasError) {
            return Center(
              child: Padding(
                padding: const EdgeInsets.all(24),
                child: Text('诊断失败: ${snapshot.error}'),
              ),
            );
          }

          final report = snapshot.data!;
          return ListView(
            padding: const EdgeInsets.all(16),
            children: [
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text('Server URL',
                          style: Theme.of(context).textTheme.labelMedium),
                      const SizedBox(height: 4),
                      SelectableText(report.serverUrl),
                      const SizedBox(height: 12),
                      Text('HTTP URL',
                          style: Theme.of(context).textTheme.labelMedium),
                      const SizedBox(height: 4),
                      SelectableText(report.httpUrl),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 12),
              for (final check in report.checks) ...[
                Card(
                  child: ListTile(
                    leading: Icon(
                      check.success
                          ? Icons.check_circle_outline
                          : Icons.error_outline,
                      color: check.success
                          ? colorScheme.primary
                          : colorScheme.error,
                    ),
                    title: Text(check.title),
                    subtitle: Padding(
                      padding: const EdgeInsets.only(top: 6),
                      child: SelectableText(check.detail),
                    ),
                  ),
                ),
                const SizedBox(height: 12),
              ],
              Text(
                '如果域名检查失败，但 IP + Host 成功，通常表示 DNS、代理或网络环境有问题。',
                style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                      color: colorScheme.onSurfaceVariant,
                    ),
              ),
            ],
          );
        },
      ),
    );
  }
}
