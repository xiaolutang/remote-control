import 'package:flutter/material.dart';

/// A mixin that provides [_scheduleScrollToLatest] functionality.
///
/// Attach to any [State] or mixin that has access to a [ScrollController]
/// and is [mounted]. Call [scheduleScrollToLatest] after content changes
/// that should auto-scroll to the bottom.
///
/// Usage:
/// ```dart
/// class _MyState extends State<MyWidget> with ScrollToLatestMixin {
///   final _scrollController = ScrollController();
///
///   void _onContentChanged() {
///     scheduleScrollToLatest(_scrollController);
///   }
/// }
/// ```
mixin ScrollToLatestMixin {
  bool get mounted;

  /// Schedules a scroll to [maxScrollExtent] after the next frame.
  ///
  /// Safe to call even when [controller] has no clients or the widget
  /// is no longer mounted – both conditions are checked inside the
  /// post-frame callback.
  void scheduleScrollToLatest(
    ScrollController controller, {
    Duration duration = const Duration(milliseconds: 200),
    Curve curve = Curves.easeOut,
  }) {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted || !controller.hasClients) return;
      controller.animateTo(
        controller.position.maxScrollExtent,
        duration: duration,
        curve: curve,
      );
    });
  }
}
