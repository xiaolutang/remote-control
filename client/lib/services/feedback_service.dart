import 'dart:convert';
import 'dart:io' show Platform;

import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;

import '../models/feedback_model.dart';

/// 反馈提交服务
class FeedbackService {
  final String serverUrl;
  final String token;
  final String sessionId;

  final http.Client _client;

  FeedbackService({
    required this.serverUrl,
    required this.token,
    required this.sessionId,
    http.Client? client,
  }) : _client = client ?? http.Client();

  /// 将 WebSocket URL 转换为 HTTP URL
  String _getHttpUrl() {
    if (serverUrl.startsWith('ws://')) {
      return serverUrl.replaceFirst('ws://', 'http://');
    } else if (serverUrl.startsWith('wss://')) {
      return serverUrl.replaceFirst('wss://', 'https://');
    }
    return serverUrl;
  }

  /// 获取当前平台标识
  String _getPlatform() {
    if (Platform.isAndroid) return 'android';
    if (Platform.isIOS) return 'ios';
    if (Platform.isMacOS) return 'macos';
    if (Platform.isWindows) return 'windows';
    if (Platform.isLinux) return 'linux';
    return 'unknown';
  }

  /// 提交反馈
  ///
  /// 自动附加 platform 和 appVersion。
  /// 成功返回 [FeedbackResponse]，失败抛出异常。
  Future<FeedbackResponse> submit(
    FeedbackCategory category,
    String description,
  ) async {
    final httpUrl = _getHttpUrl();

    final request = FeedbackSubmitRequest(
      sessionId: sessionId,
      category: category,
      description: description,
      platform: _getPlatform(),
      appVersion: _appVersion,
    );

    debugPrint('[Feedback] Submitting ${category.name}: $description');

    final response = await _client.post(
      Uri.parse('$httpUrl/api/feedback'),
      headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer $token',
      },
      body: jsonEncode(request.toJson()),
    );

    final data = jsonDecode(response.body) as Map<String, dynamic>;

    if (response.statusCode == 200) {
      debugPrint('[Feedback] Submitted successfully: ${data['feedback_id']}');
      return FeedbackResponse.fromJson(data);
    } else {
      debugPrint('[Feedback] Submit failed: ${response.statusCode}');
      throw Exception(data['detail'] ?? '反馈提交失败');
    }
  }
}

/// 应用版本号（预留，后续从 package_info_plus 获取）
const String _appVersion = '1.0.0';
