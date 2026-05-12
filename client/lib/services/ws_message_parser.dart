part of 'websocket_service.dart';

class _CollectingStringSink implements StringSink {
  StringBuffer _buffer = StringBuffer();

  @override
  void write(Object? obj) {
    _buffer.write(obj);
  }

  @override
  void writeAll(Iterable<dynamic> objects, [String separator = '']) {
    _buffer.writeAll(objects, separator);
  }

  @override
  void writeCharCode(int charCode) {
    _buffer.writeCharCode(charCode);
  }

  @override
  void writeln([Object? obj = '']) {
    _buffer.writeln(obj);
  }

  String take() {
    final value = _buffer.toString();
    _buffer = StringBuffer();
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

void _wsResetTerminalDecoders(WebSocketService s) {
  s._liveUtf8Decoder.reset();
  s._snapshotUtf8Decoder.reset();
  s._lastSnapshotActiveBuffer = TerminalBufferKind.main;
  s._bracketedPasteModeEnabled = false;
  s._terminalModeTail = '';
}

const String _kBracketedPasteEnableSequence = '\x1b[?2004h';
const String _kBracketedPasteDisableSequence = '\x1b[?2004l';
const int _kTerminalModeTailLength = 32;

void _wsTrackTerminalModes(WebSocketService s, String payload) {
  if (payload.isEmpty) {
    return;
  }

  final combined = s._terminalModeTail + payload;
  var nextBracketedPasteMode = s._bracketedPasteModeEnabled;
  var cursor = 0;

  while (cursor < combined.length) {
    final enableIndex =
        combined.indexOf(_kBracketedPasteEnableSequence, cursor);
    final disableIndex =
        combined.indexOf(_kBracketedPasteDisableSequence, cursor);
    if (enableIndex < 0 && disableIndex < 0) {
      break;
    }

    final shouldEnable =
        disableIndex < 0 || (enableIndex >= 0 && enableIndex < disableIndex);
    if (shouldEnable) {
      nextBracketedPasteMode = true;
      cursor = enableIndex + _kBracketedPasteEnableSequence.length;
    } else {
      nextBracketedPasteMode = false;
      cursor = disableIndex + _kBracketedPasteDisableSequence.length;
    }
  }

  if (combined.length <= _kTerminalModeTailLength) {
    s._terminalModeTail = combined;
  } else {
    s._terminalModeTail =
        combined.substring(combined.length - _kTerminalModeTailLength);
  }

  if (nextBracketedPasteMode != s._bracketedPasteModeEnabled) {
    s._bracketedPasteModeEnabled = nextBracketedPasteMode;
    s._notify();
  }
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

void _wsApplyPtySize(
  WebSocketService s,
  Map<String, dynamic>? pty, {
  bool notify = true,
}) {
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
    final nextViews = viewsData.map(
      (k, v) => MapEntry(k, safeIntFromMapValue(v)),
    );
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

    if (data['encrypted'] == true && s._encryptionEnabled) {
      try {
        data = s._crypto.decryptMessage(data);
      } catch (e) {
        _log.error('Decrypt failed: $e');
        return;
      }
    }

    final type = data['type'] as String?;
    switch (type) {
      case MessageType.connected:
        _wsApplyConnectedMessage(s, data);
        break;
      case MessageType.snapshot:
      case MessageType.snapshotStart:
      case MessageType.snapshotChunk:
      case MessageType.data:
      case MessageType.output:
        {
          final msgAttachEpoch = data['attach_epoch'];
          final msgEpoch =
              msgAttachEpoch is num ? msgAttachEpoch.toInt() : null;
          final currentEpoch = s._attachEpoch;
          if (msgEpoch != null &&
              currentEpoch != null &&
              msgEpoch < currentEpoch) {
            break;
          }
          if (type == MessageType.snapshotStart) {
            s._snapshotUtf8Decoder.reset();
            s._lastSnapshotActiveBuffer = TerminalBufferKind.main;
          }
          final payload = data['payload'] as String?;
          if (payload != null) {
            final isSnapshotPayload = type == MessageType.snapshot ||
                type == MessageType.snapshotStart ||
                type == MessageType.snapshotChunk;
            final activeBuffer = _wsParseActiveBuffer(data['active_buffer']);
            if (type == MessageType.snapshot || type == MessageType.snapshotStart) {
              s._snapshotUtf8Decoder.reset();
            }
            if (activeBuffer != null && isSnapshotPayload) {
              s._lastSnapshotActiveBuffer = activeBuffer;
            }
            final bytes = base64.decode(payload);
            final decoded = (isSnapshotPayload
                    ? s._snapshotUtf8Decoder
                    : s._liveUtf8Decoder)
                .decode(bytes);
            if (decoded.isEmpty) {
              break;
            }
            final recoveryEpoch = data['recovery_epoch'];
            _wsEmitTerminalPayload(
              s,
              type: type ?? MessageType.output,
              payload: decoded,
              attachEpoch: msgEpoch,
              recoveryEpoch:
                  recoveryEpoch is num ? recoveryEpoch.toInt() : null,
              activeBuffer: activeBuffer,
            );
          }
          break;
        }
      case MessageType.snapshotComplete:
        {
          final msgAttachEpoch = data['attach_epoch'];
          final msgEpoch =
              msgAttachEpoch is num ? msgAttachEpoch.toInt() : null;
          final currentEpoch = s._attachEpoch;
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
              type: MessageType.snapshotChunk,
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
      case MessageType.presence:
        _wsApplyPresenceMessage(s, data);
        break;
      case MessageType.resize:
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
      case MessageType.pong:
        break;
      case MessageType.error:
        s._errorMessage = data['message'] as String?;
        s._notify();
        break;
      case MessageType.terminalClosed:
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
      case MessageType.terminalsChanged:
        _log.info(
          'received terminals_changed: '
          'action=${data['action']} terminal_id=${data['terminal_id']}',
        );
        s._terminalsChangedController.add(data);
        break;
      case MessageType.deviceKicked:
        _log.warning(
          'received device_kicked: reason=${data['reason']}',
        );
        s._deviceKickedController.add(null);
        break;
      default:
        _log.warning('unknown message type: $type');
        break;
    }
  } catch (e) {
    _log.error('Error parsing message: $e');
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
  _wsTrackTerminalModes(s, payload);
  s._outputFrameController.add(
    TerminalOutputFrame(
      kind: switch (type) {
        MessageType.snapshot => TerminalOutputKind.snapshot,
        MessageType.snapshotChunk => TerminalOutputKind.snapshotChunk,
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
        MessageType.snapshot => TerminalProtocolEventKind.snapshot,
        MessageType.snapshotChunk => TerminalProtocolEventKind.snapshotChunk,
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
