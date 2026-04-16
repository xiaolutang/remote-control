import 'shortcut_item.dart';
import 'terminal_shortcut.dart';

class ClaudeCommandPack {
  const ClaudeCommandPack._();

  static ShortcutItem _cmd(String name, int order, String description) =>
      ShortcutItem(
        id: 'claude_$name',
        label: '/$name',
        source: ShortcutItemSource.builtin,
        section: ShortcutItemSection.smart,
        action: TerminalShortcutAction(
          type: TerminalShortcutActionType.sendText,
          value: '/$name\r',
        ),
        order: order,
        scope: ShortcutItemScope.project,
        description: description,
      );

  static final List<ShortcutItem> defaults = [
    _cmd('help', 10, '查看 Claude Code 可用命令和帮助入口'),
    _cmd('status', 20, '查看当前会话状态和上下文信息'),
    _cmd('clear', 30, '清理当前终端显示，保留会话继续操作'),
    _cmd('compact', 40, '压缩当前上下文，适合继续长会话'),
    _cmd('commit', 50, '提交当前代码改动'),
    _cmd('model', 60, '切换 AI 模型'),
    _cmd('fast', 70, '切换快速输出模式'),
    _cmd('doctor', 80, '诊断当前环境和配置'),
    _cmd('config', 90, '打开 Claude Code 设置'),
  ];

  static List<ShortcutItem> cloneDefaults() {
    return defaults.map((item) => item.copyWith()).toList(growable: false);
  }
}
