import 'dart:io' show Platform;

import 'package:flutter/foundation.dart';

import '../models/assistant_plan.dart';
import '../models/command_sequence_draft.dart';
import '../models/config.dart';
import '../models/project_context_settings.dart';
import '../models/project_context_snapshot.dart';
import '../models/recent_launch_context.dart';
import '../models/runtime_device.dart';
import '../models/runtime_terminal.dart';
import '../models/terminal_launch_plan.dart';
import 'auth_service.dart';
import 'config_service.dart';
import 'planner_provider.dart';
import 'runtime_device_service.dart';
import 'terminal_launch_plan_service.dart';
import 'websocket_service.dart';

class RuntimeSelectionController extends ChangeNotifier {
  RuntimeSelectionController({
    required this.serverUrl,
    required this.token,
    required RuntimeDeviceService runtimeService,
    ConfigService? configService,
    TerminalLaunchPlanService? terminalLaunchPlanService,
    List<RuntimeDevice> initialDevices = const <RuntimeDevice>[],
  })  : _runtimeService = runtimeService,
        _configService = configService ?? ConfigService(),
        _terminalLaunchPlanService =
            terminalLaunchPlanService ?? TerminalLaunchPlanService(),
        _initialDevices = List<RuntimeDevice>.unmodifiable(initialDevices);

  final String serverUrl;
  final String token;
  final RuntimeDeviceService _runtimeService;
  final ConfigService _configService;
  final TerminalLaunchPlanService _terminalLaunchPlanService;
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
  ProjectContextSettings? _projectContextSettings;
  DeviceProjectContextSnapshot? _projectContextSnapshot;
  bool _loadingProjectContextSettings = false;
  bool _savingProjectContextSettings = false;
  bool _loadingProjectContextSnapshot = false;

  List<RuntimeDevice> get devices => _devices;
  List<RuntimeTerminal> get terminals => _terminals;
  bool get loadingDevices => _loadingDevices;
  bool get loadingTerminals => _loadingTerminals;
  bool get creatingTerminal => _creatingTerminal;
  String? get errorMessage => _errorMessage;

  /// 401 认证错误（被踢/过期），UI 层据此弹窗并跳转登录页
  AuthException? get authError => _authError;
  String? get selectedDeviceId => _selectedDeviceId;
  ProjectContextSettings? get projectContextSettings => _projectContextSettings;
  DeviceProjectContextSnapshot? get projectContextSnapshot =>
      _projectContextSnapshot;
  bool get loadingProjectContextSettings => _loadingProjectContextSettings;
  bool get savingProjectContextSettings => _savingProjectContextSettings;
  bool get loadingProjectContextSnapshot => _loadingProjectContextSnapshot;
  RecentLaunchContext? get recentLaunchContextForSelectedDevice {
    final deviceId = _selectedDeviceId;
    if (deviceId == null || deviceId.isEmpty) {
      return null;
    }
    return _config.recentLaunchContexts[deviceId];
  }

  List<TerminalLaunchPlan> get recommendedLaunchPlans =>
      _terminalLaunchPlanService.buildRecommendedPlans(
        deviceId: _selectedDeviceId,
        terminals: _terminals,
        recentContext: recentLaunchContextForSelectedDevice,
        projectContextSnapshot: _projectContextSnapshot,
      );

  Future<PlannerResolutionResult> resolveLaunchIntent(
    String intent, {
    String? conversationId,
    String? messageId,
    void Function(AssistantPlanProgressEvent event)? onProgress,
  }) async {
    final deviceId = _selectedDeviceId;
    if (deviceId != null &&
        (_projectContextSettings == null ||
            _projectContextSettings!.deviceId != deviceId)) {
      await loadProjectContextSettings();
    }

    if (deviceId == null || !_shouldUseServicePlanner()) {
      return _terminalLaunchPlanService.resolveIntent(
        intent: intent,
        deviceId: deviceId,
        terminals: _terminals,
        recentContext: recentLaunchContextForSelectedDevice,
        projectContextSnapshot: _projectContextSnapshot,
        projectContextSettings: _projectContextSettings,
      );
    }

    try {
      final resolvedConversationId =
          conversationId ?? _buildAssistantConversationId(deviceId);
      final resolvedMessageId = messageId ?? _buildAssistantMessageId();
      final remotePlan = onProgress == null
          ? await _runtimeService.createAssistantPlan(
              token,
              deviceId,
              intent: intent,
              conversationId: resolvedConversationId,
              messageId: resolvedMessageId,
            )
          : await _runtimeService.createAssistantPlanStream(
              token,
              deviceId,
              intent: intent,
              conversationId: resolvedConversationId,
              messageId: resolvedMessageId,
              onProgress: onProgress,
            );
      return _resolutionFromAssistantPlan(
        remotePlan,
        intent: intent,
      );
    } on AuthException {
      rethrow;
    } catch (error) {
      final localResult = await _terminalLaunchPlanService.resolveIntent(
        intent: intent,
        deviceId: deviceId,
        terminals: _terminals,
        recentContext: recentLaunchContextForSelectedDevice,
        projectContextSnapshot: _projectContextSnapshot,
        projectContextSettings: _projectContextSettings,
      );
      final fallbackReason = _assistantFallbackReason(error);
      return localResult.copyWith(
        fallbackUsed: true,
        fallbackReason: fallbackReason,
        reasoningKind:
            localResult.provider == 'local_rules' ? 'fallback' : 'claude_cli',
      );
    }
  }

