import 'package:flutter/material.dart';

/// 显示重命名对话框
///
/// 通用重命名对话框，用于设备名称编辑和终端标题编辑。
/// [context] BuildContext
/// [title] 对话框标题（如"编辑设备"、"编辑终端标题"）
/// [initialValue] 当前名称
/// [labelText] 输入框标签（如"设备名称"、"终端标题"）
/// [inputKey] 输入框的 Key（用于测试定位）
/// [submitKey] 提交按钮的 Key（用于测试定位）
/// [onConfirm] 确认回调，参数为新名称。
///   返回 true 表示成功（对话框关闭），返回 false 表示失败（对话框保持打开）。
Future<void> showRenameDialog({
  required BuildContext context,
  required String title,
  required String initialValue,
  required String labelText,
  required String inputKey,
  required String submitKey,
  required Future<bool> Function(String newName) onConfirm,
}) async {
  final controller = TextEditingController(text: initialValue);

  await showDialog<void>(
    context: context,
    builder: (dialogContext) {
      return AlertDialog(
        title: Text(title),
        content: SingleChildScrollView(
          child: TextField(
            key: Key(inputKey),
            controller: controller,
            decoration: InputDecoration(labelText: labelText),
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(),
            child: const Text('取消'),
          ),
          FilledButton(
            key: Key(submitKey),
            onPressed: () async {
              final success = await onConfirm(controller.text);
              if (!dialogContext.mounted) return;
              if (success) {
                Navigator.of(dialogContext).pop();
              }
            },
            child: const Text('保存'),
          ),
        ],
      );
    },
  );

  WidgetsBinding.instance.addPostFrameCallback((_) {
    controller.dispose();
  });
}
