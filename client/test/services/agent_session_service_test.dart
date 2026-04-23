import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:rc_client/models/agent_session_event.dart';
import 'package:rc_client/services/agent_session_service.dart';

void main() {
  group('AgentSessionService', () {
    const testServerUrl = 'wss://localhost:8888';
    const testHttpUrl = 'https://localhost:8888';
    const testToken = 'test-jwt-token';
    const testDeviceId = 'mbp-01';
    const testSessionId = 'sess-abc123';

    /// 构建 SSE 文本（event: xxx\ndata: xxx\n\n 格式）
    String buildSSE(List<MapEntry<String, String>> events) {
      final buffer = StringBuffer();
      for (final entry in events) {
        buffer.writeln('event: ${entry.key}');
        buffer.writeln('data: ${entry.value}');
        buffer.writeln();
      }
      return buffer.toString();
    }

    group('SSE 事件解析', () {
      test('解析 trace 事件', () async {
        final sseText = buildSSE([
          MapEntry('trace', jsonEncode({
            'tool': 'execute_command',
            'input_summary': 'ls ~',
            'output_summary': 'Desktop\nDocuments\n...',
          })),
        ]);

        final client = MockClient.streaming((request, bodyStream) async {
          return http.StreamedResponse(
            Stream.value(utf8.encode(sseText)),
            200,
            headers: const {'content-type': 'text/event-stream'},
          );
        });

        final service = AgentSessionService(
          serverUrl: testServerUrl,
          client: client,
        );

        final events = await service
            .runSession(
              deviceId: testDeviceId,
              intent: '列出主目录',
              token: testToken,
            )
            .toList();

        expect(events, hasLength(1));
        expect(events[0], isA<AgentTraceEvent>());
        final trace = events[0] as AgentTraceEvent;
        expect(trace.tool, 'execute_command');
        expect(trace.inputSummary, 'ls ~');
        expect(trace.outputSummary, 'Desktop\nDocuments\n...');
      });

      test('解析 question 事件', () async {
        final sseText = buildSSE([
          MapEntry('question', jsonEncode({
            'question': '选择项目',
            'options': ['project-a', 'project-b'],
            'multi_select': false,
          })),
        ]);

        final client = MockClient.streaming((request, bodyStream) async {
          return http.StreamedResponse(
            Stream.value(utf8.encode(sseText)),
            200,
            headers: const {'content-type': 'text/event-stream'},
          );
        });

        final service = AgentSessionService(
          serverUrl: testServerUrl,
          client: client,
        );

        final events = await service
            .runSession(
              deviceId: testDeviceId,
              intent: '进入项目',
              token: testToken,
            )
            .toList();

        expect(events, hasLength(1));
        expect(events[0], isA<AgentQuestionEvent>());
        final question = events[0] as AgentQuestionEvent;
        expect(question.question, '选择项目');
        expect(question.options, ['project-a', 'project-b']);
        expect(question.multiSelect, isFalse);
      });

      test('解析 result 事件', () async {
        final sseText = buildSSE([
          MapEntry('result', jsonEncode({
            'summary': '进入项目A',
            'steps': [
              {'id': 's1', 'label': '进入目录', 'command': 'cd ~/project-a'},
              {'id': 's2', 'label': '启动 Claude', 'command': 'claude'},
            ],
            'provider': 'agent',
            'source': 'recommended',
            'need_confirm': true,
            'aliases': {'project-a': '/Users/user/project-a'},
          })),
        ]);

        final client = MockClient.streaming((request, bodyStream) async {
          return http.StreamedResponse(
            Stream.value(utf8.encode(sseText)),
            200,
            headers: const {'content-type': 'text/event-stream'},
          );
        });

        final service = AgentSessionService(
          serverUrl: testServerUrl,
          client: client,
        );

        final events = await service
            .runSession(
              deviceId: testDeviceId,
              intent: '进入项目A',
              token: testToken,
            )
            .toList();

        expect(events, hasLength(1));
        expect(events[0], isA<AgentResultEvent>());
        final result = events[0] as AgentResultEvent;
        expect(result.summary, '进入项目A');
        expect(result.steps, hasLength(2));
        expect(result.steps[0].id, 's1');
        expect(result.steps[0].label, '进入目录');
        expect(result.steps[0].command, 'cd ~/project-a');
        expect(result.steps[1].command, 'claude');
        expect(result.provider, 'agent');
        expect(result.source, 'recommended');
        expect(result.needConfirm, isTrue);
        expect(result.aliases['project-a'], '/Users/user/project-a');
      });

      test('解析 error 事件', () async {
        final sseText = buildSSE([
          MapEntry('error', jsonEncode({
            'code': 'AGENT_OFFLINE',
            'message': '设备不在线',
          })),
        ]);

        final client = MockClient.streaming((request, bodyStream) async {
          return http.StreamedResponse(
            Stream.value(utf8.encode(sseText)),
            200,
            headers: const {'content-type': 'text/event-stream'},
          );
        });

        final service = AgentSessionService(
          serverUrl: testServerUrl,
          client: client,
        );

        final events = await service
            .runSession(
              deviceId: testDeviceId,
              intent: '测试错误',
              token: testToken,
            )
            .toList();

        expect(events, hasLength(1));
        expect(events[0], isA<AgentErrorEvent>());
        final error = events[0] as AgentErrorEvent;
        expect(error.code, 'AGENT_OFFLINE');
        expect(error.message, '设备不在线');
      });

      test('完整会话流程：trace → question → result', () async {
        final sseText = buildSSE([
          MapEntry('trace', jsonEncode({
            'tool': 'scan_projects',
            'input_summary': '扫描项目',
            'output_summary': '找到 2 个项目',
          })),
          MapEntry('trace', jsonEncode({
            'tool': 'read_context',
            'input_summary': '读取上下文',
            'output_summary': '已获取项目列表',
          })),
          MapEntry('question', jsonEncode({
            'question': '选择项目',
            'options': ['project-a', 'project-b'],
            'multi_select': false,
          })),
          MapEntry('result', jsonEncode({
            'summary': '进入 project-a',
            'steps': [
              {'id': 's1', 'label': '进入目录', 'command': 'cd ~/project-a'},
            ],
            'provider': 'agent',
            'source': 'recommended',
            'need_confirm': true,
            'aliases': {},
          })),
        ]);

        final client = MockClient.streaming((request, bodyStream) async {
          return http.StreamedResponse(
            Stream.value(utf8.encode(sseText)),
            200,
            headers: const {'content-type': 'text/event-stream'},
          );
        });

        final service = AgentSessionService(
          serverUrl: testServerUrl,
          client: client,
        );

        final events = await service
            .runSession(
              deviceId: testDeviceId,
              intent: '进入项目',
              token: testToken,
            )
            .toList();

        expect(events, hasLength(4));
        expect(events[0], isA<AgentTraceEvent>());
        expect(events[1], isA<AgentTraceEvent>());
        expect(events[2], isA<AgentQuestionEvent>());
        expect(events[3], isA<AgentResultEvent>());
      });
    });

    group('keepalive 注释帧', () {
      test('keepalive 注释帧不触发业务事件', () async {
        final sseText = 'event: trace\n'
            'data: {"tool":"scan","input_summary":"扫描","output_summary":"完成"}\n'
            '\n'
            ': keepalive\n'
            '\n'
            'event: result\n'
            'data: {"summary":"完成","steps":[],"provider":"agent","source":"recommended","need_confirm":false,"aliases":{}}\n'
            '\n';

        final client = MockClient.streaming((request, bodyStream) async {
          return http.StreamedResponse(
            Stream.value(utf8.encode(sseText)),
            200,
            headers: const {'content-type': 'text/event-stream'},
          );
        });

        final service = AgentSessionService(
          serverUrl: testServerUrl,
          client: client,
        );

        final events = await service
            .runSession(
              deviceId: testDeviceId,
              intent: '测试 keepalive',
              token: testToken,
            )
            .toList();

        // 只有 trace 和 result，keepalive 不产生事件
        expect(events, hasLength(2));
        expect(events[0], isA<AgentTraceEvent>());
        expect(events[1], isA<AgentResultEvent>());
      });
    });

    group('respond HTTP 调用', () {
      test('成功发送回复', () async {
        final client = MockClient((request) async {
          expect(request.method, 'POST');
          expect(
            request.url.toString(),
            '$testHttpUrl/api/runtime/devices/$testDeviceId/assistant/agent/$testSessionId/respond',
          );
          expect(
            request.headers['Authorization'],
            'Bearer $testToken',
          );
          final body = jsonDecode(request.body) as Map<String, dynamic>;
          expect(body['answer'], 'project-a');
          return http.Response(jsonEncode({'ok': true}), 200);
        });

        final service = AgentSessionService(
          serverUrl: testServerUrl,
          client: client,
        );

        final result = await service.respond(
          deviceId: testDeviceId,
          sessionId: testSessionId,
          answer: 'project-a',
          token: testToken,
        );

        expect(result, isTrue);
      });

      test('回复失败抛出异常', () async {
        final client = MockClient((request) async {
          return http.Response('Internal Server Error', 500);
        });

        final service = AgentSessionService(
          serverUrl: testServerUrl,
          client: client,
        );

        expect(
          () => service.respond(
            deviceId: testDeviceId,
            sessionId: testSessionId,
            answer: 'test',
            token: testToken,
          ),
          throwsA(isA<AgentSessionException>()),
        );
      });
    });

    group('cancel HTTP 调用', () {
      test('成功取消会话', () async {
        final client = MockClient((request) async {
          expect(request.method, 'POST');
          expect(
            request.url.toString(),
            '$testHttpUrl/api/runtime/devices/$testDeviceId/assistant/agent/$testSessionId/cancel',
          );
          return http.Response(jsonEncode({'ok': true}), 200);
        });

        final service = AgentSessionService(
          serverUrl: testServerUrl,
          client: client,
        );

        final result = await service.cancel(
          deviceId: testDeviceId,
          sessionId: testSessionId,
          token: testToken,
        );

        expect(result, isTrue);
      });

      test('取消失败抛出异常', () async {
        final client = MockClient((request) async {
          return http.Response('Forbidden', 403);
        });

        final service = AgentSessionService(
          serverUrl: testServerUrl,
          client: client,
        );

        expect(
          () => service.cancel(
            deviceId: testDeviceId,
            sessionId: testSessionId,
            token: testToken,
          ),
          throwsA(isA<AgentSessionException>()),
        );
      });
    });

    group('reportExecution HTTP 调用', () {
      test('成功回写执行结果', () async {
        final client = MockClient((request) async {
          expect(request.method, 'POST');
          expect(
            request.url.toString(),
            '$testHttpUrl/api/runtime/devices/$testDeviceId/assistant/agent/$testSessionId/report',
          );
          expect(
            request.headers['Authorization'],
            'Bearer $testToken',
          );
          final body = jsonDecode(request.body) as Map<String, dynamic>;
          expect(body['success'], isTrue);
          expect(body['executed_command'], 'cd ~/project-a && claude');
          expect(body.containsKey('failure_step'), isFalse);
          return http.Response(
            jsonEncode({'status': 'ok', 'session_id': testSessionId, 'idempotent': false}),
            200,
          );
        });

        final service = AgentSessionService(
          serverUrl: testServerUrl,
          client: client,
        );

        await service.reportExecution(
          deviceId: testDeviceId,
          sessionId: testSessionId,
          success: true,
          executedCommand: 'cd ~/project-a && claude',
          token: testToken,
        );
      });

      test('失败回写包含 failure_step', () async {
        final client = MockClient((request) async {
          final body = jsonDecode(request.body) as Map<String, dynamic>;
          expect(body['success'], isFalse);
          expect(body['failure_step'], 'step-2');
          expect(body['executed_command'], 'cd ~/project-b');
          return http.Response(
            jsonEncode({'status': 'ok', 'session_id': testSessionId, 'idempotent': false}),
            200,
          );
        });

        final service = AgentSessionService(
          serverUrl: testServerUrl,
          client: client,
        );

        await service.reportExecution(
          deviceId: testDeviceId,
          sessionId: testSessionId,
          success: false,
          executedCommand: 'cd ~/project-b',
          failureStep: 'step-2',
          token: testToken,
        );
      });

      test('服务端返回非 200 抛出异常', () async {
        final client = MockClient((request) async {
          return http.Response('Not Found', 404);
        });

        final service = AgentSessionService(
          serverUrl: testServerUrl,
          client: client,
        );

        expect(
          () => service.reportExecution(
            deviceId: testDeviceId,
            sessionId: testSessionId,
            success: true,
            token: testToken,
          ),
          throwsA(isA<AgentSessionException>()),
        );
      });

      test('不带 token 时不发送 Authorization header', () async {
        final client = MockClient((request) async {
          expect(request.headers.containsKey('Authorization'), isFalse);
          return http.Response(
            jsonEncode({'status': 'ok', 'session_id': testSessionId, 'idempotent': false}),
            200,
          );
        });

        final service = AgentSessionService(
          serverUrl: testServerUrl,
          client: client,
        );

        await service.reportExecution(
          deviceId: testDeviceId,
          sessionId: testSessionId,
          success: true,
        );
      });
    });

    group('断连恢复', () {
      test('resume 恢复 asking 状态重发 QuestionEvent', () async {
        final sseText = buildSSE([
          MapEntry('question', jsonEncode({
            'question': '选择项目',
            'options': ['project-a', 'project-b'],
            'multi_select': false,
          })),
        ]);

        final client = MockClient.streaming((request, bodyStream) async {
          expect(request.method, 'GET');
          expect(
            request.url.toString(),
            '$testHttpUrl/api/runtime/devices/$testDeviceId/assistant/agent/$testSessionId/resume',
          );
          return http.StreamedResponse(
            Stream.value(utf8.encode(sseText)),
            200,
            headers: const {'content-type': 'text/event-stream'},
          );
        });

        final service = AgentSessionService(
          serverUrl: testServerUrl,
          client: client,
        );

        final events = await service
            .resumeSession(
              deviceId: testDeviceId,
              sessionId: testSessionId,
              token: testToken,
            )
            .toList();

        expect(events, hasLength(1));
        expect(events[0], isA<AgentQuestionEvent>());
        final question = events[0] as AgentQuestionEvent;
        expect(question.question, '选择项目');
      });

      test('resume 恢复 completed 状态重发 ResultEvent', () async {
        final sseText = buildSSE([
          MapEntry('result', jsonEncode({
            'summary': '已恢复结果',
            'steps': [
              {'id': 's1', 'label': '步骤1', 'command': 'echo hello'},
            ],
            'provider': 'agent',
            'source': 'recommended',
            'need_confirm': false,
            'aliases': {},
          })),
        ]);

        final client = MockClient.streaming((request, bodyStream) async {
          return http.StreamedResponse(
            Stream.value(utf8.encode(sseText)),
            200,
            headers: const {'content-type': 'text/event-stream'},
          );
        });

        final service = AgentSessionService(
          serverUrl: testServerUrl,
          client: client,
        );

        final events = await service
            .resumeSession(
              deviceId: testDeviceId,
              sessionId: testSessionId,
              token: testToken,
            )
            .toList();

        expect(events, hasLength(1));
        expect(events[0], isA<AgentResultEvent>());
        final result = events[0] as AgentResultEvent;
        expect(result.summary, '已恢复结果');
      });

      test('resume 恢复 expired 状态返回 ErrorEvent', () async {
        final sseText = buildSSE([
          MapEntry('error', jsonEncode({
            'code': 'SESSION_EXPIRED',
            'message': '会话已过期',
          })),
        ]);

        final client = MockClient.streaming((request, bodyStream) async {
          return http.StreamedResponse(
            Stream.value(utf8.encode(sseText)),
            200,
            headers: const {'content-type': 'text/event-stream'},
          );
        });

        final service = AgentSessionService(
          serverUrl: testServerUrl,
          client: client,
        );

        final events = await service
            .resumeSession(
              deviceId: testDeviceId,
              sessionId: testSessionId,
              token: testToken,
            )
            .toList();

        expect(events, hasLength(1));
        expect(events[0], isA<AgentErrorEvent>());
        final error = events[0] as AgentErrorEvent;
        expect(error.code, 'SESSION_EXPIRED');
        expect(error.message, '会话已过期');
      });
    });

    group('降级到 planner', () {
      test('服务端返回 409 触发降级 FallbackEvent', () async {
        final client = MockClient.streaming((request, bodyStream) async {
          return http.StreamedResponse(
            Stream.value(utf8.encode(jsonEncode({
              'code': 'AGENT_OFFLINE',
              'message': '设备不在线',
            }))),
            409,
          );
        });

        final service = AgentSessionService(
          serverUrl: testServerUrl,
          client: client,
        );

        final events = await service
            .runSession(
              deviceId: testDeviceId,
              intent: '测试降级',
              token: testToken,
            )
            .toList();

        expect(events, hasLength(1));
        expect(events[0], isA<AgentFallbackEvent>());
        final fallback = events[0] as AgentFallbackEvent;
        expect(fallback.code, 'AGENT_OFFLINE');
        expect(fallback.reason, '设备不在线');
      });

      test('服务端返回 409 缺少 code 使用默认值', () async {
        final client = MockClient.streaming((request, bodyStream) async {
          return http.StreamedResponse(
            Stream.value(utf8.encode('not json')),
            409,
          );
        });

        final service = AgentSessionService(
          serverUrl: testServerUrl,
          client: client,
        );

        final events = await service
            .runSession(
              deviceId: testDeviceId,
              intent: '测试降级',
              token: testToken,
            )
            .toList();

        expect(events, hasLength(1));
        expect(events[0], isA<AgentFallbackEvent>());
        final fallback = events[0] as AgentFallbackEvent;
        expect(fallback.code, 'AGENT_OFFLINE');
        expect(fallback.reason, 'Agent 不可用');
      });
    });

    group('会话超时处理', () {
      test('SESSION_EXPIRED 错误清除活跃会话', () async {
        final sseText = buildSSE([
          MapEntry('error', jsonEncode({
            'code': 'SESSION_EXPIRED',
            'message': '会话超时（10分钟）',
          })),
        ]);

        final client = MockClient.streaming((request, bodyStream) async {
          return http.StreamedResponse(
            Stream.value(utf8.encode(sseText)),
            200,
            headers: const {'content-type': 'text/event-stream'},
          );
        });

        final service = AgentSessionService(
          serverUrl: testServerUrl,
          client: client,
        );

        final events = await service
            .runSession(
              deviceId: testDeviceId,
              intent: '测试超时',
              token: testToken,
            )
            .toList();

        expect(events, hasLength(1));
        expect(events[0], isA<AgentErrorEvent>());
        expect((events[0] as AgentErrorEvent).code, 'SESSION_EXPIRED');
        expect(service.activeSessionId, isNull);
      });

      test('服务端返回 410 标记会话已过期', () async {
        final client = MockClient.streaming((request, bodyStream) async {
          return http.StreamedResponse(
            Stream.value(utf8.encode(jsonEncode({
              'code': 'SESSION_EXPIRED',
              'message': '会话已过期',
            }))),
            410,
          );
        });

        final service = AgentSessionService(
          serverUrl: testServerUrl,
          client: client,
        );

        final events = await service
            .resumeSession(
              deviceId: testDeviceId,
              sessionId: testSessionId,
              token: testToken,
            )
            .toList();

        expect(events, hasLength(1));
        expect(events[0], isA<AgentErrorEvent>());
        final error = events[0] as AgentErrorEvent;
        expect(error.code, 'SESSION_EXPIRED');
        expect(error.message, '会话已过期');
      });
    });

    group('认证 token 注入', () {
      test('runSession 请求携带 Authorization header', () async {
        final client = MockClient.streaming((request, bodyStream) async {
          expect(request.headers['Authorization'], 'Bearer $testToken');
          expect(request.headers['Accept'], 'text/event-stream');

          return http.StreamedResponse(
            Stream.value(utf8.encode(buildSSE([
              MapEntry('result', jsonEncode({
                'summary': '完成',
                'steps': [],
                'provider': 'agent',
                'source': 'recommended',
                'need_confirm': false,
                'aliases': {},
              })),
            ]))),
            200,
          );
        });

        final service = AgentSessionService(
          serverUrl: testServerUrl,
          client: client,
        );

        await service
            .runSession(
              deviceId: testDeviceId,
              intent: '测试认证',
              token: testToken,
            )
            .toList();
      });

      test('runSession 请求携带 conversation_id', () async {
        final client = MockClient.streaming((request, bodyStream) async {
          final body =
              jsonDecode(await bodyStream.bytesToString()) as Map<String, dynamic>;
          expect(body['intent'], '测试意图');
          expect(body['conversation_id'], 'conv-xyz');

          return http.StreamedResponse(
            Stream.value(utf8.encode(buildSSE([
              MapEntry('result', jsonEncode({
                'summary': '完成',
                'steps': [],
                'provider': 'agent',
                'source': 'recommended',
                'need_confirm': false,
                'aliases': {},
              })),
            ]))),
            200,
          );
        });

        final service = AgentSessionService(
          serverUrl: testServerUrl,
          client: client,
        );

        await service
            .runSession(
              deviceId: testDeviceId,
              intent: '测试意图',
              token: testToken,
              conversationId: 'conv-xyz',
            )
            .toList();
      });
    });

    group('服务端 URL 构建', () {
      test('ws:// 协议转为 http://', () async {
        const wsUrl = 'ws://192.168.1.100:8888';
        const httpUrl = 'http://192.168.1.100:8888';

        final client = MockClient.streaming((request, bodyStream) async {
          expect(request.url.toString(), startsWith(httpUrl));
          return http.StreamedResponse(
            Stream.value(utf8.encode(buildSSE([
              MapEntry('result', jsonEncode({
                'summary': 'ok',
                'steps': [],
                'provider': 'agent',
                'source': 'recommended',
                'need_confirm': false,
                'aliases': {},
              })),
            ]))),
            200,
          );
        });

        final service = AgentSessionService(
          serverUrl: wsUrl,
          client: client,
        );

        await service
            .runSession(
              deviceId: testDeviceId,
              intent: 'test',
              token: testToken,
            )
            .toList();
      });
    });
  });

  group('AgentSessionEvent 模型', () {
    test('AgentTraceEvent.fromJson 处理缺失字段', () {
      final event = AgentTraceEvent.fromJson({});
      expect(event.tool, '');
      expect(event.inputSummary, '');
      expect(event.outputSummary, '');
    });

    test('AgentQuestionEvent.fromJson 处理缺失字段', () {
      final event = AgentQuestionEvent.fromJson({});
      expect(event.question, '');
      expect(event.options, isEmpty);
      expect(event.multiSelect, isFalse);
    });

    test('AgentResultEvent.fromJson 处理缺失字段', () {
      final event = AgentResultEvent.fromJson({});
      expect(event.summary, '');
      expect(event.steps, isEmpty);
      expect(event.provider, 'agent');
      expect(event.source, 'recommended');
      expect(event.needConfirm, isTrue);
      expect(event.aliases, isEmpty);
    });

    test('AgentErrorEvent.fromJson 处理缺失字段', () {
      final event = AgentErrorEvent.fromJson({});
      expect(event.code, 'UNKNOWN');
      expect(event.message, '');
    });

    test('AgentResultStep.fromJson 处理缺失字段', () {
      final step = AgentResultStep.fromJson({});
      expect(step.id, '');
      expect(step.label, '');
      expect(step.command, '');
    });
  });
}
