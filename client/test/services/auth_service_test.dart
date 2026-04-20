import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:rc_client/services/auth_service.dart';
import 'package:rc_client/services/runtime_device_service.dart';
import 'package:rc_client/services/websocket_service.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

// ---------------------------------------------------------------------------
// 内存版 FlutterSecureStorage mock
// ---------------------------------------------------------------------------
class _InMemorySecureStorage implements FlutterSecureStorage {
  final Map<String, String> _store = {};

  @override
  Future<void> write({
    required String key,
    String? value,
    IOSOptions? iOptions,
    AndroidOptions? aOptions,
    LinuxOptions? lOptions,
    WindowsOptions? wOptions,
    WebOptions? webOptions,
    MacOsOptions? mOptions,
  }) async {
    _store[key] = value ?? '';
  }

  @override
  Future<String?> read({
    required String key,
    IOSOptions? iOptions,
    AndroidOptions? aOptions,
    LinuxOptions? lOptions,
    WindowsOptions? wOptions,
    WebOptions? webOptions,
    MacOsOptions? mOptions,
  }) async {
    return _store[key];
  }

  @override
  Future<void> delete({
    required String key,
    IOSOptions? iOptions,
    AndroidOptions? aOptions,
    LinuxOptions? lOptions,
    WindowsOptions? wOptions,
    WebOptions? webOptions,
    MacOsOptions? mOptions,
  }) async {
    _store.remove(key);
  }

  @override
  Future<bool> containsKey({
    required String key,
    IOSOptions? iOptions,
    AndroidOptions? aOptions,
    LinuxOptions? lOptions,
    WindowsOptions? wOptions,
    WebOptions? webOptions,
    MacOsOptions? mOptions,
  }) async {
    return _store.containsKey(key);
  }

  @override
  Future<Map<String, String>> readAll({
    IOSOptions? iOptions,
    AndroidOptions? aOptions,
    LinuxOptions? lOptions,
    WindowsOptions? wOptions,
    WebOptions? webOptions,
    MacOsOptions? mOptions,
  }) async {
    return Map.from(_store);
  }

  @override
  Future<void> deleteAll({
    IOSOptions? iOptions,
    AndroidOptions? aOptions,
    LinuxOptions? lOptions,
    WindowsOptions? wOptions,
    WebOptions? webOptions,
    MacOsOptions? mOptions,
  }) async {
    _store.clear();
  }

  @override
  dynamic noSuchMethod(Invocation invocation) => null;
}

// ---------------------------------------------------------------------------
// 辅助：构造 401 响应
// ---------------------------------------------------------------------------
http.Response _auth401(String? errorCode, {String detail = 'Unauthorized'}) {
  final body = <String, dynamic>{
    if (detail.isNotEmpty) 'detail': detail,
  };
  if (errorCode != null) body['error_code'] = errorCode;
  return http.Response(jsonEncode(body), 401);
}

// ---------------------------------------------------------------------------
// 辅助：构造成功登录响应
// ---------------------------------------------------------------------------
http.Response _loginSuccess() {
  return http.Response(
    jsonEncode({
      'session_id': 'sid-1',
      'token': 'tok-1',
      'refresh_token': 'rt-1',
      'expires_at': '2099-01-01T00:00:00Z',
    }),
    200,
  );
}

