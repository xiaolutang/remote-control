import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:rc_client/services/network_diagnostic_service.dart';

void main() {
  group('NetworkDiagnosticService', () {
    late HttpServer server;

    tearDown(() async {
      await server.close(force: true);
    });

    test('health returns status ok -> check succeeds', () async {
      server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      server.listen((request) async {
        expect(request.uri.path, '/health');
        request.response.statusCode = 200;
        request.response.headers.contentType = ContentType.json;
        request.response.write(jsonEncode({
          'status': 'ok',
          'service': 'rc-server',
        }));
        await request.response.close();
      });

      final report = await const NetworkDiagnosticService().run(
        serverUrl: 'ws://127.0.0.1:${server.port}',
      );

      expect(report.httpUrl, 'http://127.0.0.1:${server.port}');
      expect(report.checks[1].title, '健康检查');
      expect(report.checks[1].success, isTrue);
      expect(report.checks[2].title, '健康检查 (DIRECT)');
      expect(report.checks[2].success, isTrue);
    });

    test('health returns success false payload -> check fails', () async {
      server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      server.listen((request) async {
        expect(request.uri.path, '/health');
        request.response.statusCode = 200;
        request.response.headers.contentType = ContentType.json;
        request.response.write(jsonEncode({
          'code': 500,
          'msg': '404 NOT_FOUND',
          'success': false,
        }));
        await request.response.close();
      });

      final report = await const NetworkDiagnosticService().run(
        serverUrl: 'ws://127.0.0.1:${server.port}',
      );

      expect(report.checks[1].title, '健康检查');
      expect(report.checks[1].success, isFalse);
      expect(report.checks[2].title, '健康检查 (DIRECT)');
      expect(report.checks[2].success, isFalse);
    });
  });
}
