import 'dart:convert';

import 'package:http/http.dart' as http;

/// Mock HTTP Client for testing services.
///
/// Enqueue responses before invoking the method under test.
class MockHttpClient extends http.BaseClient {
  final List<_EnqueuedResponse> _responses = [];

  http.Request? _lastRequest;

  http.Request? get lastRequest => _lastRequest;

  void enqueueResponse(http.Response response) {
    _responses.add(_EnqueuedResponse(response));
  }

  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) async {
    if (request is http.Request) {
      _lastRequest = request;
    }
    if (_responses.isEmpty) {
      return http.StreamedResponse(
        Stream.value(utf8.encode('{}')),
        200,
      );
    }
    final enqueued = _responses.removeAt(0);
    return http.StreamedResponse(
      Stream.value(enqueued.response.bodyBytes),
      enqueued.response.statusCode,
      headers: enqueued.response.headers,
    );
  }
}

class _EnqueuedResponse {
  const _EnqueuedResponse(this.response);
  final http.Response response;
}
