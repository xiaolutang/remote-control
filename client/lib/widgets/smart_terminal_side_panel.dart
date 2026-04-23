import 'dart:async';

import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../models/agent_session_event.dart';
import '../models/assistant_plan.dart';
import '../models/command_sequence_draft.dart';
import '../models/terminal_launch_plan.dart';
import '../services/agent_session_service.dart';
import '../services/command_planner/planner_provider.dart';
import '../services/runtime_selection_controller.dart';
import '../services/websocket_service.dart';
import 'package:provider/provider.dart';

part 'smart_terminal_side_panel_content.dart';

/// 侧滑式智能终端助手面板。
///
/// 在桌面端终端视图内以 FAB + 侧滑面板形式呈现，
/// 用于意图解析和命令注入。覆盖终端上方，不推动终端布局。
class SmartTerminalSidePanel extends StatefulWidget {
  const SmartTerminalSidePanel({
    super.key,
    required this.child,
  });

  /// 底层终端内容
  final Widget child;

  @override
  State<SmartTerminalSidePanel> createState() => _SmartTerminalSidePanelState();
}

class _SmartTerminalSidePanelState extends State<SmartTerminalSidePanel> {
  bool _panelOpen = false;
  static const String _firstUseKey =
      'smart_terminal_side_panel_first_use_seen_v1';
  bool _showFirstUseHint = false;

  @override
  void initState() {
    super.initState();
    _restoreFirstUseHint();
  }

  Future<void> _restoreFirstUseHint() async {
    final prefs = await SharedPreferences.getInstance();
    if (prefs.getBool(_firstUseKey) ?? false) return;
    if (!mounted) return;
    setState(() => _showFirstUseHint = true);
  }

  void _openPanel() {
    setState(() {
      _panelOpen = true;
      if (_showFirstUseHint) {
        _showFirstUseHint = false;
        SharedPreferences.getInstance().then((p) => p.setBool(_firstUseKey, true));
      }
    });
  }

  void _closePanel() {
    setState(() => _panelOpen = false);
  }

  @override
  Widget build(BuildContext context) {
    final screenWidth = MediaQuery.sizeOf(context).width;
    final panelWidth = (screenWidth * 0.38).clamp(320.0, 420.0);
    final colorScheme = Theme.of(context).colorScheme;

    return Stack(
      children: [
        // 底层终端内容
        Positioned.fill(child: widget.child),

        // FAB 悬浮按钮
        if (!_panelOpen)
          Positioned(
            right: 20,
            bottom: 24,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                if (_showFirstUseHint)
                  Container(
                    margin: const EdgeInsets.only(bottom: 8),
                    padding:
                        const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                    decoration: BoxDecoration(
                      color: colorScheme.inverseSurface.withValues(alpha: 0.88),
                      borderRadius: BorderRadius.circular(12),
                    ),
                    child: Text(
                      '点我可以智能生成命令',
                      style: Theme.of(context).textTheme.bodySmall?.copyWith(
                            color: colorScheme.onInverseSurface,
                          ),
                    ),
                  ),
                FloatingActionButton(
                  key: const Key('smart-terminal-fab'),
                  heroTag: 'smart_terminal_fab',
                  onPressed: _openPanel,
                  backgroundColor: const Color(0xFF1F5EFF),
                  child: const Icon(Icons.auto_awesome, color: Colors.white),
                ),
              ],
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
              ),
            ),
          ),
        ),
      ],
    );
  }
}
