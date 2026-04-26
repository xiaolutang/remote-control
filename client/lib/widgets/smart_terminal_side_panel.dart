import 'dart:async';

import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../models/agent_conversation_projection.dart';
import '../models/agent_session_event.dart';
import '../models/command_sequence_draft.dart';
import '../models/terminal_launch_plan.dart';
import '../services/agent_session_service.dart';
import '../services/runtime_selection_controller.dart';
import '../services/usage_summary_service.dart';
import '../services/websocket_service.dart';
import 'mobile_bottom_inset.dart';
import 'package:provider/provider.dart';

part 'smart_terminal_side_panel_content.dart';

typedef AgentSessionServiceFactory = AgentSessionService Function(
  String serverUrl,
);
typedef UsageSummaryServiceFactory = UsageSummaryService Function(
  String serverUrl,
);

/// 侧滑式智能终端助手面板。
///
/// 在终端视图内以 FAB + 侧滑面板形式呈现，
/// 用于意图解析和命令注入。覆盖终端上方，不推动终端布局。
class SmartTerminalSidePanel extends StatefulWidget {
  const SmartTerminalSidePanel({
    super.key,
    required this.child,
    this.agentSessionServiceBuilder,
    this.usageSummaryServiceBuilder,
  });

  /// 底层终端内容
  final Widget child;
  final AgentSessionServiceFactory? agentSessionServiceBuilder;
  final UsageSummaryServiceFactory? usageSummaryServiceBuilder;

  @override
  State<SmartTerminalSidePanel> createState() => _SmartTerminalSidePanelState();
}

class _SmartTerminalSidePanelState extends State<SmartTerminalSidePanel> {
  bool _panelOpen = false;
  static const String _firstUseKey =
      'smart_terminal_side_panel_first_use_seen_v1';
  static const String _fabPositionXKey =
      'smart_terminal_side_panel_fab_position_x_v1';
  static const String _fabPositionYKey =
      'smart_terminal_side_panel_fab_position_y_v1';
  static const double _fabSize = 56;
  static const double _fabMargin = 16;
  bool _showFirstUseHint = false;
  Offset? _fabPositionRatio;

  @override
  void initState() {
    super.initState();
    _restoreFirstUseHint();
    _restoreFabPosition();
  }

  Future<void> _restoreFirstUseHint() async {
    final prefs = await SharedPreferences.getInstance();
    if (prefs.getBool(_firstUseKey) ?? false) return;
    if (!mounted) return;
    setState(() => _showFirstUseHint = true);
  }

  Future<void> _restoreFabPosition() async {
    final prefs = await SharedPreferences.getInstance();
    final x = prefs.getDouble(_fabPositionXKey);
    final y = prefs.getDouble(_fabPositionYKey);
    if (x == null || y == null) return;
    if (!mounted) return;
    setState(() {
      _fabPositionRatio = Offset(x.clamp(0.0, 1.0), y.clamp(0.0, 1.0));
    });
  }

  Future<void> _saveFabPosition() async {
    final ratio = _fabPositionRatio;
    if (ratio == null) return;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setDouble(_fabPositionXKey, ratio.dx);
    await prefs.setDouble(_fabPositionYKey, ratio.dy);
  }

  void _openPanel() {
    // 打开智能面板时先释放终端输入焦点，避免移动端软键盘仍属于终端输入。
    FocusManager.instance.primaryFocus?.unfocus();
    setState(() {
      _panelOpen = true;
      if (_showFirstUseHint) {
        _showFirstUseHint = false;
        SharedPreferences.getInstance()
            .then((p) => p.setBool(_firstUseKey, true));
      }
    });
  }

  void _closePanel() {
    setState(() => _panelOpen = false);
  }

  Rect _fabBounds(Size size, EdgeInsets padding) {
    final minLeft = padding.left + _fabMargin;
    final maxLeft = size.width - padding.right - _fabMargin - _fabSize;
    final minTop = padding.top + _fabMargin;
    final maxTop = size.height - padding.bottom - _fabMargin - _fabSize;
    return Rect.fromLTRB(
      minLeft,
      minTop,
      maxLeft.clamp(minLeft, double.infinity),
      maxTop.clamp(minTop, double.infinity),
    );
  }

