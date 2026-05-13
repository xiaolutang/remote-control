import 'dart:convert';

import '../models/feedback_model.dart';
import '../utils/platform_utils.dart';
import 'api_service_base.dart';
import 'app_logger.dart';

/// 反馈提交服务
class FeedbackService extends ApiServiceBase {
  final String token;
  final String sessionId;

  static final AppLogger _log = AppLogger('Feedback');

  FeedbackService({
    required super.serverUrl,
    required this.token,
    required this.sessionId,
    super.client,
  });

  /// 提交反馈
  ///
  /// 自动附加 platform 和 appVersion。
  /// 成功返回 [FeedbackResponse]，失败抛出异常。
  Future<FeedbackResponse> submit(
    FeedbackCategory category,
    String description,
  ) async {
    final request = FeedbackSubmitRequest(
      sessionId: sessionId,
      category: category,
      description: description,
      platform: getPlatform(),
      appVersion: _appVersion,
    );

    _log.info('Submitting ${category.name}: $description');

    final response = await client.post(
      Uri.parse('$httpUrl/api/feedback'),
      headers: authHeaders(token),
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

  /// 轻量级反馈提交（best-effort，不抛异常）。
  ///
  /// 用于 Agent 面板中的快捷反馈（点赞/点踩/举报），成功返回 true。
  Future<bool> submitQuick({
    required String feedbackType,
    String? description,
    String? terminalId,
    String? resultEventId,
  }) async {
    final payload = <String, dynamic>{
      'session_id': sessionId,
      'category': 'other',
      'description': description ?? feedbackType,
      'terminal_id': terminalId ?? '',
      'feedback_type': feedbackType,
    };
    if (resultEventId != null) {
      payload['result_event_id'] = resultEventId;
    }
    try {
      final response = await client.post(
        Uri.parse('$httpUrl/api/feedback'),
        headers: authHeaders(token),
        body: jsonEncode(payload),
      );
      return response.statusCode == 200;
    } catch (e) {
      _log.debug('submitQuick failed: $e');
      return false;
    }
  }
}

/// 应用版本号（预留，后续从 package_info_plus 获取）
const String _appVersion = '1.0.0';
