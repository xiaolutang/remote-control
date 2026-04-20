import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math';

import 'package:asn1lib/asn1lib.dart' as asn1;
import 'package:flutter/foundation.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:pointycastle/export.dart';

class _HttpProbeResult {
  const _HttpProbeResult({
    required this.statusCode,
    required this.body,
  });

  final int statusCode;
  final String body;

  Map<String, dynamic> decodeJson(String label) {
    try {
      final decoded = jsonDecode(body);
      if (decoded is Map<String, dynamic>) {
        return decoded;
      }
      throw const FormatException('response is not a JSON object');
    } catch (error) {
      throw TestFailure(
        'E2E $label returned invalid JSON: $error, body=${_compact(body)}',
      );
    }
  }
}

class _WsProbeResult {
  const _WsProbeResult({
    required this.frame,
    required this.message,
  });

  final String frame;
  final Map<String, dynamic> message;
}

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  const bool runInHarness = bool.fromEnvironment(
    'RUN_PRODUCTION_NETWORK_PROBE_INTEGRATION',
    defaultValue: false,
  );

  group('Production network e2e', () {
    const host = 'rc.xiaolutang.top';

    final serverIp = (_readConfig(
      key: 'RC_TEST_SERVER_IP',
      fallback: '',
    )).trim();
    final username = (_readConfig(
      key: 'RC_TEST_USERNAME',
      fallback: 'prod_test',
    )).trim();
    final password = (_readConfig(
      key: 'RC_TEST_PASSWORD',
      fallback: 'test123456',
    )).trim();

    // Opt-in only: this harness hits a Flutter integration_test TLS socket
    // teardown issue after the probe already succeeds on macOS/iOS/Android.
    testWidgets(
      'validates deterministic ip+host health, login, and websocket auth',
      (_) async {
        expect(
          serverIp,
          isNotEmpty,
          reason: 'RC_TEST_SERVER_IP is required for production e2e. '
              'This test only gates the deterministic IP + Host path.',
        );

        final ipBase = 'https://$serverIp/rc';
        final ipWsBase = 'wss://$serverIp/rc';

        final dns = await InternetAddress.lookup(host);
        debugPrint(
          'E2E dns $host -> ${dns.map((entry) => entry.address).join(",")}',
        );

        final health = await _getHttp(
          label: 'ip-host-health',
          uri: Uri.parse('$ipBase/health').replace(
            queryParameters: {'probe': 'ip-health-e2e'},
          ),
          headers: const {HttpHeaders.hostHeader: host},
        );
        debugPrint(
          'E2E ip-host-health status=${health.statusCode} body=${_compact(health.body)}',
        );
        expect(
          health.statusCode,
          200,
          reason: 'IP + Host health check must succeed for e2e gating.',
        );

        final login = await _postJsonHttp(
          label: 'ip-host-login',
          uri: Uri.parse('$ipBase/api/login').replace(
            queryParameters: {'probe': 'ip-login-e2e'},
          ),
          headers: const {HttpHeaders.hostHeader: host},
          body: <String, dynamic>{
            'username': username,
            'password': password,
            'view': 'mobile',
          },
        );
        debugPrint(
          'E2E ip-host-login status=${login.statusCode} body=${_compact(login.body)}',
        );
        expect(
          login.statusCode,
          200,
          reason: 'IP + Host login must succeed for e2e gating.',
        );

        final loginData = login.decodeJson('ip-host-login');
        expect(loginData['success'], true);

        final sessionId = loginData['session_id']?.toString();
        final token = loginData['token']?.toString();
        expect(sessionId, isNotEmpty, reason: 'login must return session_id');
        expect(token, isNotEmpty, reason: 'login must return token');

        final encryptedAesKey = await _fetchEncryptedAesKey(
          uri: Uri.parse('$ipBase/api/public-key').replace(
            queryParameters: {'probe': 'ip-public-key-e2e'},
          ),
          hostHeader: host,
        );

        final wsResult = await _authenticateWebSocket(
          label: 'ip-host-ws-auth',
          uri: Uri.parse('$ipWsBase/ws/client').replace(
            queryParameters: <String, String>{
              'session_id': sessionId!,
              'view': 'mobile',
              'probe': 'ip-ws-e2e',
            },
          ),
          token: token!,
          hostHeader: host,
          encryptedAesKey: encryptedAesKey,
        );
        debugPrint(
          'E2E ip-host-ws-auth first=${_compact(wsResult.frame)}',
        );

        expect(wsResult.message['type'], 'connected');
        expect(wsResult.message['session_id'], sessionId);
        expect(wsResult.message['view'], 'mobile');
        expect(wsResult.message['device_id'], isNotNull);
      },
      skip: !runInHarness,
    );
  });
}