  Offset _resolveFabOffset(Size size, EdgeInsets padding) {
    final bounds = _fabBounds(size, padding);
    final ratio = _fabPositionRatio;
    if (ratio == null) {
      return Offset(bounds.right, bounds.bottom);
    }
    return Offset(
      bounds.left + (bounds.right - bounds.left) * ratio.dx,
      bounds.top + (bounds.bottom - bounds.top) * ratio.dy,
    );
  }

  void _moveFab({
    required Offset delta,
    required Size size,
    required EdgeInsets padding,
  }) {
    final bounds = _fabBounds(size, padding);
    final current = _resolveFabOffset(size, padding);
    final next = Offset(
      (current.dx + delta.dx).clamp(bounds.left, bounds.right),
      (current.dy + delta.dy).clamp(bounds.top, bounds.bottom),
    );
    setState(() {
      _fabPositionRatio = Offset(
        bounds.right == bounds.left
            ? 0
            : (next.dx - bounds.left) / (bounds.right - bounds.left),
        bounds.bottom == bounds.top
            ? 0
            : (next.dy - bounds.top) / (bounds.bottom - bounds.top),
      );
    });
  }

  @override
  Widget build(BuildContext context) {
    final screenWidth = MediaQuery.sizeOf(context).width;
    final isCompact = screenWidth < 600;
    final panelWidth =
        isCompact ? screenWidth : (screenWidth * 0.38).clamp(320.0, 420.0);
    final colorScheme = Theme.of(context).colorScheme;

    return LayoutBuilder(
      builder: (context, constraints) {
        final size = constraints.biggest;
        final padding = MediaQuery.paddingOf(context);
        final fabOffset = _resolveFabOffset(size, padding);

        return Stack(
          children: [
            // 底层终端内容
            Positioned.fill(child: widget.child),

            // FAB 悬浮按钮，可拖动避开手机端输入栏/快捷栏。
            if (!_panelOpen)
              Positioned(
                left: fabOffset.dx,
                top: fabOffset.dy,
                child: GestureDetector(
                  onPanUpdate: (details) {
                    _moveFab(
                      delta: details.delta,
                      size: size,
                      padding: padding,
                    );
                  },
                  onPanEnd: (_) => _saveFabPosition(),
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    crossAxisAlignment: CrossAxisAlignment.end,
                    children: [
                      if (_showFirstUseHint && fabOffset.dy > 56)
                        Container(
                          margin: const EdgeInsets.only(bottom: 8),
                          padding: const EdgeInsets.symmetric(
                            horizontal: 12,
                            vertical: 6,
                          ),
                          decoration: BoxDecoration(
                            color: colorScheme.inverseSurface
                                .withValues(alpha: 0.88),
                            borderRadius: BorderRadius.circular(12),
                          ),
                          child: Text(
                            '点我可以智能生成命令',
                            style:
                                Theme.of(context).textTheme.bodySmall?.copyWith(
                                      color: colorScheme.onInverseSurface,
                                    ),
                          ),
                        ),
                      FloatingActionButton(
                        key: const Key('smart-terminal-fab'),
                        heroTag: 'smart_terminal_fab',
                        onPressed: _openPanel,
                        backgroundColor: colorScheme.primary,
                        child:
                            Icon(Icons.auto_awesome, color: colorScheme.onPrimary),
                      ),
                    ],
                  ),
                ),
              ),

            // 半透明遮罩
            if (_panelOpen)
              Positioned.fill(
                child: GestureDetector(
                  onTap: _closePanel,
                  child: Container(
                    color: Colors.black.withValues(alpha: 0.32),
                  ),
                ),
              ),

            // 侧滑面板
            AnimatedSlide(
              offset: _panelOpen ? Offset.zero : const Offset(1, 0),
              duration: const Duration(milliseconds: 260),
              curve: Curves.easeOutCubic,
              child: Align(
                alignment: Alignment.centerRight,
                child: SizedBox(
                  width: panelWidth,
                  height: double.infinity,
                  child: _SmartTerminalSidePanelContent(
                    onClose: _closePanel,
                    agentSessionServiceBuilder:
                        widget.agentSessionServiceBuilder,
                    usageSummaryServiceBuilder:
                        widget.usageSummaryServiceBuilder,
                  ),
                ),
              ),
            ),
          ],
        );
      },
    );
  }
}
