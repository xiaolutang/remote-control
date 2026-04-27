import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:xterm/xterm.dart';

import '../models/shortcut_item.dart';
import '../models/terminal_shortcut.dart';
import '../services/logout_helper.dart';
import '../services/runtime_device_service.dart';
import '../services/shortcut_config_service.dart';
import '../services/terminal_session_manager.dart';
import '../services/websocket_service.dart';
import 'login_screen.dart';

/// TerminalScreen 的非 UI 逻辑控制器。
///
/// 管理 WebSocket 绑定、协议事件路由、连接生命周期、认证/错误处理、
/// 以及快捷键配置。UI 层（_TerminalScreenState）仅负责 build 方法。
class TerminalScreenController extends ChangeNotifier {
  TerminalScreenController({
    required TargetPlatform Function() platformGetter,
  }) : _platformGetter = platformGetter;

  final TargetPlatform Function() _platformGetter;

  // ─── 公开只读状态 ────────────────────────────────────────────

  Terminal? _terminal;
  Terminal? get terminal => _terminal;

  WebSocketService? _webSocketService;
  WebSocketService? get webSocketService => _webSocketService;

  bool _showErrorBanner = false;
  bool get showErrorBanner => _showErrorBanner;

  bool _authDialogShowing = false;
  bool get authDialogShowing => _authDialogShowing;

  Map<String, int> _views = {'mobile': 0, 'desktop': 0};
  Map<String, int> get views => Map.unmodifiable(_views);

  ShortcutLayout _shortcutLayout =
      const ShortcutLayout(coreItems: [], smartItems: []);
  ShortcutLayout get shortcutLayout => _shortcutLayout;

  ValueListenable<String>? _terminalOutputText;
  ValueListenable<String>? get terminalOutputText => _terminalOutputText;

  final ValueNotifier<String> _localTerminalOutputText =
      ValueNotifier<String>('');
  ValueNotifier<String> get localTerminalOutputText =>
      _localTerminalOutputText;

  ValueListenable<String> get outputListenable =>
      _terminalOutputText ?? _localTerminalOutputText;

  /// 是否是移动端平台
  bool get isMobilePlatform {
    if (kIsWeb) return false;
    final platform = _platformGetter();
    return platform == TargetPlatform.android ||
        platform == TargetPlatform.iOS;
  }

  // ─── 内部状态 ──────────────────────────────────────────────────

  final TerminalController _terminalController = TerminalController();
  TerminalController get terminalController => _terminalController;

  StreamSubscription<TerminalProtocolEvent>? _eventSubscription;
  StreamSubscription<void>? _deviceKickedSubscription;
  StreamSubscription<void>? _tokenInvalidSubscription;

  late final ShortcutConfigService _shortcutConfigService =
      ShortcutConfigService();

  static const String _shortcutProfileId =
      TerminalShortcutProfile.claudeCodeId;
  static const String _defaultProjectId = 'current-project';

  TerminalShortcutProfile get _shortcutProfile =>
      TerminalShortcutProfile.fromId(_shortcutProfileId);

  // ─── Session 绑定 ──────────────────────────────────────────────

  /// 绑定 WebSocketService 到终端。
  ///
  /// 如果 terminalId 非空，走 TerminalSessionManager coordinator 路径；
  /// 否则走本地终端路径（非协调模式）。
  void bindSession(
    WebSocketService service,
    TerminalSessionManager sessionManager,
  ) {
    if (identical(_webSocketService, service) && _terminal != null) {
      return;
    }

    _detachServiceBindings();
    _webSocketService = service;

    final terminalId = service.terminalId;
    if ((terminalId ?? '').isNotEmpty) {
      // F074: 通过 coordinator API 获取 RendererAdapter
      final adapter = sessionManager.getRendererAdapter(
        service.deviceId,
        terminalId!,
      );
      if (adapter != null) {
        _terminal = adapter.terminalForView;
        _terminalOutputText = adapter.outputText;
        sessionManager.bindTerminalOutput(
          service.deviceId,
          terminalId,
          sessionManager.getOrCreate(
            service.deviceId,
            terminalId,
            () => service,
          ),
        );
        _configureTerminalCallbacks(service, adapter.terminalForView);
      } else {
        final adapter = sessionManager.ensureRendererAdapter(
          service.deviceId,
          terminalId,
          () => Terminal(maxLines: 10000),
          service: service,
        );
        _terminal = adapter.terminalForView;
        _terminalOutputText = adapter.outputText;
        _configureTerminalCallbacks(service, _terminal!);
      }
    } else {
      _terminal ??= Terminal(maxLines: 10000);
      _terminalOutputText = _localTerminalOutputText;
      _configureTerminalCallbacks(service, _terminal!);
    }

    service.addListener(_onStatusChanged);
    _eventSubscription = service.eventStream.listen(
      _onProtocolEvent,
      onError: _onOutputError,
    );
    _deviceKickedSubscription =
        service.deviceKickedStream.listen((_) => _onDeviceKicked());
    _tokenInvalidSubscription =
        service.tokenInvalidStream.listen((_) => _onTokenInvalid());
    _views = Map<String, int>.from(service.views);

    notifyListeners();
  }