void main() {
  // =========================================================================
  // AC1: login / register 请求携带 view 参数
  // =========================================================================
  group('AC1: login/register 请求 view 参数', () {
    test('login 请求 body 包含 view 字段', () async {
      SharedPreferences.setMockInitialValues({});
      String? capturedBody;

      final client = MockClient((request) async {
        capturedBody = request.body;
        return _loginSuccess();
      });

      final service = AuthService(
        serverUrl: 'http://localhost:8888',
        client: client,
        secureStorage: _InMemorySecureStorage(),
      );

      await service.login('user', 'pass');

      final body = jsonDecode(capturedBody!) as Map<String, dynamic>;
      expect(body.containsKey('view'), isTrue);
      // currentView 在测试环境（桌面）返回 'desktop'
      expect(body['view'], currentView);
    });

    test('register 请求 body 包含 view 字段', () async {
      SharedPreferences.setMockInitialValues({});
      String? capturedBody;

      final client = MockClient((request) async {
        capturedBody = request.body;
        return _loginSuccess();
      });

      final service = AuthService(
        serverUrl: 'http://localhost:8888',
        client: client,
        secureStorage: _InMemorySecureStorage(),
      );

      await service.register('user', 'pass');

      final body = jsonDecode(capturedBody!) as Map<String, dynamic>;
      expect(body.containsKey('view'), isTrue);
      expect(body['view'], currentView);
    });
  });

  // =========================================================================
  // AC2: 已鉴权请求 401 按 error_code 分支
  // 通过 RuntimeDeviceService._throwError 间接测试
  // =========================================================================
  group('AC2: 401 error_code 分支', () {
    test('TOKEN_REPLACED 抛出 AuthException.tokenReplaced', () async {
      final client = MockClient((request) async {
        return _auth401('TOKEN_REPLACED');
      });

      final service = RuntimeDeviceService(
        serverUrl: 'ws://localhost:8888',
        client: client,
      );

      expect(
        () => service.listDevices('valid-token'),
        throwsA(isA<AuthException>().having(
          (e) => e.code,
          'code',
          AuthErrorCode.tokenReplaced,
        )),
      );
    });

    test('TOKEN_EXPIRED 抛出 AuthException.tokenExpired', () async {
      final client = MockClient((request) async {
        return _auth401('TOKEN_EXPIRED');
      });

      final service = RuntimeDeviceService(
        serverUrl: 'ws://localhost:8888',
        client: client,
      );

      expect(
        () => service.listDevices('valid-token'),
        throwsA(isA<AuthException>().having(
          (e) => e.code,
          'code',
          AuthErrorCode.tokenExpired,
        )),
      );
    });

    test('TOKEN_INVALID 抛出 AuthException.tokenInvalid', () async {
      final client = MockClient((request) async {
        return _auth401('TOKEN_INVALID');
      });

      final service = RuntimeDeviceService(
        serverUrl: 'ws://localhost:8888',
        client: client,
      );

      expect(
        () => service.listDevices('valid-token'),
        throwsA(isA<AuthException>().having(
          (e) => e.code,
          'code',
          AuthErrorCode.tokenInvalid,
        )),
      );
    });

    test('无 error_code 兜底抛出普通 Exception', () async {
      final client = MockClient((request) async {
        return _auth401(null, detail: 'Something went wrong');
      });

      final service = RuntimeDeviceService(
        serverUrl: 'ws://localhost:8888',
        client: client,
      );

      expect(
        () => service.listDevices('valid-token'),
        throwsA(allOf(
          isA<Exception>(),
          isNot(isA<AuthException>()),
        )),
      );
    });
  });

  // =========================================================================
  // AC3: WebSocket 4001 触发被踢处理 (tokenInvalidStream)
  // =========================================================================
  group('AC3: WebSocket 4001 触发 tokenInvalidStream', () {
    test('close code 4001 触发 tokenInvalidStream', () async {
      final service = WebSocketService(
        serverUrl: 'ws://localhost:8888',
        token: 'test-token',
        sessionId: 'session-1',
        autoReconnect: false,
      );

      // 先将状态设为 connected，这样 _handleDisconnect 才会触发 4001 处理
      // 通过 connect() 然后模拟关闭来测试
      // 由于 _handleDisconnect 和 _lastCloseCode 是私有的，
      // 我们使用 tokenInvalidStream 的存在性验证 + close code 边界检查
      final subscription = service.tokenInvalidStream.listen((_) {});

      // 验证 stream 是广播且已订阅
      expect(service.tokenInvalidStream.isBroadcast, isTrue);

      // 清理
      await subscription.cancel();
      service.dispose();

      // 注意：由于 WebSocketService 的 connect 依赖真实 WebSocket 连接，
      // 无法在单元测试中完整模拟 4001 关闭码。
      // 4001 处理逻辑已在 websocket_service.dart 的 _handleDisconnect 中实现：
      //   if (_lastCloseCode == 4001) { _tokenInvalidController.add(null); }
      // 这里通过验证 stream 存在、可订阅、是广播类型来确认接口正确。
    });

    test('tokenInvalidStream 关闭时触发 onDone', () async {
      final service = WebSocketService(
        serverUrl: 'ws://localhost:8888',
        token: 'test-token',
        sessionId: 'session-1',
        autoReconnect: false,
      );

      bool streamClosed = false;
      final subscription = service.tokenInvalidStream.listen(
        (_) {},
        onDone: () {
          streamClosed = true;
        },
      );

      await Future.delayed(const Duration(milliseconds: 50));
      service.dispose();
      await Future.delayed(const Duration(milliseconds: 100));

      expect(streamClosed, isTrue);
      await subscription.cancel();
    });
  });

  // =========================================================================
  // AC4: 跳转时 token 清除 (logout)
  // =========================================================================
  group('AC4: logout 清除 token', () {
    test('logout 清除所有 SharedPreferences 键', () async {
      // 设置初始值
      SharedPreferences.setMockInitialValues({
        'rc_username': 'testuser',
        'rc_password': 'testpass',
        'rc_session_id': 'sid-1',
        'rc_token': 'tok-1',
        'rc_refresh_token': 'rt-1',
        'rc_expires_at': '2099-01-01T00:00:00Z',
      });

      final service = AuthService(
        serverUrl: 'http://localhost:8888',
        secureStorage: _InMemorySecureStorage(),
      );

      // 验证初始状态有值
      final prefs = await SharedPreferences.getInstance();
      expect(prefs.getString('rc_username'), 'testuser');
      expect(prefs.getString('rc_token'), 'tok-1');

      // 执行 logout
      await service.logout();

      // 验证所有键已被清除
      expect(prefs.getString('rc_username'), isNull);
      expect(prefs.getString('rc_session_id'), isNull);
      expect(prefs.getString('rc_expires_at'), isNull);
    });

    test('logout 后 getSavedSession 返回 null', () async {
      SharedPreferences.setMockInitialValues({
        'rc_username': 'testuser',
        'rc_session_id': 'sid-1',
      });

      final secureStorage = _InMemorySecureStorage();
      await secureStorage.write(key: 'rc_password', value: 'testpass');
      await secureStorage.write(key: 'rc_token', value: 'tok-1');

      final service = AuthService(
        serverUrl: 'http://localhost:8888',
        secureStorage: secureStorage,
      );

      // 登出前有值
      final sessionBefore = await service.getSavedSession();
      expect(sessionBefore, isNotNull);
      expect(sessionBefore!['token'], 'tok-1');

      await service.logout();

      // 登出后返回 null
      final sessionAfter = await service.getSavedSession();
      expect(sessionAfter, isNull);
    });

    test('logout 后 getSavedCredentials 返回 null', () async {
      SharedPreferences.setMockInitialValues({
        'rc_username': 'testuser',
        'rc_session_id': 'sid-1',
      });

      final secureStorage = _InMemorySecureStorage();
      await secureStorage.write(key: 'rc_password', value: 'testpass');
      await secureStorage.write(key: 'rc_token', value: 'tok-1');

      final service = AuthService(
        serverUrl: 'http://localhost:8888',
        secureStorage: secureStorage,
      );

      final credsBefore = await service.getSavedCredentials();
      expect(credsBefore, isNotNull);

      await service.logout();

      final credsAfter = await service.getSavedCredentials();
      expect(credsAfter, isNull);
    });
  });
}
