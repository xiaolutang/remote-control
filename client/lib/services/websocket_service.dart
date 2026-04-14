import 'dart:async';
import 'dart:convert';
import 'dart:io' show HttpClient;
import 'package:flutter/foundation.dart';
import 'package:web_socket_channel/io.dart';
import 'package:web_socket_channel/web_socket_channel.dart';
import 'http_client_factory.dart';
import 'logger_service.dart';

/// 连接状态
enum ConnectionStatus {
  disconnected,
  connecting,
  connected,
  reconnecting,
  error,
}

/// 视图类型 (CONTRACT-003)
enum ViewType {
  mobile,
  desktop,
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

  ConnectionStatus _status = ConnectionStatus.disconnected;
  String? _errorMessage;
  int _retryCount = 0;
  bool _allowReconnect = true;
  bool _agentOnline = false;
  bool _deviceOnline = false;
  String _owner = '';
  String? _terminalStatus;
  Map<String, int> _views = {'mobile': 0, 'desktop': 0};
  int? _lastCloseCode;
  String? _lastCloseReason;

  final StreamController<String> _outputController =
      StreamController<String>.broadcast();
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
    this.maxRetries = 5,
    this.reconnectDelay = const Duration(seconds: 1),
    LoggerService? logger,
  }) : _logger = logger;

  ConnectionStatus get status => _status;
  String? get errorMessage => _errorMessage;
  Stream<String> get outputStream => _outputController.stream;
  Stream<Map<String, int>> get presenceStream => _presenceController.stream;
  Stream<Map<String, dynamic>> get terminalsChangedStream => _terminalsChangedController.stream;
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
  int? get lastCloseCode => _lastCloseCode;
  String? get lastCloseReason => _lastCloseReason;
  /// 是否因认证失败而永久断开（close code 4001 或 4011），
  /// 此类服务不可复用，应丢弃重建。
  bool get isAuthFailed =>
      _lastCloseCode == 4001 || _lastCloseCode == 4011;

  String get _viewTypeString => viewType == ViewType.desktop ? 'desktop' : 'mobile';

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
    notifyListeners();

    // 日志埋点：开始连接
    _logger?.info('WebSocket connecting', metadata: {
      'server_url': serverUrl,
      'session_id': sessionId,
      'view_type': _viewTypeString,
    });

    try {
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

      // 连接后立即发送 auth 消息（不再通过 URL query 传 token）
      _channel!.sink.add(jsonEncode({
        'type': 'auth',
        'token': token,
      }));

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
                _status = ConnectionStatus.connected;
                _retryCount = 0;
                // 解析 connected 消息（CONTRACT-003）
                _agentOnline = data['agent_online'] ?? false;
                _deviceOnline = data['device_online'] ?? _agentOnline;
                _owner = data['owner'] ?? '';
                _terminalStatus = data['terminal_status'] as String?;
                notifyListeners();
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
      final data = jsonDecode(message) as Map<String, dynamic>;
      final type = data['type'] as String?;

      switch (type) {
        case 'data':
          final payload = data['payload'] as String?;
          if (payload != null) {
            final bytes = base64Decode(payload);
            final decoded = utf8.decode(bytes, allowMalformed: true);
            _outputController.add(decoded);
          }
          break;
        case 'presence':
          // 处理 presence 消息（CONTRACT-003）
          final viewsData = data['views'] as Map<String, dynamic>?;
          if (viewsData != null) {
            _views = viewsData.map((k, v) => MapEntry(k, v as int));
            _presenceController.add(_views);
            notifyListeners();
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
          notifyListeners();
          unawaited(disconnect());
          break;
        case 'terminals_changed':
          // 跨平台终端变化通知
          debugPrint('[WebSocketService] received terminals_changed: action=${data['action']} terminal_id=${data['terminal_id']}');
          _terminalsChangedController.add(data);
          break;
        case 'device_kicked':
          debugPrint('[WebSocketService] received device_kicked: reason=${data['reason']}');
          _deviceKickedController.add(null);
          break;
      }
    } catch (e) {
      debugPrint('Error parsing message: $e');
    }
  }

  Uint8List base64Decode(String source) {
    return base64.decode(source);
  }

  /// 处理断开连接
  void _handleDisconnect() {
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

  /// 发送数据
  void send(String data) {
    if (_status != ConnectionStatus.connected || _channel == null) {
      return;
    }

    final message = jsonEncode({
      'type': 'data',
      'payload': base64Encode(utf8.encode(data)),
      'timestamp': DateTime.now().toUtc().toIso8601String(),
    });

    _channel!.sink.add(message);
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
        debugPrint('[WebSocketService] WS closed: code=$closeCode reason=$closeReason');
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

    final message = jsonEncode({
      'type': 'resize',
      'rows': rows,
      'cols': cols,
    });

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

    final delay = reconnectDelay * (1 << _retryCount);
    _retryCount++;

    _reconnectTimer?.cancel();
    _reconnectTimer = Timer(delay, () {
      connect();
    });
  }

  /// 断开连接
  Future<void> disconnect({bool notify = true}) async {
    _allowReconnect = false;
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
    _presenceController.close();
    _terminalsChangedController.close();
    _deviceKickedController.close();
    _tokenInvalidController.close();
    super.dispose();
  }
}
