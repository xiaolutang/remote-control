import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

import '../models/scheduled_task.dart';
import '../services/scheduled_task_service.dart';
import 'design_tokens.dart';
import 'snack_bar_helper.dart';

/// 定时发送选项菜单。
///
/// 弹出带文本输入框的定时选项，提供快捷时间和自定义时间选项。
/// 选择后通过 ScheduledTaskService.create() 创建任务。
///
/// [textContent] 可选：如果提供则直接使用，否则显示输入框让用户填写。
Future<bool> showScheduleBottomSheet({
  required BuildContext context,
  required String token,
  required String sessionId,
  required String terminalId,
  String? textContent,
  required String serverUrl,
  http.Client? client,
}) async {
  final service = ScheduledTaskService(
    serverUrl: serverUrl,
    client: client,
  );

  final result = await showModalBottomSheet<_ScheduleResult>(
    context: context,
    backgroundColor: Colors.transparent,
    isScrollControlled: true,
    builder: (ctx) {
      return _ScheduleBottomSheetContent(
        initialText: textContent,
        onSelect: (r) => Navigator.pop(ctx, r),
      );
    },
  );

  if (result == null) return false;

  try {
    // 追加 \r 以模拟按下 Enter 键
    final textWithEnter = result.textContent.endsWith('\r')
        ? result.textContent
        : '${result.textContent}\r';
    await service.create(
      token: token,
      sessionId: sessionId,
      terminalId: terminalId,
      textContent: textWithEnter,
      executeAt: result.executeAt.toUtc().toIso8601String(),
      repeatType: result.repeatType,
    );
    if (context.mounted) {
      final timeLabel = _formatExecuteAt(result.executeAt);
      showAppSnackBar(context, '定时任务已创建：$timeLabel');
    }
    return true;
  } on ScheduledTaskException catch (e) {
    if (context.mounted) {
      showAppSnackBar(context, e.message);
    }
    return false;
  }
}

String _formatExecuteAt(DateTime dt) {
  final time = '${dt.hour.toString().padLeft(2, '0')}:${dt.minute.toString().padLeft(2, '0')}';
  return '${dt.month}月${dt.day}日 $time';
}

class _ScheduleBottomSheetContent extends StatefulWidget {
  final String? initialText;
  final ValueChanged<_ScheduleResult> onSelect;

  const _ScheduleBottomSheetContent({
    this.initialText,
    required this.onSelect,
  });

  @override
  State<_ScheduleBottomSheetContent> createState() =>
      _ScheduleBottomSheetContentState();
}

