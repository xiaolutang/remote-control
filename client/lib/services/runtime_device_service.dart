import 'dart:convert';

import 'package:http/http.dart' as http;

import '../models/runtime_device.dart';
import '../models/runtime_terminal.dart';
import 'auth_service.dart';
import 'http_client_factory.dart';

class RuntimeDeviceService {
  RuntimeDeviceService({
    required this.serverUrl,
    http.Client? client,
  }) : _client = client ?? HttpClientFactory.create();

  final String serverUrl;
  final http.Client _client;

  String get _httpUrl {
    if (serverUrl.startsWith('ws://')) {
      return serverUrl.replaceFirst('ws://', 'http://');
    }
    if (serverUrl.startsWith('wss://')) {
      return serverUrl.replaceFirst('wss://', 'https://');
    }
    return serverUrl;
  }

  Map<String, String> _headers(String token) => {
        'Authorization': 'Bearer $token',
        'Content-Type': 'application/json',
      };

  /// 处理非 200 响应，对 401 按 error_code 分支抛出 AuthException
  Never _throwError(http.Response response, String defaultMessage) {
    final data = jsonDecode(response.body) as Map<String, dynamic>;
    if (response.statusCode == 401) {
      final errorCode = data['error_code'] as String?;
      switch (errorCode) {
        case 'TOKEN_REPLACED':
          throw AuthException(
              AuthErrorCode.tokenReplaced, '您已在其他设备登录');
        case 'TOKEN_EXPIRED':
          throw AuthException(
              AuthErrorCode.tokenExpired, '登录已过期');
        case 'TOKEN_INVALID':
          throw AuthException(
              AuthErrorCode.tokenInvalid, '认证信息无效');
      }
    }
    throw Exception(data['detail'] ?? defaultMessage);
  }

  Future<List<RuntimeDevice>> listDevices(String token) async {
    final response = await _client.get(
      Uri.parse('$_httpUrl/api/runtime/devices'),
      headers: _headers(token),
    );
    final data = jsonDecode(response.body) as Map<String, dynamic>;
    if (response.statusCode != 200) {
      _throwError(response, '加载设备失败');
    }

    final devices = (data['devices'] as List<dynamic>? ?? const [])
        .whereType<Map<String, dynamic>>()
        .map(RuntimeDevice.fromJson)
        .toList(growable: false);
    return devices;
  }

  Future<List<RuntimeTerminal>> listTerminals(String token, String deviceId) async {
    final response = await _client.get(
      Uri.parse('$_httpUrl/api/runtime/devices/$deviceId/terminals'),
      headers: _headers(token),
    );
    final data = jsonDecode(response.body) as Map<String, dynamic>;
    if (response.statusCode != 200) {
      _throwError(response, '加载终端失败');
    }

    return (data['terminals'] as List<dynamic>? ?? const [])
        .whereType<Map<String, dynamic>>()
        .map(RuntimeTerminal.fromJson)
        .toList(growable: false);
  }

  Future<RuntimeTerminal?> getTerminal(
    String token,
    String deviceId,
    String terminalId,
  ) async {
    final terminals = await listTerminals(token, deviceId);
    for (final terminal in terminals) {
      if (terminal.terminalId == terminalId) {
        return terminal;
      }
    }
    return null;
  }

  Future<RuntimeTerminal> createTerminal(
    String token,
    String deviceId, {
    required String title,
    required String cwd,
    required String command,
    Map<String, String> env = const {},
    String? terminalId,
  }) async {
    final resolvedTerminalId =
        terminalId ?? 'term-${DateTime.now().millisecondsSinceEpoch}';
    final response = await _client.post(
      Uri.parse('$_httpUrl/api/runtime/devices/$deviceId/terminals'),
      headers: _headers(token),
      body: jsonEncode({
        'terminal_id': resolvedTerminalId,
        'title': title,
        'cwd': cwd,
        'command': command,
        'env': env,
      }),
    );
    final data = jsonDecode(response.body) as Map<String, dynamic>;
    if (response.statusCode != 200) {
      _throwError(response, '创建终端失败');
    }
    return RuntimeTerminal.fromJson(data);
  }

  Future<RuntimeTerminal> closeTerminal(
    String token,
    String deviceId,
    String terminalId,
  ) async {
    final response = await _client.delete(
      Uri.parse('$_httpUrl/api/runtime/devices/$deviceId/terminals/$terminalId'),
      headers: _headers(token),
    );
    final data = jsonDecode(response.body) as Map<String, dynamic>;
    if (response.statusCode != 200) {
      _throwError(response, '关闭终端失败');
    }
    return RuntimeTerminal.fromJson(data);
  }

  Future<RuntimeDevice> updateDevice(
    String token,
    String deviceId,
    {String? name}) async {
    final response = await _client.patch(
      Uri.parse('$_httpUrl/api/runtime/devices/$deviceId'),
      headers: _headers(token),
      body: jsonEncode({
        if (name != null) 'name': name,
      }),
    );
    final data = jsonDecode(response.body) as Map<String, dynamic>;
    if (response.statusCode != 200) {
      _throwError(response, '更新设备配置失败');
    }
    return RuntimeDevice.fromJson(data);
  }

  Future<RuntimeTerminal> updateTerminalTitle(
    String token,
    String deviceId,
    String terminalId,
    String title,
  ) async {
    final response = await _client.patch(
      Uri.parse('$_httpUrl/api/runtime/devices/$deviceId/terminals/$terminalId'),
      headers: _headers(token),
      body: jsonEncode({'title': title}),
    );
    final data = jsonDecode(response.body) as Map<String, dynamic>;
    if (response.statusCode != 200) {
      _throwError(response, '更新终端标题失败');
    }
    return RuntimeTerminal.fromJson(data);
  }
}
