import 'package:flutter/material.dart';

double resolveMobileBottomInset(
  MediaQueryData mediaQuery, {
  bool keyboardOnly = false,
}) {
  if (mediaQuery.viewInsets.bottom > 0) {
    return mediaQuery.viewInsets.bottom;
  }
  if (keyboardOnly) {
    return 0;
  }
  return mediaQuery.padding.bottom > mediaQuery.systemGestureInsets.bottom
      ? mediaQuery.padding.bottom
      : mediaQuery.systemGestureInsets.bottom;
}
