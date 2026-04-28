part of 'websocket_service.dart';

// ============================================================
// UTF-8 流式解码辅助类
// ============================================================

class _CollectingStringSink implements StringSink {
  String _value = '';

  @override
  void write(Object? obj) {
    _value += '$obj';
  }

  @override
  void writeAll(Iterable<dynamic> objects, [String separator = '']) {
    _value += objects.join(separator);
  }

  @override
  void writeCharCode(int charCode) {
    _value += String.fromCharCode(charCode);
  }

  @override
  void writeln([Object? obj = '']) {
    _value += '$obj\n';
  }

  String take() {
    final value = _value;
    _value = '';
    return value;
  }
}

class _StreamingUtf8Decoder {
  _StreamingUtf8Decoder() {
    _resetDecoder();
  }

  final _sink = _CollectingStringSink();
  late ByteConversionSink _decoder;

  String decode(List<int> bytes, {bool endOfInput = false}) {
    if (bytes.isNotEmpty) {
      _decoder.add(bytes);
    }
    if (endOfInput) {
      _decoder.close();
      final output = _sink.take();
      _resetDecoder();
      return output;
    }
    return _sink.take();
  }

  void reset() {
    _sink.take();
    _resetDecoder();
  }

  void _resetDecoder() {
    _decoder = const Utf8Decoder(
      allowMalformed: true,
    ).startChunkedConversion(StringConversionSink.fromStringSink(_sink));
  }
}

// ============================================================
// 顶层辅助函数 — 同库可访问 WebSocketService 的私有成员
// ============================================================

void _wsResetTerminalDecoders(WebSocketService s) {
  s._liveUtf8Decoder.reset();
  s._snapshotUtf8Decoder.reset();
  s._lastSnapshotActiveBuffer = TerminalBufferKind.main;
}

TerminalBufferKind? _wsParseActiveBuffer(dynamic raw) {
  if (raw is! String) {
    return null;
  }
  switch (raw) {
    case 'main':
      return TerminalBufferKind.main;
    case 'alt':
      return TerminalBufferKind.alt;
    default:
      return null;
  }
}

void _wsApplyPtySize(WebSocketService s, Map<String, dynamic>? pty,
    {bool notify = true}) {
  if (pty == null) {
    return;
  }
  final rows = pty['rows'];
  final cols = pty['cols'];
  if (rows is! num || cols is! num) {
    return;
  }
  final normalizedRows = rows.toInt();
  final normalizedCols = cols.toInt();
  if (normalizedRows <= 0 || normalizedCols <= 0) {
    return;
  }
  final changed = normalizedRows != s._ptyRows || normalizedCols != s._ptyCols;
  s._ptyRows = normalizedRows;
  s._ptyCols = normalizedCols;
  if (!changed) {
    return;
  }
  s._ptySizeController.add(
    TerminalPtySize(rows: normalizedRows, cols: normalizedCols),
  );
  if (notify) {
    s._notify();
  }
}

bool _wsApplyTerminalMeta(WebSocketService s, Map<String, dynamic> data) {
  var changed = false;

  final geometryOwnerView = data['geometry_owner_view'];
  final nextGeometryOwnerView =
      geometryOwnerView is String ? geometryOwnerView : null;
  if (nextGeometryOwnerView != s._geometryOwnerView) {
    s._geometryOwnerView = nextGeometryOwnerView;
    changed = true;
  }

  final viewsData = data['views'] as Map<String, dynamic>?;
  if (viewsData != null) {
    final nextViews = viewsData.map((k, v) => MapEntry(k, v as int));
    if (!mapEquals(nextViews, s._views)) {
      s._views = nextViews;
      s._presenceController.add(s._views);
      changed = true;
    }
  }

  return changed;
}

void _wsApplyConnectedMessage(WebSocketService s, Map<String, dynamic> data) {
  _wsResetTerminalDecoders(s);
  s._status = ConnectionStatus.connected;
  s._retryCount = 0;
  s._agentOnline = data['agent_online'] ?? false;
  s._deviceOnline = data['device_online'] ?? s._agentOnline;
  s._owner = data['owner'] ?? '';
  s._terminalStatus = data['terminal_status'] as String?;
  final attachEpoch = data['attach_epoch'];
  s._attachEpoch = attachEpoch is num ? attachEpoch.toInt() : null;
  final recoveryEpoch = data['recovery_epoch'];
  s._recoveryEpoch = recoveryEpoch is num ? recoveryEpoch.toInt() : null;
  _wsApplyTerminalMeta(s, data);
  _wsApplyPtySize(s, data['pty'] as Map<String, dynamic>?, notify: false);
  s._eventController.add(
    TerminalProtocolEvent(
      kind: TerminalProtocolEventKind.connected,
      attachEpoch: s._attachEpoch,
      recoveryEpoch: s._recoveryEpoch,
      ptySize: s._ptyRows != null && s._ptyCols != null
          ? TerminalPtySize(rows: s._ptyRows!, cols: s._ptyCols!)
          : null,
      views: s._views,
      geometryOwnerView: s._geometryOwnerView,
      terminalStatus: s._terminalStatus,
    ),
  );
  s._notify();
  if ((s.terminalId ?? '').isNotEmpty) {
    s._terminalConnectedController.add(null);
  }
}

