import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math';
import 'dart:typed_data';

import 'package:asn1lib/asn1lib.dart' as asn1;
import 'package:pointycastle/export.dart';

class ProductionProbeConfig {
  const ProductionProbeConfig({
    required this.serverIp,
    required this.host,
    required this.username,
    required this.password,
    this.probeRuntimeTerminal = false,
    this.requireOnlineDevice = false,
    this.runtimeDeviceId,
  });

  final String serverIp;
  final String host;
  final String username;
  final String password;
  final bool probeRuntimeTerminal;
  final bool requireOnlineDevice;
  final String? runtimeDeviceId;
}

class ProductionProbeResult {
  const ProductionProbeResult({
    required this.healthStatusCode,
    required this.loginStatusCode,
    required this.connectedMessage,
    this.runtimeTerminalResult,
  });

  final int healthStatusCode;
  final int loginStatusCode;
  final Map<String, dynamic> connectedMessage;
  final RuntimeTerminalProbeResult? runtimeTerminalResult;
}

class RuntimeTerminalProbeResult {
  const RuntimeTerminalProbeResult({
    required this.executed,
    required this.skipped,
    this.skipReason,
    this.deviceId,
    this.deviceName,
    this.candidateCwd,
    this.createdTerminalId,
    this.createdStatus,
    this.closedStatus,
  });

  final bool executed;
  final bool skipped;
  final String? skipReason;
  final String? deviceId;
  final String? deviceName;
  final String? candidateCwd;
  final String? createdTerminalId;
  final String? createdStatus;
  final String? closedStatus;
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

class _WsProbeResult {
  const _WsProbeResult({
    required this.frame,
    required this.message,
  });

