import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import 'theme_controller.dart';

/// 显示主题选择器底部弹窗
///
/// 在多个 screen 中复用，避免重复代码。
Future<void> showThemePickerSheet(BuildContext context) async {
  final controller = context.read<ThemeController>();
  final selected = await showModalBottomSheet<ThemeMode>(
    context: context,
    builder: (context) {
      return SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const ListTile(title: Text('主题模式')),
            RadioListTile<ThemeMode>(
              title: const Text('跟随系统'),
              value: ThemeMode.system,
              groupValue: controller.themeMode,
              onChanged: (value) => Navigator.of(context).pop(value),
            ),
            RadioListTile<ThemeMode>(
              title: const Text('浅色'),
              value: ThemeMode.light,
              groupValue: controller.themeMode,
              onChanged: (value) => Navigator.of(context).pop(value),
            ),
            RadioListTile<ThemeMode>(
              title: const Text('深色'),
              value: ThemeMode.dark,
              groupValue: controller.themeMode,
              onChanged: (value) => Navigator.of(context).pop(value),
            ),
          ],
        ),
      );
    },
  );

  if (selected != null) {
    await controller.setThemeMode(selected);
  }
}
