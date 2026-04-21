import 'dart:async';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../models/app_environment_presentation.dart';
import '../services/auth_service.dart';
import '../services/desktop_agent_manager.dart';
import '../services/environment_service.dart';
import 'network_settings_screen.dart';
import 'terminal_workspace_screen.dart';

/// 登录/注册屏幕
class LoginScreen extends StatefulWidget {
  const LoginScreen({
    super.key,
    this.authServiceBuilder,
    this.workspaceBuilder,
  });

  final AuthService Function(String serverUrl)? authServiceBuilder;
  final Widget Function(String token)? workspaceBuilder;

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _formKey = GlobalKey<FormState>();
  final _usernameController = TextEditingController(text: 'test');
  final _passwordController = TextEditingController(text: 'test123');
  final _confirmPasswordController = TextEditingController();

  bool _isLoginMode = true;
  bool _isLoading = false;
  bool _obscurePassword = true;
  bool _obscureConfirmPassword = true;
  String? _errorMessage;

  @override
  void dispose() {
    _usernameController.dispose();
    _passwordController.dispose();
    _confirmPasswordController.dispose();
    super.dispose();
  }

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

  String? _validatePassword(String? value) {
    if (value == null || value.isEmpty) {
      return '请输入密码';
    }
    if (value.length < 6) {
      return '密码至少 6 个字符';
    }
    return null;
  }

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
      final authService = widget.authServiceBuilder?.call(serverUrl) ??
          AuthService(serverUrl: serverUrl);
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

      if (!mounted) {
        return;
      }

      final token = result['token'] as String;
      final sessionId = result['session_id'] as String?;
      final username = _usernameController.text.trim();

      if (sessionId != null && sessionId.isNotEmpty) {
        final agentManager = context.read<DesktopAgentManager>();
        unawaited(
          agentManager
              .onLogin(
                serverUrl: serverUrl,
                token: token,
                username: username,
                deviceId: sessionId,
              )
              .catchError((_) {}),
        );
      }

      if (!mounted) {
        return;
      }