void _wsApplyPresenceMessage(WebSocketService s, Map<String, dynamic> data) {
  if (_wsApplyTerminalMeta(s, data)) {
    s._eventController.add(
      TerminalProtocolEvent(
        kind: TerminalProtocolEventKind.presence,
        views: s._views,
        geometryOwnerView: s._geometryOwnerView,
        terminalStatus: s._terminalStatus,
      ),
    );
    s._notify();
  }
}

void _wsHandleMessage(WebSocketService s, String message) {
  try {
    var data = jsonDecode(message) as Map<String, dynamic>;

    // 解密 AES 加密消息
    if (data['encrypted'] == true && s._encryptionEnabled) {
      try {
        data = s._crypto.decryptMessage(data);
      } catch (e) {
        debugPrint('[WebSocketService] Decrypt failed: $e');
        return;
      }
    }

    final type = data['type'] as String?;

    switch (type) {
      case 'connected':
        _wsApplyConnectedMessage(s, data);
        break;
      case 'snapshot':
      case 'snapshot_start':
      case 'snapshot_chunk':
      case 'data':
      case 'output':
        {
          final msgAttachEpoch = data['attach_epoch'];
          final msgEpoch =
              msgAttachEpoch is num ? msgAttachEpoch.toInt() : null;
          final currentEpoch = s._attachEpoch;
          // 旧 epoch 消息静默丢弃（不变量 #32）
          if (msgEpoch != null &&
              currentEpoch != null &&
              msgEpoch < currentEpoch) {
            break;
          }
          if (type == 'snapshot_start') {
            s._snapshotUtf8Decoder.reset();
            s._lastSnapshotActiveBuffer = TerminalBufferKind.main;
          }
          final payload = data['payload'] as String?;
          if (payload != null) {
            final isSnapshotPayload = type == 'snapshot' ||
                type == 'snapshot_start' ||
                type == 'snapshot_chunk';
            final activeBuffer = _wsParseActiveBuffer(data['active_buffer']);
            if (type == 'snapshot' || type == 'snapshot_start') {
              s._snapshotUtf8Decoder.reset();
            }
            if (activeBuffer != null && isSnapshotPayload) {
              s._lastSnapshotActiveBuffer = activeBuffer;
            }
            final bytes = base64.decode(payload);
            final decoded =
                (isSnapshotPayload ? s._snapshotUtf8Decoder : s._liveUtf8Decoder)
                    .decode(bytes);
            if (decoded.isEmpty) {
              break;
            }
            final recoveryEpoch = data['recovery_epoch'];
            _wsEmitTerminalPayload(
              s,
              type: type ?? 'output',
              payload: decoded,
              attachEpoch: msgEpoch,
              recoveryEpoch:
                  recoveryEpoch is num ? recoveryEpoch.toInt() : null,
              activeBuffer: activeBuffer,
            );
          }
          break;
        }
      case 'snapshot_complete':
        {
          final msgAttachEpoch = data['attach_epoch'];
          final msgEpoch =
              msgAttachEpoch is num ? msgAttachEpoch.toInt() : null;
          final currentEpoch = s._attachEpoch;
          // 旧 epoch 消息静默丢弃（不变量 #32）
          if (msgEpoch != null &&
              currentEpoch != null &&
              msgEpoch < currentEpoch) {
            break;
          }
          final recoveryEpoch = data['recovery_epoch'] is num
              ? (data['recovery_epoch'] as num).toInt()
              : null;
          final flushedSnapshot = s._snapshotUtf8Decoder.decode(
            const <int>[],
            endOfInput: true,
          );
          if (flushedSnapshot.isNotEmpty) {
            _wsEmitTerminalPayload(
              s,
              type: 'snapshot_chunk',
              payload: flushedSnapshot,
              attachEpoch: msgEpoch,
              recoveryEpoch: recoveryEpoch,
              activeBuffer: s._lastSnapshotActiveBuffer,
            );
          }
          s._outputFrameController.add(
            const TerminalOutputFrame(
              kind: TerminalOutputKind.snapshotComplete,
              payload: '',
            ),
          );
          s._eventController.add(
            TerminalProtocolEvent(
              kind: TerminalProtocolEventKind.snapshotComplete,
              attachEpoch: msgEpoch,
              recoveryEpoch: recoveryEpoch,
            ),
          );
          break;
        }
      case 'presence':
        _wsApplyPresenceMessage(s, data);
        break;
      case 'resize':
        final rows = data['rows'];
        final cols = data['cols'];
        _wsApplyPtySize(s, {
          'rows': data['rows'],
          'cols': data['cols'],
        });
        if (rows is num && cols is num) {
          s._eventController.add(
            TerminalProtocolEvent(
              kind: TerminalProtocolEventKind.resize,
              ptySize: TerminalPtySize(
                rows: rows.toInt(),
                cols: cols.toInt(),
              ),
            ),
          );
        }
        break;
      case 'pong':
        // 心跳响应，忽略
        break;
      case 'error':
        s._errorMessage = data['message'] as String?;
        s._notify();
        break;
      case 'terminal_closed':
        s._terminalStatus = 'closed';
        s._errorMessage = 'terminal 已关闭';
        s._allowReconnect = false;
        s._status = ConnectionStatus.disconnected;
        s._eventController.add(
          const TerminalProtocolEvent(
            kind: TerminalProtocolEventKind.closed,
            terminalStatus: 'closed',
          ),
        );
        s._notify();
        unawaited(s.disconnect());
        break;
      case 'terminals_changed':
        // 跨平台终端变化通知
        debugPrint(
            '[WebSocketService] received terminals_changed: action=${data['action']} terminal_id=${data['terminal_id']}');
        s._terminalsChangedController.add(data);
        break;
      case 'device_kicked':
        debugPrint(
            '[WebSocketService] received device_kicked: reason=${data['reason']}');
        s._deviceKickedController.add(null);
        break;
      default:
        debugPrint('[WebSocketService] unknown message type: $type');
        break;
    }
  } catch (e) {
    debugPrint('Error parsing message: $e');
  }
}

