import 'dart:io' show Platform;

import 'package:flutter/foundation.dart';

import '../models/config.dart';
import '../models/runtime_device.dart';
import '../models/runtime_terminal.dart';
import 'auth_service.dart';
import 'config_service.dart';
import 'runtime_device_service.dart';
import 'websocket_service.dart';

class RuntimeSelectionController extends ChangeNotifier {
  RuntimeSelectionController({
    required this.serverUrl,
    required this.token,
    required RuntimeDeviceService runtimeService,
    ConfigService? configService,
    List<RuntimeDevice> initialDevices = const <RuntimeDevice>[],
  })  : _runtimeService = runtimeService,
        _configService = configService ?? ConfigService(),
        _initialDevices = List<RuntimeDevice>.unmodifiable(initialDevices);

  final String serverUrl;
  final String token;
  final RuntimeDeviceService _runtimeService;
  final ConfigService _configService;
  final String? _localHostname = _resolveLocalHostname();
  final List<RuntimeDevice> _initialDevices;

  List<RuntimeDevice> _devices = const [];
  List<RuntimeTerminal> _terminals = const [];
  bool _loadingDevices = false;
  bool _loadingTerminals = false;
  bool _creatingTerminal = false;
  String? _errorMessage;
  AuthException? _authError;
  String? _selectedDeviceId;
  AppConfig _config = const AppConfig();

  List<RuntimeDevice> get devices => _devices;
  List<RuntimeTerminal> get terminals => _terminals;
  bool get loadingDevices => _loadingDevices;
  bool get loadingTerminals => _loadingTerminals;
  bool get creatingTerminal => _creatingTerminal;
  String? get errorMessage => _errorMessage;

  /// 401 认证错误（被踢/过期），UI 层据此弹窗并跳转登录页
  AuthException? get authError => _authError;
  String? get selectedDeviceId => _selectedDeviceId;

  RuntimeDevice? get selectedDevice {
    for (final device in _devices) {
      if (device.deviceId == _selectedDeviceId) {
        return device;
      }
    }
    return null;
  }

  bool get isDesktopPlatform => !(Platform.isAndroid || Platform.isIOS);

  bool get isLocalDeviceSelected =>
      isDesktopPlatform &&
      selectedDevice != null &&
      _matchesLocalDevice(selectedDevice!);

  Future<void> initialize() async {
    final config = await _configService.loadConfig();
    _config = config;
    _selectedDeviceId =
        config.preferredDeviceId.isEmpty ? null : config.preferredDeviceId;
    if (_initialDevices.isNotEmpty) {
      _devices = _initialDevices;
      final next = _selectedDeviceId;
      if (_devices.isEmpty) {
        _selectedDeviceId = null;
        _terminals = const [];
      } else if (next != null &&
          _devices.any((device) => device.deviceId == next)) {
        await selectDevice(next, notify: false);
      } else {
        await selectDevice(_resolveInitialDeviceId(_devices), notify: false);
      }
      notifyListeners();
      return;
    }
    await loadDevices();
  }

  Future<void> loadDevices() async {
    _loadingDevices = true;
    _errorMessage = null;
    _authError = null;
    notifyListeners();

    try {
      _devices = await _runtimeService.listDevices(token);
      final preferred = _selectedDeviceId;
      if (_devices.isEmpty) {
        _selectedDeviceId = null;
        _terminals = const [];
      } else if (preferred != null &&
          _devices.any((device) => device.deviceId == preferred)) {
        await selectDevice(preferred, notify: false);
      } else {
        final next = _resolveInitialDeviceId(_devices);
        await selectDevice(next, notify: false);
      }
    } catch (error) {
      _handleError(error);
    } finally {
      _loadingDevices = false;
      notifyListeners();
    }
  }

  Future<void> selectDevice(String deviceId, {bool notify = true}) async {
    _selectedDeviceId = deviceId;
    await _persistPreferredDevice(deviceId);
    await _loadTerminalsForDevice(deviceId, notify: notify);
  }

  /// 刷新当前设备的终端列表（用于跨平台同步等场景）
  ///
  /// 此方法会确保终端列表与服务器状态同步，适用于：
  /// - 收到其他平台的终端变化通知
  /// - 手动刷新终端列表
  /// - 重新连接后恢复状态
  ///
  /// [silent] 为 true 时不显示 loading 状态，避免 UI 闪烁
  Future<void> refreshTerminals({bool silent = false}) async {
    final deviceId = selectedDeviceId ?? _resolveInitialDeviceId(_devices);
    if (_devices.any((d) => d.deviceId == deviceId)) {
      await _loadTerminalsForDevice(deviceId, notify: true, silent: silent);
    }
  }

