import 'dart:convert';

import 'package:http/http.dart' as http;

import '../models/feedback_model.dart';
import '../utils/platform_utils.dart';
import 'app_logger.dart';
import 'http_client_factory.dart';
import 'server_url_helper.dart';

/// 反馈提交服务
class FeedbackService {
  final String serverUrl;
  final String token;
  final String sessionId;

  final http.Client _client;

  static final AppLogger _log = AppLogger('Feedback');

  FeedbackService({
    required this.serverUrl,
    required this.token,
    required this.sessionId,
    http.Client? client,
  }) : _client = client ?? HttpClientFactory.create();

  /// 将 WebSocket URL 转换为 HTTP URL
  String _getHttpUrl() => serverUrlToHttpBase(serverUrl);

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
      platform: getPlatform(),
      appVersion: _appVersion,
    );

    _log.info('Submitting ${category.name}: $description');

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
      _log.info('Submitted successfully: ${data['feedback_id']}');
      return FeedbackResponse.fromJson(data);
    } else {
      _log.error('Submit failed: ${response.statusCode}');
      throw Exception(data['detail'] ?? '反馈提交失败');
    }
  }
}

/// 应用版本号（预留，后续从 package_info_plus 获取）
const String _appVersion = '1.0.0';
