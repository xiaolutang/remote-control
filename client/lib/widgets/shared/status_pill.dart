import 'package:flutter/material.dart';

/// A compact pill-shaped status indicator.
///
/// Two modes:
/// - **Icon mode**: pass [icon] + [label] to show icon + text.
/// - **Label-only mode**: pass [label] + [backgroundColor] + [textColor]
///   for a text-only pill with custom colors.
class StatusPill extends StatelessWidget {
  const StatusPill({
    super.key,
    required this.label,
    this.icon,
    this.backgroundColor,
    this.textColor,
    this.padding,
    this.borderRadius,
    this.textStyle,
  });

  /// Text displayed inside the pill.
  final String label;

  /// Optional leading icon. When provided the pill renders icon + label.
  final IconData? icon;

  /// Background color. Required in label-only mode; in icon mode defaults
  /// to `colorScheme.surface` at 75 % opacity.
  final Color? backgroundColor;

  /// Text / icon color. Required in label-only mode; in icon mode defaults
  /// to the default text / icon color.
  final Color? textColor;

  /// Override padding. Defaults vary by mode.
  final EdgeInsetsGeometry? padding;

  /// Override border radius. Defaults to circular(999).
  final BorderRadius? borderRadius;

  /// Override text style. Defaults to `labelSmall` with semi-bold weight.
  final TextStyle? textStyle;

  @override
  Widget build(BuildContext context) {
    final resolvedBorderRadius =
        borderRadius ?? BorderRadius.circular(999);

    if (icon != null) {
      // Icon mode
      final bg = backgroundColor ??
          Theme.of(context).colorScheme.surface.withValues(alpha: 0.75);
      final pad = padding ??
          const EdgeInsets.symmetric(horizontal: 10, vertical: 8);
      return Container(
        padding: pad,
        decoration: BoxDecoration(
          color: bg,
          borderRadius: resolvedBorderRadius,
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, size: 16, color: textColor),
            const SizedBox(width: 6),
            Text(label, style: TextStyle(color: textColor)),
          ],
        ),
      );
    }

    // Label-only mode
    assert(backgroundColor != null,
        'backgroundColor is required when icon is null');
    final pad = padding ??
        const EdgeInsets.symmetric(horizontal: 8, vertical: 4);
    return Container(
      padding: pad,
      decoration: BoxDecoration(
        color: backgroundColor,
        borderRadius: resolvedBorderRadius,
      ),
      child: Text(
        label,
        style: textStyle ??
            Theme.of(context).textTheme.labelSmall?.copyWith(
                  color: textColor,
                  fontWeight: FontWeight.w600,
                ),
      ),
    );
  }
}
