import 'package:flutter/widgets.dart';

// F005: 桌面端键盘快捷键 - Intent 和 Action 定义
// Intent 类保持 public 以便测试通过 Actions.invoke 直接触发。
// Flutter Shortcuts 在 test 环境中 key event + modifier 分发不可靠，
// 这是 Flutter 社区推荐的可测试 Shortcuts 模式。

/// Cmd/Ctrl+1/2/3 切换终端
class SwitchTerminalIntent extends Intent {
  const SwitchTerminalIntent(this.index);

  final int index;
}

class SwitchTerminalAction extends Action<SwitchTerminalIntent> {
  SwitchTerminalAction({required this.onSwitch});

  final void Function(int index) onSwitch;

  @override
  Object? invoke(SwitchTerminalIntent intent) {
    onSwitch(intent.index);
    return null;
  }
}

/// Cmd/Ctrl+W 关闭当前终端
class CloseCurrentTerminalIntent extends Intent {
  const CloseCurrentTerminalIntent();
}

class CloseCurrentTerminalAction extends Action<CloseCurrentTerminalIntent> {
  CloseCurrentTerminalAction({required this.onClose});

  final void Function() onClose;

  @override
  Object? invoke(CloseCurrentTerminalIntent intent) {
    onClose();
    return null;
  }
}
