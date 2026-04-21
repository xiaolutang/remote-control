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
}
