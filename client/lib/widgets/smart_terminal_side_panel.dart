import 'package:flutter/material.dart';

/// 侧滑式智能终端助手面板。
///
/// 在桌面端终端视图内以 FAB + 侧滑面板形式呈现，
/// 用于意图解析和命令注入。
///
/// 当前为骨架实现，仅渲染 child（终端内容），
/// 后续 F087 会在此处添加 FAB 和侧滑面板。
class SmartTerminalSidePanel extends StatelessWidget {
  const SmartTerminalSidePanel({
    super.key,
    required this.child,
  });

  /// 底层终端内容
  final Widget child;

  @override
  Widget build(BuildContext context) {
    return child;
  }
}
