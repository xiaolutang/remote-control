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

part 'websocket_service_handlers.dart';

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

  // -- Public getters --

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

  /// 包装 notifyListeners 以允许 part 文件中的顶层函数调用
  void _notify() => notifyListeners();

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

  // -- 委托到 part 文件中的顶层函数（connect 内部调用） --

  void _resetTerminalDecoders() => _wsResetTerminalDecoders(this);

  void _applyConnectedMessage(Map<String, dynamic> data) =>
      _wsApplyConnectedMessage(this, data);

  void _handleMessage(String message) => _wsHandleMessage(this, message);

  @visibleForTesting
  void debugHandleMessage(String message) => _handleMessage(message);

  Uint8List base64Decode(String source) => base64.decode(source);

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
                _wsStartHeartbeat(this);

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

          _wsHandleDisconnect(this);
          if (!completer.isCompleted) {
            completer.completeError(error);
          }
        },
        onDone: () {
          _wsCaptureCloseCode(this);
          _wsHandleDisconnect(this);
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
        _wsScheduleReconnect(this);
      }

      return false;
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

  /// 断开连接
  Future<void> disconnect({bool notify = true}) async {
    _allowReconnect = false;
    _encryptionEnabled = false;
    _crypto.clearAesKey();
    _resetTerminalDecoders();
    _wsStopHeartbeat(this);
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
