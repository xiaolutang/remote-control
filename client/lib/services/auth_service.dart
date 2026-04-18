import 'dart:convert';
import 'dart:io' show HttpClient, HttpHeaders, Platform, SystemEncoding;
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'http_client_factory.dart';
import 'logger_service.dart';
import 'user_info_service.dart';
import 'crypto_service.dart';

/// 根据运行平台判断 view 参数
String get currentView {
  return (Platform.isAndroid || Platform.isIOS) ? 'mobile' : 'desktop';
}

/// 已鉴权请求 401 错误类型
enum AuthErrorCode {
  tokenReplaced,
  tokenExpired,
  tokenInvalid,
}

/// 已鉴权请求返回 401 时抛出的异常
class AuthException implements Exception {
  final AuthErrorCode code;
  final String message;
  AuthException(this.code, this.message);

  @override
  String toString() => message;
}

/// 认证服务
///
/// 职责：仅管理 token 的存储和清除。
/// 敏感数据（密码、token）使用 flutter_secure_storage 存储。
/// 非敏感数据（用户名）保留在 SharedPreferences。
/// Agent 生命周期由调用方（logout handler）通过 DesktopAgentManager 管理。
class AuthService {
  final String serverUrl;

  // 日志服务（可选)
  final LoggerService? _logger;
  final http.Client _client;
  final CryptoService _crypto;
  final FlutterSecureStorage _secureStorage;

  AuthService({
    required this.serverUrl,
    LoggerService? logger,
    http.Client? client,
    FlutterSecureStorage? secureStorage,
  })  : _logger = logger,
        _client = client ?? HttpClientFactory.create(),
        _crypto = CryptoService.instance,
        _secureStorage = secureStorage ??
            FlutterSecureStorage(
              aOptions: const AndroidOptions(encryptedSharedPreferences: true),
              iOptions: const IOSOptions(
                  accessibility: KeychainAccessibility.first_unlock),
              // Keep macOS secure storage behavior identical across debug and
              // release builds until stable signing/keychain-sharing is set up.
              mOptions: const MacOsOptions(useDataProtectionKeyChain: false),
            );

  /// 将 WebSocket URL 转换为 HTTP URL
  String _getHttpUrl() {
    if (serverUrl.startsWith('ws://')) {
      return serverUrl.replaceFirst('ws://', 'http://');
    } else if (serverUrl.startsWith('wss://')) {
      return serverUrl.replaceFirst('wss://', 'https://');
    }
    return serverUrl;
  }

  /// 注册
  Future<Map<String, dynamic>> register(
      String username, String password) async {
    final httpUrl = _getHttpUrl();

    // 拉取公钥并加密密码
    final body = <String, dynamic>{
      'username': username,
      'view': currentView,
    };
    try {
      await _crypto.fetchPublicKey(httpUrl);
      final encryptedPwd = base64Encode(
        _crypto.rsaEncrypt(utf8.encode(password)),
      );
      body['password_encrypted'] = encryptedPwd;
    } catch (e) {
      // ws:// 必须加密（不变量 #27），公钥获取失败则拒绝注册
      if (serverUrl.startsWith('ws://')) {
        throw Exception('安全连接建立失败，无法安全注册');
      }
      // wss:// 由 TLS 保护，可回退到明文密码
      body['password'] = password;
    }

    final response = await _client.post(
      Uri.parse('$httpUrl/api/register'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode(body),
    );

    final data = jsonDecode(response.body);

    if (response.statusCode == 200) {
      // 保存登录信息
      await _saveCredentials(username, password);
      await _saveSession(data);
      await UserInfoService().saveLoginTime();
      return data;
    } else {
      throw Exception(data['detail'] ?? '注册失败');
    }
  }

  /// 登录
  Future<Map<String, dynamic>> login(String username, String password) async {
    final httpUrl = _getHttpUrl();
    final uri = Uri.parse('$httpUrl/api/login');

    _logger?.info('Login attempt', metadata: {'username': username});

    // 拉取公钥并加密密码
    final body = <String, dynamic>{
      'username': username,
      'view': currentView,
    };
    try {
      await _crypto.fetchPublicKey(httpUrl);
      final encryptedPwd = base64Encode(
        _crypto.rsaEncrypt(utf8.encode(password)),
      );
      body['password_encrypted'] = encryptedPwd;
    } catch (e) {
      // ws:// 必须加密（不变量 #27），公钥获取失败则拒绝登录
      if (serverUrl.startsWith('ws://')) {
        _logger?.error(
            'Public key fetch failed on ws://, refusing plaintext login',
            metadata: {'error': e.toString()});
        throw Exception('安全连接建立失败，无法安全登录');
      }
      // wss:// 由 TLS 保护，可回退到明文密码
      _logger?.warn('Public key fetch failed, TLS protects transport',
          metadata: {'error': e.toString()});
      body['password'] = password;
    }

    http.Response response;
    try {
      response = await _client.post(
        uri,
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode(body),
      );
    } catch (e) {
      await _debugProbeLoginFailure(
        uri: uri,
        username: username,
        password: password,
        originalError: e,
      );
      rethrow;
    }

    final data = jsonDecode(response.body);

    if (response.statusCode == 200) {
      // 保存登录信息
      await _saveCredentials(username, password);
      await _saveSession(data);
      await UserInfoService().saveLoginTime();

      _logger?.info('Login successful', metadata: {
        'username': username,
        'session_id': data['session_id'],
      });

      return data;
    } else {
      _logger?.error('Login failed', metadata: {
        'username': username,
        'status_code': response.statusCode,
        'error': data['detail'],
      });

      throw Exception(data['detail'] ?? '登录失败');
    }
  }

  Future<void> _debugProbeLoginFailure({
    required Uri uri,
    required String username,
    required String password,
    required Object originalError,
  }) async {
    if (!kDebugMode) {
      return;
    }

    debugPrint('[AuthService] login primary client failed: $originalError');
    await _debugRawHttpProbe(
      label: 'system-proxy',
      uri: uri,
      username: username,
      password: password,
      useSystemProxy: true,
    );
    await _debugRawHttpProbe(
      label: 'direct',
      uri: uri,
      username: username,
      password: password,
      useSystemProxy: false,
    );
  }

  Future<void> _debugRawHttpProbe({
    required String label,
    required Uri uri,
    required String username,
    required String password,
    required bool useSystemProxy,
  }) async {
    final client = HttpClient()
      ..connectionTimeout = const Duration(seconds: 10);
    if (kDebugMode) {
      client.badCertificateCallback = (_, __, ___) => true;
    }
    client.findProxy =
        useSystemProxy ? HttpClient.findProxyFromEnvironment : (_) => 'DIRECT';

    try {
      final request = await client.postUrl(uri);
      request.persistentConnection = false;
      request.headers.set(HttpHeaders.contentTypeHeader, 'application/json');
      request.write(jsonEncode({
        'username': username,
        'password': password,
        'view': currentView,
      }));
      final response = await request.close();
      final body = await response.transform(SystemEncoding().decoder).join();
      debugPrint(
        '[AuthService] raw probe($label) '
        'status=${response.statusCode} body=$body',
      );
    } catch (e) {
      debugPrint('[AuthService] raw probe($label) failed: $e');
    } finally {
      client.close(force: true);
    }
  }

  /// 保存凭证（密码存入 secure storage，用户名保留 SharedPreferences）
  Future<void> _saveCredentials(String username, String password) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('rc_username', username);
    await _secureStorage.write(key: 'rc_password', value: password);
    // 迁移旧 SharedPreferences 中的密码
    final oldPassword = prefs.getString('rc_password');
    if (oldPassword != null) {
      await prefs.remove('rc_password');
    }
  }

