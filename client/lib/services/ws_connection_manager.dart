part of 'websocket_service.dart';

Future<bool> _wsConnect(WebSocketService s) async {
  if (s._status == ConnectionStatus.connected ||
      s._status == ConnectionStatus.connecting) {
    return true;
  }

  await s._streamSubscription?.cancel();
  s._streamSubscription = null;
  await s._channel?.sink.close();
  s._channel = null;
  s._wsHttpClient?.close();
  s._wsHttpClient = null;

  s._status = ConnectionStatus.connecting;
  s._allowReconnect = true;
  s._errorMessage = null;
  s._resetTerminalDecoders();
  s._notify();

  s._logger?.info('WebSocket connecting', metadata: {
    'server_url': s.serverUrl,
    'session_id': s.sessionId,
    'view_type': s._viewTypeString,
  });

  try {
    if (s._requiresApplicationLayerEncryption && !s._hasPublicKey) {
      try {
        await s._ensurePublicKeyLoaded();
      } catch (_) {
        s._status = ConnectionStatus.error;
        s._errorMessage = '安全连接建立失败';
        s._notify();
        return false;
      }
    }

    final queryParameters = <String, String>{'view': s._viewTypeString};
    if (s.sessionId.isNotEmpty) {
      queryParameters['session_id'] = s.sessionId;
    }
    if ((s.deviceId ?? '').isNotEmpty) {
      queryParameters['device_id'] = s.deviceId!;
    }
    if ((s.terminalId ?? '').isNotEmpty) {
      queryParameters['terminal_id'] = s.terminalId!;
    }
    final wsUri = Uri.parse('${s.serverUrl}/ws/client').replace(
      queryParameters: queryParameters,
    );
    s._wsHttpClient = HttpClientFactory.createRaw();
    s._channel = IOWebSocketChannel.connect(
      wsUri.toString(),
      customClient: s._wsHttpClient,
    );

    final authMessage = <String, dynamic>{
      'type': 'auth',
      'token': s.token,
    };
    var aesKeyExchanged = false;
    if (s._requiresApplicationLayerEncryption) {
      try {
        s._crypto.generateAesKey();
        authMessage['encrypted_aes_key'] = s._crypto.getEncryptedAesKeyBase64();
        aesKeyExchanged = true;
      } catch (e) {
        debugPrint('[WebSocketService] AES key exchange failed: $e');
        s._crypto.clearAesKey();
      }
    }
    if (s._requiresApplicationLayerEncryption && !aesKeyExchanged) {
      s._status = ConnectionStatus.error;
      s._errorMessage = '安全连接建立失败';
      s._notify();
      await s._channel?.sink.close();
      return false;
    }
    s._channel!.sink.add(jsonEncode(authMessage));

    final completer = Completer<bool>();
    var isFirstMessage = true;
    s._streamSubscription = s._channel!.stream.listen(
      (message) {
        if (isFirstMessage) {
          isFirstMessage = false;
          _wsHandleInitialMessage(
            s,
            message: message!,
            aesKeyExchanged: aesKeyExchanged,
            completer: completer,
          );
        } else {
          s._handleMessage(message!);
        }
      },
      onError: (error) {
        s._status = ConnectionStatus.error;
        s._errorMessage = error.toString();
        s._notify();
        s._logger?.error('WebSocket error', metadata: {
          'error': error.toString(),
          'retry_count': s._retryCount,
        });
        _wsHandleDisconnect(s);
        if (!completer.isCompleted) {
          completer.completeError(error);
        }
      },
      onDone: () {
        _wsCaptureCloseCode(s);
        _wsHandleDisconnect(s);
        if (!completer.isCompleted) {
          completer.completeError(Exception('Connection closed'));
        }
      },
    );

    return await completer.future.timeout(
      const Duration(seconds: 30),
      onTimeout: () => throw TimeoutException('Connection timeout'),
    );
  } catch (e) {
    s._status = ConnectionStatus.error;
    s._errorMessage = e.toString();
    s._notify();
    s._logger?.error('WebSocket connection failed', metadata: {
      'error': e.toString(),
      'server_url': s.serverUrl,
    });
    if (s.autoReconnect && s._allowReconnect && s._retryCount < s.maxRetries) {
      _wsScheduleReconnect(s);
    }
    return false;
  }
}

void _wsHandleInitialMessage(
  WebSocketService s, {
  required String message,
  required bool aesKeyExchanged,
  required Completer<bool> completer,
}) {
  try {
    final data = jsonDecode(message) as Map<String, dynamic>;
    if (data['type'] == 'connected') {
      s._encryptionEnabled = aesKeyExchanged;
      s._applyConnectedMessage(data);
      _wsStartHeartbeat(s);
      s._logger?.info('WebSocket connected', metadata: {
        'session_id': s.sessionId,
        'agent_online': s._agentOnline,
        'owner': s._owner,
        'view': s._viewTypeString,
      });
      completer.complete(true);
    } else {
      completer.completeError(
        Exception('Unexpected message type: ${data['type']}'),
      );
    }
  } catch (e) {
    completer.completeError(e);
  }
}

