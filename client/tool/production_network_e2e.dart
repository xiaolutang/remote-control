import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math';
import 'dart:typed_data';

import 'package:asn1lib/asn1lib.dart' as asn1;
import 'package:pointycastle/export.dart';

class ProbeConfig {
  const ProbeConfig({
    required this.serverIp,
    required this.host,
    required this.username,
    required this.password,
  });

  final String serverIp;
  final String host;
  final String username;
  final String password;
}

class ProbeResult {
  const ProbeResult({
    required this.healthStatusCode,
    required this.loginStatusCode,
    required this.connectedMessage,
  });

  final int healthStatusCode;
  final int loginStatusCode;
  final Map<String, dynamic> connectedMessage;
}

class _HttpProbeResult {
  const _HttpProbeResult({
    required this.statusCode,
    required this.body,
  });

  final int statusCode;
  final String body;

  Map<String, dynamic> decodeJson(String label) {
    final decoded = jsonDecode(body);
    if (decoded is Map<String, dynamic>) {
      return decoded;
    }
    throw FormatException('$label response is not a JSON object');
  }
}

Future<void> main(List<String> args) async {
  try {
    final config = _parseConfig(args);
    final result = await _runProbe(config);

    stdout.writeln('production-network-e2e: PASS');
    stdout.writeln('  host: ${config.host}');
    stdout.writeln('  server_ip: ${config.serverIp}');
    stdout.writeln('  health_status: ${result.healthStatusCode}');
    stdout.writeln('  login_status: ${result.loginStatusCode}');
    stdout.writeln(
      '  connected_type: ${result.connectedMessage['type']}'
      ' session_id=${result.connectedMessage['session_id']}'
      ' device_id=${result.connectedMessage['device_id']}',
    );
    exitCode = 0;
  } catch (error, stackTrace) {
    stderr.writeln('production-network-e2e: FAIL');
    stderr.writeln('  error: $error');
    stderr.writeln(stackTrace);
    exitCode = 1;
  }
}

ProbeConfig _parseConfig(List<String> args) {
  String? argValue(String name) {
    for (var index = 0; index < args.length; index++) {
      if (args[index] == name) {
        if (index + 1 >= args.length) {
          throw ArgumentError('Missing value for $name');
        }
        return args[index + 1];
      }
    }
    return null;
  }

  if (args.contains('--help') || args.contains('-h')) {
    stdout.writeln('Usage: dart run tool/production_network_e2e.dart '
        '--server-ip YOUR_SERVER_IP '
        '[--host rc.xiaolutang.top] '
        '[--username prod_test] '
        '[--password test123456]');
    exit(0);
  }

  final serverIp = (argValue('--server-ip') ??
          Platform.environment['RC_TEST_SERVER_IP'] ??
          '')
      .trim();
  if (serverIp.isEmpty) {
    throw ArgumentError(
      'server ip is required. Use --server-ip or RC_TEST_SERVER_IP.',
    );
  }

  final host = (argValue('--host') ??
          Platform.environment['RC_TEST_HOST'] ??
          'rc.xiaolutang.top')
      .trim();
  final username = (argValue('--username') ??
          Platform.environment['RC_TEST_USERNAME'] ??
          'prod_test')
      .trim();
  final password = (argValue('--password') ??
          Platform.environment['RC_TEST_PASSWORD'] ??
          'test123456')
      .trim();

  return ProbeConfig(
    serverIp: serverIp,
    host: host,
    username: username,
    password: password,
  );
}