  Future<void> _loadTerminalsForDevice(String deviceId,
      {bool notify = true, bool silent = false}) async {
    // silent 模式下不设置 loading 状态，避免 UI 闪烁
    if (!silent) {
      _loadingTerminals = true;
      _errorMessage = null;
      if (notify) {
        notifyListeners();
      }
    }

    try {
      _terminals =
          _sortTerminals(await _runtimeService.listTerminals(token, deviceId));
      _syncSelectedDeviceTerminalCount();
    } catch (error) {
      _terminals = const [];
      _handleError(error);
    } finally {
      if (!silent) {
        _loadingTerminals = false;
      }
      notifyListeners();
    }
  }

  Future<RuntimeTerminal?> createTerminal({
    required String title,
    required String cwd,
    required String command,
  }) async {
    final device = selectedDevice;
    if (device == null) {
      _errorMessage = '请先选择设备';
      notifyListeners();
      return null;
    }
    if (!device.canCreateTerminal) {
      _errorMessage = device.agentOnline ? 'terminal 数量已达上限' : '电脑当前离线';
      notifyListeners();
      return null;
    }

    _creatingTerminal = true;
    _errorMessage = null;
    _authError = null;
    notifyListeners();
    try {
      final terminal = await _runtimeService.createTerminal(
        token,
        device.deviceId,
        title: title,
        cwd: cwd,
        command: command,
      );
      _terminals = _sortTerminals([..._terminals, terminal]);
      _syncSelectedDeviceTerminalCount();
      notifyListeners();
      return terminal;
    } catch (error) {
      _handleError(error);
      notifyListeners();
      return null;
    } finally {
      _creatingTerminal = false;
      notifyListeners();
    }
  }

  Future<RuntimeTerminal?> closeTerminal(String terminalId) async {
    final device = selectedDevice;
    if (device == null) {
      _errorMessage = '请先选择设备';
      notifyListeners();
      return null;
    }

    RuntimeTerminal? terminal;
    for (final item in _terminals) {
      if (item.terminalId == terminalId) {
        terminal = item;
        break;
      }
    }
    if (terminal == null) {
      _errorMessage = 'terminal 不存在';
      notifyListeners();
      return null;
    }
    _errorMessage = null;
    _authError = null;
    notifyListeners();
    try {
      final closed = await _runtimeService.closeTerminal(
          token, device.deviceId, terminalId);
      _terminals = _sortTerminals([
        for (final item in _terminals)
          if (item.terminalId == terminalId) closed else item,
      ]);
      _syncSelectedDeviceTerminalCount();
      notifyListeners();
      return closed;
    } catch (error) {
      _handleError(error);
      notifyListeners();
      return null;
    }
  }

  Future<RuntimeDevice?> updateSelectedDevice({
    required String name,
  }) async {
    final device = selectedDevice;
    if (device == null) {
      _errorMessage = '请先选择设备';
      notifyListeners();
      return null;
    }

    final trimmed = name.trim();
    if (trimmed.isEmpty) {
      _errorMessage = '设备名称不能为空';
      notifyListeners();
      return null;
    }
    _errorMessage = null;
    _authError = null;
    notifyListeners();
    try {
      final updated = await _runtimeService.updateDevice(
        token,
        device.deviceId,
        name: trimmed,
      );
      _devices = [
        for (final item in _devices)
          if (item.deviceId == updated.deviceId) updated else item,
      ];
      notifyListeners();
      return updated;
    } catch (error) {
      _handleError(error);
      notifyListeners();
      return null;
    }
  }

  Future<RuntimeTerminal?> renameTerminal(
      String terminalId, String title) async {
    final device = selectedDevice;
    if (device == null) {
      _errorMessage = '请先选择设备';
      notifyListeners();
      return null;
    }

    final trimmed = title.trim();
    if (trimmed.isEmpty) {
      _errorMessage = '终端标题不能为空';
      notifyListeners();
      return null;
    }

    _errorMessage = null;
    _authError = null;
    notifyListeners();
    try {
      final updated = await _runtimeService.updateTerminalTitle(
        token,
        device.deviceId,
        terminalId,
        trimmed,
      );
      _terminals = _sortTerminals([
        for (final item in _terminals)
          if (item.terminalId == terminalId) updated else item,
      ]);
      notifyListeners();
      return updated;
    } catch (error) {
      _handleError(error);
      notifyListeners();
      return null;
    }
  }

