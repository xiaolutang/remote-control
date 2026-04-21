import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:rc_client/services/auth_service.dart';
import 'package:rc_client/services/crypto_service.dart';
import 'package:shared_preferences/shared_preferences.dart';

class _InMemorySecureStorage implements FlutterSecureStorage {
  final Map<String, String> _store = <String, String>{};

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
    if (value == null) {
      _store.remove(key);
      return;
    }
    _store[key] = value;
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
    return Map<String, String>.from(_store);
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

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  const bool runInHarness = bool.fromEnvironment(
    'RUN_LOCAL_GATEWAY_AUTH_INTEGRATION',
    defaultValue: false,
  );

  group('Local gateway integration', () {
    testWidgets('register/login works via wss://localhost/rc and stores scoped key',
        (_) async {
      SharedPreferences.setMockInitialValues(<String, Object>{});

      final timestamp = DateTime.now().millisecondsSinceEpoch;
      final username = 'local_it_$timestamp';
      const password = 'Test123456';
      const serverUrl = 'wss://localhost/rc';
      const httpBaseUrl = 'https://localhost/rc';
      final secureStorage = _InMemorySecureStorage();

      final registerService = AuthService(
        serverUrl: serverUrl,
        secureStorage: secureStorage,
      );
      final registerResult = await registerService.register(username, password);
      expect(registerResult['token'], isNotNull);
      expect(registerResult['session_id'], isNotNull);

      final loginService = AuthService(
        serverUrl: serverUrl,
        secureStorage: secureStorage,
      );
      final loginResult = await loginService.login(username, password);
      expect(loginResult['token'], isNotNull);
      expect(loginResult['session_id'], isNotNull);

      final prefs = await SharedPreferences.getInstance();
      final fingerprintKey =
          CryptoService.fingerprintPrefsKeyForBaseUrl(httpBaseUrl);
      expect(prefs.getString(fingerprintKey), isNotNull);
      expect(prefs.getString('rc_username'), username);
      expect(await secureStorage.read(key: 'rc_password'), password);
    }, skip: !runInHarness);
  });
}
