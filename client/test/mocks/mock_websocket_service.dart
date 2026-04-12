import 'dart:async';
import 'package:flutter/foundation.dart';
import 'package:rc_client/services/websocket_service.dart';

/// Mock WebSocketService 用于测试
class MockWebSocketService extends ChangeNotifier implements WebSocketService {
  final List<String> sentMessages = [];
  int connectCallCount = 0;
  final StreamController<String> _outputController = StreamController<String>.broadcast();
  final StreamController<Map<String, int>> _presenceController = StreamController<Map<String, int>>.broadcast();
  final StreamController<Map<String, dynamic>> _terminalsChangedController =
      StreamController<Map<String, dynamic>>.broadcast();
  final StreamController<void> _deviceKickedController =
      StreamController<void>.broadcast();
  final StreamController<void> _tokenInvalidController =
      StreamController<void>.broadcast();

  ConnectionStatus _status = ConnectionStatus.disconnected;
  String? _errorMessage;
  bool _agentOnline = false;
  final String _sessionId = 'test-session-123';
  final String? _deviceId = 'device-1';
  final String? _terminalId = 'term-1';
  bool _deviceOnline = true;
  String? _terminalStatus = 'attached';
  Map<String, int> _views = {'mobile': 0, 'desktop': 0};
  int? _lastCloseCode;
  String? _lastCloseReason;

  @override
  final String serverUrl = 'ws://localhost:8765';

  @override
  final String token = 'test-token';

  @override
  final ViewType viewType = ViewType.mobile;

  @override
  final bool autoReconnect = true;

  @override
  final int maxRetries = 5;

  @override
  final Duration reconnectDelay = const Duration(seconds: 1);

  @override
  ConnectionStatus get status => _status;

  @override
  String? get errorMessage => _errorMessage;

  @override
  bool get agentOnline => _agentOnline;

  @override
  bool get deviceOnline => _deviceOnline;

  @override
  String get sessionId => _sessionId;

  @override
  String? get deviceId => _deviceId;

  @override
  String? get terminalId => _terminalId;

  @override
  String? get terminalStatus => _terminalStatus;

  @override
  bool get isConnected => _status == ConnectionStatus.connected;

  @override
  String get owner => 'test-owner';

  @override
  Map<String, int> get views => _views;

  @override
  Stream<String> get outputStream => _outputController.stream;

  @override
  Stream<Map<String, int>> get presenceStream => _presenceController.stream;

  @override
  Stream<Map<String, dynamic>> get terminalsChangedStream => _terminalsChangedController.stream;

  @override
  Stream<void> get deviceKickedStream => _deviceKickedController.stream;

  @override
  Stream<void> get tokenInvalidStream => _tokenInvalidController.stream;

  @override
  int? get lastCloseCode => _lastCloseCode;

  @override
  String? get lastCloseReason => _lastCloseReason;

  @override
  bool get isAuthFailed => _lastCloseCode == 4001 || _lastCloseCode == 4011;

  /// 模拟连接成功
  void simulateConnect({bool agentOnline = true}) {
    _status = ConnectionStatus.connected;
    _agentOnline = agentOnline;
    _errorMessage = null;
    notifyListeners();
  }

  /// 模拟断开连接
  void simulateDisconnect() {
    _status = ConnectionStatus.disconnected;
    _agentOnline = false;
    notifyListeners();
  }

  /// 模拟连接错误
  void simulateError(String message) {
    _status = ConnectionStatus.error;
    _errorMessage = message;
    notifyListeners();
  }

  /// 模拟重连中
  void simulateReconnecting() {
    _status = ConnectionStatus.reconnecting;
    notifyListeners();
  }

  /// 模拟接收终端输出
  void simulateOutput(String data) {
    _outputController.add(data);
  }

  /// 模拟 presence 更新
  void simulatePresence(Map<String, int> views) {
    _views = views;
    _presenceController.add(views);
  }

  /// 获取已发送的消息列表
  List<String> getSentMessages() => List.unmodifiable(sentMessages);

  /// 清空已发送消息
  void clearSentMessages() {
    sentMessages.clear();
  }

  @override
  Future<bool> connect() async {
    connectCallCount++;
    _status = ConnectionStatus.connecting;
    await Future.delayed(const Duration(milliseconds: 100));
    simulateConnect();
    return true;
  }

  @override
  Future<void> disconnect({bool notify = true}) async {
    _status = ConnectionStatus.disconnected;
    _agentOnline = false;
    if (notify) {
      notifyListeners();
    }
  }

  @override
  void send(String data) {
    sentMessages.add(data);
  }

  @override
  void resize(int rows, int cols) {
    // 模拟 resize
  }

  @override
  void sendLine(String data) {
    send('$data\r\n');
  }

  @override
  void sendKey(String key) {
    send(key);
  }

  @override
  Uint8List base64Decode(String source) {
    return Uint8List.fromList(source.codeUnits);
  }

  @override
  void dispose() {
    _outputController.close();
    _presenceController.close();
    _terminalsChangedController.close();
    _deviceKickedController.close();
    _tokenInvalidController.close();
    super.dispose();
  }
}
