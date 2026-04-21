import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rc_client/services/secure_storage_service.dart';

class _CountingSecureStorage implements FlutterSecureStorage {
  final Map<String, String> _store = <String, String>{};
  int readCallCount = 0;

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
    readCallCount += 1;
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
  test('does not eager-load every tracked secret when reading a single key',
      () async {
    final storage = _CountingSecureStorage()
      .._store[SecureStorageService.passwordKey] = 'pwd'
      .._store[SecureStorageService.tokenKey] = 'tok'
      .._store[SecureStorageService.refreshTokenKey] = 'rt';
    final service = SecureStorageService(storage: storage);

    expect(
      await service.read(SecureStorageService.tokenKey),
      'tok',
    );
    expect(await service.read(SecureStorageService.tokenKey), 'tok');

    expect(storage.readCallCount, 2);
  });

  test(
      'tracked batch write seeds cache so later reads do not hit secure storage again',
      () async {
    final storage = _CountingSecureStorage();
    final service = SecureStorageService(storage: storage);

    await service.writeTrackedEntries(<String, String?>{
      SecureStorageService.passwordKey: 'pwd',
      SecureStorageService.tokenKey: 'tok',
      SecureStorageService.refreshTokenKey: 'refresh-token',
    });

    expect(
      await service.read(SecureStorageService.refreshTokenKey),
      'refresh-token',
    );
    expect(storage.readCallCount, 0);
  });

  test('legacy tracked entries are migrated to bundle for the next launch',
      () async {
    final storage = _CountingSecureStorage()
      .._store[SecureStorageService.tokenKey] = 'tok'
      .._store[SecureStorageService.refreshTokenKey] = 'rt';

    final firstLaunch = SecureStorageService(storage: storage);
    final firstValues = await firstLaunch.readTrackedEntries(
      const <String>[
        SecureStorageService.tokenKey,
        SecureStorageService.refreshTokenKey,
      ],
    );

    expect(firstValues[SecureStorageService.tokenKey], 'tok');
    expect(firstValues[SecureStorageService.refreshTokenKey], 'rt');
    expect(storage.readCallCount, 3);

    storage.readCallCount = 0;
    final secondLaunch = SecureStorageService(storage: storage);
    final secondValues = await secondLaunch.readTrackedEntries(
      const <String>[
        SecureStorageService.tokenKey,
        SecureStorageService.refreshTokenKey,
      ],
    );

    expect(secondValues[SecureStorageService.tokenKey], 'tok');
    expect(secondValues[SecureStorageService.refreshTokenKey], 'rt');
    expect(storage.readCallCount, 1);
  });
}
