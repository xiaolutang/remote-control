import 'dart:convert';
import 'dart:io';
import 'dart:math';
import 'dart:typed_data';

import 'package:asn1lib/asn1lib.dart' as asn1;
import 'package:pointycastle/export.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// 应用层加密服务：RSA-OAEP + AES-256-GCM + TOFU 公钥信任
class CryptoService {
  CryptoService._();
  static final CryptoService instance = CryptoService._();

  static const _keyFingerprintPrefsKey = 'rc_server_key_fingerprint';

  RSAPublicKey? _publicKey;
  String? _fingerprint;

  /// 当前 AES 会话密钥（每次 WebSocket 连接生成新的）
  Uint8List? _aesKey;

  /// 获取服务器公钥信息并校验指纹（TOFU）
  ///
  /// [httpBaseUrl] 例: http://192.168.1.78:8080
  /// 如果指纹不匹配（可能中间人攻击），抛出异常。
  Future<void> fetchPublicKey(String httpBaseUrl) async {
    final uri = Uri.parse('$httpBaseUrl/api/public-key');
    final client = HttpClient();
    try {
      client.connectionTimeout = const Duration(seconds: 10);
      final request = await client.getUrl(uri);
      final response = await request.close();
      final body =
          await response.transform(utf8.decoder).join();
      final data = jsonDecode(body) as Map<String, dynamic>;

      final pem = data['public_key_pem'] as String;
      final fingerprint = data['fingerprint'] as String;

      // 解析 PEM 公钥
      _publicKey = _parseRsaPublicKeyFromPem(pem);
      _fingerprint = fingerprint;

      // TOFU: 校验指纹
      await _verifyFingerprint(fingerprint);
    } finally {
      client.close(force: true);
    }
  }

  /// RSA-OAEP-SHA256 加密（用于加密密码和 AES 密钥）
  Uint8List rsaEncrypt(Uint8List plaintext) {
    if (_publicKey == null) {
      throw StateError('Public key not loaded. Call fetchPublicKey first.');
    }
    final cipher = OAEPEncoding.withSHA256(RSAEngine())
      ..init(
        true,
        PublicKeyParameter<RSAPublicKey>(_publicKey!),
      );
    return cipher.process(plaintext);
  }

  /// 生成新的 AES-256 会话密钥
  Uint8List generateAesKey() {
    final secureRandom = FortunaRandom();
    final seeds = List<int>.generate(32, (_) => Random.secure().nextInt(256));
    secureRandom.seed(KeyParameter(Uint8List.fromList(seeds)));
    _aesKey = Uint8List(32);
    for (var i = 0; i < 32; i++) {
      _aesKey![i] = secureRandom.nextUint8();
    }
    return _aesKey!;
  }

  /// 获取 RSA 加密后的 AES 密钥（base64），用于 auth 消息
  String getEncryptedAesKeyBase64() {
    if (_publicKey == null || _aesKey == null) {
      throw StateError('Public key and AES key required');
    }
    final encrypted = rsaEncrypt(_aesKey!);
    return base64Encode(encrypted);
  }

  /// AES-256-GCM 加密消息
  Map<String, dynamic> encryptMessage(Map<String, dynamic> message) {
    if (_aesKey == null) return message;

    final plaintext = utf8.encode(jsonEncode(message));
    final iv = _generateIv();
    final cipher = GCMBlockCipher(AESEngine())
      ..init(true, AEADParameters(
        KeyParameter(_aesKey!),
        128, // tag length in bits
        iv,
        Uint8List(0), // no additional data
      ));

    final output = cipher.process(Uint8List.fromList(plaintext));
    return {
      'encrypted': true,
      'iv': base64Encode(iv),
      'data': base64Encode(output),
    };
  }

  /// AES-256-GCM 解密消息
  Map<String, dynamic> decryptMessage(Map<String, dynamic> raw) {
    if (_aesKey == null) throw StateError('AES key not set');

    final iv = base64Decode(raw['iv'] as String);
    final data = base64Decode(raw['data'] as String);

    final cipher = GCMBlockCipher(AESEngine())
      ..init(false, AEADParameters(
        KeyParameter(_aesKey!),
        128,
        iv,
        Uint8List(0),
      ));

    final decrypted = cipher.process(data);
    return jsonDecode(utf8.decode(decrypted)) as Map<String, dynamic>;
  }

  /// 判断消息类型是否需要加密
  bool shouldEncrypt(String msgType) {
    return !const {'auth', 'connected', 'ping', 'pong'}.contains(msgType);
  }

  /// 清除 AES 密钥（断开连接时调用）
  void clearAesKey() {
    _aesKey = null;
  }

  /// 当前公钥指纹
  String? get fingerprint => _fingerprint;

  /// 当前公钥是否已加载
  bool get hasPublicKey => _publicKey != null;

  // ---- 内部方法 ----

  Uint8List _generateIv() {
    final iv = Uint8List(12);
    final random = Random.secure();
    for (var i = 0; i < 12; i++) {
      iv[i] = random.nextInt(256);
    }
    return iv;
  }

  /// TOFU 校验：首次存储指纹，后续比对
  Future<void> _verifyFingerprint(String fingerprint) async {
    final prefs = await SharedPreferences.getInstance();
    final stored = prefs.getString(_keyFingerprintPrefsKey);

    if (stored == null) {
      // 首次连接，存储指纹
      await prefs.setString(_keyFingerprintPrefsKey, fingerprint);
      return;
    }

    if (stored != fingerprint) {
      throw SecurityException(
        '服务器密钥指纹已变更！可能存在中间人攻击。\n'
        '已存储: $stored\n'
        '当前: $fingerprint',
      );
    }
  }

  /// 重置已存储的指纹（用户确认信任新密钥时调用）
  Future<void> resetFingerprint() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_keyFingerprintPrefsKey);
  }

  /// 从 PEM 格式解析 RSA 公钥
  RSAPublicKey _parseRsaPublicKeyFromPem(String pem) {
    final lines = pem.split('\n');
    final base64Str = lines
        .where((line) =>
            !line.startsWith('-----') && line.trim().isNotEmpty)
        .join();

    final keyBytes = base64Decode(base64Str);
    final asn1Parser = asn1.ASN1Parser(keyBytes);
    final topLevel = asn1Parser.nextObject() as asn1.ASN1Sequence;

    final algorithmSeq = topLevel.elements![0] as asn1.ASN1Sequence;
    final algorithmOid =
        (algorithmSeq.elements![0] as asn1.ASN1ObjectIdentifier).identifier;
    if (algorithmOid != '1.2.840.113549.1.1.1') {
      throw FormatException('Not an RSA public key');
    }

    final bitString = topLevel.elements![1] as asn1.ASN1BitString;
    final innerParser = asn1.ASN1Parser(bitString.contentBytes());
    final rsaSeq = innerParser.nextObject() as asn1.ASN1Sequence;

    final modulus = (rsaSeq.elements![0] as asn1.ASN1Integer).valueAsBigInteger;
    final exponent =
        (rsaSeq.elements![1] as asn1.ASN1Integer).valueAsBigInteger;

    return RSAPublicKey(modulus, exponent);
  }

}

class SecurityException implements Exception {
  final String message;
  SecurityException(this.message);

  @override
  String toString() => message;
}
