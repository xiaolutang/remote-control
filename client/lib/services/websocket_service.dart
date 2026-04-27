import 'dart:async';
import 'dart:convert';
import 'dart:io' show HttpClient;
import 'package:flutter/foundation.dart';
import 'package:web_socket_channel/io.dart';
import 'package:web_socket_channel/web_socket_channel.dart';
import '../models/terminal_protocol.dart';
import 'server_url_helper.dart';
import 'http_client_factory.dart';
import 'logger_service.dart';
import 'crypto_service.dart';

export '../models/terminal_protocol.dart';

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

/// WebSocket 服务
class WebSocketService extends ChangeNotifier {
  WebSocketChannel? _channel;
  HttpClient? _wsHttpClient;
  Timer? _heartbeatTimer;
  Timer? _reconnectTimer;
  StreamSubscription? _streamSubscription;

  final String serverUrl;
  final String token;
  final String sessionId;
  final String? deviceId;
  final String? terminalId;
  final ViewType viewType;
  final bool autoReconnect;
  final int maxRetries;
  final Duration reconnectDelay;

  // 日志服务（可选）
  final LoggerService? _logger;

  // 加密服务
  final CryptoService _crypto = CryptoService.instance;
  final Future<void> Function(String httpBaseUrl)? _publicKeyFetcher;
  final bool Function()? _hasPublicKeyChecker;
  bool _encryptionEnabled = false;

  ConnectionStatus _status = ConnectionStatus.disconnected;
  String? _errorMessage;
  int _retryCount = 0;
  bool _allowReconnect = true;
  bool _agentOnline = false;
  bool _deviceOnline = false;
  String _owner = '';
  String? _terminalStatus;
  Map<String, int> _views = {'mobile': 0, 'desktop': 0};
  String? _geometryOwnerView;
  int? _lastCloseCode;
  String? _lastCloseReason;
  int? _ptyRows;
  int? _ptyCols;
  int? _attachEpoch;
  int? _recoveryEpoch;
  final _liveUtf8Decoder = _StreamingUtf8Decoder();
  final _snapshotUtf8Decoder = _StreamingUtf8Decoder();
  TerminalBufferKind _lastSnapshotActiveBuffer = TerminalBufferKind.main;

  final StreamController<String> _outputController =
      StreamController<String>.broadcast();
  final StreamController<TerminalOutputFrame> _outputFrameController =
      StreamController<TerminalOutputFrame>.broadcast();
  final StreamController<TerminalProtocolEvent> _eventController =
      StreamController<TerminalProtocolEvent>.broadcast();
  final StreamController<void> _terminalConnectedController =
      StreamController<void>.broadcast();
  final StreamController<TerminalPtySize> _ptySizeController =
      StreamController<TerminalPtySize>.broadcast();
  final StreamController<Map<String, int>> _presenceController =
      StreamController<Map<String, int>>.broadcast();
  final StreamController<Map<String, dynamic>> _terminalsChangedController =
      StreamController<Map<String, dynamic>>.broadcast();
  final StreamController<void> _deviceKickedController =
      StreamController<void>.broadcast();
  final StreamController<void> _tokenInvalidController =
      StreamController<void>.broadcast();

  WebSocketService({
    required this.serverUrl,
    required this.token,
    required this.sessionId,
    this.deviceId,
    this.terminalId,
    this.viewType = ViewType.mobile,
    this.autoReconnect = true,
    this.maxRetries = 60,
    this.reconnectDelay = const Duration(seconds: 1),
    LoggerService? logger,
    Future<void> Function(String httpBaseUrl)? publicKeyFetcher,
    bool Function()? hasPublicKeyChecker,
  })  : _logger = logger,
        _publicKeyFetcher = publicKeyFetcher,
        _hasPublicKeyChecker = hasPublicKeyChecker;

  ConnectionStatus get status => _status;
  String? get errorMessage => _errorMessage;
  @Deprecated('Use eventStream with TerminalProtocolEventKind.output instead')
  Stream<String> get outputStream => _outputController.stream;
  Stream<TerminalOutputFrame> get outputFrameStream =>
      _outputFrameController.stream;
  Stream<TerminalProtocolEvent> get eventStream => _eventController.stream;
  Stream<void> get terminalConnectedStream =>
      _terminalConnectedController.stream;
  Stream<TerminalPtySize> get ptySizeStream => _ptySizeController.stream;
  @Deprecated('Use eventStream with TerminalProtocolEventKind.presence instead')
  Stream<Map<String, int>> get presenceStream => _presenceController.stream;
  Stream<Map<String, dynamic>> get terminalsChangedStream =>
      _terminalsChangedController.stream;
  Stream<void> get deviceKickedStream => _deviceKickedController.stream;

