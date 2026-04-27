import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:xterm/xterm.dart';

import '../models/terminal_shortcut.dart';
import '../navigation/account_menu_actions.dart';
import '../services/account_menu_action_handler.dart';
import '../services/config_service.dart';
import '../services/runtime_selection_controller.dart';
import '../services/terminal_session_manager.dart';
import '../services/terminal_view_config.dart';
import '../services/ui_helpers.dart';
import '../services/websocket_service.dart';
import '../models/shortcut_item.dart';
import '../widgets/shortcut_menu_widgets.dart';
import '../widgets/smart_terminal_side_panel.dart';
import '../widgets/terminal_shortcut_bar.dart';
import '../widgets/tui_selector.dart';
import 'login_screen.dart';
import 'terminal_screen_controller.dart';

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
  late final TerminalScreenController _ctrl;
  late final TerminalViewConfig _viewConfig;
  final FocusNode _terminalFocusNode = FocusNode();

  @override
  void initState() {
    super.initState();
    final platform = widget.platformOverride ?? defaultTargetPlatform;
    _ctrl = TerminalScreenController(
      platformGetter: () => platform,
    );
    _viewConfig = TerminalViewConfig.forPlatform(platform);
    _ctrl.addListener(_onControllerChanged);
    unawaited(_ctrl.loadShortcutItems());
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final service = context.read<WebSocketService>();
    final sessionManager = context.read<TerminalSessionManager>();
    _ctrl.bindSession(service, sessionManager);
    unawaited(_ctrl.connectToServer(service, sessionManager, _requestFocus));
    unawaited(_ctrl.loadPresenceSnapshot(service));
  }

  void _onControllerChanged() {
    if (!mounted) return;
    setState(() {});
    if (_ctrl.authDialogShowing) {
      _releaseInputFocus();
      if (_ctrl.isDeviceKicked) {
        _showDeviceKickedDialog();
      } else {
        _showTokenExpiredDialog();
      }
    }
  }

  void _requestFocus() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) _terminalFocusNode.requestFocus();
    });
  }

  void _releaseInputFocus() {
    _terminalFocusNode.unfocus();
    FocusScope.of(context).unfocus();
  }

  // ─── 认证弹窗 ──────────────────────────────────────────────────

  void _showDeviceKickedDialog() {
    final sessionManager = context.read<TerminalSessionManager>();
    showDialog(
      context: context,
      barrierDismissible: false,
      builder: (ctx) => AlertDialog(
        title: const Text('您已在其他设备上登录'),
        content: const Text('同一终端已被其他设备连接，当前连接已断开。'),
        actions: [
          TextButton(
            onPressed: () => _ctrl.confirmDeviceKicked(ctx, sessionManager),
            child: const Text('确定'),
          ),
        ],
      ),
    );
  }

  void _showTokenExpiredDialog() {
    showDialog(
      context: context,
      barrierDismissible: false,
      builder: (ctx) => AlertDialog(
        title: const Text('登录已过期'),
        content: const Text('您的登录已过期，请重新登录。'),
        actions: [
          TextButton(
            onPressed: () => _ctrl.confirmTokenExpired(ctx),
            child: const Text('重新登录'),
          ),
        ],
      ),
    );
  }

  // ─── Shortcut 菜单 ─────────────────────────────────────────────

  void _showShortcutMenu() {
    ShortcutMenuWidgets.showMenu(
      context: context,
      layout: _ctrl.shortcutLayout,
      onItemPressed: _ctrl.handleShortcutPressed,
      onOpenSettings: _showShortcutSettingsSheet,
      releaseInputFocus: _releaseInputFocus,
    );
  }

  Future<void> _showShortcutSettingsSheet() async {
    if (!mounted) return;
    _releaseInputFocus();

    final scs = _ctrl.shortcutConfigService;
    var editableItems = _ctrl.sortShortcutItems(await scs.loadShortcutItems());
    var projectItems = _ctrl.sortShortcutItems(
      await scs.loadProjectShortcutItems(_ctrl.defaultProjectId),
    );
    var navigationMode = await scs.loadClaudeNavigationMode();
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
              final normalized = _ctrl.normalizeShortcutOrder(items);
              await scs.saveShortcutItems(normalized);
              editableItems = normalized;
              if (!mounted) return;
              await _ctrl.loadShortcutItems();
              setModalState(() {});
            }

            Future<void> toggleItem(ShortcutItem item, bool enabled) async {
              await applyItems(editableItems
                  .map((c) => c.id == item.id ? c.copyWith(enabled: enabled) : c)
                  .toList(growable: false));
            }

            Future<void> moveItem(int oldIndex, int newIndex) async {
              if (newIndex < 0 || newIndex >= editableItems.length) return;
              final updated = List<ShortcutItem>.from(editableItems);
              updated.insert(newIndex, updated.removeAt(oldIndex));
              await applyItems(updated);
            }

            Future<void> restoreDefaults() async {
              editableItems = _ctrl
                  .sortShortcutItems(await scs.restoreDefaultShortcutItems());
              if (!mounted) return;
              await _ctrl.loadShortcutItems();
              setModalState(() {});
            }

            Future<void> applyProjectItems(List<ShortcutItem> items) async {
              final normalized = _ctrl.normalizeShortcutOrder(items).map((i) {
                return i.copyWith(
                  source: ShortcutItemSource.project,
                  scope: ShortcutItemScope.project,
                );
              }).toList(growable: false);
              await scs.saveProjectShortcutItems(_ctrl.defaultProjectId, normalized);
              projectItems = normalized;
              if (!mounted) return;
              await _ctrl.loadShortcutItems();
              setModalState(() {});
            }

            Future<void> moveProjectItem(int o, int n) async {
              if (n < 0 || n >= projectItems.length) return;
              final updated = List<ShortcutItem>.from(projectItems);
              updated.insert(n, updated.removeAt(o));
              await applyProjectItems(updated);
            }

            Future<void> deleteProjectItem(ShortcutItem item) async {
              await applyProjectItems(
                projectItems.where((c) => c.id != item.id).toList(),
              );
            }

            Future<void> editProjectItem([ShortcutItem? initial]) async {
              final edited = await ShortcutMenuWidgets.showProjectCommandEditor(
                context, initialItem: initial,
              );
              if (edited == null) return;
              final updated = List<ShortcutItem>.from(projectItems);
              final idx = updated.indexWhere((c) => c.id == edited.id);
              if (idx >= 0) {
                updated[idx] = edited;
              } else {
                updated.add(edited.copyWith(
                  order: updated.length + 1,
                  source: ShortcutItemSource.project,
                  scope: ShortcutItemScope.project,
                ));
              }
              await applyProjectItems(updated);
            }

            Future<void> updateNavMode(ClaudeNavigationMode mode) async {
              await scs.saveClaudeNavigationMode(mode);
              navigationMode = mode;
              if (!mounted) return;
              await _ctrl.loadShortcutItems();
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
                      _dragHandle(colorScheme),
                      const SizedBox(height: 16),
                      Row(children: [
                        Expanded(
                          child: Text('管理快捷命令',
                              style: theme.textTheme.titleLarge
                                  ?.copyWith(fontWeight: FontWeight.w700)),
                        ),
                        TextButton(
                            onPressed: restoreDefaults,
                            child: const Text('恢复默认')),
                        IconButton(
                          key: const Key('shortcut-settings-close'),
                          tooltip: '关闭',
                          onPressed: () => Navigator.of(context).pop(),
                          icon: const Icon(Icons.close),
                        ),
                      ]),
                      const SizedBox(height: 4),
                      Text('支持显示/隐藏、顺序调整，以及当前项目命令的维护。',
                          style: theme.textTheme.bodySmall?.copyWith(
                              color: colorScheme.onSurfaceVariant, height: 1.35)),
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
                      ShortcutMenuWidgets.buildNavModeSection(
                        theme: theme,
                        colorScheme: colorScheme,
                        mode: navigationMode,
                        onUpdate: updateNavMode,
                      ),
                      const SizedBox(height: 16),
                      Flexible(
                        child: ListView.separated(
                          shrinkWrap: true,
                          itemCount: editableItems.length + 1,
                          separatorBuilder: (_, __) => const SizedBox(height: 10),
                          itemBuilder: (context, index) {
                            if (index == editableItems.length) {
                              return ShortcutMenuWidgets.buildProjectCommandsSection(
                                context: context,
                                projectItems: projectItems,
                                editProjectItem: editProjectItem,
                                deleteProjectItem: deleteProjectItem,
                                moveProjectItem: moveProjectItem,
                              );
                            }
                            return ShortcutMenuWidgets.buildEditableItemTile(
                              context: context,
                              item: editableItems[index],
                              index: index,
                              total: editableItems.length,
                              toggleItem: toggleItem,
                              moveItem: moveItem,
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

  Widget _dragHandle(ColorScheme colorScheme) => Center(
        child: Container(
          width: 40,
          height: 5,
          decoration: BoxDecoration(
            color: colorScheme.outlineVariant,
            borderRadius: BorderRadius.circular(999),
          ),
        ),
      );

  // ─── Theme ──────────────────────────────────────────────────────

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

  Future<void> _handleAccountAction(AccountMenuAction action) async {
    _releaseInputFocus();
    if (action == AccountMenuAction.theme) {
      await showThemePickerSheet(context);
      return;
    }
    final configService = ConfigService();
    final config = await configService.loadConfig();
    if (!mounted) return;
    await handleAccountMenuAction(
      context,
      action: action,
      serverUrl: config.serverUrl,
      token: config.token ?? '',
      logoutDestinationBuilder: (_) => const LoginScreen(),
      onTheme: _showThemePicker,
    );
  }

  // ─── Lifecycle & build ─────────────────────────────────────────

  @override
  void dispose() {
    _ctrl.removeListener(_onControllerChanged);
    _ctrl.dispose();
    _terminalFocusNode.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colorScheme = theme.colorScheme;
    final terminalTheme = _buildTerminalTheme(theme);
    final service = _ctrl.webSocketService;
    final vc = _viewConfig;

    final terminalShellColor =
        theme.brightness == Brightness.dark ? Colors.black : const Color(0xFFF3F6FB);
    final terminalPanelColor = theme.brightness == Brightness.dark
        ? const Color(0xFF0C1117)
        : Colors.white;
    final terminalBorderColor =
        theme.brightness == Brightness.dark ? Colors.white10 : colorScheme.outlineVariant;

    final content = Column(
      children: [
        if (_ctrl.showErrorBanner)
          _buildErrorBanner(colorScheme),
        Expanded(
          child: Container(
            color: terminalShellColor,
            child: Consumer<WebSocketService>(
              builder: (context, svc, _) {
                if (svc.status == ConnectionStatus.reconnecting) {
                  return _buildCenteredMessage(
                      '正在重连... (${svc.errorMessage ?? ""})', colorScheme);
                }
                if (svc.status == ConnectionStatus.connecting) {
                  return _buildCenteredMessage('正在连接...', colorScheme);
                }
                return SafeArea(
                  top: false,
                  child: GestureDetector(
                    key: const Key('terminal-touch-layer'),
                    behavior: HitTestBehavior.translucent,
                    onTap: _terminalFocusNode.requestFocus,
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
                          _ctrl.terminal!,
                          controller: _ctrl.terminalController,
                          focusNode: _terminalFocusNode,
                          autofocus: vc.autofocus,
                          autoResize: service != null && _ctrl.shouldAutoResize(service),
                          theme: terminalTheme,
                          padding: const EdgeInsets.fromLTRB(12, 12, 12, 10),
                          backgroundOpacity: 1,
                          deleteDetection: true,
                          keyboardType: TextInputType.text,
                          inputAction: vc.inputAction,
                          enableSuggestions: vc.enableSuggestions,
                          enableIMEPersonalizedLearning: vc.enableIMEPersonalizedLearning,
                          autocorrect: false,
                          textStyle: vc.textStyle,
                        ),
                      ),
                    ),
                  ),
                );
              },
            ),
          ),
        ),
        if (vc.showTuiSelector)
          ValueListenableBuilder<String>(
            valueListenable: _ctrl.outputListenable,
            builder: (context, output, _) => TuiSelector(
              terminalOutput: output,
              onSelect: _ctrl.sendSpecialKey,
            ),
          ),
        if (vc.showShortcutBar &&
            (_ctrl.shortcutLayout.coreItems.isNotEmpty ||
                _ctrl.shortcutLayout.smartItems.isNotEmpty))
          TerminalShortcutBar(
            items: _ctrl.shortcutLayout.coreItems,
            onItemPressed: _ctrl.handleShortcutPressed,
            trailing: _ctrl.shortcutLayout.smartItems.isEmpty
                ? null
                : TextButton(
                    onPressed: _showShortcutMenu, child: const Text('更多')),
          ),
      ],
    );

    if (widget.embedded) {
      return _wrapWithSidePanel(context, content);
    }

    return Scaffold(
      resizeToAvoidBottomInset: vc.resizeToAvoidBottomInset,
      appBar: AppBar(
        title: const Text('Remote Terminal'),
        actions: [
          Consumer<WebSocketService>(
            builder: (context, svc, _) =>
                _buildStatusIndicator(svc.status, svc, colorScheme),
          ),
          PopupMenuButton<AccountMenuAction>(
            onSelected: _handleAccountAction,
            itemBuilder: (_) => buildAccountMenuEntries(),
          ),
        ],
      ),
      body: content,
    );
  }

  Widget _buildErrorBanner(ColorScheme colorScheme) {
    return Material(
      color: colorScheme.errorContainer,
      child: InkWell(
        onTap: _onRetryConnection,
        child: Container(
          width: double.infinity,
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
          child: Row(children: [
            Icon(Icons.error_outline, color: colorScheme.onErrorContainer, size: 20),
            const SizedBox(width: 12),
            Expanded(
              child: Consumer<WebSocketService>(
                builder: (context, s, _) => Text(_ctrl.getErrorMessage(s),
                    style: TextStyle(color: colorScheme.onErrorContainer)),
              ),
            ),
            TextButton(onPressed: _onRetryConnection, child: const Text('重试')),
          ]),
        ),
      ),
    );
  }

  Widget _buildCenteredMessage(String message, ColorScheme colorScheme) {
    return Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          const CircularProgressIndicator(),
          const SizedBox(height: 16),
          Text(message, style: TextStyle(color: colorScheme.onSurfaceVariant)),
        ],
      ),
    );
  }

  Future<void> _onRetryConnection() async {
    await _ctrl.retryConnection(context.read<TerminalSessionManager>());
    if (!mounted || !_viewConfig.requestFocusAfterRetry) return;
    _terminalFocusNode.requestFocus();
  }

  Widget _wrapWithSidePanel(BuildContext context, Widget content) {
    try {
      final controller = context.read<RuntimeSelectionController>();
      if (controller.selectedDeviceId != null) {
        return SmartTerminalSidePanel(child: content);
      }
    } on ProviderNotFoundException {
      // standalone 模式无 RuntimeSelectionController
    }
    return content;
  }

  Widget _buildStatusIndicator(
      ConnectionStatus status, WebSocketService service, ColorScheme cs) {
    Color color;
    String text;
    switch (status) {
      case ConnectionStatus.connected:
        color = Colors.green;
        text = service.deviceOnline ? '电脑在线' : '电脑离线';
      case ConnectionStatus.connecting:
        color = Colors.orange;
        text = '连接中...';
      case ConnectionStatus.reconnecting:
        color = Colors.orange;
        text = '重连中...';
      case ConnectionStatus.error:
        color = Colors.red;
        text = '错误';
      default:
        color = Colors.grey;
        text = '未连接';
    }
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(
          width: 8, height: 8,
          decoration: BoxDecoration(color: color, shape: BoxShape.circle),
        ),
        const SizedBox(width: 8),
        Text(text, style: TextStyle(color: color)),
        if (status == ConnectionStatus.connected) ...[
          const SizedBox(height: 12),
          Icon(Icons.phone_android, size: 14, color: cs.onSurfaceVariant),
          Text(' ${_ctrl.views['mobile'] ?? 0}',
              style: TextStyle(color: cs.onSurfaceVariant, fontSize: 12)),
          const SizedBox(width: 4),
          Icon(Icons.computer, size: 14, color: cs.onSurfaceVariant),
          Text(' ${_ctrl.views['desktop'] ?? 0}',
              style: TextStyle(color: cs.onSurfaceVariant, fontSize: 12)),
        ],
      ],
    );
  }
}
