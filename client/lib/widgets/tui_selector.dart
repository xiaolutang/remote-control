import 'package:flutter/material.dart';

import 'mobile_bottom_inset.dart';

/// TUI 选项解析正则表达式（静态缓存）
class TuiPatterns {
  TuiPatterns._();

  /// 数字选项：1. xxx, 2. xxx, 1) xxx, 2) xxx
  static final RegExp numbered = RegExp(r'^\s*(\d)[.)]\s*(.+)$');

  /// [y/n] 选项
  static final RegExp yesNo = RegExp(r'\[([yY])/([nN])\]');

  /// 确认提示：Press Enter to continue
  static final RegExp confirm = RegExp(
    r'(Press|Hit)\s+(Enter|any key|return)',
    caseSensitive: false,
  );
}

/// TUI 选项模型
class TuiOption {
  /// 选项标识符（如 '1', 'y', 'n'）
  final String key;

  /// 选项显示文本
  final String label;

  /// 选项类型
  final TuiOptionType type;

  const TuiOption({
    required this.key,
    required this.label,
    required this.type,
  });
}

/// TUI 选项类型
enum TuiOptionType {
  /// 数字选项（1. xxx, 2. xxx）
  numbered,

  /// 是/否选项（[y/n]）
  yesNo,

  /// 确认选项（Press Enter to continue）
  confirm,
}

/// TUI 选项选择器组件
///
/// 解析终端输出中的选项模式，提供可触摸选择的按钮列表。
class TuiSelector extends StatefulWidget {
  /// 终端输出文本
  final String terminalOutput;

  /// 选择回调，参数为要发送的键
  final void Function(String key) onSelect;

  const TuiSelector({
    super.key,
    required this.terminalOutput,
    required this.onSelect,
  });

  @override
  State<TuiSelector> createState() => TuiSelectorState();

  /// 从终端输出中解析选项
  static List<TuiOption> parseOptions(String output) {
    final options = <TuiOption>[];
    final lines = output.split('\n');

    for (final line in lines) {
      // 匹配数字选项
      final numberedMatch = TuiPatterns.numbered.firstMatch(line);
      if (numberedMatch != null) {
        options.add(TuiOption(
          key: numberedMatch.group(1)!,
          label: numberedMatch.group(2)!.trim(),
          type: TuiOptionType.numbered,
        ));
      }

      // 匹配 [y/n] 选项
      if (TuiPatterns.yesNo.hasMatch(line)) {
        // 添加 Yes 选项
        if (options.where((o) => o.key.toLowerCase() == 'y').isEmpty) {
          options.add(const TuiOption(
            key: 'y',
            label: 'Yes',
            type: TuiOptionType.yesNo,
          ));
        }
        // 添加 No 选项
        if (options.where((o) => o.key.toLowerCase() == 'n').isEmpty) {
          options.add(const TuiOption(
            key: 'n',
            label: 'No',
            type: TuiOptionType.yesNo,
          ));
        }
      }

      // 匹配确认提示
      if (TuiPatterns.confirm.hasMatch(line)) {
        options.add(const TuiOption(
          key: '\r',
          label: 'Enter',
          type: TuiOptionType.confirm,
        ));
      }
    }

    // 去重
    final seen = <String>{};
    return options.where((option) {
      if (seen.contains(option.key)) {
        return false;
      }
      seen.add(option.key);
      return true;
    }).toList();
  }
}

class TuiSelectorState extends State<TuiSelector> {
  List<TuiOption> _currentOptions = [];

  @override
  void didUpdateWidget(TuiSelector oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.terminalOutput != oldWidget.terminalOutput) {
      _updateOptions();
    }
  }

  @override
  void initState() {
    super.initState();
    _updateOptions();
  }

  void _updateOptions() {
    setState(() {
      _currentOptions = TuiSelector.parseOptions(widget.terminalOutput);
    });
  }

  void _onOptionTap(TuiOption option) {
    widget.onSelect(option.key);
  }

  @override
  Widget build(BuildContext context) {
    if (_currentOptions.isEmpty) {
      return const SizedBox.shrink();
    }

    final mediaQuery = MediaQuery.of(context);
    final bottomInset = resolveMobileBottomInset(mediaQuery);

    return Container(
      decoration: BoxDecoration(
        color: Colors.grey[900],
        border: Border(
          top: BorderSide(color: Colors.grey[800]!),
        ),
      ),
      child: Padding(
        padding: EdgeInsets.fromLTRB(8, 4, 8, 8 + bottomInset),
        child: SingleChildScrollView(
          scrollDirection: Axis.horizontal,
          child: Row(
            children: _currentOptions.map((option) {
              return Padding(
                padding: const EdgeInsets.symmetric(horizontal: 4),
                child: _buildOptionButton(option),
              );
            }).toList(),
          ),
        ),
      ),
    );
  }

  Widget _buildOptionButton(TuiOption option) {
    Color buttonColor;
    IconData? icon;

    switch (option.type) {
      case TuiOptionType.yesNo:
        buttonColor = option.key.toLowerCase() == 'y'
            ? const Color.fromRGBO(76, 175, 80, 0.8) // Green 800
            : const Color.fromRGBO(244, 67, 54, 0.8); // Red
        icon = option.key.toLowerCase() == 'y' ? Icons.check : Icons.close;
        break;
      case TuiOptionType.confirm:
        buttonColor = const Color.fromRGBO(33, 150, 243, 0.8); // Blue
        icon = Icons.keyboard_return;
        break;
      case TuiOptionType.numbered:
        buttonColor = Colors.grey[800]!;
        break;
    }

    return Material(
      color: buttonColor,
      borderRadius: BorderRadius.circular(8),
      child: InkWell(
        onTap: () => _onOptionTap(option),
        borderRadius: BorderRadius.circular(8),
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              if (icon != null) ...[
                Icon(icon, size: 16, color: Colors.white),
                const SizedBox(width: 4),
              ],
              Text(
                option.key == '\r' ? 'Enter' : option.key.toUpperCase(),
                style: const TextStyle(
                  color: Colors.white,
                  fontWeight: FontWeight.bold,
                  fontSize: 12,
                ),
              ),
              if (option.label.isNotEmpty &&
                  option.type != TuiOptionType.yesNo) ...[
                const SizedBox(width: 4),
                Text(
                  option.label.length > 20
                      ? '${option.label.substring(0, 20)}...'
                      : option.label,
                  style: const TextStyle(
                    color: Color.fromRGBO(255, 255, 255, 0.8),
                    fontSize: 12,
                  ),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}