  /// WS close code 4001 (token 验证失败) 时触发，UI 层应跳转登录页
  Stream<void> get tokenInvalidStream => _tokenInvalidController.stream;
  bool get isConnected => _status == ConnectionStatus.connected;
  bool get agentOnline => _agentOnline;

  /// 设备在线状态 - 来自 Server 首包消息中的 device_online
  /// 表示 Agent 到 Server 的连接状态，与客户端 WebSocket 连接状态无关
  bool get deviceOnline => _deviceOnline;
  String get owner => _owner;
  String? get terminalStatus => _terminalStatus;
  Map<String, int> get views => _views;
  String? get geometryOwnerView => _geometryOwnerView;
  bool get isGeometryOwner => _geometryOwnerView == _viewTypeString;
  int? get lastCloseCode => _lastCloseCode;
  String? get lastCloseReason => _lastCloseReason;
  int? get ptyRows => _ptyRows;
  int? get ptyCols => _ptyCols;
  int? get attachEpoch => _attachEpoch;
  int? get recoveryEpoch => _recoveryEpoch;

  /// 是否因认证失败而永久断开（close code 4001 或 4011），
  /// 此类服务不可复用，应丢弃重建。
  bool get isAuthFailed => _lastCloseCode == 4001 || _lastCloseCode == 4011;

  /// 永久失败：认证失败或终端已关闭，此类服务不可恢复。
  bool get isPermanentlyFailed => isAuthFailed || terminalStatus == 'closed';

  String get _viewTypeString =>
      viewType == ViewType.desktop ? 'desktop' : 'mobile';

  String get _httpBaseUrl => serverUrlToHttpBase(serverUrl);
  bool get _requiresApplicationLayerEncryption =>
      requiresApplicationLayerEncryption(serverUrl);

  bool get _hasPublicKey =>
      _hasPublicKeyChecker?.call() ?? _crypto.hasPublicKey;

  Future<void> _ensurePublicKeyLoaded() async {
    if (_hasPublicKey) {
      return;
    }
    final fetcher = _publicKeyFetcher ?? _crypto.fetchPublicKey;
    await fetcher(_httpBaseUrl);
  }

  @visibleForTesting
  Future<void> debugEnsurePublicKeyLoaded() => _ensurePublicKeyLoaded();

  @visibleForTesting
  bool get debugRequiresApplicationLayerEncryption =>
      _requiresApplicationLayerEncryption;

  void _resetTerminalDecoders() {
    _liveUtf8Decoder.reset();
    _snapshotUtf8Decoder.reset();
    _lastSnapshotActiveBuffer = TerminalBufferKind.main;
  }