  WebSocketService buildTerminalService(RuntimeTerminal terminal) {
    final viewType = Platform.isIOS || Platform.isAndroid
        ? ViewType.mobile
        : ViewType.desktop;
    return WebSocketService(
      serverUrl: serverUrl,
      token: token,
      sessionId: '',
      deviceId: selectedDeviceId,
      terminalId: terminal.terminalId,
      viewType: viewType,
      autoReconnect: _config.autoReconnect,
      maxRetries: _config.maxRetries,
      reconnectDelay: _config.reconnectDelay,
    );
  }

  Future<void> _persistPreferredDevice(String deviceId) async {
    _config = _config.copyWith(preferredDeviceId: deviceId);
    await _configService.saveConfig(
      _config,
    );
  }

  List<RuntimeTerminal> _sortTerminals(List<RuntimeTerminal> terminals) {
    final sorted = terminals.toList();
    int rank(RuntimeTerminal terminal) {
      switch (terminal.status) {
        case 'attached':
          return 0;
        case 'detached':
          return 1;
        case 'pending':
          return 2;
        case 'closing':
          return 3;
        case 'closed':
          return 4;
        default:
          return 5;
      }
    }

    sorted.sort((a, b) {
      final statusCompare = rank(a).compareTo(rank(b));
      if (statusCompare != 0) return statusCompare;

      final aUpdated = a.updatedAt;
      final bUpdated = b.updatedAt;
      if (aUpdated != null && bUpdated != null) {
        final timeCompare = bUpdated.compareTo(aUpdated);
        if (timeCompare != 0) return timeCompare;
      } else if (aUpdated != null) {
        return -1;
      } else if (bUpdated != null) {
        return 1;
      }

      return a.title.compareTo(b.title);
    });
    return List.unmodifiable(sorted);
  }

  void _syncSelectedDeviceTerminalCount() {
    final selectedId = _selectedDeviceId;
    if (selectedId == null) {
      return;
    }

    final activeCount =
        _terminals.where((terminal) => terminal.status != 'closed').length;

    _devices = [
      for (final device in _devices)
        if (device.deviceId == selectedId)
          device.copyWith(activeTerminals: activeCount)
        else
          device,
    ];
  }

  String _resolveInitialDeviceId(List<RuntimeDevice> devices) {
    if (isDesktopPlatform) {
      final local = _findLocalDevice(devices);
      if (local != null) {
        return local.deviceId;
      }
    }

    final online = devices.where((device) => device.agentOnline).toList();
    return (online.isNotEmpty ? online.first : devices.first).deviceId;
  }

  RuntimeDevice? _findLocalDevice(List<RuntimeDevice> devices) {
    for (final device in devices) {
      if (_matchesLocalDevice(device)) {
        return device;
      }
    }
    return null;
  }

  bool _matchesLocalDevice(RuntimeDevice device) {
    final localHostname = _normalizeHost(_localHostname);
    if (localHostname == null) {
      return false;
    }

    final deviceHostname = _normalizeHost(device.hostname);
    if (deviceHostname != null && deviceHostname == localHostname) {
      return true;
    }

    final deviceName = _normalizeHost(device.name);
    return deviceName != null && deviceName == localHostname;
  }

  static String? _resolveLocalHostname() {
    if (Platform.isAndroid || Platform.isIOS) {
      return null;
    }
    try {
      return Platform.localHostname;
    } catch (_) {
      return null;
    }
  }

  static String? _normalizeHost(String? value) {
    final trimmed = (value ?? '').trim().toLowerCase();
    if (trimmed.isEmpty) {
      return null;
    }
    return trimmed;
  }

  /// 统一错误处理：AuthException 设置 _authError，其他设置 _errorMessage
  void _handleError(Object error) {
    if (error is AuthException) {
      _authError = error;
      _errorMessage = null;
    } else {
      _authError = null;
      _errorMessage = error.toString().replaceFirst('Exception: ', '');
    }
  }
}
