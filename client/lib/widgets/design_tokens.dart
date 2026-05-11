import 'package:flutter/material.dart';

/// 设计 token -- 统一管理颜色、圆角等常量

/// 微弱边框色（outlineVariant 14% 透明度）
Color subtleBorderColor(ColorScheme colors) =>
    colors.outlineVariant.withValues(alpha: 0.14);

/// 标准卡片装饰（surfaceContainerLow + 圆角 12）
Decoration cardDecoration(ColorScheme colors) => BoxDecoration(
      color: colors.surfaceContainerLow,
      borderRadius: AppRadius.cardBorder,
    );

/// 圆角常量
class AppRadius {
  AppRadius._();

  static const double card = 12;
  static const double button = 18;
  static BorderRadius get cardBorder => BorderRadius.circular(card);
  static BorderRadius get buttonBorder => BorderRadius.circular(button);
}
