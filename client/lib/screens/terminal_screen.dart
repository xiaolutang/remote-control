import 'dart:async';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:xterm/xterm.dart';

import '../models/shortcut_item.dart';
import '../models/terminal_shortcut.dart';
import '../services/auth_service.dart';
import '../services/config_service.dart';
import '../services/logout_helper.dart';
import '../services/runtime_device_service.dart';
import '../services/shortcut_config_service.dart';
import '../services/terminal_session_manager.dart';
import '../services/ui_helpers.dart';
import '../services/websocket_service.dart';
import '../widgets/terminal_shortcut_bar.dart';
import '../widgets/tui_selector.dart';
import 'login_screen.dart';
import 'user_profile_screen.dart';

/// 终端屏幕
class TerminalScreen extends StatefulWidget {
  const TerminalScreen({
    super.key,
    this.platformOverride,
    this.embedded = false,
  });

  final TargetPlatform? platformOverride;
  final bool embedded;

  @override
  State<TerminalScreen> createState() => _TerminalScreenState();
}

class _TerminalScreenState extends State<TerminalScreen> {
  Terminal? _terminal;
  WebSocketService? _webSocketService;
  late final ShortcutConfigService _shortcutConfigService;
  final TerminalController _terminalController = TerminalController();
  final FocusNode _terminalFocusNode = FocusNode();
  final ValueNotifier<String> _localTerminalOutputText =
      ValueNotifier<String>('');
  ValueListenable<String>? _terminalOutputText;

  StreamSubscription<String>? _outputSubscription;
  StreamSubscription<Map<String, int>>? _presenceSubscription;
  StreamSubscription<void>? _deviceKickedSubscription;
  StreamSubscription<void>? _tokenInvalidSubscription;
  bool _showErrorBanner = false;
  bool _authDialogShowing = false;
  Map<String, int> _views = {'mobile': 0, 'desktop': 0};
  ShortcutLayout _shortcutLayout =
      const ShortcutLayout(coreItems: [], smartItems: []);

  /// 终端输出缓冲区，用于 TUI 选择器解析
  /// 保留最近 50 行输出
  final List<String> _localOutputBuffer = [];
  static const int _maxBufferLines = 50;
  static const String _shortcutProfileId = TerminalShortcutProfile.claudeCodeId;
  static const String _defaultProjectId = 'current-project';

  /// 是否是移动端平台
  bool get _isMobilePlatform {
    if (kIsWeb) return false;
    final platform = widget.platformOverride ?? defaultTargetPlatform;
    return platform == TargetPlatform.android || platform == TargetPlatform.iOS;
  }

  // TODO(F072): 迁入 TerminalSessionCoordinator，UI 层不应承载 geometry owner 策略
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

  bool _shouldAutoResize(WebSocketService service) {
    return !_shouldFollowSharedPty(service);
  }

  TerminalShortcutProfile get _shortcutProfile =>
      TerminalShortcutProfile.fromId(_shortcutProfileId);

  @override
  void initState() {
    super.initState();
    _shortcutConfigService = ShortcutConfigService();
    _loadShortcutItems();
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    _bindSession(context.read<WebSocketService>());
  }

  Terminal get _activeTerminal => _terminal!;
  WebSocketService get _activeService => _webSocketService!;
  ValueListenable<String> get _terminalOutputListenable =>
      _terminalOutputText ?? _localTerminalOutputText;

  void _bindSession(WebSocketService service) {
    if (identical(_webSocketService, service) && _terminal != null) {
      return;
    }

    _detachServiceBindings();
    _webSocketService = service;

    final terminalId = service.terminalId;
    if ((terminalId ?? '').isNotEmpty) {
      final sessionManager = context.read<TerminalSessionManager>();
      _terminal = sessionManager.getOrCreateTerminal(
        service.deviceId,
        terminalId!,
        () => Terminal(maxLines: 10000),
        service: service,
      );
      _terminalOutputText = sessionManager.getTerminalOutputListenable(
        service.deviceId,
        terminalId,
      );
    } else {
      _terminal ??= Terminal(maxLines: 10000);
      _terminalOutputText = _localTerminalOutputText;
      _outputSubscription =
          service.outputStream.listen(_onOutput, onError: _onOutputError);
    }

    _configureTerminalCallbacks(service);
    service.addListener(_onStatusChanged);
    _presenceSubscription = service.presenceStream.listen(_onPresence);
    _deviceKickedSubscription =
        service.deviceKickedStream.listen((_) => _onDeviceKicked());
    _tokenInvalidSubscription =
        service.tokenInvalidStream.listen((_) => _onTokenInvalid());
    _views = Map<String, int>.from(service.views);

    unawaited(_connectToServer(service));
    unawaited(_loadPresenceSnapshot(service));
  }

