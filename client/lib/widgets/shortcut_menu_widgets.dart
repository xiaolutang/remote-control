import 'package:flutter/material.dart';

import '../models/shortcut_item.dart';
import '../models/terminal_shortcut.dart';

/// 快捷命令菜单 + 设置面板的纯 UI 组件。
///
/// 从 terminal_screen.dart 提取出来以降低屏幕文件行数。
class ShortcutMenuWidgets {
  ShortcutMenuWidgets._();

  /// 展示快捷命令菜单 bottom sheet。
  static Future<void> showMenu({
    required BuildContext context,
    required ShortcutLayout layout,
    required Future<void> Function(ShortcutItem) onItemPressed,
    required VoidCallback onOpenSettings,
    required VoidCallback releaseInputFocus,
  }) async {
    if (layout.smartItems.isEmpty) return;
    releaseInputFocus();

    await showModalBottomSheet<void>(
      context: context,
      backgroundColor: Colors.transparent,
      isScrollControlled: true,
      builder: (context) {
        final theme = Theme.of(context);
        final colorScheme = theme.colorScheme;
        final builtinItems = layout.smartItems
            .where((item) => item.source != ShortcutItemSource.project)
            .toList(growable: false);
        final projectItems = layout.smartItems
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
                _dragHandle(colorScheme),
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
                      onPressed: () {
                        Navigator.of(context).pop();
                        onOpenSettings();
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
                  _buildSection(
                    context: context,
                    title: 'Claude Code',
                    items: builtinItems,
                    onItemPressed: onItemPressed,
                  ),
                ],
                if (projectItems.isNotEmpty) ...[
                  const SizedBox(height: 20),
                  _buildSection(
                    context: context,
                    title: '当前项目',
                    items: projectItems,
                    onItemPressed: onItemPressed,
                  ),
                ],
              ],
            ),
          ),
        );
      },
    );
  }

  static Widget _dragHandle(ColorScheme colorScheme) => Center(
        child: Container(
          width: 40,
          height: 5,
          decoration: BoxDecoration(
            color: colorScheme.outlineVariant,
            borderRadius: BorderRadius.circular(999),
          ),
        ),
      );

  static Widget _buildSection({
    required BuildContext context,
    required String title,
    required List<ShortcutItem> items,
    required Future<void> Function(ShortcutItem) onItemPressed,
  }) {
    final theme = Theme.of(context);
    final colorScheme = theme.colorScheme;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(title,
            style: theme.textTheme.labelMedium?.copyWith(
                color: colorScheme.primary,
                fontSize: 12,
                fontWeight: FontWeight.w700,
                letterSpacing: 0.4)),
        const SizedBox(height: 10),
        for (var i = 0; i < items.length; i++) ...[
          _buildTile(context, items[i], onItemPressed),
          if (i != items.length - 1) const SizedBox(height: 10),
        ],
      ],
    );
  }

  static Widget _buildTile(
    BuildContext context,
    ShortcutItem item,
    Future<void> Function(ShortcutItem) onItemPressed,
  ) {
    final theme = Theme.of(context);
    final colorScheme = theme.colorScheme;
    return Material(
      color: colorScheme.surface,
      borderRadius: BorderRadius.circular(18),
      child: InkWell(
        borderRadius: BorderRadius.circular(18),
        onTap: () async {
          Navigator.of(context).pop();
          await onItemPressed(item);
        },
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
          child: Row(children: [
            Expanded(
              child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(item.label,
                        style: theme.textTheme.titleSmall?.copyWith(
                            color: colorScheme.onSurface,
                            fontSize: 15,
                            fontWeight: FontWeight.w600)),
                    const SizedBox(height: 4),
                    Text(description(item),
                        style: theme.textTheme.bodySmall?.copyWith(
                            color: colorScheme.onSurfaceVariant,
                            fontSize: 12,
                            height: 1.3)),
                  ]),
            ),
            const SizedBox(width: 12),
            item.pinned
                ? Icon(Icons.push_pin, color: colorScheme.primary, size: 18)
                : Icon(Icons.north_east,
                    color: colorScheme.onSurfaceVariant, size: 18),
          ]),
        ),
      ),
    );
  }

  /// 项目命令值的显示格式（去掉末尾 \r）
  static String projectCommandValue(ShortcutItem item) {
    final value = item.action.value;
    return value.endsWith('\r') ? value.substring(0, value.length - 1) : value;
  }

  static String description(ShortcutItem item) {
    if (item.description != null && item.description!.isNotEmpty) {
      return item.description!;
    }
    return item.source == ShortcutItemSource.project
        ? '发送当前项目的预设命令'
        : '发送预设快捷命令到终端';
  }

  /// 构建项目命令的 ShortcutItem
  static ShortcutItem buildProjectCommandItem({
    ShortcutItem? initialItem,
    required String label,
    required String command,
  }) {
    final normalizedCommand = command.trim();
    return ShortcutItem(
      id: initialItem?.id ??
          'project_${DateTime.now().microsecondsSinceEpoch}',
      label: label.trim(),
      source: ShortcutItemSource.project,
      section: ShortcutItemSection.smart,
      action: TerminalShortcutAction(
        type: TerminalShortcutActionType.sendText,
        value:
            normalizedCommand.endsWith('\r') ? normalizedCommand : '$normalizedCommand\r',
      ),
      order: initialItem?.order ?? 0,
      scope: ShortcutItemScope.project,
    );
  }

  /// 展示项目命令编辑器对话框
  static Future<ShortcutItem?> showProjectCommandEditor(
    BuildContext context, {
    ShortcutItem? initialItem,
  }) async {
    final labelController =
        TextEditingController(text: initialItem?.label ?? '');
    final commandController = TextEditingController(
      text: initialItem == null ? '' : projectCommandValue(initialItem),
    );

    final result = await showDialog<ShortcutItem>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(initialItem == null ? '新增项目命令' : '编辑项目命令'),
        content: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(
                key: const Key('project-command-label-field'),
                controller: labelController,
                decoration: const InputDecoration(
                    labelText: '名称', hintText: '例如：运行测试'),
                textInputAction: TextInputAction.next,
              ),
              const SizedBox(height: 12),
              TextField(
                key: const Key('project-command-value-field'),
                controller: commandController,
                decoration: const InputDecoration(
                    labelText: '命令', hintText: '例如：pnpm test'),
                textInputAction: TextInputAction.done,
                onSubmitted: (_) => Navigator.of(context).pop(
                  buildProjectCommandItem(
                    initialItem: initialItem,
                    label: labelController.text,
                    command: commandController.text,
                  ),
                ),
              ),
            ],
          ),
        ),
        actions: [
          TextButton(
              onPressed: () => Navigator.of(context).pop(),
              child: const Text('取消')),
          FilledButton(
            key: const Key('save-project-command'),
            onPressed: () => Navigator.of(context).pop(
              buildProjectCommandItem(
                initialItem: initialItem,
                label: labelController.text,
                command: commandController.text,
              ),
            ),
            child: const Text('保存'),
          ),
        ],
      ),
    );

    if (result == null) return null;
    if (result.label.trim().isEmpty ||
        projectCommandValue(result).trim().isEmpty) {
      return null;
    }
    return result;
  }

  /// 项目命令 tile widget
  static Widget buildProjectCommandTile({
    required BuildContext context,
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
        child: Row(children: [
          Expanded(
            child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(item.label,
                      style: theme.textTheme.titleSmall
                          ?.copyWith(fontWeight: FontWeight.w600)),
                  const SizedBox(height: 4),
                  Text(projectCommandValue(item),
                      style: theme.textTheme.bodySmall?.copyWith(
                          color: colorScheme.onSurfaceVariant)),
                ]),
          ),
          IconButton(
              key: Key('project-command-up-${item.id}'),
              tooltip: '上移 ${item.label}',
              onPressed: onMoveUp,
              icon: const Icon(Icons.keyboard_arrow_up)),
          IconButton(
              key: Key('project-command-down-${item.id}'),
              tooltip: '下移 ${item.label}',
              onPressed: onMoveDown,
              icon: const Icon(Icons.keyboard_arrow_down)),
          IconButton(
              key: Key('project-command-edit-${item.id}'),
              tooltip: '编辑 ${item.label}',
              onPressed: onEdit,
              icon: const Icon(Icons.edit_outlined)),
          IconButton(
              key: Key('project-command-delete-${item.id}'),
              tooltip: '删除 ${item.label}',
              onPressed: onDelete,
              icon: const Icon(Icons.delete_outline)),
        ]),
      ),
    );
  }

  // ─── Settings sheet shared widgets ──────────────────────────────

  static Widget buildNavModeSection({
    required ThemeData theme,
    required ColorScheme colorScheme,
    required ClaudeNavigationMode mode,
    required Future<void> Function(ClaudeNavigationMode) onUpdate,
  }) {
    return Material(
      color: colorScheme.surfaceContainerLow,
      borderRadius: BorderRadius.circular(18),
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Claude 导航模式',
                style: theme.textTheme.titleSmall
                    ?.copyWith(fontWeight: FontWeight.w700)),
            const SizedBox(height: 4),
            Text(
                '如果 Claude Code 列表里出现整页翻动，可以切到应用方向键模式再试。',
                style: theme.textTheme.bodySmall?.copyWith(
                    color: colorScheme.onSurfaceVariant, height: 1.35)),
            const SizedBox(height: 12),
            SegmentedButton<ClaudeNavigationMode>(
              showSelectedIcon: false,
              segments: const [
                ButtonSegment(
                    value: ClaudeNavigationMode.standard, label: Text('标准')),
                ButtonSegment(
                    value: ClaudeNavigationMode.application,
                    label: Text('应用')),
              ],
              selected: {mode},
              onSelectionChanged: (s) => onUpdate(s.first),
            ),
          ],
        ),
      ),
    );
  }

  static Widget buildEditableItemTile({
    required BuildContext context,
    required ShortcutItem item,
    required int index,
    required int total,
    required Future<void> Function(ShortcutItem, bool) toggleItem,
    required Future<void> Function(int, int) moveItem,
  }) {
    final theme = Theme.of(context);
    final colorScheme = theme.colorScheme;
    return Material(
      color: colorScheme.surfaceContainerLow,
      borderRadius: BorderRadius.circular(18),
      child: Padding(
        padding:
            const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
        child: Row(children: [
          Expanded(
            child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(item.label,
                      style: theme.textTheme.titleSmall?.copyWith(
                          fontWeight: FontWeight.w600)),
                  const SizedBox(height: 4),
                  Text(description(item),
                      style: theme.textTheme.bodySmall?.copyWith(
                          color: colorScheme.onSurfaceVariant, height: 1.3)),
                ]),
          ),
          IconButton(
            key: Key('shortcut-move-up-${item.id}'),
            tooltip: '上移 ${item.label}',
            onPressed: index == 0 ? null : () => moveItem(index, index - 1),
            icon: const Icon(Icons.keyboard_arrow_up),
          ),
          IconButton(
            key: Key('shortcut-move-down-${item.id}'),
            tooltip: '下移 ${item.label}',
            onPressed: index == total - 1
                ? null
                : () => moveItem(index, index + 1),
            icon: const Icon(Icons.keyboard_arrow_down),
          ),
          Switch(
            key: Key('shortcut-toggle-${item.id}'),
            value: item.enabled,
            onChanged: (v) => toggleItem(item, v),
          ),
        ]),
      ),
    );
  }

  static Widget buildProjectCommandsSection({
    required BuildContext context,
    required List<ShortcutItem> projectItems,
    required Future<void> Function([ShortcutItem?]) editProjectItem,
    required Future<void> Function(ShortcutItem) deleteProjectItem,
    required Future<void> Function(int, int) moveProjectItem,
  }) {
    final theme = Theme.of(context);
    final colorScheme = theme.colorScheme;
    return Material(
      color: colorScheme.surfaceContainerLow,
      borderRadius: BorderRadius.circular(18),
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(children: [
              Expanded(
                child: Text('当前项目命令',
                    style: theme.textTheme.titleSmall
                        ?.copyWith(fontWeight: FontWeight.w700)),
              ),
              TextButton.icon(
                onPressed: () => editProjectItem(),
                icon: const Icon(Icons.add, size: 18),
                label: const Text('新增'),
              ),
            ]),
            const SizedBox(height: 6),
            Text(
                '这些命令只属于当前项目，会在命令面板的"当前项目"分组里展示。',
                style: theme.textTheme.bodySmall?.copyWith(
                    color: colorScheme.onSurfaceVariant, height: 1.35)),
            if (projectItems.isEmpty) ...[
              const SizedBox(height: 12),
              Text('还没有项目命令，先新增一个常用命令。',
                  style: theme.textTheme.bodySmall?.copyWith(
                      color: colorScheme.onSurfaceVariant)),
            ] else ...[
              const SizedBox(height: 12),
              for (var pi = 0; pi < projectItems.length; pi++) ...[
                buildProjectCommandTile(
                  context: context,
                  item: projectItems[pi],
                  onMoveUp:
                      pi == 0 ? null : () => moveProjectItem(pi, pi - 1),
                  onMoveDown: pi == projectItems.length - 1
                      ? null
                      : () => moveProjectItem(pi, pi + 1),
                  onEdit: () => editProjectItem(projectItems[pi]),
                  onDelete: () => deleteProjectItem(projectItems[pi]),
                ),
                if (pi != projectItems.length - 1)
                  const SizedBox(height: 10),
              ],
            ],
          ],
        ),
      ),
    );
  }
}
