import 'package:flutter/material.dart';

import '../models/app_environment.dart';
import '../models/feedback_model.dart';

/// AppEnvironment 的 IconData 扩展。
///
/// 将 UI 依赖（Icons）从 models/ 层剥离到 widgets/ 层。
extension AppEnvironmentIconX on AppEnvironment {
  IconData get icon {
    switch (this) {
      case AppEnvironment.local:
        return Icons.lan_outlined;
      case AppEnvironment.direct:
        return Icons.route_outlined;
      case AppEnvironment.production:
        return Icons.cloud_outlined;
    }
  }
}

/// FeedbackCategory 的 IconData 扩展。
///
/// 将 UI 依赖（Icons）从 models/ 层剥离到 widgets/ 层。
extension FeedbackCategoryIconX on FeedbackCategory {
  IconData get icon {
    switch (this) {
      case FeedbackCategory.connection:
        return Icons.wifi_off;
      case FeedbackCategory.terminal:
        return Icons.terminal;
      case FeedbackCategory.crash:
        return Icons.bug_report;
      case FeedbackCategory.suggestion:
        return Icons.lightbulb_outline;
      case FeedbackCategory.other:
        return Icons.feedback;
    }
  }
}