  /// 保存会话（token 存入 secure storage）
  Future<void> _saveSession(Map<String, dynamic> data) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('rc_session_id', data['session_id'] ?? '');
    await prefs.setString('rc_expires_at', data['expires_at'] ?? '');
    await _secureStorage.write(key: 'rc_token', value: data['token'] ?? '');
    await _secureStorage.write(
        key: 'rc_refresh_token', value: data['refresh_token'] ?? '');
    // 迁移旧 SharedPreferences 中的 token
    final oldToken = prefs.getString('rc_token');
    if (oldToken != null) {
      await prefs.remove('rc_token');
    }
    final oldRefreshToken = prefs.getString('rc_refresh_token');
    if (oldRefreshToken != null) {
      await prefs.remove('rc_refresh_token');
    }
  }

  /// 获取保存的凭证
  Future<Map<String, String>?> getSavedCredentials() async {
    final prefs = await SharedPreferences.getInstance();
    final username = prefs.getString('rc_username');
    // 优先从 secure storage 读取密码
    String? password = await _secureStorage.read(key: 'rc_password');
    // 兼容旧版本：如果 secure storage 无密码但 SharedPreferences 有，自动迁移
    if (password == null) {
      final oldPassword = prefs.getString('rc_password');
      if (oldPassword != null) {
        await _secureStorage.write(key: 'rc_password', value: oldPassword);
        await prefs.remove('rc_password');
        password = oldPassword;
      }
    }

    if (username != null && password != null) {
      return {'username': username, 'password': password};
    }
    return null;
  }

  /// 获取保存的会话
  Future<Map<String, String>?> getSavedSession() async {
    final prefs = await SharedPreferences.getInstance();
    final sessionId = prefs.getString('rc_session_id');
    // 优先从 secure storage 读取 token
    String? token = await _secureStorage.read(key: 'rc_token');
    // 兼容旧版本：如果 secure storage 无 token 但 SharedPreferences 有，自动迁移
    if (token == null) {
      final oldToken = prefs.getString('rc_token');
      if (oldToken != null) {
        await _secureStorage.write(key: 'rc_token', value: oldToken);
        await prefs.remove('rc_token');
        token = oldToken;
      }
    }

    if (sessionId != null && token != null) {
      return {'session_id': sessionId, 'token': token};
    }
    return null;
  }

  /// 自动登录
  Future<Map<String, dynamic>?> autoLogin() async {
    final credentials = await getSavedCredentials();
    if (credentials != null) {
      try {
        return await login(credentials['username']!, credentials['password']!);
      } catch (e) {
        return null;
      }
    }
    return null;
  }

  /// 登出 — 清除本地凭证和 token
  ///
  /// Agent 生命周期由调用方负责：在调用 logout() 之前，
  /// 调用方应先通过 DesktopAgentManager.onLogout() 关闭 Agent。
  Future<void> logout() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove('rc_username');
    await prefs.remove('rc_session_id');
    await prefs.remove('rc_expires_at');
    // 清除 secure storage 中的敏感数据
    await _secureStorage.delete(key: 'rc_password');
    await _secureStorage.delete(key: 'rc_token');
    await _secureStorage.delete(key: 'rc_refresh_token');
    await UserInfoService().clearLoginTime();
  }
}