Future<void> _wsSend(WebSocketService s, String data) async {
  if (s._status != ConnectionStatus.connected || s._channel == null) {
    return;
  }
  // Bracketed Paste Mode: 多行内容（如 AI prompt 注入）用 BPM 转义序列包裹，
  // 防止终端将换行解释为多次输入导致截断。
  final content = data.contains('\n')
      ? '\x1b[200~$data\x1b[201~'
      : data;
  final raw = {
    'type': 'data',
    'payload': base64Encode(utf8.encode(content)),
    'timestamp': DateTime.now().toUtc().toIso8601String(),
  };
  final message = s._encryptionEnabled && s._crypto.shouldEncrypt('data')
      ? jsonEncode(s._crypto.encryptMessage(raw))
      : jsonEncode(raw);
  s._channel!.sink.add(message);
  if (s._channel is IOWebSocketChannel) {
    await (s._channel as IOWebSocketChannel).ready;
  }
}

void _wsResize(WebSocketService s, int rows, int cols) {
  if (s._status != ConnectionStatus.connected || s._channel == null) {
    return;
  }
  final raw = {'type': 'resize', 'rows': rows, 'cols': cols};
  final message = s._encryptionEnabled && s._crypto.shouldEncrypt('resize')
      ? jsonEncode(s._crypto.encryptMessage(raw))
      : jsonEncode(raw);
  s._channel!.sink.add(message);
}

Future<void> _wsDisconnect(WebSocketService s, {bool notify = true}) async {
  s._allowReconnect = false;
  s._encryptionEnabled = false;
  s._crypto.clearAesKey();
  s._resetTerminalDecoders();
  _wsStopHeartbeat(s);
  s._reconnectTimer?.cancel();
  await s._streamSubscription?.cancel();
  s._streamSubscription = null;

  if (s._channel != null) {
    await s._channel!.sink.close();
    s._channel = null;
  }
  s._wsHttpClient?.close();
  s._wsHttpClient = null;
  s._status = ConnectionStatus.disconnected;
  if (notify) {
    s._notify();
  }
}

void _wsDispose(WebSocketService s) {
  s.disconnect(notify: false);
  s._outputController.close();
  s._outputFrameController.close();
  s._eventController.close();
  s._terminalConnectedController.close();
  s._ptySizeController.close();
  s._presenceController.close();
  s._terminalsChangedController.close();
  s._deviceKickedController.close();
  s._tokenInvalidController.close();
}

void _wsHandleDisconnect(WebSocketService s) {
  _wsResetTerminalDecoders(s);
  _wsStopHeartbeat(s);

  if (s._lastCloseCode == 4001) {
    s._errorMessage = '登录已失效';
    s._allowReconnect = false;
    s._tokenInvalidController.add(null);
  } else if (s._lastCloseCode == 4011) {
    s._allowReconnect = false;
  }

  if (s._status == ConnectionStatus.connected) {
    s._status = ConnectionStatus.disconnected;
    s._notify();
    s._logger?.warn('WebSocket disconnected', metadata: {
      'session_id': s.sessionId,
      'auto_reconnect': s.autoReconnect,
      'close_code': s._lastCloseCode,
    });
  } else if (s._status != ConnectionStatus.disconnected) {
    s._status = ConnectionStatus.disconnected;
    s._notify();
  }

  if (s.autoReconnect && s._allowReconnect && s._retryCount < s.maxRetries) {
    _wsScheduleReconnect(s);
  }
}

void _wsCaptureCloseCode(WebSocketService s) {
  try {
    final closeCode = s._channel?.closeCode;
    final closeReason = s._channel?.closeReason;
    if (closeCode != null) {
      s._lastCloseCode = closeCode;
      s._lastCloseReason = closeReason;
      debugPrint(
        '[WebSocketService] WS closed: code=$closeCode reason=$closeReason',
      );
    }
  } catch (e) {
    debugPrint('[WebSocketService] error capturing close code: $e');
  }
}

void _wsStartHeartbeat(WebSocketService s) {
  _wsStopHeartbeat(s);
  s._heartbeatTimer = Timer.periodic(const Duration(seconds: 30), (_) {
    if (s._status == ConnectionStatus.connected && s._channel != null) {
      s._channel!.sink.add(jsonEncode({'type': 'ping'}));
    }
  });
}

void _wsStopHeartbeat(WebSocketService s) {
  s._heartbeatTimer?.cancel();
  s._heartbeatTimer = null;
}

void _wsScheduleReconnect(WebSocketService s) {
  s._status = ConnectionStatus.reconnecting;
  s._notify();

  final delay = s.reconnectDelay * (1 << s._retryCount).clamp(0, 6);
  s._retryCount++;
  s._reconnectTimer?.cancel();
  s._reconnectTimer = Timer(delay, () {
    s.connect();
  });
}
