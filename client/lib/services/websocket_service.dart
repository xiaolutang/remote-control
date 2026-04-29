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

part 'ws_message_parser.dart';
part 'ws_connection_manager.dart';

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
  bool _bracketedPasteModeEnabled = false;
  String _terminalModeTail = '';
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
  bool get bracketedPasteModeEnabled => _bracketedPasteModeEnabled;
  bool get canSend => _status == ConnectionStatus.connected && _channel != null;

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

  @visibleForTesting
  String debugEncodeDataMessage(String data) =>
      _wsEncodeDataMessage(this, data);

  Uint8List base64Decode(String source) => base64.decode(source);

  /// 连接到服务器
  Future<bool> connect() => _wsConnect(this);

  /// 发送数据并等待消息 flush 到网络（不变量 #61）
  Future<void> send(String data) => _wsSend(this, data);

  /// 用于必须成功送达用户输入的场景；连接不可写时显式抛错。
  Future<void> sendOrThrow(String data) => _wsSendOrThrow(this, data);

  void sendLine(String data) {
    send('$data\r');
  }

  /// 发送特殊键
  void sendKey(String key) {
    send(key);
  }

  /// 调整终端大小
  void resize(int rows, int cols) => _wsResize(this, rows, cols);

  /// 断开连接
  Future<void> disconnect({bool notify = true}) =>
      _wsDisconnect(this, notify: notify);

  /// 释放资源
  @override
  void dispose() {
    _wsDispose(this);
    super.dispose();
  }
}
