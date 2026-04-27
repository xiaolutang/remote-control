import 'package:flutter/material.dart';
import 'package:xterm/xterm.dart';

/// Platform-adaptive terminal UI configuration.
///
/// Centralises every platform-driven UI decision that was previously
/// scattered across `terminal_screen.dart` as individual `isMobilePlatform`
/// checks.  The screen now reads a **single** `TerminalViewConfig` instance
/// instead of repeating the same boolean guard.
class TerminalViewConfig {
  const TerminalViewConfig._({
    required this.isMobile,
    required this.textStyle,
    required this.autofocus,
    required this.inputAction,
    required this.enableSuggestions,
    required this.enableIMEPersonalizedLearning,
    required this.showTuiSelector,
    required this.showShortcutBar,
    required this.resizeToAvoidBottomInset,
    required this.requestFocusAfterRetry,
  });

  /// Build the correct config for [platform].
  factory TerminalViewConfig.forPlatform(TargetPlatform platform) {
    final isMobile =
        platform == TargetPlatform.android || platform == TargetPlatform.iOS;
    return TerminalViewConfig._(
      isMobile: isMobile,
      textStyle: isMobile ? _mobileStyle(platform) : _desktopStyle,
      autofocus: !isMobile,
      inputAction: isMobile ? TextInputAction.send : TextInputAction.newline,
      enableSuggestions: isMobile,
      enableIMEPersonalizedLearning: isMobile,
      showTuiSelector: isMobile,
      showShortcutBar: isMobile,
      resizeToAvoidBottomInset: !isMobile,
      requestFocusAfterRetry: !isMobile,
    );
  }

  final bool isMobile;
  final TerminalStyle textStyle;
  final bool autofocus;
  final TextInputAction inputAction;
  final bool enableSuggestions;
  final bool enableIMEPersonalizedLearning;
  final bool showTuiSelector;
  final bool showShortcutBar;
  final bool resizeToAvoidBottomInset;
  final bool requestFocusAfterRetry;

  // ─── Styles ──────────────────────────────────────────────────────

  static const TerminalStyle _desktopStyle =
      TerminalStyle(fontSize: 14, fontFamily: 'monospace');

  static TerminalStyle _mobileStyle(TargetPlatform platform) {
    if (platform == TargetPlatform.iOS) {
      return const TerminalStyle(
        fontSize: 13,
        height: 1.2,
        fontFamily: 'Courier',
        fontFamilyFallback: [
          'Courier New',
          'Menlo',
          'Monaco',
          'SF Mono',
          'Noto Sans Mono CJK SC',
          'Noto Sans Mono CJK TC',
          'Noto Sans Mono CJK KR',
          'Noto Sans Mono CJK JP',
          'Noto Sans Mono CJK HK',
          'PingFang SC',
          'Hiragino Sans GB',
          'Noto Color Emoji',
          'Noto Sans Symbols',
          'monospace',
          'sans-serif',
        ],
      );
    }
    return const TerminalStyle(
      fontSize: 13,
      height: 1.2,
      fontFamily: 'monospace',
      fontFamilyFallback: [
        'Roboto Mono',
        'Noto Sans Mono',
        'Noto Sans Mono CJK SC',
        'Noto Sans Mono CJK TC',
        'Noto Sans Mono CJK KR',
        'Noto Sans Mono CJK JP',
        'Noto Sans Mono CJK HK',
        'Noto Color Emoji',
        'Noto Sans Symbols',
        'monospace',
        'sans-serif',
      ],
    );
  }
}