Future<ProbeResult> _runProbe(ProbeConfig config) async {
  final ipBase = 'https://${config.serverIp}/rc';
  final ipWsBase = 'wss://${config.serverIp}/rc';

  final dns = await InternetAddress.lookup(config.host);
  stdout.writeln(
    'dns ${config.host} -> ${dns.map((entry) => entry.address).join(",")}',
  );

  final health = await _getHttp(
    label: 'ip-host-health',
    uri: Uri.parse('$ipBase/health').replace(
      queryParameters: const {'probe': 'ip-health-e2e'},
    ),
    headers: {HttpHeaders.hostHeader: config.host},
  );
  stdout.writeln(
    'health status=${health.statusCode} body=${_compact(health.body)}',
  );
  if (health.statusCode != 200) {
    throw StateError('health failed: status=${health.statusCode}');
  }

  final login = await _postJsonHttp(
    label: 'ip-host-login',
    uri: Uri.parse('$ipBase/api/login').replace(
      queryParameters: const {'probe': 'ip-login-e2e'},
    ),
    headers: {HttpHeaders.hostHeader: config.host},
    body: <String, dynamic>{
      'username': config.username,
      'password': config.password,
      'view': 'mobile',
    },
  );
  stdout.writeln(
    'login status=${login.statusCode} body=${_compact(login.body)}',
  );
  if (login.statusCode != 200) {
    throw StateError('login failed: status=${login.statusCode}');
  }

  final loginData = login.decodeJson('login');
  if (loginData['success'] != true) {
    throw StateError('login success flag is not true: ${login.body}');
  }

  final sessionId = loginData['session_id']?.toString();
  final token = loginData['token']?.toString();
  if (sessionId == null || sessionId.isEmpty) {
    throw StateError('login returned empty session_id');
  }
  if (token == null || token.isEmpty) {
    throw StateError('login returned empty token');
  }

  final encryptedAesKey = await _fetchEncryptedAesKey(
    uri: Uri.parse('$ipBase/api/public-key').replace(
      queryParameters: const {'probe': 'ip-public-key-e2e'},
    ),
    hostHeader: config.host,
  );

  final wsResult = await _authenticateWebSocket(
    label: 'ip-host-ws-auth',
    uri: Uri.parse('$ipWsBase/ws/client').replace(
      queryParameters: <String, String>{
        'session_id': sessionId,
        'view': 'mobile',
        'probe': 'ip-ws-e2e',
      },
    ),
    token: token,
    hostHeader: config.host,
    encryptedAesKey: encryptedAesKey,
  );
  stdout.writeln('ws first=${_compact(wsResult.frame)}');

  if (wsResult.message['type'] != 'connected') {
    throw StateError('unexpected ws message type: ${wsResult.message}');
  }
  if (wsResult.message['session_id'] != sessionId) {
    throw StateError('ws session_id mismatch: ${wsResult.message}');
  }
  if (wsResult.message['view'] != 'mobile') {
    throw StateError('ws view mismatch: ${wsResult.message}');
  }
  if (wsResult.message['device_id'] == null) {
    throw StateError('ws device_id missing: ${wsResult.message}');
  }

  return ProbeResult(
    healthStatusCode: health.statusCode,
    loginStatusCode: login.statusCode,
    connectedMessage: wsResult.message,
  );
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
    throw StateError('$label request failed: $error');
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
          StateError(
            '$label expected first websocket frame to be String, '
            'got ${event.runtimeType}',
          ),
        );
      },
      onError: (Object error, StackTrace stackTrace) {
        if (!firstFrame.isCompleted) {
          firstFrame.completeError(
            StateError('$label websocket stream failed: $error'),
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
      throw StateError(
        '$label received no websocket frame. '
        'closeCode=${socket.closeCode} closeReason=${socket.closeReason}',
      );
    }

    final decoded = jsonDecode(first);
    if (decoded is! Map<String, dynamic>) {
      throw FormatException('$label websocket frame is not a JSON object');
    }
    return _WsProbeResult(frame: first, message: decoded);
  } catch (error) {
    throw StateError('$label request failed: $error');
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
    throw StateError(
      'ip-public-key failed: status=${response.statusCode} '
      'body=${_compact(response.body)}',
    );
  }
  final data = response.decodeJson('ip-public-key');
  final pem = data['public_key_pem']?.toString();
  if (pem == null || pem.isEmpty) {
    throw StateError(
      'ip-public-key missing public_key_pem, body=${_compact(response.body)}',
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
    throw StateError('public key is not RSA: $algorithmOid');
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