class _ScheduleBottomSheetContentState
    extends State<_ScheduleBottomSheetContent> {
  late final TextEditingController _textController;
  bool _hasText = false;
  String? _expandedTile; // null | 'custom' | 'daily'
  int _selectedHour = 0;
  int _selectedMinute = 0;
  int _selectedDayOffset = 0;
  FixedExtentScrollController? _hourController;
  FixedExtentScrollController? _minuteController;

  @override
  void initState() {
    super.initState();
    _textController = TextEditingController(text: widget.initialText ?? '');
    _hasText = _textController.text.isNotEmpty;
    _textController.addListener(() {
      final hasText = _textController.text.isNotEmpty;
      if (hasText != _hasText) setState(() => _hasText = hasText);
    });
    _syncTimeToNow();
  }

  void _syncTimeToNow() {
    final now = TimeOfDay.now();
    _selectedHour = now.hour;
    _selectedMinute = now.minute;
    _selectedDayOffset = 0;
  }

  @override
  void dispose() {
    _textController.dispose();
    _hourController?.dispose();
    _minuteController?.dispose();
    super.dispose();
  }

  void _toggleTile(String tile) {
    setState(() {
      if (_expandedTile == tile) {
        _expandedTile = null;
        _hourController?.dispose();
        _hourController = null;
        _minuteController?.dispose();
        _minuteController = null;
      } else {
        _expandedTile = tile;
        _syncTimeToNow();
        _hourController?.dispose();
        _minuteController?.dispose();
        _hourController = FixedExtentScrollController(initialItem: _selectedHour);
        _minuteController = FixedExtentScrollController(initialItem: _selectedMinute);
      }
    });
  }

  void _confirmExpanded(ScheduledTaskRepeatType repeatType) {
    final now = DateTime.now();
    var executeAt = DateTime(
      now.year, now.month, now.day,
      _selectedHour, _selectedMinute,
    ).add(Duration(days: _selectedDayOffset));
    if (_selectedDayOffset == 0 && executeAt.isBefore(now)) {
      executeAt = executeAt.add(const Duration(days: 1));
    }
    widget.onSelect(_ScheduleResult(
      textContent: _textController.text,
      executeAt: executeAt,
      repeatType: repeatType,
    ));
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colorScheme = theme.colorScheme;

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
              offset: const Offset(0, 12),
            ),
          ],
        ),
        child: SingleChildScrollView(
          padding: EdgeInsets.fromLTRB(
            16, 12, 16, 20 + MediaQuery.of(context).viewInsets.bottom,
          ),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              _dragHandle(colorScheme),
              const SizedBox(height: 16),
              Text(
                '定时发送',
                style: theme.textTheme.titleLarge?.copyWith(
                  color: colorScheme.onSurface,
                  fontSize: 20,
                  fontWeight: FontWeight.w700,
                ),
              ),
              if (widget.initialText == null) ...[
                const SizedBox(height: 4),
                Text(
                  '输入命令，选择一个执行时间。',
                  style: theme.textTheme.bodySmall?.copyWith(
                    color: colorScheme.onSurfaceVariant,
                    fontSize: 13,
                    height: 1.35,
                  ),
                ),
                const SizedBox(height: 16),
                TextField(
                  controller: _textController,
                  autofocus: true,
                  maxLines: 2,
                  minLines: 1,
                  decoration: InputDecoration(
                    hintText: '输入要定时发送的命令...',
                    border: OutlineInputBorder(
                      borderRadius: AppRadius.buttonBorder,
                    ),
                    enabledBorder: OutlineInputBorder(
                      borderRadius: AppRadius.buttonBorder,
                      borderSide: BorderSide(
                        color: subtleBorderColor(colorScheme),
                      ),
                    ),
                    focusedBorder: OutlineInputBorder(
                      borderRadius: AppRadius.buttonBorder,
                      borderSide: BorderSide(
                        color: colorScheme.primary,
                        width: 1.5,
                      ),
                    ),
                    filled: true,
                    fillColor: colorScheme.surface,
                    contentPadding: const EdgeInsets.symmetric(
                      horizontal: 16, vertical: 14,
                    ),
                  ),
                ),
              ],
              const SizedBox(height: 20),
              _buildSectionLabel(context, '快捷时间'),
              const SizedBox(height: 10),
              Row(
                children: [
                  _quickTimeChip('5 分钟后', const Duration(minutes: 5)),
                  const SizedBox(width: 8),
                  _quickTimeChip('30 分钟后', const Duration(minutes: 30)),
                  const SizedBox(width: 8),
                  _quickTimeChip('1 小时后', const Duration(hours: 1)),
                ],
              ),
              const SizedBox(height: 20),
              _buildSectionLabel(context, '更多选项'),
              const SizedBox(height: 10),
              // 自定义时间
              _ExpandableTile(
                icon: Icons.access_time,
                label: '自定义时间',
                subtitle: '选择具体的日期和时间',
                expanded: _expandedTile == 'custom',
                enabled: _hasText,
                onTap: () => _toggleTile('custom'),
                expandedContent: _expandedTile == 'custom'
                    ? _buildCustomTimeContent(context)
                    : const SizedBox.shrink(),
              ),
              const SizedBox(height: 8),
              // 每日重复
              _ExpandableTile(
                icon: Icons.repeat,
                label: '每日重复',
                subtitle: '每天在同一时间自动执行',
                expanded: _expandedTile == 'daily',
                enabled: _hasText,
                onTap: () => _toggleTile('daily'),
                expandedContent: _expandedTile == 'daily'
                    ? _buildDailyTimeContent(context)
                    : const SizedBox.shrink(),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildCustomTimeContent(BuildContext context) {
    final theme = Theme.of(context);
    final colorScheme = theme.colorScheme;
    return Column(
      children: [
        const SizedBox(height: 12),
        // 日期条
        SizedBox(
          height: 56,
          child: ListView.separated(
            scrollDirection: Axis.horizontal,
            itemCount: 7,
            separatorBuilder: (_, __) => const SizedBox(width: 6),
            itemBuilder: (_, i) {
              final selected = _selectedDayOffset == i;
              final date = DateTime.now().add(Duration(days: i));
              final weekday = _weekdayLabel(date.weekday);
              return GestureDetector(
                onTap: () => setState(() => _selectedDayOffset = i),
                child: Container(
                  width: 56,
                  decoration: BoxDecoration(
                    color: selected ? colorScheme.primary : colorScheme.surface,
                    borderRadius: AppRadius.cardBorder,
                    border: Border.all(
                      color: selected
                          ? colorScheme.primary
                          : subtleBorderColor(colorScheme),
                    ),
                  ),
                  child: Column(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      Text(
                        i == 0 ? '今天' : i == 1 ? '明天' : '${date.month}/${date.day}',
                        style: TextStyle(
                          fontSize: 11,
                          fontWeight: FontWeight.w600,
                          color: selected
                              ? colorScheme.onPrimary
                              : colorScheme.onSurface,
                        ),
                      ),
                      if (i > 1) ...[
                        const SizedBox(height: 2),
                        Text(
                          weekday,
                          style: TextStyle(
                            fontSize: 10,
                            color: selected
                                ? colorScheme.onPrimary.withValues(alpha: 0.7)
                                : colorScheme.onSurfaceVariant,
                          ),
                        ),
                      ],
                    ],
                  ),
                ),
              );
            },
          ),
        ),
        const SizedBox(height: 12),
        // 时间滚轮
        _buildTimeWheels(theme, colorScheme),
        const SizedBox(height: 12),
        _buildConfirmButton(
          colorScheme: colorScheme,
          label: '确认创建',
          onPressed: () => _confirmExpanded(ScheduledTaskRepeatType.once),
        ),
      ],
    );
  }

  Widget _buildDailyTimeContent(BuildContext context) {
    final theme = Theme.of(context);
    final colorScheme = theme.colorScheme;
    return Column(
      children: [
        const SizedBox(height: 12),
        _buildTimeWheels(theme, colorScheme),
        const SizedBox(height: 12),
        _buildConfirmButton(
          colorScheme: colorScheme,
          label: '确认每日重复',
          onPressed: () => _confirmExpanded(ScheduledTaskRepeatType.daily),
        ),
      ],
    );
  }

  Widget _buildTimeWheels(ThemeData theme, ColorScheme colorScheme) {
    return Row(
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        _buildWheel(
          isHour: true,
          itemCount: 24,
          formatLabel: (i) => i.toString().padLeft(2, '0'),
          onChanged: (v) => setState(() => _selectedHour = v),
          colorScheme: colorScheme,
        ),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 8),
          child: Text(':',
              style: theme.textTheme.headlineMedium?.copyWith(
                fontWeight: FontWeight.w600,
                color: colorScheme.onSurface,
              )),
        ),
        _buildWheel(
          isHour: false,
          itemCount: 60,
          formatLabel: (i) => i.toString().padLeft(2, '0'),
          onChanged: (v) => setState(() => _selectedMinute = v),
          colorScheme: colorScheme,
        ),
      ],
    );
  }

  Widget _buildWheel({
    required bool isHour,
    required int itemCount,
    required String Function(int) formatLabel,
    required ValueChanged<int> onChanged,
    required ColorScheme colorScheme,
  }) {
    final controller = isHour ? _hourController! : _minuteController!;
    return SizedBox(
      width: 72,
      height: 160,
      child: CupertinoPicker(
        scrollController: controller,
        itemExtent: 36,
        diameterRatio: 1.2,
        squeeze: 1.0,
        useMagnifier: true,
        magnification: 1.1,
        onSelectedItemChanged: onChanged,
        children: List.generate(itemCount, (i) {
          return Center(
            child: Text(
              formatLabel(i),
              style: TextStyle(
                fontSize: 20,
                fontWeight: FontWeight.w600,
                color: colorScheme.onSurface,
              ),
            ),
          );
        }),
      ),
    );
  }

  static Widget _buildConfirmButton({
    required ColorScheme colorScheme,
    required String label,
    required VoidCallback onPressed,
  }) {
    return SizedBox(
      width: double.infinity,
      child: FilledButton(
        style: FilledButton.styleFrom(
          backgroundColor: colorScheme.primary,
          foregroundColor: colorScheme.onPrimary,
          padding: const EdgeInsets.symmetric(vertical: 12),
          shape: RoundedRectangleBorder(
            borderRadius: AppRadius.buttonBorder,
          ),
        ),
        onPressed: onPressed,
        child: Text(label,
            style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 14)),
      ),
    );
  }

  static String _weekdayLabel(int weekday) {
    const labels = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'];
    return labels[weekday - 1];
  }

  Widget _quickTimeChip(String label, Duration offset) {
    return Expanded(
      child: _TimeChip(
        label: label,
        icon: Icons.timer_outlined,
        enabled: _hasText,
        onTap: () => widget.onSelect(_ScheduleResult(
          textContent: _textController.text,
          executeAt: DateTime.now().add(offset),
          repeatType: ScheduledTaskRepeatType.once,
        )),
      ),
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

  Widget _buildSectionLabel(BuildContext context, String title) {
    final theme = Theme.of(context);
    final colorScheme = theme.colorScheme;
    return Align(
      alignment: Alignment.centerLeft,
      child: Text(
        title,
        style: theme.textTheme.labelMedium?.copyWith(
          color: colorScheme.primary,
          fontSize: 12,
          fontWeight: FontWeight.w700,
          letterSpacing: 0.4,
        ),
      ),
    );
  }
}

// ─── 内联可展开 Tile ────────────────────────────────────────

class _ExpandableTile extends StatelessWidget {
  final IconData icon;
  final String label;
  final String subtitle;
  final bool expanded;
  final bool enabled;
  final VoidCallback onTap;
  final Widget expandedContent;

  const _ExpandableTile({
    required this.icon,
    required this.label,
    required this.subtitle,
    required this.expanded,
    required this.enabled,
    required this.onTap,
    required this.expandedContent,
  });

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colorScheme = theme.colorScheme;
    final active = enabled && expanded;

    return Material(
      color: active
          ? colorScheme.surface
          : enabled
              ? colorScheme.surface
              : colorScheme.surfaceContainerHighest,
      borderRadius: AppRadius.buttonBorder,
      child: Container(
        decoration: BoxDecoration(
          borderRadius: AppRadius.buttonBorder,
          border: active
              ? Border.all(color: colorScheme.primary.withValues(alpha: 0.3))
              : null,
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            // 标题行
            InkWell(
              borderRadius: AppRadius.buttonBorder,
              onTap: enabled ? onTap : null,
              child: Padding(
                padding: const EdgeInsets.fromLTRB(16, 14, 12, 14),
                child: Row(
                  children: [
                    Icon(icon,
                        size: 20,
                        color: enabled
                            ? colorScheme.primary
                            : colorScheme.onSurface.withValues(alpha: 0.3)),
                    const SizedBox(width: 14),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(label, style: theme.textTheme.titleSmall?.copyWith(
                            fontWeight: FontWeight.w600,
                            color: enabled
                                ? colorScheme.onSurface
                                : colorScheme.onSurface.withValues(alpha: 0.3),
                          )),
                          const SizedBox(height: 3),
                          Text(subtitle, style: theme.textTheme.bodySmall?.copyWith(
                            color: enabled
                                ? colorScheme.onSurfaceVariant
                                : colorScheme.onSurfaceVariant.withValues(alpha: 0.3),
                            fontSize: 12,
                            height: 1.3,
                          )),
                        ],
                      ),
                    ),
                    AnimatedRotation(
                      turns: expanded ? 0.25 : 0,
                      duration: const Duration(milliseconds: 200),
                      child: Icon(Icons.chevron_right,
                          size: 18,
                          color: enabled
                              ? colorScheme.onSurfaceVariant
                              : colorScheme.onSurface.withValues(alpha: 0.3)),
                    ),
                  ],
                ),
              ),
            ),
            // 展开内容
            if (expanded) ...[
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 0, 16, 14),
                child: expandedContent,
              ),
            ],
          ],
        ),
      ),
    );
  }
}

