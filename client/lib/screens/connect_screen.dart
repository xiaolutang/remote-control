import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../models/config.dart';
import '../services/config_service.dart';
import '../services/websocket_service.dart';
import 'terminal_screen.dart';

/// 连接配置屏幕
class ConnectScreen extends StatefulWidget {
  const ConnectScreen({super.key});

  @override
  State<ConnectScreen> createState() => _ConnectScreenState();
}

class _ConnectScreenState extends State<ConnectScreen> {
  final _formKey = GlobalKey<FormState>();
  final _serverController = TextEditingController();
  final _tokenController = TextEditingController();
  final _sessionController = TextEditingController();

  late ConfigService _configService;
  late AppConfig _config;

  @override
  void initState() {
    super.initState();
    _configService = ConfigService();
    _loadConfig();
  }

  Future<void> _loadConfig() async {
    final config = await _configService.loadConfig();
    setState(() {
      _config = config;
      _serverController.text = config.serverUrl;
      _tokenController.text = config.token ?? '';
      _sessionController.text = config.sessionId;
    });
  }

  Future<void> _saveAndConnect() async {
    if (!_formKey.currentState!.validate()) {
      return;
    }

    final config = _config.copyWith(
      serverUrl: _serverController.text,
      token: _tokenController.text,
      sessionId: _sessionController.text,
    );

    await _configService.saveConfig(config);

    // 创建 WebSocket 服务并导航
    final service = WebSocketService(
      serverUrl: config.serverUrl,
      token: config.token!,
      sessionId: config.sessionId,
      autoReconnect: config.autoReconnect,
      maxRetries: config.maxRetries,
      reconnectDelay: config.reconnectDelay,
    );

    if (!mounted) return;

    Navigator.push(
      context,
      MaterialPageRoute(
        builder: (context) => ChangeNotifierProvider.value(
          value: service,
          child: const TerminalScreen(),
        ),
      ),
    );
  }

  @override
  void dispose() {
    _serverController.dispose();
    _tokenController.dispose();
    _sessionController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Remote Control Client'),
      ),
      body: Form(
        key: _formKey,
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              TextFormField(
                controller: _serverController,
                decoration: const InputDecoration(
                  labelText: '服务器地址',
                  hintText: 'wss://example.com',
                  border: OutlineInputBorder(),
                ),
                validator: (value) {
                  if (value == null || value.isEmpty) {
                    return '请输入服务器地址';
                  }
                  return null;
                },
              ),
              const SizedBox(height: 16),
              TextFormField(
                controller: _tokenController,
                decoration: const InputDecoration(
                  labelText: '认证 Token',
                  hintText: 'JWT Token',
                  border: OutlineInputBorder(),
                ),
                validator: (value) {
                  if (value == null || value.isEmpty) {
                    return '请输入 Token';
                  }
                  return null;
                },
              ),
              const SizedBox(height: 16),
              TextFormField(
                controller: _sessionController,
                decoration: const InputDecoration(
                  labelText: 'Session ID',
                  hintText: '会话标识',
                  border: OutlineInputBorder(),
                ),
                validator: (value) {
                  if (value == null || value.isEmpty) {
                    return '请输入 Session ID';
                  }
                  return null;
                },
              ),
              const SizedBox(height: 24),
              ElevatedButton(
                onPressed: _saveAndConnect,
                child: const Text('连接'),
              ),
              const Spacer(),
              const Text(
                '使用说明',
                style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold),
              ),
              const SizedBox(height: 8),
              const Text(
                '1. 在服务器上运行 rc-agent\n'
                '2. 获取 Session ID 和 Token\n'
                '3. 填写上述信息并点击连接',
                style: TextStyle(fontSize: 14),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