      Navigator.pushReplacement(
        context,
        MaterialPageRoute(
          builder: (context) =>
              widget.workspaceBuilder?.call(token) ??
              TerminalWorkspaceScreen(token: token),
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

  void _setMode(bool loginMode) {
    if (_isLoginMode == loginMode) {
      return;
    }
    setState(() {
      _isLoginMode = loginMode;
      _errorMessage = null;
      _confirmPasswordController.clear();
    });
  }

  Future<void> _openNetworkSettings() async {
    final previousEnvironment = EnvironmentService.instance.currentEnvironment;
    final previousServerUrl = EnvironmentService.instance.currentServerUrl;
    await Navigator.push(
      context,
      MaterialPageRoute(
        builder: (context) => NetworkSettingsScreen(
          username: _usernameController.text.trim(),
          password: _passwordController.text,
        ),
      ),
    );
    if (mounted &&
        (previousEnvironment !=
                EnvironmentService.instance.currentEnvironment ||
            previousServerUrl !=
                EnvironmentService.instance.currentServerUrl)) {
      setState(() {});
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colorScheme = theme.colorScheme;
    final environment = EnvironmentService.instance.currentEnvironment;
    final serverUrl = EnvironmentService.instance.currentServerUrl;

    return Scaffold(
      body: SafeArea(
        child: Center(
          child: ScrollConfiguration(
            behavior: ScrollConfiguration.of(
              context,
            ).copyWith(scrollbars: false),
            child: SingleChildScrollView(
              padding: const EdgeInsets.all(24),
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 460),
                child: Card(
                  margin: EdgeInsets.zero,
                  child: Padding(
                    padding: const EdgeInsets.all(24),
                    child: Form(
                      key: _formKey,
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [
                          Row(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Expanded(
                                child: Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    Text(
                                      'Remote Control',
                                      style: theme.textTheme.headlineMedium
                                          ?.copyWith(
                                        fontWeight: FontWeight.w700,
                                      ),
                                    ),
                                    const SizedBox(height: 8),
                                    Text(
                                      _isLoginMode
                                          ? '登录到你的终端工作台'
                                          : '创建账号并立即开始使用',
                                      style:
                                          theme.textTheme.bodyLarge?.copyWith(
                                        color: colorScheme.onSurfaceVariant,
                                      ),
                                    ),
                                  ],
                                ),
                              ),
                              const SizedBox(width: 12),
                              TextButton.icon(
                                onPressed:
                                    _isLoading ? null : _openNetworkSettings,
                                icon: const Icon(Icons.tune),
                                label: const Text('网络设置'),
                              ),
                            ],
                          ),
                          const SizedBox(height: 20),
                          Container(
                            padding: const EdgeInsets.all(16),
                            decoration: BoxDecoration(
                              color: colorScheme.surfaceContainerHighest,
                              borderRadius: BorderRadius.circular(20),
                            ),
                            child: Row(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Container(
                                  height: 44,
                                  width: 44,
                                  decoration: BoxDecoration(
                                    color: colorScheme.primaryContainer,
                                    borderRadius: BorderRadius.circular(14),
                                  ),
                                  child: Icon(
                                    environment.icon,
                                    color: colorScheme.onPrimaryContainer,
                                  ),
                                ),
                                const SizedBox(width: 14),
                                Expanded(
                                  child: Column(
                                    crossAxisAlignment:
                                        CrossAxisAlignment.start,
                                    children: [
                                      Text(
                                        '当前网络',
                                        style: theme.textTheme.labelLarge,
                                      ),
                                      const SizedBox(height: 4),
                                      Text(
                                        environment.title,
                                        style: theme.textTheme.titleMedium,
                                      ),
                                      const SizedBox(height: 4),
                                      Text(
                                        serverUrl,
                                        style: theme.textTheme.bodyMedium
                                            ?.copyWith(
                                          color: colorScheme.onSurfaceVariant,
                                        ),
                                      ),
                                    ],
                                  ),
                                ),
                              ],
                            ),
                          ),
                          const SizedBox(height: 24),
                          SegmentedButton<bool>(
                            segments: const [
                              ButtonSegment<bool>(
                                value: true,
                                label: Text('登录'),
                                icon: Icon(Icons.login),
                              ),
                              ButtonSegment<bool>(
                                value: false,
                                label: Text('创建账号'),
                                icon: Icon(Icons.person_add_alt_1),
                              ),
                            ],
                            selected: {_isLoginMode},
                            onSelectionChanged: _isLoading
                                ? null
                                : (selected) => _setMode(selected.first),
                          ),
                          const SizedBox(height: 24),
                          TextFormField(
                            controller: _usernameController,
                            decoration: const InputDecoration(
                              labelText: '用户名',
                              hintText: '请输入用户名',
                              prefixIcon: Icon(Icons.person_outline),
                              border: OutlineInputBorder(),
                            ),
                            textInputAction: TextInputAction.next,
                            validator: _validateUsername,
                            enabled: !_isLoading,
                          ),
                          const SizedBox(height: 16),
                          TextFormField(
                            controller: _passwordController,
                            decoration: InputDecoration(
                              labelText: '密码',
                              hintText: '请输入密码',
                              prefixIcon: const Icon(Icons.lock_outline),
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
                            onFieldSubmitted:
                                _isLoginMode ? (_) => _submit() : null,
                          ),
                          if (!_isLoginMode) ...[
                            const SizedBox(height: 16),
                            TextFormField(
                              controller: _confirmPasswordController,
                              decoration: InputDecoration(
                                labelText: '确认密码',
                                hintText: '请再次输入密码',
                                prefixIcon:
                                    const Icon(Icons.verified_user_outlined),
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
                          ],
                          if (_errorMessage != null) ...[
                            const SizedBox(height: 16),
                            Container(
                              padding: const EdgeInsets.all(12),
                              decoration: BoxDecoration(
                                color: colorScheme.errorContainer,
                                borderRadius: BorderRadius.circular(12),
                              ),
                              child: Row(
                                children: [
                                  Icon(
                                    Icons.error_outline,
                                    color: colorScheme.error,
                                  ),
                                  const SizedBox(width: 8),
                                  Expanded(
                                    child: Text(
                                      _errorMessage!,
                                      style: TextStyle(
                                        color: colorScheme.onErrorContainer,
                                      ),
                                    ),
                                  ),
                                ],
                              ),
                            ),
                          ],
                          const SizedBox(height: 20),
                          FilledButton(
                            onPressed: _isLoading ? null : _submit,
                            style: FilledButton.styleFrom(
                              padding: const EdgeInsets.symmetric(vertical: 16),
                            ),
                            child: _isLoading
                                ? const SizedBox(
                                    height: 20,
                                    width: 20,
                                    child: CircularProgressIndicator(
                                        strokeWidth: 2),
                                  )
                                : Text(_isLoginMode ? '继续登录' : '完成注册'),
                          ),
                          const SizedBox(height: 12),
                          Text(
                            _isLoginMode
                                ? '如果网络不可达，可先进入网络设置切换环境并自动诊断。'
                                : '注册成功后会自动进入终端工作台，并在桌面端尝试拉起 Agent。',
                            textAlign: TextAlign.center,
                            style: theme.textTheme.bodySmall?.copyWith(
                              color: colorScheme.onSurfaceVariant,
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