// ─── 快捷时间 Chip ──────────────────────────────────────────

class _TimeChip extends StatelessWidget {
  final String label;
  final IconData icon;
  final bool enabled;
  final VoidCallback onTap;

  const _TimeChip({
    required this.label,
    required this.icon,
    required this.enabled,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final colorScheme = Theme.of(context).colorScheme;
    return Material(
      color: enabled
          ? colorScheme.surface
          : colorScheme.surfaceContainerHighest,
      borderRadius: AppRadius.cardBorder,
      child: InkWell(
        borderRadius: AppRadius.cardBorder,
        onTap: enabled ? onTap : null,
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 14),
          decoration: BoxDecoration(
            borderRadius: AppRadius.cardBorder,
            border: Border.all(
              color: enabled
                  ? subtleBorderColor(colorScheme)
                  : colorScheme.outlineVariant.withValues(alpha: 0.06),
            ),
          ),
          child: Column(
            children: [
              Icon(icon,
                  size: 20,
                  color: enabled
                      ? colorScheme.primary
                      : colorScheme.onSurface.withValues(alpha: 0.3)),
              const SizedBox(height: 6),
              Text(
                label,
                textAlign: TextAlign.center,
                style: TextStyle(
                  fontSize: 12,
                  fontWeight: FontWeight.w600,
                  color: enabled
                      ? colorScheme.onSurface
                      : colorScheme.onSurface.withValues(alpha: 0.3),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

// ─── 结果数据 ───────────────────────────────────────────────

class _ScheduleResult {
  final String textContent;
  final DateTime executeAt;
  final ScheduledTaskRepeatType repeatType;

  _ScheduleResult({
    required this.textContent,
    required this.executeAt,
    required this.repeatType,
  });
}