  TerminalBufferKind? _parseActiveBuffer(dynamic raw) {
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

  void _applyPtySize(Map<String, dynamic>? pty, {bool notify = true}) {
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
    final changed = normalizedRows != _ptyRows || normalizedCols != _ptyCols;
    _ptyRows = normalizedRows;
    _ptyCols = normalizedCols;
    if (!changed) {
      return;
    }
    _ptySizeController.add(
      TerminalPtySize(rows: normalizedRows, cols: normalizedCols),
    );
    if (notify) {
      notifyListeners();
    }
  }

  bool _applyTerminalMeta(Map<String, dynamic> data) {
    var changed = false;

    final geometryOwnerView = data['geometry_owner_view'];
    final nextGeometryOwnerView =
        geometryOwnerView is String ? geometryOwnerView : null;
    if (nextGeometryOwnerView != _geometryOwnerView) {
      _geometryOwnerView = nextGeometryOwnerView;
      changed = true;
    }

    final viewsData = data['views'] as Map<String, dynamic>?;
    if (viewsData != null) {
      final nextViews = viewsData.map((k, v) => MapEntry(k, v as int));
      if (!mapEquals(nextViews, _views)) {
        _views = nextViews;
        _presenceController.add(_views);
        changed = true;
      }
    }

    return changed;
  }

  void _applyConnectedMessage(Map<String, dynamic> data) {
    _resetTerminalDecoders();
    _status = ConnectionStatus.connected;
    _retryCount = 0;
    _agentOnline = data['agent_online'] ?? false;
    _deviceOnline = data['device_online'] ?? _agentOnline;
    _owner = data['owner'] ?? '';
    _terminalStatus = data['terminal_status'] as String?;
    final attachEpoch = data['attach_epoch'];
    _attachEpoch = attachEpoch is num ? attachEpoch.toInt() : null;
    final recoveryEpoch = data['recovery_epoch'];
    _recoveryEpoch = recoveryEpoch is num ? recoveryEpoch.toInt() : null;
    _applyTerminalMeta(data);
    _applyPtySize(data['pty'] as Map<String, dynamic>?, notify: false);
    _eventController.add(
      TerminalProtocolEvent(
        kind: TerminalProtocolEventKind.connected,
        attachEpoch: _attachEpoch,
        recoveryEpoch: _recoveryEpoch,
        ptySize: _ptyRows != null && _ptyCols != null
            ? TerminalPtySize(rows: _ptyRows!, cols: _ptyCols!)
            : null,
        views: _views,
        geometryOwnerView: _geometryOwnerView,
        terminalStatus: _terminalStatus,
      ),
    );
    notifyListeners();
    if ((terminalId ?? '').isNotEmpty) {
      _terminalConnectedController.add(null);
    }
  }

  void _applyPresenceMessage(Map<String, dynamic> data) {
    if (_applyTerminalMeta(data)) {
      _eventController.add(
        TerminalProtocolEvent(
          kind: TerminalProtocolEventKind.presence,
          views: _views,
          geometryOwnerView: _geometryOwnerView,
          terminalStatus: _terminalStatus,
        ),
      );
      notifyListeners();
    }
  }

  /// 连接到服务器
  Future<bool> connect() async {
    if (_status == ConnectionStatus.connected ||
        _status == ConnectionStatus.connecting) {
      return true;
    }

    // 清理旧的订阅和连接，避免内存泄漏
    await _streamSubscription?.cancel();
    _streamSubscription = null;
    await _channel?.sink.close();
    _channel = null;
    _wsHttpClient?.close();
    _wsHttpClient = null;

    _status = ConnectionStatus.connecting;
    _allowReconnect = true;
    _errorMessage = null;
    _resetTerminalDecoders();
    notifyListeners();

    // 日志埋点：开始连接
    _logger?.info('WebSocket connecting', metadata: {
      'server_url': serverUrl,
      'session_id': sessionId,
      'view_type': _viewTypeString,
    });

    try {
      if (_requiresApplicationLayerEncryption && !_hasPublicKey) {
        try {
          await _ensurePublicKeyLoaded();
        } catch (e) {
          _status = ConnectionStatus.error;
          _errorMessage = '安全连接建立失败';
          notifyListeners();
          return false;
        }
      }

      // WS URL 不再携带 token，认证通过首条 auth 消息完成
      final queryParameters = <String, String>{
        'view': _viewTypeString,
      };
      if (sessionId.isNotEmpty) {
        queryParameters['session_id'] = sessionId;
      }
      if ((deviceId ?? '').isNotEmpty) {
        queryParameters['device_id'] = deviceId!;
      }
      if ((terminalId ?? '').isNotEmpty) {
        queryParameters['terminal_id'] = terminalId!;
      }
      final wsUri = Uri.parse('$serverUrl/ws/client').replace(
        queryParameters: queryParameters,
      );
      final wsUrl = wsUri.toString();
      _wsHttpClient = HttpClientFactory.createRaw();
      _channel = IOWebSocketChannel.connect(
        wsUrl,
        customClient: _wsHttpClient,
      );

      // 连接后立即发送 auth 消息（携带加密的 AES 会话密钥）
      final authMessage = <String, dynamic>{
        'type': 'auth',
        'token': token,
      };
      bool aesKeyExchanged = false;
      if (_requiresApplicationLayerEncryption) {
        try {
          _crypto.generateAesKey();
          authMessage['encrypted_aes_key'] = _crypto.getEncryptedAesKeyBase64();
          aesKeyExchanged = true;
        } catch (e) {
          debugPrint('[WebSocketService] AES key exchange failed: $e');
          _crypto.clearAesKey();
        }
      }
      // ws:// 连接必须成功完成 AES 密钥交换（不变量 #27）
      // 在发送 auth 前检查：若无 AES 密钥则直接拒绝，不发送明文 auth
      if (_requiresApplicationLayerEncryption && !aesKeyExchanged) {
        _status = ConnectionStatus.error;
        _errorMessage = '安全连接建立失败';
        notifyListeners();
        await _channel?.sink.close();
        return false;
      }
      _channel!.sink.add(jsonEncode(authMessage));

      // 使用 Completer 等待第一条确认消息
      final completer = Completer<bool>();
      bool isFirstMessage = true;

      // 监听所有消息
      _streamSubscription = _channel!.stream.listen(
        (message) {
          if (isFirstMessage) {
            isFirstMessage = false;
            try {
              final data = jsonDecode(message!) as Map<String, dynamic>;
              if (data['type'] == 'connected') {
                _encryptionEnabled = aesKeyExchanged;
                _applyConnectedMessage(data);
                _startHeartbeat();

                // 日志埋点：连接成功
                _logger?.info('WebSocket connected', metadata: {
                  'session_id': sessionId,
                  'agent_online': _agentOnline,
                  'owner': _owner,
                  'view': _viewTypeString,
                });

                completer.complete(true);
              } else {
                completer.completeError(
                    Exception('Unexpected message type: ${data['type']}'));
              }
            } catch (e) {
              completer.completeError(e);
            }
          } else {
            _handleMessage(message!);
          }
        },
        onError: (error) {
          _status = ConnectionStatus.error;
          _errorMessage = error.toString();
          notifyListeners();

          // 日志埋点：连接错误
          _logger?.error('WebSocket error', metadata: {
            'error': error.toString(),
            'retry_count': _retryCount,
          });

          _handleDisconnect();
          if (!completer.isCompleted) {
            completer.completeError(error);
          }
        },
        onDone: () {
          _captureCloseCode();
          _handleDisconnect();
          if (!completer.isCompleted) {
            completer.completeError(Exception('Connection closed'));
          }
        },
      );

      // 等待连接确认或超时
      return await completer.future.timeout(
        const Duration(seconds: 30),
        onTimeout: () {
          throw TimeoutException('Connection timeout');
        },
      );
    } catch (e) {
      _status = ConnectionStatus.error;
      _errorMessage = e.toString();
      notifyListeners();

      // 日志埋点：连接失败
      _logger?.error('WebSocket connection failed', metadata: {
        'error': e.toString(),
        'server_url': serverUrl,
      });

      if (autoReconnect && _allowReconnect && _retryCount < maxRetries) {
        _scheduleReconnect();
      }

      return false;
    }
  }

  /// 处理消息
  void _handleMessage(String message) {
    try {
      var data = jsonDecode(message) as Map<String, dynamic>;

      // 解密 AES 加密消息
      if (data['encrypted'] == true && _encryptionEnabled) {
        try {
          data = _crypto.decryptMessage(data);
        } catch (e) {
          debugPrint('[WebSocketService] Decrypt failed: $e');
          return;
        }
      }

      final type = data['type'] as String?;

      switch (type) {
        case 'connected':
          _applyConnectedMessage(data);
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
            final currentEpoch = _attachEpoch;
            // 旧 epoch 消息静默丢弃（不变量 #32）
            if (msgEpoch != null &&
                currentEpoch != null &&
                msgEpoch < currentEpoch) {
              break;
            }
            if (type == 'snapshot_start') {
              _snapshotUtf8Decoder.reset();
              _lastSnapshotActiveBuffer = TerminalBufferKind.main;
            }
            final payload = data['payload'] as String?;
            if (payload != null) {
              final isSnapshotPayload = type == 'snapshot' ||
                  type == 'snapshot_start' ||
                  type == 'snapshot_chunk';
              final activeBuffer = _parseActiveBuffer(data['active_buffer']);
              if (type == 'snapshot' || type == 'snapshot_start') {
                _snapshotUtf8Decoder.reset();
              }
              if (activeBuffer != null && isSnapshotPayload) {
                _lastSnapshotActiveBuffer = activeBuffer;
              }
              final bytes = base64Decode(payload);
              final decoded =
                  (isSnapshotPayload ? _snapshotUtf8Decoder : _liveUtf8Decoder)
                      .decode(bytes);
              if (decoded.isEmpty) {
                break;
              }
              final recoveryEpoch = data['recovery_epoch'];
              _emitTerminalPayload(
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
            final currentEpoch = _attachEpoch;
            // 旧 epoch 消息静默丢弃（不变量 #32）
            if (msgEpoch != null &&
                currentEpoch != null &&
                msgEpoch < currentEpoch) {
              break;
            }
            final recoveryEpoch = data['recovery_epoch'] is num
                ? (data['recovery_epoch'] as num).toInt()
                : null;
            final flushedSnapshot = _snapshotUtf8Decoder.decode(
              const <int>[],
              endOfInput: true,
            );
            if (flushedSnapshot.isNotEmpty) {
              _emitTerminalPayload(
                type: 'snapshot_chunk',
                payload: flushedSnapshot,
                attachEpoch: msgEpoch,
                recoveryEpoch: recoveryEpoch,
                activeBuffer: _lastSnapshotActiveBuffer,
              );
            }
            _outputFrameController.add(
              const TerminalOutputFrame(
                kind: TerminalOutputKind.snapshotComplete,
                payload: '',
              ),
            );
            _eventController.add(
              TerminalProtocolEvent(
                kind: TerminalProtocolEventKind.snapshotComplete,
                attachEpoch: msgEpoch,
                recoveryEpoch: recoveryEpoch,
              ),
            );
            break;
          }
        case 'presence':
          _applyPresenceMessage(data);
          break;
        case 'resize':
          final rows = data['rows'];
          final cols = data['cols'];
          _applyPtySize({
            'rows': data['rows'],
            'cols': data['cols'],
          });
          if (rows is num && cols is num) {
            _eventController.add(
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
          _errorMessage = data['message'] as String?;
          notifyListeners();
          break;
        case 'terminal_closed':
          _terminalStatus = 'closed';
          _errorMessage = 'terminal 已关闭';
          _allowReconnect = false;
          _status = ConnectionStatus.disconnected;
          _eventController.add(
            const TerminalProtocolEvent(
              kind: TerminalProtocolEventKind.closed,
              terminalStatus: 'closed',
            ),
          );
          notifyListeners();
          unawaited(disconnect());
          break;
        case 'terminals_changed':
          // 跨平台终端变化通知
          debugPrint(
              '[WebSocketService] received terminals_changed: action=${data['action']} terminal_id=${data['terminal_id']}');
          _terminalsChangedController.add(data);
          break;
        case 'device_kicked':
          debugPrint(
              '[WebSocketService] received device_kicked: reason=${data['reason']}');
          _deviceKickedController.add(null);
          break;
        default:
          debugPrint('[WebSocketService] unknown message type: $type');
          break;
      }
    } catch (e) {
      debugPrint('Error parsing message: $e');
    }
  }

  @visibleForTesting
  void debugHandleMessage(String message) {
    _handleMessage(message);
  }

  void _emitTerminalPayload({
    required String type,
    required String payload,
    required int? attachEpoch,
    required int? recoveryEpoch,
    required TerminalBufferKind? activeBuffer,
  }) {
    _outputFrameController.add(
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
    _eventController.add(
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
    _outputController.add(payload);
  }

  Uint8List base64Decode(String source) {
    return base64.decode(source);
  }

  /// 处理断开连接
  void _handleDisconnect() {
    _resetTerminalDecoders();
    _stopHeartbeat();

    // 根据 close code 设置错误信息（无论当前连接状态）
    if (_lastCloseCode == 4001) {
      // token 验证失败，通知 UI 层跳转登录页
      _errorMessage = '登录已失效';
      _allowReconnect = false;
      _tokenInvalidController.add(null);
    } else if (_lastCloseCode == 4011) {
      // 被新设备替换，停止重连（旧 token 已失效，重连会被 4001 拒绝）
      _allowReconnect = false;
    }

    if (_status == ConnectionStatus.connected) {
      _status = ConnectionStatus.disconnected;

      notifyListeners();

      // 日志埋点：连接断开
      _logger?.warn('WebSocket disconnected', metadata: {
        'session_id': sessionId,
        'auto_reconnect': autoReconnect,
        'close_code': _lastCloseCode,
      });
    } else if (_status != ConnectionStatus.disconnected) {
      // 连接尚未建立就被断开（如 WS 握手阶段被拒绝）
      _status = ConnectionStatus.disconnected;
      notifyListeners();
    }

    if (autoReconnect && _allowReconnect && _retryCount < maxRetries) {
      _scheduleReconnect();
    }
  }

  /// 发送数据并等待消息 flush 到网络（不变量 #61）
  Future<void> send(String data) async {
    if (_status != ConnectionStatus.connected || _channel == null) {
      return;
    }

    final raw = {
      'type': 'data',
      'payload': base64Encode(utf8.encode(data)),
      'timestamp': DateTime.now().toUtc().toIso8601String(),
    };

    final message = _encryptionEnabled && _crypto.shouldEncrypt('data')
        ? jsonEncode(_crypto.encryptMessage(raw))
        : jsonEncode(raw);

    _channel!.sink.add(message);
    // 等待 IOWebSocketChannel 内部 ready Future，确保消息已 flush 到网络
    if (_channel is IOWebSocketChannel) {
      await (_channel as IOWebSocketChannel).ready;
    }
  }

  void sendLine(String data) {
    send('$data\r');
  }

  /// 发送特殊键
  void sendKey(String key) {
    send(key);
  }

  /// 从 WebSocketChannel 捕获 close code
  void _captureCloseCode() {
    try {
      final closeCode = _channel?.closeCode;
      final closeReason = _channel?.closeReason;
      if (closeCode != null) {
        _lastCloseCode = closeCode;
        _lastCloseReason = closeReason;
        debugPrint(
            '[WebSocketService] WS closed: code=$closeCode reason=$closeReason');
      }
    } catch (e) {
      debugPrint('[WebSocketService] error capturing close code: $e');
    }
  }

  /// 调整终端大小
  void resize(int rows, int cols) {
    if (_status != ConnectionStatus.connected || _channel == null) {
      return;
    }

    final raw = {
      'type': 'resize',
      'rows': rows,
      'cols': cols,
    };

    final message = _encryptionEnabled && _crypto.shouldEncrypt('resize')
        ? jsonEncode(_crypto.encryptMessage(raw))
        : jsonEncode(raw);

    _channel!.sink.add(message);
  }

  /// 开始心跳
  void _startHeartbeat() {
    _stopHeartbeat();
    _heartbeatTimer = Timer.periodic(const Duration(seconds: 30), (_) {
      if (_status == ConnectionStatus.connected && _channel != null) {
        _channel!.sink.add(jsonEncode({'type': 'ping'}));
      }
    });
  }

  /// 停止心跳
  void _stopHeartbeat() {
    _heartbeatTimer?.cancel();
    _heartbeatTimer = null;
  }

  /// 安排重连
  void _scheduleReconnect() {
    _status = ConnectionStatus.reconnecting;
    notifyListeners();

    final delay = reconnectDelay * (1 << _retryCount).clamp(0, 6); // 上限 64 秒
    _retryCount++;

    _reconnectTimer?.cancel();
    _reconnectTimer = Timer(delay, () {
      connect();
    });
  }

  /// 断开连接
  Future<void> disconnect({bool notify = true}) async {
    _allowReconnect = false;
    _encryptionEnabled = false;
    _crypto.clearAesKey();
    _resetTerminalDecoders();
    _stopHeartbeat();
    _reconnectTimer?.cancel();
    await _streamSubscription?.cancel();
    _streamSubscription = null;

    if (_channel != null) {
      await _channel!.sink.close();
      _channel = null;
    }
    _wsHttpClient?.close();
    _wsHttpClient = null;

    _status = ConnectionStatus.disconnected;
    if (notify) {
      notifyListeners();
    }
  }

  /// 释放资源
  @override
  void dispose() {
    disconnect(notify: false);
    _outputController.close();
    _outputFrameController.close();
    _eventController.close();
    _terminalConnectedController.close();
    _ptySizeController.close();
    _presenceController.close();
    _terminalsChangedController.close();
    _deviceKickedController.close();
    _tokenInvalidController.close();
    super.dispose();
  }
}