void _wsEmitTerminalPayload(
  WebSocketService s, {
  required String type,
  required String payload,
  required int? attachEpoch,
  required int? recoveryEpoch,
  required TerminalBufferKind? activeBuffer,
}) {
  s._outputFrameController.add(
    TerminalOutputFrame(
      kind: switch (type) {
        'snapshot' => TerminalOutputKind.snapshot,
        'snapshot_chunk' => TerminalOutputKind.snapshotChunk,
        _ => TerminalOutputKind.data,
      },
      payload: payload,
      attachEpoch: attachEpoch,
      recoveryEpoch: recoveryEpoch,
      activeBuffer: activeBuffer,
    ),
  );
  s._eventController.add(
    TerminalProtocolEvent(
      kind: switch (type) {
        'snapshot' => TerminalProtocolEventKind.snapshot,
        'snapshot_chunk' => TerminalProtocolEventKind.snapshotChunk,
        _ => TerminalProtocolEventKind.output,
      },
      payload: payload,
      attachEpoch: attachEpoch,
      recoveryEpoch: recoveryEpoch,
      activeBuffer: activeBuffer,
    ),
  );
  s._outputController.add(payload);
}

/// 处理断开连接
void _wsHandleDisconnect(WebSocketService s) {
  _wsResetTerminalDecoders(s);
  _wsStopHeartbeat(s);

  // 根据 close code 设置错误信息（无论当前连接状态）
  if (s._lastCloseCode == 4001) {
    // token 验证失败，通知 UI 层跳转登录页
    s._errorMessage = '登录已失效';
    s._allowReconnect = false;
    s._tokenInvalidController.add(null);
  } else if (s._lastCloseCode == 4011) {
    // 被新设备替换，停止重连（旧 token 已失效，重连会被 4001 拒绝）
    s._allowReconnect = false;
  }

  if (s._status == ConnectionStatus.connected) {
    s._status = ConnectionStatus.disconnected;

    s._notify();

    // 日志埋点：连接断开
    s._logger?.warn('WebSocket disconnected', metadata: {
      'session_id': s.sessionId,
      'auto_reconnect': s.autoReconnect,
      'close_code': s._lastCloseCode,
    });
  } else if (s._status != ConnectionStatus.disconnected) {
    // 连接尚未建立就被断开（如 WS 握手阶段被拒绝）
    s._status = ConnectionStatus.disconnected;
    s._notify();
  }

  if (s.autoReconnect && s._allowReconnect && s._retryCount < s.maxRetries) {
    _wsScheduleReconnect(s);
  }
}

/// 从 WebSocketChannel 捕获 close code
void _wsCaptureCloseCode(WebSocketService s) {
  try {
    final closeCode = s._channel?.closeCode;
    final closeReason = s._channel?.closeReason;
    if (closeCode != null) {
      s._lastCloseCode = closeCode;
      s._lastCloseReason = closeReason;
      debugPrint(
          '[WebSocketService] WS closed: code=$closeCode reason=$closeReason');
    }
  } catch (e) {
    debugPrint('[WebSocketService] error capturing close code: $e');
  }
}

/// 开始心跳
void _wsStartHeartbeat(WebSocketService s) {
  _wsStopHeartbeat(s);
  s._heartbeatTimer = Timer.periodic(const Duration(seconds: 30), (_) {
    if (s._status == ConnectionStatus.connected && s._channel != null) {
      s._channel!.sink.add(jsonEncode({'type': 'ping'}));
    }
  });
}

/// 停止心跳
void _wsStopHeartbeat(WebSocketService s) {
  s._heartbeatTimer?.cancel();
  s._heartbeatTimer = null;
}

/// 安排重连
void _wsScheduleReconnect(WebSocketService s) {
  s._status = ConnectionStatus.reconnecting;
  s._notify();

  final delay = s.reconnectDelay * (1 << s._retryCount).clamp(0, 6); // 上限 64 秒
  s._retryCount++;

  s._reconnectTimer?.cancel();
  s._reconnectTimer = Timer(delay, () {
    s.connect();
  });
}