  Future<TerminalLaunchPlan> resolveLaunchPlanFromIntent(String intent) async {
    final result = await resolveLaunchIntent(intent);
    return result.plan;
  }

  TerminalLaunchPlan normalizeLaunchPlan(TerminalLaunchPlan plan) {
    return _terminalLaunchPlanService.normalizePlan(plan);
  }

  TerminalLaunchPlan finalizeLaunchPlan(TerminalLaunchPlan plan) {
    return _terminalLaunchPlanService.finalizePlan(
      plan: plan,
      deviceId: _selectedDeviceId,
      projectContextSnapshot: _projectContextSnapshot,
    );
  }

  ProjectContextCandidate? resolveCandidateForCwd(String? cwd) {
    return _terminalLaunchPlanService.resolveCandidateForCwd(
      deviceId: _selectedDeviceId,
      projectContextSnapshot: _projectContextSnapshot,
      cwd: cwd,
    );
  }

  bool requiresManualConfirmationForCwd(
    String cwd, {
    String? currentCwd,
    bool currentRequiresManualConfirmation = false,
  }) {
    return _terminalLaunchPlanService.requiresManualConfirmationForCwd(
      cwd: cwd,
      deviceId: _selectedDeviceId,
      projectContextSnapshot: _projectContextSnapshot,
      currentCwd: currentCwd,
      currentRequiresManualConfirmation: currentRequiresManualConfirmation,
    );
  }

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
    _projectContextSnapshot = _selectedDeviceId == null
        ? null
        : config.projectContextSnapshots[_selectedDeviceId];
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
    _projectContextSettings = null;
    _projectContextSnapshot = _config.projectContextSnapshots[deviceId];
    await _persistPreferredDevice(deviceId);
    await _loadTerminalsForDevice(deviceId, notify: notify);
    await loadProjectContextSnapshot(forceRefresh: true, notify: notify);
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

  Future<void> rememberSuccessfulLaunchPlan(TerminalLaunchPlan plan) async {
    final deviceId = _selectedDeviceId;
    if (deviceId == null || deviceId.isEmpty) {
      return;
    }

    final contexts = Map<String, RecentLaunchContext>.from(
      _config.recentLaunchContexts,
    );
    contexts[deviceId] = _terminalLaunchPlanService.buildRecentLaunchContext(
      deviceId: deviceId,
      plan: plan,
    );
    _config = _config.copyWith(recentLaunchContexts: contexts);
    await _configService.saveConfig(_config);
    notifyListeners();
  }

  Future<DeviceProjectContextSnapshot?> loadProjectContextSnapshot({
    bool forceRefresh = false,
    bool notify = true,
  }) async {
    final deviceId = _selectedDeviceId;
    if (deviceId == null || deviceId.isEmpty) {
      return null;
    }
    if (!forceRefresh && _projectContextSnapshot?.deviceId == deviceId) {
      return _projectContextSnapshot;
    }

    _loadingProjectContextSnapshot = true;
    if (notify) {
      notifyListeners();
    }
    try {
      final snapshot = await _runtimeService.getProjectContextSnapshot(
        token,
        deviceId,
      );
      await _persistProjectContextSnapshot(snapshot);
      return snapshot;
    } catch (_) {
      _projectContextSnapshot = _config.projectContextSnapshots[deviceId];
      return _projectContextSnapshot;
    } finally {
      _loadingProjectContextSnapshot = false;
      if (notify) {
        notifyListeners();
      }
    }
  }

  Future<DeviceProjectContextSnapshot?> refreshProjectContextSnapshot({
    bool notify = true,
  }) async {
    final deviceId = _selectedDeviceId;
    if (deviceId == null || deviceId.isEmpty) {
      return null;
    }
    _loadingProjectContextSnapshot = true;
    if (notify) {
      notifyListeners();
    }
    try {
      final snapshot = await _runtimeService.refreshProjectContextSnapshot(
        token,
        deviceId,
      );
      await _persistProjectContextSnapshot(snapshot);
      return snapshot;
    } catch (_) {
      return _projectContextSnapshot;
    } finally {
      _loadingProjectContextSnapshot = false;
      if (notify) {
        notifyListeners();
      }
    }
  }

  Future<ProjectContextSettings?> loadProjectContextSettings({
    bool forceRefresh = false,
  }) async {
    final deviceId = _selectedDeviceId;
    if (deviceId == null || deviceId.isEmpty) {
      _errorMessage = '请先选择设备';
      notifyListeners();
      return null;
    }
    if (!forceRefresh && _projectContextSettings?.deviceId == deviceId) {
      return _projectContextSettings;
    }

    _loadingProjectContextSettings = true;
    _errorMessage = null;
    _authError = null;
    notifyListeners();
    try {
      final settings = await _runtimeService.getProjectContextSettings(
        token,
        deviceId,
      );
      _projectContextSettings = settings;
      return settings;
    } catch (error) {
      _handleError(error);
      return null;
    } finally {
      _loadingProjectContextSettings = false;
      notifyListeners();
    }
  }

