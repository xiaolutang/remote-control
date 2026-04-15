import 'package:flutter/material.dart';
import '../models/app_environment.dart';
import '../services/auth_service.dart';
import '../services/desktop_agent_manager.dart';
import '../services/environment_service.dart';
import '../services/terminal_session_manager.dart';
import '../services/ui_helpers.dart';
import 'network_diagnostic_screen.dart';
import 'terminal_workspace_screen.dart';
import 'package:provider/provider.dart';

/// 登录/注册屏幕
class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _formKey = GlobalKey<FormState>();
  final _usernameController = TextEditingController();
  final _passwordController = TextEditingController();
  final _confirmPasswordController = TextEditingController();
  final _hostController = TextEditingController();
  final _portController = TextEditingController();

  bool _isLoginMode = true;
  bool _isLoading = false;
  bool _obscurePassword = true;
  bool _obscureConfirmPassword = true;
  String? _errorMessage;

  late AppEnvironment _selectedEnvironment;

  @override
  void initState() {
    super.initState();
    _selectedEnvironment = EnvironmentService.instance.currentEnvironment;
    _syncHostPortControllers();
  }

  /// 根据当前环境同步 host/port 输入框
  void _syncHostPortControllers() {
    final env = EnvironmentService.instance;
    if (_selectedEnvironment == AppEnvironment.direct) {
      _hostController.text = env.directHost;
      _portController.text = env.directPort;
    } else {
      _hostController.text = env.localHost;
      _portController.text = env.localPort;
    }
  }

  @override
  void dispose() {
    _usernameController.dispose();
    _passwordController.dispose();
    _confirmPasswordController.dispose();
    _hostController.dispose();
    _portController.dispose();
    super.dispose();
  }

  /// 验证用户名
  String? _validateUsername(String? value) {
    if (value == null || value.isEmpty) {
      return '请输入用户名';
    }
    if (value.length < 3) {
      return '用户名至少 3 个字符';
    }
    if (value.length > 32) {
      return '用户名最多 32 个字符';
    }
    return null;
  }

  /// 验证密码
  String? _validatePassword(String? value) {
    if (value == null || value.isEmpty) {
      return '请输入密码';
    }
    if (value.length < 6) {
      return '密码至少 6 个字符';
    }
    return null;
  }

  /// 验证确认密码
  String? _validateConfirmPassword(String? value) {
    if (!_isLoginMode) {
      if (value == null || value.isEmpty) {
        return '请确认密码';
      }
      if (value != _passwordController.text) {
        return '两次输入的密码不一致';
      }
    }
    return null;
  }

  /// 提交表单
  Future<void> _submit() async {
    if (!_formKey.currentState!.validate()) {
      return;
    }

    setState(() {
      _isLoading = true;
      _errorMessage = null;
    });

    try {
      final serverUrl = EnvironmentService.instance.currentServerUrl;
      final authService = AuthService(serverUrl: serverUrl);
      Map<String, dynamic> result;

      if (_isLoginMode) {
        result = await authService.login(
          _usernameController.text.trim(),
          _passwordController.text,
        );
      } else {
        result = await authService.register(
          _usernameController.text.trim(),
          _passwordController.text,
        );
      }

      if (!mounted) return;

      // 登录/注册成功，跳转到终端工作台
      final token = result['token'] as String;
      final sessionId = result['session_id'] as String?;
      final username = _usernameController.text.trim();

      // 启动 Agent（桌面端，不阻塞进入首页）
      if (sessionId != null && sessionId.isNotEmpty) {
        try {
          final agentManager = context.read<DesktopAgentManager>();
          await agentManager
              .onLogin(
                serverUrl: serverUrl,
                token: token,
                username: username,
                deviceId: sessionId,
              )
              .timeout(
                const Duration(seconds: 15),
                onTimeout: () {},
              );
        } catch (_) {
          // Agent 启动失败，继续进入首页
        }
      }

      if (!mounted) return;

      Navigator.pushReplacement(
        context,
        MaterialPageRoute(
          builder: (context) => TerminalWorkspaceScreen(
            serverUrl: serverUrl,
            token: token,
          ),
        ),
      );
    } catch (e) {
      debugPrint('[LoginScreen] submit failed: $e');
      setState(() {
        _errorMessage = e.toString().replaceAll('Exception: ', '');
      });
    } finally {
      if (mounted) {
        setState(() {
          _isLoading = false;
        });
      }
    }
  }

  /// 切换环境（含协调层编排）
  Future<void> _switchEnvironment(AppEnvironment newEnv) async {
    if (newEnv == _selectedEnvironment) return;

    setState(() => _isLoading = true);
    try {
      // 协调层编排：停 Agent → 断终端 → 清凭证 → 更新环境
      final agentManager = context.read<DesktopAgentManager>();
      final sessionManager = context.read<TerminalSessionManager>();
      final serverUrl = EnvironmentService.instance.currentServerUrl;

      await Future.wait([
        // 停止 Agent（桌面端）
        () async {
          try {
            await agentManager.onLogout();
          } catch (_) {}
        }(),
        // 断开终端
        () async {
          try {
            await sessionManager.disconnectAll();
          } catch (_) {}
        }(),
        // 清除凭证
        () async {
          try {
            await AuthService(serverUrl: serverUrl).logout();
          } catch (_) {}
        }(),
      ]);

      // 更新环境状态
      await EnvironmentService.instance.switchEnvironment(newEnv);

      if (!mounted) return;
      setState(() {
        _selectedEnvironment = newEnv;
        _errorMessage = null;
        _syncHostPortControllers();
      });
    } finally {
      if (mounted) setState(() => _isLoading = false);
    }
  }

  /// 保存 host/port 到 EnvironmentService
  Future<void> _saveHostPort() async {
    final env = EnvironmentService.instance;
    if (_selectedEnvironment == AppEnvironment.direct) {
      if (_hostController.text != env.directHost) {
        await env.updateDirectHost(_hostController.text);
      }
      if (_portController.text != env.directPort) {
        await env.updateDirectPort(_portController.text);
      }
      if (env.directHost != _hostController.text) {
        _hostController.text = env.directHost;
      }
      if (env.directPort != _portController.text) {
        _portController.text = env.directPort;
      }
    } else {
      if (_hostController.text != env.localHost) {
        await env.updateLocalHost(_hostController.text);
      }
      if (_portController.text != env.localPort) {
        await env.updateLocalPort(_portController.text);
      }
      if (env.localHost != _hostController.text) {
        _hostController.text = env.localHost;
      }
      if (env.localPort != _portController.text) {
        _portController.text = env.localPort;
      }
    }
  }

  /// 切换登录/注册模式
  void _toggleMode() {
    setState(() {
      _isLoginMode = !_isLoginMode;
      _errorMessage = null;
      _confirmPasswordController.clear();
    });
  }

  Future<void> _showThemePicker() async {
    await showThemePickerSheet(context);
  }

  void _openNetworkDiagnostic() {
    Navigator.push(
      context,
      MaterialPageRoute(
        builder: (context) => NetworkDiagnosticScreen(
          serverUrl: EnvironmentService.instance.currentServerUrl,
          username: _usernameController.text.trim(),
          password: _passwordController.text,
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 400),
              child: Form(
                key: _formKey,
                child: Column(
                  mainAxisAlignment: MainAxisAlignment.center,
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Align(
                      alignment: Alignment.centerRight,
                      child: IconButton(
                        tooltip: '主题',
                        onPressed: _showThemePicker,
                        icon: const Icon(Icons.palette_outlined),
                      ),
                    ),
                    // 环境选择
                    SegmentedButton<AppEnvironment>(
                      segments: const [
                        ButtonSegment(
                          value: AppEnvironment.local,
                          label: Text('本地'),
                          icon: Icon(Icons.lan),
                        ),
                        ButtonSegment(
                          value: AppEnvironment.direct,
                          label: Text('直连'),
                          icon: Icon(Icons.link),
                        ),
                        ButtonSegment(
                          value: AppEnvironment.production,
                          label: Text('线上'),
                          icon: Icon(Icons.cloud),
                        ),
                      ],
                      selected: {_selectedEnvironment},
                      onSelectionChanged: (selected) {
                        _switchEnvironment(selected.first);
                      },
                    ),
                    const SizedBox(height: 12),
                    // host/port 编辑区（本地和直连环境显示）
                    if (_selectedEnvironment == AppEnvironment.local ||
                        _selectedEnvironment == AppEnvironment.direct) ...[
                      Row(
                        children: [
                          Expanded(
                            flex: 3,
                            child: TextFormField(
                              controller: _hostController,
                              decoration: InputDecoration(
                                labelText: 'Host',
                                hintText: _selectedEnvironment ==
                                        AppEnvironment.direct
                                    ? '服务器 IP'
                                    : 'localhost',
                                prefixIcon: const Icon(Icons.dns),
                                border: const OutlineInputBorder(),
                                isDense: true,
                                helperText: '字母、数字、点、短横线',
                                helperMaxLines: 1,
                              ),
                              enabled: !_isLoading,
                              onChanged: (_) => _saveHostPort(),
                            ),
                          ),
                          const SizedBox(width: 8),
                          Expanded(
                            flex: 1,
                            child: TextFormField(
                              controller: _portController,
                              decoration: InputDecoration(
                                labelText: '端口',
                                hintText: _selectedEnvironment ==
                                        AppEnvironment.direct
                                    ? '8080'
                                    : '留空',
                                prefixIcon: const Icon(Icons.numbers),
                                border: const OutlineInputBorder(),
                                isDense: true,
                                helperText: '1-65535',
                                helperMaxLines: 1,
                              ),
                              keyboardType: TextInputType.number,
                              enabled: !_isLoading,
                              onChanged: (_) => _saveHostPort(),
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: 16),
                    ],
                    // 标题
                    Icon(
                      Icons.terminal,
                      size: 64,
                      color: Theme.of(context).colorScheme.primary,
                    ),
                    const SizedBox(height: 16),
                    Text(
                      'Remote Control',
                      style:
                          Theme.of(context).textTheme.headlineMedium?.copyWith(
                                fontWeight: FontWeight.bold,
                              ),
                      textAlign: TextAlign.center,
                    ),
                    const SizedBox(height: 8),
                    Text(
                      _isLoginMode ? '登录您的账号' : '创建新账号',
                      style: Theme.of(context).textTheme.bodyLarge?.copyWith(
                            color:
                                Theme.of(context).colorScheme.onSurfaceVariant,
                          ),
                      textAlign: TextAlign.center,
                    ),
                    const SizedBox(height: 32),

                    // 用户名输入框
                    TextFormField(
                      controller: _usernameController,
                      decoration: const InputDecoration(
                        labelText: '用户名',
                        hintText: '请输入用户名',
                        prefixIcon: Icon(Icons.person),
                        border: OutlineInputBorder(),
                      ),
                      textInputAction: TextInputAction.next,
                      validator: _validateUsername,
                      enabled: !_isLoading,
                    ),
                    const SizedBox(height: 16),

                    // 密码输入框
                    TextFormField(
                      controller: _passwordController,
                      decoration: InputDecoration(
                        labelText: '密码',
                        hintText: '请输入密码',
                        prefixIcon: const Icon(Icons.lock),
                        suffixIcon: IconButton(
                          icon: Icon(
                            _obscurePassword
                                ? Icons.visibility
                                : Icons.visibility_off,
                          ),
                          onPressed: () {
                            setState(() {
                              _obscurePassword = !_obscurePassword;
                            });
                          },
                        ),
                        border: const OutlineInputBorder(),
                      ),
                      obscureText: _obscurePassword,
                      textInputAction: _isLoginMode
                          ? TextInputAction.done
                          : TextInputAction.next,
                      validator: _validatePassword,
                      enabled: !_isLoading,
                      onFieldSubmitted: _isLoginMode ? (_) => _submit() : null,
                    ),
                    const SizedBox(height: 16),

                    // 确认密码输入框（仅注册模式）
                    if (!_isLoginMode) ...[
                      TextFormField(
                        controller: _confirmPasswordController,
                        decoration: InputDecoration(
                          labelText: '确认密码',
                          hintText: '请再次输入密码',
                          prefixIcon: const Icon(Icons.lock_outline),
                          suffixIcon: IconButton(
                            icon: Icon(
                              _obscureConfirmPassword
                                  ? Icons.visibility
                                  : Icons.visibility_off,
                            ),
                            onPressed: () {
                              setState(() {
                                _obscureConfirmPassword =
                                    !_obscureConfirmPassword;
                              });
                            },
                          ),
                          border: const OutlineInputBorder(),
                        ),
                        obscureText: _obscureConfirmPassword,
                        textInputAction: TextInputAction.done,
                        validator: _validateConfirmPassword,
                        enabled: !_isLoading,
                        onFieldSubmitted: (_) => _submit(),
                      ),
                      const SizedBox(height: 16),
                    ],

                    // 错误提示
                    if (_errorMessage != null) ...[
                      Container(
                        padding: const EdgeInsets.all(12),
                        decoration: BoxDecoration(
                          color: Theme.of(context).colorScheme.errorContainer,
                          borderRadius: BorderRadius.circular(8),
                        ),
                        child: Row(
                          children: [
                            Icon(
                              Icons.error_outline,
                              color: Theme.of(context).colorScheme.error,
                            ),
                            const SizedBox(width: 8),
                            Expanded(
                              child: Text(
                                _errorMessage!,
                                style: TextStyle(
                                  color: Theme.of(context)
                                      .colorScheme
                                      .onErrorContainer,
                                ),
                              ),
                            ),
                          ],
                        ),
                      ),
                      const SizedBox(height: 16),
                    ],

                    // 提交按钮
                    ElevatedButton(
                      onPressed: _isLoading ? null : _submit,
                      style: ElevatedButton.styleFrom(
                        padding: const EdgeInsets.symmetric(vertical: 16),
                      ),
                      child: _isLoading
                          ? const SizedBox(
                              height: 20,
                              width: 20,
                              child: CircularProgressIndicator(strokeWidth: 2),
                            )
                          : Text(_isLoginMode ? '登录' : '注册'),
                    ),
                    const SizedBox(height: 16),
                    OutlinedButton.icon(
                      onPressed: _isLoading ? null : _openNetworkDiagnostic,
                      icon: const Icon(Icons.network_check),
                      label: const Text('网络诊断'),
                    ),
                    const SizedBox(height: 16),

                    // 切换登录/注册
                    Row(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        Text(
                          _isLoginMode ? '还没有账号？' : '已有账号？',
                          style: Theme.of(context).textTheme.bodyMedium,
                        ),
                        TextButton(
                          onPressed: _isLoading ? null : _toggleMode,
                          child: Text(_isLoginMode ? '立即注册' : '立即登录'),
                        ),
                      ],
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
