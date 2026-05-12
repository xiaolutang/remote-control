import 'package:flutter/material.dart';

/// 显示应用 SnackBar（自动清除旧的）
///
/// 先调用 [ScaffoldMessenger.clearSnackBars] 清除已有的 SnackBar，
/// 然后显示新的 SnackBar 消息。避免 SnackBar 堆积。
///
/// [context] BuildContext（需要是 Scaffold 的子级）
/// [message] 要显示的文本
/// [duration] SnackBar 显示时长，默认 2 秒
void showAppSnackBar(
  BuildContext context,
  String message, {
  Duration duration = const Duration(seconds: 2),
}) {
  final messenger = ScaffoldMessenger.of(context);
  messenger.clearSnackBars();
  messenger.showSnackBar(
    SnackBar(
      content: Text(message),
      duration: duration,
    ),
  );
}