  Future<ProjectContextSettings?> updateProjectContextSettings(
    ProjectContextSettings settings,
  ) async {
    final deviceId = _selectedDeviceId;
    if (deviceId == null || deviceId.isEmpty) {
      _errorMessage = '请先选择设备';
      notifyListeners();
      return null;
    }

    _savingProjectContextSettings = true;
    _errorMessage = null;
    _authError = null;
    notifyListeners();
    try {
      final saved = await _runtimeService.saveProjectContextSettings(
        token,
        deviceId,
        settings.copyWith(deviceId: deviceId),
      );
      _projectContextSettings = saved;
      await refreshProjectContextSnapshot(notify: false);
      return saved;
    } catch (error) {
      _handleError(error);
      return null;
    } finally {
      _savingProjectContextSettings = false;
      notifyListeners();
    }
  }

  Future<void> _persistProjectContextSnapshot(
    DeviceProjectContextSnapshot snapshot,
  ) async {
    final snapshots = Map<String, DeviceProjectContextSnapshot>.from(
      _config.projectContextSnapshots,
    );
    snapshots[snapshot.deviceId] = snapshot;
    _projectContextSnapshot = snapshot;
    _config = _config.copyWith(projectContextSnapshots: snapshots);
    await _configService.saveConfig(_config);
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

  bool _shouldUseServicePlanner() {
    final config = _projectContextSettings?.plannerConfig;
    return config?.llmEnabled ?? true;
  }

  PlannerResolutionResult _resolutionFromAssistantPlan(
    AssistantPlanResult remotePlan, {
    required String intent,
  }) {
    final sequence = CommandSequenceDraft.fromAssistantCommandSequence(
      summary: remotePlan.commandSequence.summary,
      provider: remotePlan.commandSequence.provider,
      source: remotePlan.commandSequence.source,
      steps: remotePlan.commandSequence.steps,
      matchedCwd: remotePlan.evaluationContext['matched_cwd'] as String?,
      matchedLabel: remotePlan.evaluationContext['matched_label'] as String?,
      intent: PlannerIntentUtils.normalizeIntent(intent),
      needConfirm: remotePlan.commandSequence.needConfirm,
      conversationId: remotePlan.conversationId,
      messageId: remotePlan.messageId,
    );
    final plan = normalizeLaunchPlan(
      sequence.toLaunchPlan().copyWith(
            source: TerminalLaunchPlanSource.intent,
            intent: PlannerIntentUtils.normalizeIntent(intent),
            requiresManualConfirmation: sequence.requiresManualConfirmation,
          ),
    );
    return PlannerResolutionResult(
      provider: remotePlan.commandSequence.provider,
      plan: plan,
      sequence: sequence,
      matchedCandidateId:
          remotePlan.evaluationContext['matched_candidate_id'] as String?,
      reasoningKind: 'service_llm',
      fallbackUsed: remotePlan.fallbackUsed,
      fallbackReason: remotePlan.fallbackReason,
      assistantMessages: remotePlan.assistantMessages,
      trace: remotePlan.trace,
      conversationId: remotePlan.conversationId,
      messageId: remotePlan.messageId,
      limits: remotePlan.limits,
      evaluationContext: remotePlan.evaluationContext,
    );
  }

  Future<void> reportAssistantExecution({
    required CommandSequenceDraft draft,
    required String executionStatus,
    String? terminalId,
    String? failedStepId,
    String? outputSummary,
  }) async {
    final deviceId = _selectedDeviceId;
    final conversationId = draft.assistantConversationId;
    final messageId = draft.assistantMessageId;
    if (deviceId == null ||
        deviceId.isEmpty ||
        conversationId == null ||
        conversationId.isEmpty ||
        messageId == null ||
        messageId.isEmpty) {
      return;
    }

    try {
      await _runtimeService.reportAssistantExecution(
        token,
        deviceId,
        conversationId: conversationId,
        messageId: messageId,
        terminalId: terminalId,
        executionStatus: executionStatus,
        failedStepId: failedStepId,
        outputSummary: outputSummary,
        commandSequence: draft.toAssistantCommandSequence(),
      );
    } on AuthException {
      rethrow;
    } catch (_) {
      // 执行结果同步失败不影响本地终端进入，只在后续 UI 版本再做显式状态提示。
    }
  }

  static String _buildAssistantConversationId(String deviceId) {
    final normalizedDeviceId =
        deviceId.replaceAll(RegExp(r'[^A-Za-z0-9_-]'), '-');
    return 'assistant-$normalizedDeviceId';
  }

  static String _buildAssistantMessageId() =>
      'msg-${DateTime.now().microsecondsSinceEpoch}';

  static String _assistantFallbackReason(Object error) {
    if (error is RuntimeApiException) {
      final reason = error.reason?.trim();
      if (reason != null && reason.isNotEmpty) {
        return reason;
      }
    }
    return 'service_llm_unavailable';
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