String _readConfig({
  required String key,
  required String fallback,
}) {
  switch (key) {
    case 'RC_TEST_SERVER_IP':
      return const String.fromEnvironment(
        'RC_TEST_SERVER_IP',
        defaultValue: '',
      ).trim().isNotEmpty
          ? const String.fromEnvironment('RC_TEST_SERVER_IP')
          : (Platform.environment[key] ?? fallback);
    case 'RC_TEST_USERNAME':
      return const String.fromEnvironment(
        'RC_TEST_USERNAME',
        defaultValue: '',
      ).trim().isNotEmpty
          ? const String.fromEnvironment('RC_TEST_USERNAME')
          : (Platform.environment[key] ?? fallback);
    case 'RC_TEST_PASSWORD':
      return const String.fromEnvironment(
        'RC_TEST_PASSWORD',
        defaultValue: '',
      ).trim().isNotEmpty
          ? const String.fromEnvironment('RC_TEST_PASSWORD')
          : (Platform.environment[key] ?? fallback);
    default:
      return Platform.environment[key] ?? fallback;
  }
}

Future<_HttpProbeResult> _getHttp({
  required String label,
  required Uri uri,
  Map<String, String>? headers,
}) async {
  return _sendRawRequest(
    label: label,
    method: 'GET',
    uri: uri,
    headers: headers,
  );
}

Future<_HttpProbeResult> _postJsonHttp({
  required String label,
  required Uri uri,
  required Map<String, dynamic> body,
  Map<String, String>? headers,
}) async {
  return _sendRawRequest(
    label: label,
    method: 'POST',
    uri: uri,
    headers: <String, String>{
      HttpHeaders.contentTypeHeader: 'application/json',
      ...?headers,
    },
    body: jsonEncode(body),
  );
}

Future<_HttpProbeResult> _getHttpRaw({
  required String label,
  required Uri uri,
  String? hostHeader,
}) async {
  return _sendRawRequest(
    label: label,
    method: 'GET',
    uri: uri,
    headers: hostHeader == null ? null : {HttpHeaders.hostHeader: hostHeader},
  );
}

Future<_HttpProbeResult> _sendRawRequest({
  required String label,
  required String method,
  required Uri uri,
  Map<String, String>? headers,
  String? body,
}) async {
  final client = HttpClient()..connectionTimeout = const Duration(seconds: 10);
  client.badCertificateCallback = (_, __, ___) => true;
  client.findProxy = (_) => 'DIRECT';

  try {
    final request = switch (method) {
      'GET' => await client.getUrl(uri),
      'POST' => await client.postUrl(uri),
      _ => throw UnsupportedError('Unsupported method: $method'),
    };
    request.persistentConnection = false;
    for (final entry
        in headers?.entries ?? const <MapEntry<String, String>>[]) {
      request.headers.set(entry.key, entry.value);
    }
    if (body != null) {
      request.write(body);
    }
    final response = await request.close();
    final responseBody =
        await response.transform(SystemEncoding().decoder).join();
    return _HttpProbeResult(
      statusCode: response.statusCode,
      body: responseBody,
    );
  } catch (error) {
    throw TestFailure('E2E $label request failed: $error');
  }
}

