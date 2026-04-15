import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../models/app_environment.dart';

/// 纯状态服务：管理环境选择与 serverUrl 生成。
///
/// 不调用 AuthService、DesktopAgentManager 或任何 UI 组件。
/// 环境切换的副作用（登出、停 Agent 等）由 UI/协调层负责。
class EnvironmentService {
  EnvironmentService({
    SharedPreferences? prefs,
    bool Function()? debugModeProvider,
  })  : _prefs = prefs,
        _debugModeProvider = debugModeProvider ?? (() => kDebugMode);

  /// 全局单例，在 main() 中初始化后可用
  static late EnvironmentService instance;

  /// 初始化全局单例（main 中调用一次）
  static Future<void> initialize() async {
    instance = EnvironmentService();
    await instance.loadSavedState();
  }

  /// 测试用：注入自定义实例
  static void setInstance(EnvironmentService service) {
    instance = service;
  }

  static const String _keyEnvironment = 'rc_environment';
  static const String _keyLocalHost = 'rc_local_host';
  static const String _keyLocalPort = 'rc_local_port';
  static const String _keyDirectHost = 'rc_direct_host';
  static const String _keyDirectPort = 'rc_direct_port';

  static const String _productionHost = 'wss://rc.xiaolutang.top/rc';
  static const String _defaultLocalHost = 'localhost';
  static const String _defaultDirectHost = '43.136.23.47';
  static const String _defaultDirectPort = '8880';

  final SharedPreferences? _prefs;
  final bool Function() _debugModeProvider;

  AppEnvironment? _cachedEnvironment;
  String _cachedLocalHost = _defaultLocalHost;
  String _cachedLocalPort = '';
  String _cachedDirectHost = _defaultDirectHost;
  String _cachedDirectPort = _defaultDirectPort;

  /// 当前环境（同步，从内存缓存读取）
  AppEnvironment get currentEnvironment =>
      _cachedEnvironment ?? _defaultEnvironment;

  bool get _isDebug => _debugModeProvider();

  AppEnvironment get _defaultEnvironment =>
      _isDebug ? AppEnvironment.local : AppEnvironment.production;

  /// 当前 serverUrl（同步，从内存缓存读取）
  String get currentServerUrl => _serverUrlFor(currentEnvironment);

  String _serverUrlFor(AppEnvironment env) {
    switch (env) {
      case AppEnvironment.production:
        return _productionHost;
      case AppEnvironment.local:
        return _buildLocalUrl(_cachedLocalHost, _cachedLocalPort);
      case AppEnvironment.direct:
        return _buildLocalUrl(_cachedDirectHost, _cachedDirectPort);
    }
  }

  /// 从 SharedPreferences 加载持久化状态。首次使用前必须调用。
  Future<void> loadSavedState() async {
    final prefs = _prefs ?? await SharedPreferences.getInstance();
    final savedEnv = prefs.getString(_keyEnvironment);
    if (savedEnv != null) {
      try {
        _cachedEnvironment = AppEnvironment.values.byName(savedEnv);
      } catch (_) {
        // 无效的环境名，使用默认值
      }
    }
    _cachedLocalHost = prefs.getString(_keyLocalHost) ?? _defaultLocalHost;
    _cachedLocalPort = prefs.getString(_keyLocalPort) ?? '';
    _cachedDirectHost = prefs.getString(_keyDirectHost) ?? _defaultDirectHost;
    _cachedDirectPort = prefs.getString(_keyDirectPort) ?? _defaultDirectPort;
  }

  /// 切换环境（仅更新状态，无副作用）
  ///
  /// 返回新环境对应的 serverUrl。
  Future<String> switchEnvironment(AppEnvironment newEnv) async {
    _cachedEnvironment = newEnv;
    final prefs = _prefs ?? await SharedPreferences.getInstance();
    await prefs.setString(_keyEnvironment, newEnv.name);
    return currentServerUrl;
  }

  /// 更新本地环境的 host
  Future<void> updateLocalHost(String host) async {
    final sanitized = _sanitizeHost(host);
    _cachedLocalHost = sanitized;
    final prefs = _prefs ?? await SharedPreferences.getInstance();
    await prefs.setString(_keyLocalHost, sanitized);
  }

  /// 更新本地环境的 port
  Future<void> updateLocalPort(String port) async {
    final sanitized = _sanitizePort(port);
    _cachedLocalPort = sanitized;
    final prefs = _prefs ?? await SharedPreferences.getInstance();
    await prefs.setString(_keyLocalPort, sanitized);
  }

  /// 当前本地 host
  String get localHost => _cachedLocalHost;

  /// 当前本地 port
  String get localPort => _cachedLocalPort;

  /// 当前直连 host
  String get directHost => _cachedDirectHost;

  /// 当前直连 port
  String get directPort => _cachedDirectPort;

  /// 更新直连环境的 host
  Future<void> updateDirectHost(String host) async {
    final sanitized = _sanitizeHost(host);
    _cachedDirectHost = sanitized;
    final prefs = _prefs ?? await SharedPreferences.getInstance();
    await prefs.setString(_keyDirectHost, sanitized);
  }

  /// 更新直连环境的 port
  Future<void> updateDirectPort(String port) async {
    final sanitized = _sanitizePort(port);
    _cachedDirectPort = sanitized;
    final prefs = _prefs ?? await SharedPreferences.getInstance();
    await prefs.setString(_keyDirectPort, sanitized);
  }

  String _buildLocalUrl(String host, String port) {
    if (port.isEmpty) {
      return 'ws://$host';
    }
    return 'ws://$host:$port';
  }

  String _sanitizeHost(String host) {
    final trimmed = host.trim();
    // 基本格式校验：允许字母、数字、点、短横线、下划线
    if (trimmed.isEmpty || !RegExp(r'^[a-zA-Z0-9._-]+$').hasMatch(trimmed)) {
      return _defaultLocalHost;
    }
    return trimmed;
  }

  String _sanitizePort(String port) {
    final trimmed = port.trim();
    if (trimmed.isEmpty) return '';
    final parsed = int.tryParse(trimmed);
    if (parsed == null || parsed < 1 || parsed > 65535) return '';
    return trimmed;
  }
}