  /// 配置终端的 input/resize 回调
  void _configureTerminalCallbacks(
    WebSocketService service,
    Terminal terminal,
  ) {
    terminal.onResize = (width, height, pixelWidth, pixelHeight) {
      if (_shouldFollowSharedPty(service)) {
        return;
      }
      service.resize(height, width);
    };
  }

  void _detachServiceBindings() {
    if (_webSocketService != null) {
      _webSocketService!.removeListener(_onStatusChanged);
    }
    _eventSubscription?.cancel();
    _eventSubscription = null;
    _deviceKickedSubscription?.cancel();
    _deviceKickedSubscription = null;
    _tokenInvalidSubscription?.cancel();
    _tokenInvalidSubscription = null;
  }

  // ─── 连接管理 ──────────────────────────────────────────────────

  Future<void> connectToServer(
    WebSocketService service,
    TerminalSessionManager sessionManager,
    VoidCallback? onFocusRequest,
  ) async {
    final terminalId = service.terminalId;
    if ((terminalId ?? '').isNotEmpty) {
      await sessionManager.deactivateConflictingTerminalSessions(service);
      await sessionManager.connectTerminal(service.deviceId, terminalId!);
    } else {
      await service.connect();
    }

    if (!isMobilePlatform && identical(_webSocketService, service)) {
      onFocusRequest?.call();
    }
  }

  Future<void> loadPresenceSnapshot(WebSocketService service) async {
    final deviceId = service.deviceId;
    final terminalId = service.terminalId;
    if ((deviceId ?? '').isEmpty || (terminalId ?? '').isEmpty) {
      return;
    }

    try {
      final runtimeService = RuntimeDeviceService(serverUrl: service.serverUrl);
      final terminal = await runtimeService.getTerminal(
        service.token,
        deviceId!,
        terminalId!,
      );
      if (terminal == null || !identical(_webSocketService, service)) {
        return;
      }
      _views = terminal.views;
      notifyListeners();
    } catch (_) {
      // 进入页时以后端快照兜底，不影响主连接流程。
    }
  }

  Future<void> retryConnection(TerminalSessionManager sessionManager) async {
    final service = _webSocketService;
    if (service == null) return;
    final terminalId = service.terminalId;
    if ((terminalId ?? '').isNotEmpty) {
      await sessionManager.reconnectTerminal(service.deviceId, terminalId!);
    } else {
      await service.connect();
    }
  }

  // ─── 协议事件处理 ──────────────────────────────────────────────

  void _onProtocolEvent(TerminalProtocolEvent event) {
    switch (event.kind) {
      case TerminalProtocolEventKind.presence:
        final views = event.views;
        if (views != null) {
          _views = views;
          notifyListeners();
        }
        break;
      case TerminalProtocolEventKind.output:
      case TerminalProtocolEventKind.snapshot:
      case TerminalProtocolEventKind.snapshotChunk:
        final service = _webSocketService;
        if (service != null &&
            (service.terminalId ?? '').isEmpty &&
            event.payload != null) {
          _onLocalOutput(event.payload!);
        }
        break;
      case TerminalProtocolEventKind.connected:
      case TerminalProtocolEventKind.snapshotComplete:
      case TerminalProtocolEventKind.resize:
      case TerminalProtocolEventKind.closed:
        break;
    }
  }

  void _onLocalOutput(String data) {
    _terminal?.write(data);
    _updateLocalOutputBuffer(data);
  }

  /// 更新输出缓冲区（用于 TUI 选择器）
  void _updateLocalOutputBuffer(String data) {
    final lines = data.split('\n');
    bool changed = false;
    for (final line in lines) {
      if (line.isNotEmpty) {
        _localOutputBuffer.add(line);
        if (_localOutputBuffer.length > _maxBufferLines) {
          _localOutputBuffer.removeAt(0);
        }
        changed = true;
      }
    }
    if (changed) {
      _localTerminalOutputText.value = _localOutputBuffer.join('\n');
    }
  }

  final List<String> _localOutputBuffer = [];
  static const int _maxBufferLines = 50;

  // ─── 状态变更监听 ──────────────────────────────────────────────

  void _onStatusChanged() {
    final service = _webSocketService;
    if (service == null) return;

    if (service.status == ConnectionStatus.error) {
      _showErrorBanner = true;
      notifyListeners();
    } else if (service.status == ConnectionStatus.connected) {
      _showErrorBanner = false;
      _views = Map<String, int>.from(service.views);
      notifyListeners();
    }

    // 检查 WS close code 4011（被新设备替换）
    if (service.status == ConnectionStatus.disconnected &&
        service.lastCloseCode == 4011) {
      _onDeviceKicked();
      return;
    }

    // 认证失败通过 close code 判断
    if (service.isAuthFailed) {
      _handleTokenExpired();
    }
  }

  void _onOutputError(dynamic error) {
    _showErrorBanner = true;
    notifyListeners();
  }

  // ─── Geometry owner 策略 ──────────────────────────────────────

