import 'package:flutter/material.dart';

/// 反馈分类枚举
enum FeedbackCategory {
  connection,
  terminal,
  crash,
  suggestion,
  other,
}

/// 反馈分类扩展方法
extension FeedbackCategoryX on FeedbackCategory {
  /// 中文显示名
  String get displayName {
    switch (this) {
      case FeedbackCategory.connection:
        return '连接问题';
      case FeedbackCategory.terminal:
        return '终端问题';
      case FeedbackCategory.crash:
        return '崩溃';
      case FeedbackCategory.suggestion:
        return '功能建议';
      case FeedbackCategory.other:
        return '其他';
    }
  }

  /// 对应图标
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

/// 反馈提交请求模型
class FeedbackSubmitRequest {
  const FeedbackSubmitRequest({
    required this.sessionId,
    required this.category,
    required this.description,
    this.platform,
    this.appVersion,
  });

  final String sessionId;
  final FeedbackCategory category;
  final String description;
  final String? platform;
  final String? appVersion;

  Map<String, dynamic> toJson() => {
        'session_id': sessionId,
        'category': category.name,
        'description': description,
        if (platform != null) 'platform': platform,
        if (appVersion != null) 'app_version': appVersion,
      };
}

/// 反馈响应模型
class FeedbackResponse {
  const FeedbackResponse({
    required this.feedbackId,
    required this.createdAt,
  });

  final String feedbackId;
  final String createdAt;

  factory FeedbackResponse.fromJson(Map<String, dynamic> json) {
    return FeedbackResponse(
      feedbackId: json['feedback_id'] as String? ?? '',
      createdAt: json['created_at'] as String? ?? '',
    );
  }
}