  final String frame;
  final Map<String, dynamic> message;
}

Future<ProductionProbeResult> runProductionProbe(
  ProductionProbeConfig config, {
  void Function(String line)? log,
}) async {
  final logger = log ?? (_) {};
  final ipBase = 'https://${config.serverIp}/rc';
  final ipWsBase = 'wss://${config.serverIp}/rc';

  final dns = await InternetAddress.lookup(config.host);
  logger(
    'dns ${config.host} -> ${dns.map((entry) => entry.address).join(",")}',
  );

  final health = await _getHttp(
    label: 'ip-host-health',
    uri: Uri.parse('$ipBase/health').replace(
      queryParameters: const {'probe': 'ip-health-e2e'},
    ),
    headers: {HttpHeaders.hostHeader: config.host},
  );
  logger('health status=${health.statusCode} body=${compactText(health.body)}');
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
  logger('login status=${login.statusCode} body=${compactText(login.body)}');
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
  logger('ws first=${compactText(wsResult.frame)}');

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

  RuntimeTerminalProbeResult? runtimeTerminalResult;
  if (config.probeRuntimeTerminal) {
    runtimeTerminalResult = await _runRuntimeTerminalProbe(
      config: config,
      token: token,
      log: logger,
    );
  }

  return ProductionProbeResult(
    healthStatusCode: health.statusCode,
    loginStatusCode: login.statusCode,
    connectedMessage: wsResult.message,
    runtimeTerminalResult: runtimeTerminalResult,
  );
}

Future<RuntimeTerminalProbeResult> _runRuntimeTerminalProbe({
  required ProductionProbeConfig config,
  required String token,
  required void Function(String line) log,
}) async {
  final ipBase = 'https://${config.serverIp}/rc';
  final authHeaders = <String, String>{
    HttpHeaders.hostHeader: config.host,
    HttpHeaders.authorizationHeader: 'Bearer $token',
    HttpHeaders.contentTypeHeader: 'application/json',
  };

  final devicesResponse = await _getHttp(
    label: 'runtime-devices',
    uri: Uri.parse('$ipBase/api/runtime/devices').replace(
      queryParameters: const {'probe': 'runtime-devices-e2e'},
    ),
    headers: authHeaders,
  );
  log(
    'runtime devices status=${devicesResponse.statusCode} body=${compactText(devicesResponse.body)}',
  );
  if (devicesResponse.statusCode != 200) {
    throw StateError(
      'runtime devices failed: status=${devicesResponse.statusCode}',
    );
  }
  final devicesData = devicesResponse.decodeJson('runtime-devices');
  final devices = (devicesData['devices'] as List<dynamic>? ?? const [])
      .whereType<Map<String, dynamic>>()
      .toList(growable: false);

  Map<String, dynamic>? selectedDevice;
  if (config.runtimeDeviceId != null && config.runtimeDeviceId!.isNotEmpty) {
    for (final device in devices) {
      if (device['device_id']?.toString() == config.runtimeDeviceId) {
        selectedDevice = device;
        break;
      }
    }
    if (selectedDevice == null) {
      throw StateError(
        'runtime device ${config.runtimeDeviceId} not found in devices list',
      );
    }
  } else {
    for (final device in devices) {
      final agentOnline = device['agent_online'] == true;
      final activeTerminals =
          (device['active_terminals'] as num?)?.toInt() ?? 0;
      final maxTerminals = (device['max_terminals'] as num?)?.toInt() ?? 0;
      if (agentOnline && activeTerminals < maxTerminals) {
        selectedDevice = device;
        break;
      }
    }
  }

  if (selectedDevice == null) {
    final reason = 'no online device available for terminal creation';
    if (config.requireOnlineDevice) {
      throw StateError(reason);
    }
    log('runtime terminal probe skipped: $reason');
    return const RuntimeTerminalProbeResult(
      executed: false,
      skipped: true,
      skipReason: 'no online device available for terminal creation',
    );
  }

  final deviceId = selectedDevice['device_id']?.toString() ?? '';
  final deviceName = selectedDevice['name']?.toString() ?? '';
  final contextResponse = await _getHttp(
    label: 'runtime-project-context',
    uri: Uri.parse('$ipBase/api/runtime/devices/$deviceId/project-context')
        .replace(
            queryParameters: const {'probe': 'runtime-project-context-e2e'}),
    headers: authHeaders,
  );
  log(
    'runtime project-context status=${contextResponse.statusCode} body=${compactText(contextResponse.body)}',
  );
  if (contextResponse.statusCode != 200) {
    throw StateError(
      'runtime project-context failed: status=${contextResponse.statusCode}',
    );
  }
  final contextData = contextResponse.decodeJson('runtime-project-context');
  final candidates = (contextData['candidates'] as List<dynamic>? ?? const [])
      .whereType<Map<String, dynamic>>()
      .toList(growable: false);
  final candidateCwd = _pickProbeCwd(candidates);
  final terminalId = 'e2e-${DateTime.now().millisecondsSinceEpoch}';
  final title = 'E2E Runtime Probe';
  const command = '/bin/bash';

  final createResponse = await _postJsonHttp(
    label: 'runtime-create-terminal',
    uri: Uri.parse('$ipBase/api/runtime/devices/$deviceId/terminals').replace(
      queryParameters: const {'probe': 'runtime-create-terminal-e2e'},
    ),
    headers: authHeaders,
    body: <String, dynamic>{
      'terminal_id': terminalId,
      'title': title,
      'cwd': candidateCwd,
      'command': command,
      'env': const <String, String>{},
    },
  );
  log(
    'runtime create-terminal status=${createResponse.statusCode} body=${compactText(createResponse.body)}',
  );
  if (createResponse.statusCode != 200) {
    throw StateError(
      'runtime create-terminal failed: status=${createResponse.statusCode}',
    );
  }

  final createData = createResponse.decodeJson('runtime-create-terminal');
  if (createData['terminal_id']?.toString() != terminalId) {
    throw StateError(
      'runtime create-terminal returned unexpected terminal_id: ${createResponse.body}',
    );
  }
  final createdStatus = createData['status']?.toString();

  final terminalsResponse = await _getHttp(
    label: 'runtime-list-terminals',
    uri: Uri.parse('$ipBase/api/runtime/devices/$deviceId/terminals').replace(
      queryParameters: const {'probe': 'runtime-list-terminals-e2e'},
    ),
    headers: authHeaders,
  );
  log(
    'runtime list-terminals status=${terminalsResponse.statusCode} body=${compactText(terminalsResponse.body)}',
  );
  if (terminalsResponse.statusCode != 200) {
    throw StateError(
      'runtime list-terminals failed: status=${terminalsResponse.statusCode}',
    );
  }
  final terminalsData = terminalsResponse.decodeJson('runtime-list-terminals');
  final terminals = (terminalsData['terminals'] as List<dynamic>? ?? const [])
      .whereType<Map<String, dynamic>>()
      .toList(growable: false);
  final exists = terminals.any(
    (terminal) => terminal['terminal_id']?.toString() == terminalId,
  );
  if (!exists) {
    throw StateError('created terminal $terminalId not found in terminal list');
  }

  String? closedStatus;
  try {
    final closeResponse = await _sendRawRequest(
      label: 'runtime-close-terminal',
      method: 'DELETE',
      uri: Uri.parse(
              '$ipBase/api/runtime/devices/$deviceId/terminals/$terminalId')
          .replace(
              queryParameters: const {'probe': 'runtime-close-terminal-e2e'}),
      headers: authHeaders,
    );
    log(
      'runtime close-terminal status=${closeResponse.statusCode} body=${compactText(closeResponse.body)}',
    );
    if (closeResponse.statusCode != 200) {
      throw StateError(
        'runtime close-terminal failed: status=${closeResponse.statusCode}',
      );
    }
    final closeData = closeResponse.decodeJson('runtime-close-terminal');
    closedStatus = closeData['status']?.toString();
  } catch (error) {
    throw StateError('runtime close-terminal cleanup failed: $error');
  }

  return RuntimeTerminalProbeResult(
    executed: true,
    skipped: false,
    deviceId: deviceId,
    deviceName: deviceName,
    candidateCwd: candidateCwd,
    createdTerminalId: terminalId,
    createdStatus: createdStatus,
    closedStatus: closedStatus,
  );
}

String _pickProbeCwd(List<Map<String, dynamic>> candidates) {
  for (final candidate in candidates) {
    final cwd = candidate['cwd']?.toString().trim() ?? '';
    if (cwd.isNotEmpty) {
      return cwd;
    }
  }
  return '~';
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
      'DELETE' => await client.deleteUrl(uri),
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
      'body=${compactText(response.body)}',
    );
  }
  final data = response.decodeJson('ip-public-key');
  final pem = data['public_key_pem']?.toString();
  if (pem == null || pem.isEmpty) {
    throw StateError(
      'ip-public-key missing public_key_pem, body=${compactText(response.body)}',
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

String compactText(String text) {
  final normalized = text.replaceAll('\n', ' ');
  if (normalized.length <= 160) {
    return normalized;
  }
  return '${normalized.substring(0, 160)}...';
}
