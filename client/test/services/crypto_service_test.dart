import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:rc_client/services/crypto_service.dart';
import 'package:shared_preferences/shared_preferences.dart';

const _testPublicKeyPem = '''-----BEGIN PUBLIC KEY-----
MFwwDQYJKoZIhvcNAQEBBQADSwAwSAJBAN5paohWYIlgmftWMKcsNtcT5h6++42e
J/ORQ8Hf1ebpMIFmYozP+xZosNgvKNp0j4O7ZfbazZnjkt9pcZlKvwsCAwEAAQ==
-----END PUBLIC KEY-----''';

void main() {
  group('CryptoService fingerprint scope', () {
    test('uses different preference keys for local and production servers', () {
      final localKey =
          CryptoService.fingerprintPrefsKeyForBaseUrl('https://localhost/rc');
      final productionKey = CryptoService.fingerprintPrefsKeyForBaseUrl(
        'https://rc.xiaolutang.top/rc',
      );

      expect(localKey, isNot(equals(productionKey)));
      expect(localKey, contains('localhost'));
      expect(productionKey, contains('rc_xiaolutang_top'));
    });

    test('includes port for direct endpoints', () {
      final directKey = CryptoService.fingerprintPrefsKeyForBaseUrl(
        'http://127.0.0.1:8880',
      );

      expect(directKey, contains('127_0_0_1_8880'));
    });
  });

  group('CryptoService public key cache', () {
    late HttpServer server;

    tearDown(() async {
      await server.close(force: true);
    });

    test('reuses loaded key for same endpoint and reset clears in-memory state',
        () async {
      SharedPreferences.setMockInitialValues(<String, Object>{});
      final crypto = CryptoService.instance;
      var hitCount = 0;

      server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      server.listen((request) async {
        hitCount += 1;
        request.response.statusCode = 200;
        request.response.headers.contentType = ContentType.json;
        request.response.write(jsonEncode(const {
          'public_key_pem': _testPublicKeyPem,
          'fingerprint': 'fingerprint-1',
        }));
        await request.response.close();
      });

      final baseUrl = 'http://127.0.0.1:${server.port}';
      await crypto.resetFingerprintForBaseUrl(baseUrl);

      await crypto.fetchPublicKey(baseUrl);
      expect(hitCount, 1);
      expect(crypto.hasPublicKey, isTrue);

      await crypto.fetchPublicKey(baseUrl);
      expect(hitCount, 1);

      await crypto.resetFingerprintForBaseUrl(baseUrl);
      expect(crypto.hasPublicKey, isFalse);

      await crypto.fetchPublicKey(baseUrl);
      expect(hitCount, 2);
    });
  });

  group('CryptoService AES key isolation', () {
    /// 回归测试：每个 CryptoService 实例应有独立的 AES 密钥。
    /// 根因：CryptoService.instance 单例的 clearAesKey() 会清除所有连接的密钥，
    /// 导致第二个终端无法解密消息。
    test('separate instances have independent AES keys', () {
      final cryptoA = CryptoService();
      final cryptoB = CryptoService();

      // 各自生成密钥
      final keyA = cryptoA.generateAesKey();
      final keyB = cryptoB.generateAesKey();

      // 密钥不同
      expect(keyA, isNot(equals(keyB)));

      // 各自加密/解密正常
      final message = {'type': 'data', 'payload': 'hello'};
      final encryptedA = cryptoA.encryptMessage(message);
      final encryptedB = cryptoB.encryptMessage(message);

      expect(encryptedA['encrypted'], isTrue);
      expect(encryptedB['encrypted'], isTrue);

      final decryptedA = cryptoA.decryptMessage(
        Map<String, dynamic>.from(encryptedA),
      );
      final decryptedB = cryptoB.decryptMessage(
        Map<String, dynamic>.from(encryptedB),
      );
      expect(decryptedA['payload'], 'hello');
      expect(decryptedB['payload'], 'hello');

      // 关键：清除 A 的密钥不影响 B
      cryptoA.clearAesKey();
      expect(
        () => cryptoA.decryptMessage(Map<String, dynamic>.from(encryptedA)),
        throwsStateError,
      );

      // B 仍可正常解密
      final decryptedBAgain = cryptoB.decryptMessage(
        Map<String, dynamic>.from(encryptedB),
      );
      expect(decryptedBAgain['payload'], 'hello');
    });

    test('clearAesKey on one instance does not affect another', () {
      final cryptoA = CryptoService();
      final cryptoB = CryptoService();

      cryptoA.generateAesKey();
      cryptoB.generateAesKey();

      // A 断开 → 清除密钥
      cryptoA.clearAesKey();

      // B 仍能加密
      final message = {'type': 'data', 'payload': 'test'};
      final encrypted = cryptoB.encryptMessage(message);
      expect(encrypted['encrypted'], isTrue);

      // B 仍能解密
      final decrypted = cryptoB.decryptMessage(
        Map<String, dynamic>.from(encrypted),
      );
      expect(decrypted['payload'], 'test');
    });

    test('generateAesKey overwrites previous key within same instance', () {
      final crypto = CryptoService();
      final key1 = crypto.generateAesKey();

      final message = {'type': 'data', 'payload': 'old'};
      final encrypted1 = crypto.encryptMessage(message);

      // 重连场景：生成新密钥
      final key2 = crypto.generateAesKey();
      expect(key1, isNot(equals(key2)));

      // 旧密文无法解密（因为密钥已被覆盖）
      expect(
        () => crypto.decryptMessage(Map<String, dynamic>.from(encrypted1)),
        throwsA(isA<Exception>()),
      );

      // 新密钥正常工作
      final encrypted2 = crypto.encryptMessage({'type': 'data', 'payload': 'new'});
      final decrypted = crypto.decryptMessage(
        Map<String, dynamic>.from(encrypted2),
      );
      expect(decrypted['payload'], 'new');
    });
  });
}