  bool _shouldFollowSharedPty(WebSocketService service) {
    if ((service.terminalId ?? '').isNotEmpty &&
        service.status != ConnectionStatus.connected) {
      return true;
    }

    final terminalId = service.terminalId;
    if ((terminalId ?? '').isEmpty) {
      return false;
    }

    final geometryOwnerView = service.geometryOwnerView;
    if (geometryOwnerView == null) {
      return false;
    }

    return !service.isGeometryOwner;
  }

  bool shouldAutoResize(WebSocketService service) {
    return !_shouldFollowSharedPty(service);
  }

  // ─── 认证/踢出处理 ─────────────────────────────────────────────

  /// 被新设备踢出（close code 4011 或 device_kicked 消息）
  void _onDeviceKicked() {
    if (_authDialogShowing) return;
    _authDialogShowing = true;
    notifyListeners();
    // UI 层负责弹窗展示，通过 [authDialogShowing] 和 [authEventType] 驱动
  }

  void _onTokenInvalid() {
    if (_authDialogShowing) return;
    _handleTokenExpired();
  }

  void _handleTokenExpired() {
    if (_authDialogShowing) return;
    _authDialogShowing = true;
    notifyListeners();
  }

  /// 标记认证对话框已关闭（UI 层在关闭弹窗时调用）
  void clearAuthDialog() {
    _authDialogShowing = false;
  }

  /// 当前是否处于 device_kicked 状态（4011 close code）
  bool get isDeviceKicked {
    final service = _webSocketService;
    return service != null &&
        service.status == ConnectionStatus.disconnected &&
        service.lastCloseCode == 4011;
  }

  /// 处理 device_kicked 确认操作（UI 层在弹窗确定按钮调用）
  Future<void> confirmDeviceKicked(
    BuildContext context,
    TerminalSessionManager sessionManager,
  ) async {
    clearAuthDialog();
    await sessionManager.disconnectAll();
    if (!context.mounted) return;
    Navigator.of(context).pushAndRemoveUntil(
      MaterialPageRoute(
        builder: (_) => const LoginScreen(),
      ),
      (_) => false,
    );
  }

  /// 处理 token 过期确认操作（UI 层在弹窗确定按钮调用）
  Future<void> confirmTokenExpired(BuildContext context) async {
    clearAuthDialog();
    await logoutAndNavigate(
      context: context,
      destinationBuilder: (_) => const LoginScreen(),
    );
  }

  // ─── 快捷键管理 ────────────────────────────────────────────────

  Future<void> loadShortcutItems() async {
    final navigationMode =
        await _shortcutConfigService.loadClaudeNavigationMode();
    final baseItems = _shortcutProfile
        .shortcutsForNavigationMode(navigationMode)
        .asMap()
        .entries
        .map(
          (entry) => ShortcutItem.fromTerminalShortcut(
            entry.value,
            order: entry.key + 1,
          ),
        )
        .toList(growable: false);

    final configuredItems =
        await _shortcutConfigService.loadCombinedShortcutItems(
      projectId: _defaultProjectId,
    );
    final allItems = [...baseItems, ...configuredItems];

    _shortcutLayout = ShortcutItemSorter.partitionAndSort(allItems);
    notifyListeners();
  }

  void sendSpecialKey(String key) {
    _webSocketService?.send(key);
  }

  Future<void> handleShortcutPressed(ShortcutItem item) async {
    final payload = item.action.toTerminalPayload();
    if (payload.isEmpty) return;
    sendSpecialKey(payload);
    if (!item.isCore) {
      await _shortcutConfigService.updateShortcutItem(item.markUsed());
      await loadShortcutItems();
    }
  }

  ShortcutConfigService get shortcutConfigService => _shortcutConfigService;
  String get defaultProjectId => _defaultProjectId;

  List<ShortcutItem> sortShortcutItems(Iterable<ShortcutItem> items) {
    final sorted = items.toList(growable: false).toList();
    sorted.sort((a, b) {
      final byOrder = a.order.compareTo(b.order);
      if (byOrder != 0) return byOrder;
      return a.label.compareTo(b.label);
    });
    return sorted;
  }

  List<ShortcutItem> normalizeShortcutOrder(List<ShortcutItem> items) {
    return [
      for (var i = 0; i < items.length; i++)
        items[i].copyWith(order: i + 1),
    ];
  }

  // ─── 错误消息 ──────────────────────────────────────────────────

  String getErrorMessage(WebSocketService service) {
    final error = service.errorMessage ?? '连接失败';
    if (error.contains('Connection refused') || error.contains('refused')) {
      return '无法连接到服务器，请检查服务器是否启动';
    }
    if (error.contains('timeout') || error.contains('Timeout')) {
      return '连接超时，请检查网络';
    }
    if (error.contains('4503') || error.contains('Agent not connected')) {
      return '被控设备未连接，请先启动被控端 Agent';
    }
    if (error.contains('401') || error.contains('403')) {
      return '认证失败，请重新登录';
    }
    return '连接失败: $error';
  }

  // ─── 生命周期 ──────────────────────────────────────────────────

  @override
  void dispose() {
    _detachServiceBindings();
    _localTerminalOutputText.dispose();
    super.dispose();
  }
}