  void _configureTerminalCallbacks(WebSocketService service) {
    _activeTerminal.onOutput = (data) {
      if (!mounted) return;
      service.send(data);
    };
    _activeTerminal.onResize = (width, height, pixelWidth, pixelHeight) {
      if (!mounted) return;
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
    _outputSubscription?.cancel();
    _outputSubscription = null;
    _presenceSubscription?.cancel();
    _presenceSubscription = null;
    _deviceKickedSubscription?.cancel();
    _deviceKickedSubscription = null;
    _tokenInvalidSubscription?.cancel();
    _tokenInvalidSubscription = null;
  }

  Future<void> _connectToServer(WebSocketService service) async {
    final terminalId = service.terminalId;
    if ((terminalId ?? '').isNotEmpty) {
      await context
          .read<TerminalSessionManager>()
          .deactivateConflictingTerminalSessions(service);
    }
    await service.connect();

    if (!mounted ||
        _isMobilePlatform ||
        !identical(_webSocketService, service)) {
      return;
    }
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) {
        _terminalFocusNode.requestFocus();
      }
    });
  }

  Future<void> _loadPresenceSnapshot(WebSocketService service) async {
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
      if (!mounted ||
          terminal == null ||
          !identical(_webSocketService, service)) {
        return;
      }
      setState(() {
        _views = terminal.views;
      });
    } catch (_) {
      // 进入页时以后端快照兜底，不影响主连接流程。
    }
  }

  Future<void> _loadShortcutItems() async {
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

    if (!mounted) return;
    setState(() {
      _shortcutLayout = ShortcutItemSorter.partitionAndSort(allItems);
    });
  }

  void _onPresence(Map<String, int> views) {
    setState(() {
      _views = views;
    });
  }

  void _onStatusChanged() {
    if (_webSocketService == null) {
      return;
    }
    final service = _activeService;

    if (service.status == ConnectionStatus.error) {
      setState(() {
        _showErrorBanner = true;
      });
    } else if (service.status == ConnectionStatus.connected) {
      setState(() {
        _showErrorBanner = false;
        _views = Map<String, int>.from(service.views);
      });
    }

    // 检查 WS close code 4011（被新设备替换）
    if (service.status == ConnectionStatus.disconnected &&
        service.lastCloseCode == 4011) {
      _onDeviceKicked();
      return;
    }

    final error = service.errorMessage?.toLowerCase() ?? '';
    if (error.contains('401') ||
        error.contains('token 已过期') ||
        error.contains('token 过期') ||
        error.contains('token 无效') ||
        error.contains('unauthorized')) {
      _handleTokenExpired();
    }
  }

  void _onOutput(String data) {
    _activeTerminal.write(data);
    // 更新输出缓冲区（用于 TUI 选择器）
    _updateOutputBuffer(data);
  }

  /// 更新输出缓冲区
  void _updateOutputBuffer(String data) {
    final lines = data.split('\n');
    for (final line in lines) {
      if (line.isNotEmpty) {
        _localOutputBuffer.add(line);
        if (_localOutputBuffer.length > _maxBufferLines) {
          _localOutputBuffer.removeAt(0);
        }
      }
    }
    _localTerminalOutputText.value = _localOutputBuffer.join('\n');
  }

  void _onOutputError(dynamic error) {
    setState(() {
      _showErrorBanner = true;
    });
  }

  /// 被新设备踢出（close code 4011 或 device_kicked 消息）
  void _onDeviceKicked() {
    if (!mounted || _authDialogShowing) return;
    _authDialogShowing = true;
    _releaseInputFocus();

    showDialog(
      context: context,
      barrierDismissible: false,
      builder: (context) => AlertDialog(
        title: const Text('您已在其他设备上登录'),
        content: const Text('同一终端已被其他设备连接，当前连接已断开。'),
        actions: [
          TextButton(
            onPressed: () async {
              _authDialogShowing = false;
              // 清理终端会话缓存，防止旧 token 残留导致重连时 "登录已过期"
              final sessionManager = context.read<TerminalSessionManager>();
              await sessionManager.disconnectAll();
              if (!context.mounted) return;
              // 不强制清除 token（桌面端合盖重开场景）
              Navigator.of(context).pushAndRemoveUntil(
                MaterialPageRoute(
                  builder: (_) => const LoginScreen(),
                ),
                (_) => false,
              );
            },
            child: const Text('确定'),
          ),
        ],
      ),
    );
  }

  /// WS token 验证失败（close code 4001），清除 token 并跳转登录页
  void _onTokenInvalid() {
    if (!mounted || _authDialogShowing) return;
    _releaseInputFocus();
    unawaited(_handleTokenExpired());
  }

  Future<void> _handleTokenExpired() async {
    if (!mounted || _authDialogShowing) return;
    _authDialogShowing = true;
    _releaseInputFocus();

    showDialog(
      context: context,
      barrierDismissible: false,
      builder: (context) => AlertDialog(
        title: const Text('登录已过期'),
        content: const Text('您的登录已过期，请重新登录。'),
        actions: [
          TextButton(
            onPressed: () async {
              _authDialogShowing = false;
              await logoutAndNavigate(
                context: context,
                destinationBuilder: (_) => const LoginScreen(),
              );
            },
            child: const Text('重新登录'),
          ),
        ],
      ),
    );
  }

  Future<void> _retryConnection() async {
    await _activeService.connect();
    if (!mounted || _isMobilePlatform) return;
    _terminalFocusNode.requestFocus();
  }

  void _sendSpecialKey(String key) {
    _activeService.send(key);
    if (!_isMobilePlatform) {
      _terminalFocusNode.requestFocus();
    }
  }

  Future<void> _handleShortcutPressed(ShortcutItem item) async {
    final payload = item.action.toTerminalPayload();
    if (payload.isEmpty) return;
    _sendSpecialKey(payload);
    if (!item.isCore) {
      await _shortcutConfigService.updateShortcutItem(item.markUsed());
      await _loadShortcutItems();
    }
  }

  /// 请求输入焦点
  void _requestInputFocus() {
    _terminalFocusNode.requestFocus();
  }

  void _releaseInputFocus() {
    _terminalFocusNode.unfocus();
    FocusScope.of(context).unfocus();
  }

  Future<void> _showShortcutMenu() async {
    if (_shortcutLayout.smartItems.isEmpty || !mounted) return;
    _releaseInputFocus();

    await showModalBottomSheet<void>(
      context: context,
      backgroundColor: Colors.transparent,
      isScrollControlled: true,
      builder: (context) {
        final theme = Theme.of(context);
        final colorScheme = theme.colorScheme;
        final builtinItems = _shortcutLayout.smartItems
            .where((item) => item.source != ShortcutItemSource.project)
            .toList(growable: false);
        final projectItems = _shortcutLayout.smartItems
            .where((item) => item.source == ShortcutItemSource.project)
            .toList(growable: false);

        return SafeArea(
          child: Container(
            margin: const EdgeInsets.fromLTRB(12, 0, 12, 12),
            decoration: BoxDecoration(
              color: colorScheme.surfaceContainerHighest,
              borderRadius: BorderRadius.circular(24),
              border: Border.all(color: colorScheme.outlineVariant),
              boxShadow: [
                BoxShadow(
                  color: colorScheme.shadow.withValues(alpha: 0.18),
                  blurRadius: 24,
                  offset: Offset(0, 12),
                ),
              ],
            ),
            child: ListView(
              shrinkWrap: true,
              padding: const EdgeInsets.fromLTRB(16, 12, 16, 20),
              children: [
                Center(
                  child: Container(
                    width: 40,
                    height: 5,
                    decoration: BoxDecoration(
                      color: colorScheme.outlineVariant,
                      borderRadius: BorderRadius.circular(999),
                    ),
                  ),
                ),
                const SizedBox(height: 16),
                Row(
                  children: [
                    Expanded(
                      child: Text(
                        '快捷命令',
                        style: theme.textTheme.titleLarge?.copyWith(
                          color: colorScheme.onSurface,
                          fontSize: 20,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                    ),
                    TextButton.icon(
                      onPressed: () async {
                        Navigator.of(context).pop();
                        await _showShortcutSettingsSheet();
                      },
                      icon: const Icon(Icons.tune, size: 18),
                      label: const Text('管理'),
                    ),
                  ],
                ),
                const SizedBox(height: 4),
                Text(
                  '常用的 Claude Code 和项目命令会在这里展开。',
                  style: theme.textTheme.bodySmall?.copyWith(
                    color: colorScheme.onSurfaceVariant,
                    fontSize: 13,
                    height: 1.35,
                  ),
                ),
                if (builtinItems.isNotEmpty) ...[
                  const SizedBox(height: 20),
                  _buildShortcutMenuSection(
                    title: 'Claude Code',
                    items: builtinItems,
                  ),
                ],
                if (projectItems.isNotEmpty) ...[
                  const SizedBox(height: 20),
                  _buildShortcutMenuSection(
                    title: '当前项目',
                    items: projectItems,
                  ),
                ],
              ],
            ),
          ),
        );
      },
    );
  }

  Future<void> _showShortcutSettingsSheet() async {
    if (!mounted) return;
    _releaseInputFocus();

    var editableItems = _sortShortcutItems(
      await _shortcutConfigService.loadShortcutItems(),
    );
    var projectItems = _sortShortcutItems(
      await _shortcutConfigService.loadProjectShortcutItems(_defaultProjectId),
    );
    var navigationMode =
        await _shortcutConfigService.loadClaudeNavigationMode();
    if (!mounted) return;

    await showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      builder: (context) {
        final theme = Theme.of(context);
        final colorScheme = theme.colorScheme;

        return StatefulBuilder(
          builder: (context, setModalState) {
            Future<void> applyItems(List<ShortcutItem> items) async {
              final normalized = _normalizeShortcutOrder(items);
              await _shortcutConfigService.saveShortcutItems(normalized);
              editableItems = normalized;
              if (!mounted) return;
              await _loadShortcutItems();
              setModalState(() {});
            }

            Future<void> toggleItem(ShortcutItem item, bool enabled) async {
              final updated = editableItems
                  .map(
                    (candidate) => candidate.id == item.id
                        ? candidate.copyWith(enabled: enabled)
                        : candidate,
                  )
                  .toList(growable: false);
              await applyItems(updated);
            }

            Future<void> moveItem(int oldIndex, int newIndex) async {
              if (newIndex < 0 || newIndex >= editableItems.length) return;
              final updated = List<ShortcutItem>.from(editableItems);
              final item = updated.removeAt(oldIndex);
              updated.insert(newIndex, item);
              await applyItems(updated);
            }

            Future<void> restoreDefaults() async {
              final restored =
                  await _shortcutConfigService.restoreDefaultShortcutItems();
              editableItems = _sortShortcutItems(restored);
              if (!mounted) return;
              await _loadShortcutItems();
              setModalState(() {});
            }

            Future<void> applyProjectItems(List<ShortcutItem> items) async {
              final normalized = _normalizeShortcutOrder(items).map((item) {
                return item.copyWith(
                  source: ShortcutItemSource.project,
                  scope: ShortcutItemScope.project,
                );
              }).toList(growable: false);
              await _shortcutConfigService.saveProjectShortcutItems(
                _defaultProjectId,
                normalized,
              );
              projectItems = normalized;
              if (!mounted) return;
              await _loadShortcutItems();
              setModalState(() {});
            }

            Future<void> moveProjectItem(int oldIndex, int newIndex) async {
              if (newIndex < 0 || newIndex >= projectItems.length) return;
              final updated = List<ShortcutItem>.from(projectItems);
              final item = updated.removeAt(oldIndex);
              updated.insert(newIndex, item);
              await applyProjectItems(updated);
            }

            Future<void> deleteProjectItem(ShortcutItem item) async {
              final updated = projectItems
                  .where((candidate) => candidate.id != item.id)
                  .toList(growable: false);
              await applyProjectItems(updated);
            }

            Future<void> editProjectItem([ShortcutItem? initialItem]) async {
              final edited = await _showProjectCommandEditor(
                context,
                initialItem: initialItem,
              );
              if (edited == null) return;

              final updated = List<ShortcutItem>.from(projectItems);
              final index = updated.indexWhere(
                (candidate) => candidate.id == edited.id,
              );
              if (index >= 0) {
                updated[index] = edited;
              } else {
                updated.add(
                  edited.copyWith(
                    order: updated.length + 1,
                    source: ShortcutItemSource.project,
                    scope: ShortcutItemScope.project,
                  ),
                );
              }
              await applyProjectItems(updated);
            }

            Future<void> updateNavigationMode(
              ClaudeNavigationMode mode,
            ) async {
              await _shortcutConfigService.saveClaudeNavigationMode(mode);
              navigationMode = mode;
              if (!mounted) return;
              await _loadShortcutItems();
              setModalState(() {});
            }

            return SafeArea(
              child: Padding(
                padding: EdgeInsets.only(
                  bottom: MediaQuery.of(context).viewInsets.bottom,
                ),
                child: Container(
                  padding: const EdgeInsets.fromLTRB(16, 12, 16, 20),
                  constraints: const BoxConstraints(maxHeight: 560),
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Center(
                        child: Container(
                          width: 40,
                          height: 5,
                          decoration: BoxDecoration(
                            color: colorScheme.outlineVariant,
                            borderRadius: BorderRadius.circular(999),
                          ),
                        ),
                      ),
                      const SizedBox(height: 16),
                      Row(
                        children: [
                          Expanded(
                            child: Text(
                              '管理快捷命令',
                              style: theme.textTheme.titleLarge?.copyWith(
                                fontWeight: FontWeight.w700,
                              ),
                            ),
                          ),
                          TextButton(
                            onPressed: restoreDefaults,
                            child: const Text('恢复默认'),
                          ),
                          IconButton(
                            key: const Key('shortcut-settings-close'),
                            tooltip: '关闭',
                            onPressed: () => Navigator.of(context).pop(),
                            icon: const Icon(Icons.close),
                          ),
                        ],
                      ),
                      const SizedBox(height: 4),
                      Text(
                        '支持显示/隐藏、顺序调整，以及当前项目命令的维护。',
                        style: theme.textTheme.bodySmall?.copyWith(
                          color: colorScheme.onSurfaceVariant,
                          height: 1.35,
                        ),
                      ),
                      const SizedBox(height: 12),
                      Align(
                        alignment: Alignment.centerLeft,
                        child: OutlinedButton.icon(
                          key: const Key('add-project-command'),
                          onPressed: () => editProjectItem(),
                          icon: const Icon(Icons.add, size: 18),
                          label: const Text('新增项目命令'),
                        ),
                      ),
                      const SizedBox(height: 16),
                      Material(
                        color: colorScheme.surfaceContainerLow,
                        borderRadius: BorderRadius.circular(18),
                        child: Padding(
                          padding: const EdgeInsets.all(14),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                'Claude 导航模式',
                                style: theme.textTheme.titleSmall?.copyWith(
                                  fontWeight: FontWeight.w700,
                                ),
                              ),
                              const SizedBox(height: 4),
                              Text(
                                '如果 Claude Code 列表里出现整页翻动，可以切到应用方向键模式再试。',
                                style: theme.textTheme.bodySmall?.copyWith(
                                  color: colorScheme.onSurfaceVariant,
                                  height: 1.35,
                                ),
                              ),
                              const SizedBox(height: 12),
                              SegmentedButton<ClaudeNavigationMode>(
                                showSelectedIcon: false,
                                segments: const [
                                  ButtonSegment(
                                    value: ClaudeNavigationMode.standard,
                                    label: Text('标准'),
                                  ),
                                  ButtonSegment(
                                    value: ClaudeNavigationMode.application,
                                    label: Text('应用'),
                                  ),
                                ],
                                selected: {navigationMode},
                                onSelectionChanged: (selection) {
                                  updateNavigationMode(selection.first);
                                },
                              ),
                            ],
                          ),
                        ),
                      ),
                      const SizedBox(height: 16),
                      Flexible(
                        child: ListView.separated(
                          shrinkWrap: true,
                          itemCount: editableItems.length + 1,
                          separatorBuilder: (context, index) =>
                              const SizedBox(height: 10),
                          itemBuilder: (context, index) {
                            if (index == editableItems.length) {
                              return Material(
                                color: colorScheme.surfaceContainerLow,
                                borderRadius: BorderRadius.circular(18),
                                child: Padding(
                                  padding: const EdgeInsets.all(14),
                                  child: Column(
                                    crossAxisAlignment:
                                        CrossAxisAlignment.start,
                                    children: [
                                      Row(
                                        children: [
                                          Expanded(
                                            child: Text(
                                              '当前项目命令',
                                              style: theme.textTheme.titleSmall
                                                  ?.copyWith(
                                                fontWeight: FontWeight.w700,
                                              ),
                                            ),
                                          ),
                                          TextButton.icon(
                                            onPressed: () => editProjectItem(),
                                            icon:
                                                const Icon(Icons.add, size: 18),
                                            label: const Text('新增'),
                                          ),
                                        ],
                                      ),
                                      const SizedBox(height: 6),
                                      Text(
                                        '这些命令只属于当前项目，会在命令面板的“当前项目”分组里展示。',
                                        style:
                                            theme.textTheme.bodySmall?.copyWith(
                                          color: colorScheme.onSurfaceVariant,
                                          height: 1.35,
                                        ),
                                      ),
                                      if (projectItems.isEmpty) ...[
                                        const SizedBox(height: 12),
                                        Text(
                                          '还没有项目命令，先新增一个常用命令。',
                                          style: theme.textTheme.bodySmall
                                              ?.copyWith(
                                            color: colorScheme.onSurfaceVariant,
                                          ),
                                        ),
                                      ] else ...[
                                        const SizedBox(height: 12),
                                        for (var projectIndex = 0;
                                            projectIndex < projectItems.length;
                                            projectIndex++) ...[
                                          _buildProjectCommandTile(
                                            item: projectItems[projectIndex],
                                            onMoveUp: projectIndex == 0
                                                ? null
                                                : () => moveProjectItem(
                                                      projectIndex,
                                                      projectIndex - 1,
                                                    ),
                                            onMoveDown: projectIndex ==
                                                    projectItems.length - 1
                                                ? null
                                                : () => moveProjectItem(
                                                      projectIndex,
                                                      projectIndex + 1,
                                                    ),
                                            onEdit: () => editProjectItem(
                                              projectItems[projectIndex],
                                            ),
                                            onDelete: () => deleteProjectItem(
                                              projectItems[projectIndex],
                                            ),
                                          ),
                                          if (projectIndex !=
                                              projectItems.length - 1)
                                            const SizedBox(height: 10),
                                        ],
                                      ],
                                    ],
                                  ),
                                ),
                              );
                            }

                            final item = editableItems[index];
                            return Material(
                              color: colorScheme.surfaceContainerLow,
                              borderRadius: BorderRadius.circular(18),
                              child: Padding(
                                padding: const EdgeInsets.symmetric(
                                  horizontal: 14,
                                  vertical: 12,
                                ),
                                child: Row(
                                  children: [
                                    Expanded(
                                      child: Column(
                                        crossAxisAlignment:
                                            CrossAxisAlignment.start,
                                        children: [
                                          Text(
                                            item.label,
                                            style: theme.textTheme.titleSmall
                                                ?.copyWith(
                                              fontWeight: FontWeight.w600,
                                            ),
                                          ),
                                          const SizedBox(height: 4),
                                          Text(
                                            _shortcutMenuDescription(item),
                                            style: theme.textTheme.bodySmall
                                                ?.copyWith(
                                              color:
                                                  colorScheme.onSurfaceVariant,
                                              height: 1.3,
                                            ),
                                          ),
                                        ],
                                      ),
                                    ),
                                    IconButton(
                                      key: Key('shortcut-move-up-${item.id}'),
                                      tooltip: '上移 ${item.label}',
                                      onPressed: index == 0
                                          ? null
                                          : () => moveItem(index, index - 1),
                                      icon: const Icon(Icons.keyboard_arrow_up),
                                    ),
                                    IconButton(
                                      key: Key('shortcut-move-down-${item.id}'),
                                      tooltip: '下移 ${item.label}',
                                      onPressed: index ==
                                              editableItems.length - 1
                                          ? null
                                          : () => moveItem(index, index + 1),
                                      icon:
                                          const Icon(Icons.keyboard_arrow_down),
                                    ),
                                    Switch(
                                      key: Key('shortcut-toggle-${item.id}'),
                                      value: item.enabled,
                                      onChanged: (value) =>
                                          toggleItem(item, value),
                                    ),
                                  ],
                                ),
                              ),
                            );
                          },
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            );
          },
        );
      },
    );
  }

  List<ShortcutItem> _sortShortcutItems(Iterable<ShortcutItem> items) {
    final sorted = items.toList(growable: false).toList();
    sorted.sort((a, b) {
      final byOrder = a.order.compareTo(b.order);
      if (byOrder != 0) return byOrder;
      return a.label.compareTo(b.label);
    });
    return sorted;
  }

  List<ShortcutItem> _normalizeShortcutOrder(List<ShortcutItem> items) {
    return [
      for (var i = 0; i < items.length; i++) items[i].copyWith(order: i + 1),
    ];
  }

  Widget _buildProjectCommandTile({
    required ShortcutItem item,
    required VoidCallback? onMoveUp,
    required VoidCallback? onMoveDown,
    required VoidCallback onEdit,
    required VoidCallback onDelete,
  }) {
    final theme = Theme.of(context);
    final colorScheme = theme.colorScheme;

    return Material(
      color: colorScheme.surface,
      borderRadius: BorderRadius.circular(16),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 12),
        child: Row(
          children: [
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    item.label,
                    style: theme.textTheme.titleSmall?.copyWith(
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    _projectCommandValue(item),
                    style: theme.textTheme.bodySmall?.copyWith(
                      color: colorScheme.onSurfaceVariant,
                    ),
                  ),
                ],
              ),
            ),
            IconButton(
              key: Key('project-command-up-${item.id}'),
              tooltip: '上移 ${item.label}',
              onPressed: onMoveUp,
              icon: const Icon(Icons.keyboard_arrow_up),
            ),
            IconButton(
              key: Key('project-command-down-${item.id}'),
              tooltip: '下移 ${item.label}',
              onPressed: onMoveDown,
              icon: const Icon(Icons.keyboard_arrow_down),
            ),
            IconButton(
              key: Key('project-command-edit-${item.id}'),
              tooltip: '编辑 ${item.label}',
              onPressed: onEdit,
              icon: const Icon(Icons.edit_outlined),
            ),
            IconButton(
              key: Key('project-command-delete-${item.id}'),
              tooltip: '删除 ${item.label}',
              onPressed: onDelete,
              icon: const Icon(Icons.delete_outline),
            ),
          ],
        ),
      ),
    );
  }

  String _projectCommandValue(ShortcutItem item) {
    final value = item.action.value;
    if (value.endsWith('\r')) {
      return value.substring(0, value.length - 1);
    }
    return value;
  }

  Future<ShortcutItem?> _showProjectCommandEditor(
    BuildContext context, {
    ShortcutItem? initialItem,
  }) async {
    _releaseInputFocus();
    final labelController =
        TextEditingController(text: initialItem?.label ?? '');
    final commandController = TextEditingController(
      text: initialItem == null ? '' : _projectCommandValue(initialItem),
    );

    final result = await showDialog<ShortcutItem>(
      context: context,
      builder: (context) {
        return AlertDialog(
          title: Text(initialItem == null ? '新增项目命令' : '编辑项目命令'),
          content: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                TextField(
                  key: const Key('project-command-label-field'),
                  controller: labelController,
                  decoration: const InputDecoration(
                    labelText: '名称',
                    hintText: '例如：运行测试',
                  ),
                  textInputAction: TextInputAction.next,
                ),
                const SizedBox(height: 12),
                TextField(
                  key: const Key('project-command-value-field'),
                  controller: commandController,
                  decoration: const InputDecoration(
                    labelText: '命令',
                    hintText: '例如：pnpm test',
                  ),
                  textInputAction: TextInputAction.done,
                  onSubmitted: (_) {
                    Navigator.of(context).pop(
                      _buildProjectCommandItem(
                        initialItem: initialItem,
                        label: labelController.text,
                        command: commandController.text,
                      ),
                    );
                  },
                ),
              ],
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(context).pop(),
              child: const Text('取消'),
            ),
            FilledButton(
              key: const Key('save-project-command'),
              onPressed: () {
                Navigator.of(context).pop(
                  _buildProjectCommandItem(
                    initialItem: initialItem,
                    label: labelController.text,
                    command: commandController.text,
                  ),
                );
              },
              child: const Text('保存'),
            ),
          ],
        );
      },
    );

    if (result == null) return null;
    if (result.label.trim().isEmpty ||
        _projectCommandValue(result).trim().isEmpty) {
      return null;
    }
    return result;
  }

  ShortcutItem _buildProjectCommandItem({
    ShortcutItem? initialItem,
    required String label,
    required String command,
  }) {
    final normalizedCommand = command.trim();
    return ShortcutItem(
      id: initialItem?.id ??
          'project_${DateTime.now().microsecondsSinceEpoch.toString()}',
      label: label.trim(),
      source: ShortcutItemSource.project,
      section: ShortcutItemSection.smart,
      action: TerminalShortcutAction(
        type: TerminalShortcutActionType.sendText,
        value: normalizedCommand.endsWith('\r')
            ? normalizedCommand
            : '$normalizedCommand\r',
      ),
      order: initialItem?.order ?? 0,
      scope: ShortcutItemScope.project,
    );
  }

  Widget _buildShortcutMenuSection({
    required String title,
    required List<ShortcutItem> items,
  }) {
    final theme = Theme.of(context);
    final colorScheme = theme.colorScheme;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          title,
          style: theme.textTheme.labelMedium?.copyWith(
            color: colorScheme.primary,
            fontSize: 12,
            fontWeight: FontWeight.w700,
            letterSpacing: 0.4,
          ),
        ),
        const SizedBox(height: 10),
        for (var i = 0; i < items.length; i++) ...[
          _buildShortcutMenuTile(items[i]),
          if (i != items.length - 1) const SizedBox(height: 10),
        ],
      ],
    );
  }

  Widget _buildShortcutMenuTile(ShortcutItem item) {
    final theme = Theme.of(context);
    final colorScheme = theme.colorScheme;

    return Material(
      color: colorScheme.surface,
      borderRadius: BorderRadius.circular(18),
      child: InkWell(
        borderRadius: BorderRadius.circular(18),
        onTap: () async {
          Navigator.of(context).pop();
          await _handleShortcutPressed(item);
        },
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
          child: Row(
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      item.label,
                      style: theme.textTheme.titleSmall?.copyWith(
                        color: colorScheme.onSurface,
                        fontSize: 15,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      _shortcutMenuDescription(item),
                      style: theme.textTheme.bodySmall?.copyWith(
                        color: colorScheme.onSurfaceVariant,
                        fontSize: 12,
                        height: 1.3,
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 12),
              if (item.pinned)
                Icon(Icons.push_pin, color: colorScheme.primary, size: 18)
              else
                Icon(
                  Icons.north_east,
                  color: colorScheme.onSurfaceVariant,
                  size: 18,
                ),
            ],
          ),
        ),
      ),
    );
  }

  String _shortcutMenuDescription(ShortcutItem item) {
    if (item.description != null && item.description!.isNotEmpty) {
      return item.description!;
    }
    return item.source == ShortcutItemSource.project
        ? '发送当前项目的预设命令'
        : '发送预设快捷命令到终端';
  }

  TerminalTheme _buildTerminalTheme(ThemeData theme) {
    if (theme.brightness == Brightness.dark) {
      return TerminalThemes.defaultTheme;
    }

    return const TerminalTheme(
      cursor: Color(0xCC2C5EFF),
      selection: Color(0x334A7BFF),
      foreground: Color(0xFF1F2937),
      background: Color(0xFFFDFEFF),
      black: Color(0xFF1F2937),
      red: Color(0xFFC0392B),
      green: Color(0xFF1E8449),
      yellow: Color(0xFFB9770E),
      blue: Color(0xFF2E6BE6),
      magenta: Color(0xFF8E44AD),
      cyan: Color(0xFF117A8B),
      white: Color(0xFFE5E7EB),
      brightBlack: Color(0xFF6B7280),
      brightRed: Color(0xFFE74C3C),
      brightGreen: Color(0xFF27AE60),
      brightYellow: Color(0xFFF4D03F),
      brightBlue: Color(0xFF4F86FF),
      brightMagenta: Color(0xFFAF7AC5),
      brightCyan: Color(0xFF48C9B0),
      brightWhite: Color(0xFFFFFFFF),
      searchHitBackground: Color(0xFFFFF176),
      searchHitBackgroundCurrent: Color(0xFF80DEEA),
      searchHitForeground: Color(0xFF111827),
    );
  }

  Future<void> _showThemePicker() async {
    _releaseInputFocus();
    await showThemePickerSheet(context);
  }

  Future<void> _navigateToProfile() async {
    _releaseInputFocus();
    final configService = ConfigService();
    final config = await configService.loadConfig();
    final session =
        await AuthService(serverUrl: config.serverUrl).getSavedSession();
    final sessionId = session?['session_id'] ?? '';
    if (!mounted) return;
    await Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => UserProfileScreen(
          serverUrl: config.serverUrl,
          token: config.token ?? '',
          sessionId: sessionId,
        ),
      ),
    );
  }

  @override
  void dispose() {
    _detachServiceBindings();
    _localTerminalOutputText.dispose();
    _terminalFocusNode.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colorScheme = theme.colorScheme;
    final terminalTheme = _buildTerminalTheme(theme);
    final platform = widget.platformOverride ?? defaultTargetPlatform;
    final terminalTextStyle = _isMobilePlatform
        ? platform == TargetPlatform.iOS
            ? const TerminalStyle(
                fontSize: 13,
                height: 1.2,
                fontFamily: 'Courier',
                fontFamilyFallback: [
                  'Courier New',
                  'Menlo',
                  'Monaco',
                  'SF Mono',
                  'Noto Sans Mono CJK SC',
                  'Noto Sans Mono CJK TC',
                  'Noto Sans Mono CJK KR',
                  'Noto Sans Mono CJK JP',
                  'Noto Sans Mono CJK HK',
                  'PingFang SC',
                  'Hiragino Sans GB',
                  'Noto Color Emoji',
                  'Noto Sans Symbols',
                  'monospace',
                  'sans-serif',
                ],
              )
            : const TerminalStyle(
                fontSize: 13,
                height: 1.2,
                fontFamily: 'monospace',
                fontFamilyFallback: [
                  'Roboto Mono',
                  'Noto Sans Mono',
                  'Noto Sans Mono CJK SC',
                  'Noto Sans Mono CJK TC',
                  'Noto Sans Mono CJK KR',
                  'Noto Sans Mono CJK JP',
                  'Noto Sans Mono CJK HK',
                  'Noto Color Emoji',
                  'Noto Sans Symbols',
                  'monospace',
                  'sans-serif',
                ],
              )
        : const TerminalStyle(
            fontSize: 14,
            fontFamily: 'monospace',
          );
    final terminalShellColor = theme.brightness == Brightness.dark
        ? Colors.black
        : const Color(0xFFF3F6FB);
    final terminalPanelColor = theme.brightness == Brightness.dark
        ? const Color(0xFF0C1117)
        : Colors.white;
    final terminalBorderColor = theme.brightness == Brightness.dark
        ? Colors.white10
        : colorScheme.outlineVariant;

    final content = Column(
      children: [
        if (_showErrorBanner)
          Material(
            color: Theme.of(context).colorScheme.errorContainer,
            child: InkWell(
              onTap: _retryConnection,
              child: Container(
                width: double.infinity,
                padding:
                    const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
                child: Row(
                  children: [
                    Icon(
                      Icons.error_outline,
                      color: Theme.of(context).colorScheme.onErrorContainer,
                      size: 20,
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: Consumer<WebSocketService>(
                        builder: (context, service, _) {
                          return Text(
                            _getErrorMessage(service),
                            style: TextStyle(
                              color: Theme.of(context)
                                  .colorScheme
                                  .onErrorContainer,
                            ),
                          );
                        },
                      ),
                    ),
                    TextButton(
                      onPressed: _retryConnection,
                      child: const Text('重试'),
                    ),
                  ],
                ),
              ),
            ),
          ),
        Expanded(
          child: Container(
            color: terminalShellColor,
            child: Consumer<WebSocketService>(
              builder: (context, service, _) {
                if (service.status == ConnectionStatus.reconnecting) {
                  return Center(
                    child: Column(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        const CircularProgressIndicator(),
                        const SizedBox(height: 16),
                        Text(
                          '正在重连... (${service.errorMessage ?? ""})',
                          style: TextStyle(
                            color: colorScheme.onSurfaceVariant,
                          ),
                        ),
                      ],
                    ),
                  );
                }

                if (service.status == ConnectionStatus.connecting) {
                  return Center(
                    child: Column(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        CircularProgressIndicator(),
                        SizedBox(height: 16),
                        Text(
                          '正在连接...',
                          style: TextStyle(
                            color: colorScheme.onSurfaceVariant,
                          ),
                        ),
                      ],
                    ),
                  );
                }

                return SafeArea(
                  top: false,
                  child: GestureDetector(
                    key: const Key('terminal-touch-layer'),
                    behavior: HitTestBehavior.translucent,
                    onTap: _requestInputFocus,
                    child: Container(
                      margin: const EdgeInsets.all(12),
                      decoration: BoxDecoration(
                        color: terminalPanelColor,
                        borderRadius: BorderRadius.circular(20),
                        border: Border.all(color: terminalBorderColor),
                        boxShadow: [
                          BoxShadow(
                            color: colorScheme.shadow.withValues(alpha: 0.08),
                            blurRadius: 18,
                            offset: const Offset(0, 8),
                          ),
                        ],
                      ),
                      child: ClipRRect(
                        borderRadius: BorderRadius.circular(20),
                        child: TerminalView(
                          _activeTerminal,
                          controller: _terminalController,
                          focusNode: _terminalFocusNode,
                          autofocus: !_isMobilePlatform,
                          autoResize: _shouldAutoResize(service),
                          // 不设 hardwareKeyboardOnly，保持默认 false，桌面端也启用 IME 支持中文输入
                          theme: terminalTheme,
                          padding: const EdgeInsets.fromLTRB(12, 12, 12, 10),
                          backgroundOpacity: 1,
                          deleteDetection: true,
                          keyboardType: TextInputType.text,
                          inputAction: _isMobilePlatform
                              ? TextInputAction.send
                              : TextInputAction.newline,
                          enableSuggestions: _isMobilePlatform,
                          enableIMEPersonalizedLearning: _isMobilePlatform,
                          autocorrect: false,
                          textStyle: terminalTextStyle,
                        ),
                      ),
                    ),
                  ),
                );
              },
            ),
          ),
        ),
        if (_isMobilePlatform)
          ValueListenableBuilder<String>(
            valueListenable: _terminalOutputListenable,
            builder: (context, terminalOutput, _) => TuiSelector(
              terminalOutput: terminalOutput,
              onSelect: (key) {
                _activeService.send(key);
              },
            ),
          ),
        if (_isMobilePlatform &&
            (_shortcutLayout.coreItems.isNotEmpty ||
                _shortcutLayout.smartItems.isNotEmpty))
          TerminalShortcutBar(
            items: _shortcutLayout.coreItems,
            onItemPressed: _handleShortcutPressed,
            trailing: _shortcutLayout.smartItems.isEmpty
                ? null
                : TextButton(
                    onPressed: _showShortcutMenu,
                    child: const Text('更多'),
                  ),
          ),
      ],
    );

    if (widget.embedded) {
      return content;
    }

    return Scaffold(
      resizeToAvoidBottomInset: !_isMobilePlatform,
      appBar: AppBar(
        title: const Text('Remote Terminal'),
        actions: [
          Consumer<WebSocketService>(
            builder: (context, service, _) {
              return _buildStatusIndicator(service.status);
            },
          ),
          PopupMenuButton<String>(
            onSelected: (value) {
              if (value == 'profile') {
                _navigateToProfile();
              } else if (value == 'theme') {
                _showThemePicker();
              } else {
                _sendSpecialKey(value);
              }
            },
            itemBuilder: (context) => [
              const PopupMenuItem(value: 'theme', child: Text('主题')),
              const PopupMenuDivider(),
              const PopupMenuItem(value: 'profile', child: Text('个人信息')),
            ],
          ),
        ],
      ),
      body: content,
    );
  }

  String _getErrorMessage(WebSocketService service) {
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

  Widget _buildStatusIndicator(ConnectionStatus status) {
    final service = context.read<WebSocketService>();
    final colorScheme = Theme.of(context).colorScheme;
    Color color;
    String text;

    switch (status) {
      case ConnectionStatus.connected:
        color = Colors.green;
        text = service.deviceOnline ? '电脑在线' : '电脑离线';
        break;
      case ConnectionStatus.connecting:
        color = Colors.orange;
        text = '连接中...';
        break;
      case ConnectionStatus.reconnecting:
        color = Colors.orange;
        text = '重连中...';
        break;
      case ConnectionStatus.error:
        color = Colors.red;
        text = '错误';
        break;
      default:
        color = Colors.grey;
        text = '未连接';
    }

    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(
          width: 8,
          height: 8,
          decoration: BoxDecoration(
            color: color,
            shape: BoxShape.circle,
          ),
        ),
        const SizedBox(width: 8),
        Text(text, style: TextStyle(color: color)),
        // 显示 presence 信息
        if (status == ConnectionStatus.connected) ...[
          const SizedBox(width: 12),
          Icon(
            Icons.phone_android,
            size: 14,
            color: colorScheme.onSurfaceVariant,
          ),
          Text(
            ' ${_views['mobile'] ?? 0}',
            style: TextStyle(
              color: colorScheme.onSurfaceVariant,
              fontSize: 12,
            ),
          ),
          const SizedBox(width: 4),
          Icon(Icons.computer, size: 14, color: colorScheme.onSurfaceVariant),
          Text(
            ' ${_views['desktop'] ?? 0}',
            style: TextStyle(
              color: colorScheme.onSurfaceVariant,
              fontSize: 12,
            ),
          ),
        ],
      ],
    );
  }
}