Future<_WsProbeResult> _authenticateWebSocket({
  required String label,
  required Uri uri,
  required String token,
  String? hostHeader,
  String? encryptedAesKey,
}) async {
  final client = HttpClient()..connectionTimeout = const Duration(seconds: 10);
  client.badCertificateCallback = (_, __, ___) => true;
  client.findProxy = (_) => 'DIRECT';
  final authUri = uri.replace(
    queryParameters: <String, String>{
      ...uri.queryParameters,
      'token': token,
    },
  );

  try {
    final socket = await WebSocket.connect(
      authUri.toString(),
      headers: hostHeader == null
          ? null
          : <String, dynamic>{HttpHeaders.hostHeader: hostHeader},
      customClient: client,
    ).timeout(const Duration(seconds: 10));

    final firstFrame = Completer<String?>();
    final streamClosed = Completer<void>();
    late final StreamSubscription<dynamic> subscription;
    subscription = socket.listen(
      (dynamic event) {
        if (firstFrame.isCompleted) {
          return;
        }
        if (event is String) {
          firstFrame.complete(event);
          return;
        }
        firstFrame.completeError(
          TestFailure(
            'E2E $label expected first websocket frame to be String, got ${event.runtimeType}',
          ),
        );
      },
      onError: (Object error, StackTrace stackTrace) {
        if (!firstFrame.isCompleted) {
          firstFrame.completeError(
            TestFailure('E2E $label websocket stream failed: $error'),
          );
        }
        if (!streamClosed.isCompleted) {
          streamClosed.complete();
        }
      },
      onDone: () {
        if (!firstFrame.isCompleted) {
          firstFrame.complete(null);
        }
        if (!streamClosed.isCompleted) {
          streamClosed.complete();
        }
      },
      cancelOnError: false,
    );

    await Future<void>.delayed(const Duration(seconds: 1));
    if (!firstFrame.isCompleted) {
      socket.add(jsonEncode(<String, dynamic>{
        'type': 'auth',
        'token': token,
        if (encryptedAesKey != null) 'encrypted_aes_key': encryptedAesKey,
      }));
    }

    final first = await firstFrame.future.timeout(
      const Duration(seconds: 10),
      onTimeout: () => null,
    );

    await socket.close();
    await streamClosed.future.timeout(
      const Duration(seconds: 5),
      onTimeout: () {},
    );
    await subscription.cancel();

    if (first == null) {
      throw TestFailure(
        'E2E $label received no websocket frame. '
        'closeCode=${socket.closeCode} closeReason=${socket.closeReason}',
      );
    }

    try {
      final decoded = jsonDecode(first);
      if (decoded is! Map<String, dynamic>) {
        throw const FormatException('websocket frame is not a JSON object');
      }
      return _WsProbeResult(frame: first, message: decoded);
    } catch (error) {
      throw TestFailure(
        'E2E $label returned invalid websocket JSON: $error, frame=${_compact(first)}',
      );
    }
  } catch (error) {
    throw TestFailure('E2E $label request failed: $error');
  }
}

Future<String> _fetchEncryptedAesKey({
  required Uri uri,
  required String hostHeader,
}) async {
  final response = await _getHttpRaw(
    label: 'ip-public-key',
    uri: uri,
    hostHeader: hostHeader,
  );
  if (response.statusCode != 200) {
    throw TestFailure(
      'E2E ip-public-key failed: status=${response.statusCode} body=${_compact(response.body)}',
    );
  }
  final data = response.decodeJson('ip-public-key');
  final pem = data['public_key_pem']?.toString();
  if (pem == null || pem.isEmpty) {
    throw TestFailure(
      'E2E ip-public-key missing public_key_pem, body=${_compact(response.body)}',
    );
  }
  return _encryptAesKeyBase64(pem);
}

String _encryptAesKeyBase64(String pem) {
  final publicKey = _parseRsaPublicKeyFromPem(pem);
  final secureRandom = FortunaRandom();
  final seed = Uint8List.fromList(
    List<int>.generate(32, (_) => Random.secure().nextInt(256)),
  );
  secureRandom.seed(KeyParameter(seed));

  final aesKey = Uint8List(32);
  for (var index = 0; index < aesKey.length; index++) {
    aesKey[index] = secureRandom.nextUint8();
  }

  final cipher = OAEPEncoding.withSHA256(RSAEngine())
    ..init(
      true,
      PublicKeyParameter<RSAPublicKey>(publicKey),
    );
  return base64Encode(cipher.process(aesKey));
}

RSAPublicKey _parseRsaPublicKeyFromPem(String pem) {
  final lines = pem.split('\n');
  final base64Str = lines
      .where((line) => !line.startsWith('-----') && line.trim().isNotEmpty)
      .join();

  final keyBytes = base64Decode(base64Str);
  final topLevel = asn1.ASN1Parser(keyBytes).nextObject() as asn1.ASN1Sequence;
  final algorithmSeq = topLevel.elements[0] as asn1.ASN1Sequence;
  final algorithmOid =
      (algorithmSeq.elements[0] as asn1.ASN1ObjectIdentifier).identifier;
  if (algorithmOid != '1.2.840.113549.1.1.1') {
    throw TestFailure('E2E public key is not RSA: $algorithmOid');
  }

  final bitString = topLevel.elements[1] as asn1.ASN1BitString;
  final rsaSeq = asn1.ASN1Parser(bitString.contentBytes()).nextObject()
      as asn1.ASN1Sequence;
  final modulus = (rsaSeq.elements[0] as asn1.ASN1Integer).valueAsBigInteger;
  final exponent = (rsaSeq.elements[1] as asn1.ASN1Integer).valueAsBigInteger;
  return RSAPublicKey(modulus, exponent);
}

String _compact(String text) {
  final normalized = text.replaceAll('\n', ' ');
  if (normalized.length <= 160) {
    return normalized;
  }
  return '${normalized.substring(0, 160)}...';
}
