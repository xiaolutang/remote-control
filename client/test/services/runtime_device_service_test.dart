import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:rc_client/models/assistant_plan.dart';
import 'package:rc_client/services/runtime_device_service.dart';

void main() {
  group('RuntimeDeviceService', () {
    test('lists runtime devices', () async {
      final client = MockClient((request) async {
        expect(request.url.toString(),
            'http://localhost:8888/api/runtime/devices');
        return http.Response(
          jsonEncode({
            'devices': [
              {
                'device_id': 'mbp-01',
                'name': 'MacBook Pro',
                'owner': 'user1',
                'agent_online': true,
                'max_terminals': 3,
                'active_terminals': 1,
              },
            ],
          }),
          200,
        );
      });
      final service = RuntimeDeviceService(
        serverUrl: 'ws://localhost:8888',
        client: client,
      );

      final devices = await service.listDevices('token');

      expect(devices.single.deviceId, 'mbp-01');
      expect(devices.single.canCreateTerminal, isTrue);
    });

    test('creates runtime terminal', () async {
      final client = MockClient((request) async {
        expect(request.method, 'POST');
        return http.Response(
          jsonEncode({
            'terminal_id': 'term-1',
            'title': 'Claude',
            'cwd': '/tmp',
            'command': '/bin/bash',
            'status': 'detached',
            'views': {'mobile': 0, 'desktop': 0},
          }),
          200,
        );
      });
      final service = RuntimeDeviceService(
        serverUrl: 'ws://localhost:8888',
        client: client,
      );

      final terminal = await service.createTerminal(
        'token',
        'mbp-01',
        title: 'Claude',
        cwd: '/tmp',
        command: '/bin/bash',
        terminalId: 'term-1',
      );

      expect(terminal.terminalId, 'term-1');
      expect(terminal.status, 'detached');
    });

    test('gets runtime terminal snapshot from backend list', () async {
      final client = MockClient((request) async {
        expect(request.method, 'GET');
        expect(
          request.url.toString(),
          'http://localhost:8888/api/runtime/devices/mbp-01/terminals',
        );
        return http.Response(
          jsonEncode({
            'device_id': 'mbp-01',
            'device_online': true,
            'terminals': [
              {
                'terminal_id': 'term-1',
                'title': 'Claude',
                'cwd': '/tmp',
                'command': '/bin/bash',
                'status': 'attached',
                'views': {'mobile': 1, 'desktop': 1},
              },
            ],
          }),
          200,
        );
      });
      final service = RuntimeDeviceService(
        serverUrl: 'ws://localhost:8888',
        client: client,
      );

      final terminal = await service.getTerminal('token', 'mbp-01', 'term-1');

      expect(terminal, isNotNull);
      expect(terminal!.views['mobile'], 1);
      expect(terminal.views['desktop'], 1);
    });

    test('closes runtime terminal', () async {
      final client = MockClient((request) async {
        expect(request.method, 'DELETE');
        expect(
          request.url.toString(),
          'http://localhost:8888/api/runtime/devices/mbp-01/terminals/term-1',
        );
        return http.Response(
          jsonEncode({
            'terminal_id': 'term-1',
            'title': 'Claude',
            'cwd': '/tmp',
            'command': '/bin/bash',
            'status': 'closed',
            'disconnect_reason': 'server_forced_close',
            'updated_at': '2026-03-29T02:00:00Z',
            'views': {'mobile': 0, 'desktop': 0},
          }),
          200,
        );
      });
      final service = RuntimeDeviceService(
        serverUrl: 'ws://localhost:8888',
        client: client,
      );

      final terminal = await service.closeTerminal('token', 'mbp-01', 'term-1');

      expect(terminal.terminalId, 'term-1');
      expect(terminal.status, 'closed');
      expect(terminal.disconnectReason, 'server_forced_close');
    });

    test('updates device settings', () async {
      final client = MockClient((request) async {
        expect(request.method, 'PATCH');
        expect(
          request.url.toString(),
          'http://localhost:8888/api/runtime/devices/mbp-01',
        );
        expect(
          jsonDecode(request.body),
          {'name': 'New Name'},
        );
        return http.Response(
          jsonEncode({
            'device_id': 'mbp-01',
            'name': 'New Name',
            'owner': 'user1',
            'agent_online': true,
            'max_terminals': 3,
            'active_terminals': 1,
          }),
          200,
        );
      });
      final service = RuntimeDeviceService(
        serverUrl: 'ws://localhost:8888',
        client: client,
      );

      final device = await service.updateDevice(
        'token',
        'mbp-01',
        name: 'New Name',
      );

      expect(device.deviceId, 'mbp-01');
      expect(device.name, 'New Name');
      expect(device.maxTerminals, 3);
    });

    test('updates terminal title', () async {
      final client = MockClient((request) async {
        expect(request.method, 'PATCH');
        expect(
          request.url.toString(),
          'http://localhost:8888/api/runtime/devices/mbp-01/terminals/term-1',
        );
        return http.Response(
          jsonEncode({
            'terminal_id': 'term-1',
            'title': 'New Title',
            'cwd': '/tmp',
            'command': '/bin/bash',
            'status': 'detached',
            'updated_at': '2026-03-29T02:00:00Z',
            'views': {'mobile': 0, 'desktop': 0},
          }),
          200,
        );
      });
      final service = RuntimeDeviceService(
        serverUrl: 'ws://localhost:8888',
        client: client,
      );

      final terminal = await service.updateTerminalTitle(
        'token',
        'mbp-01',
        'term-1',
        'New Title',
      );

      expect(terminal.terminalId, 'term-1');
      expect(terminal.title, 'New Title');
    });

    test('streams assistant planning progress and returns final result',
        () async {
      final client = MockClient.streaming((request, bodyStream) async {
        expect(request.method, 'POST');
        expect(
          request.url.toString(),
          'http://localhost:8888/api/runtime/devices/mbp-01/assistant/plan/stream',
        );
        final body = jsonDecode(await bodyStream.bytesToString());
        expect(body['intent'], '进入 remote-control 并打开 Claude');

        final lines = [
          jsonEncode({
            'type': 'assistant_message',
            'assistant_message': {
              'type': 'assistant',
              'text': '我先读取当前设备上下文，再生成一组可确认的终端命令。',
            },
          }),
          jsonEncode({
            'type': 'trace',
            'trace_item': {
              'stage': 'context',
              'title': '读取上下文',
              'status': 'completed',
              'summary': '已整理 2 个候选项目，准备匹配目标路径。',
            },
          }),
          jsonEncode({
            'type': 'assistant_delta',
            'assistant_delta': {
              'type': 'assistant',
              'text_delta': '正在生成命令步骤...',
              'replace': false,
            },
          }),
          jsonEncode({
            'type': 'tool_call',
            'tool_call': {
              'id': 'tool-1',
              'tool_name': 'scan_projects',
              'status': 'running',
              'summary': '正在扫描项目目录',
            },
          }),
          jsonEncode({
            'type': 'status',
            'status': {
              'stage': 'planner',
              'status': 'completed',
              'title': '命令草案已生成',
              'summary': '准备返回最终规划结果',
            },
          }),
          jsonEncode({
            'type': 'result',
            'plan': {
              'conversation_id': 'conv-1',
              'message_id': 'msg-1',
              'assistant_messages': [
                {
                  'type': 'assistant',
                  'text': '我已为你生成进入项目并启动 Claude 的命令。',
                },
              ],
              'trace': [
                {
                  'stage': 'planner',
                  'title': '生成命令序列',
                  'status': 'completed',
                  'summary': '已生成 3 条可确认命令。',
                },
              ],
              'command_sequence': {
                'summary': '进入项目并启动 Claude',
                'provider': 'service_llm',
                'source': 'intent',
                'need_confirm': true,
                'steps': [
                  {
                    'id': 'step_1',
                    'label': '确认当前位置',
                    'command': 'pwd',
                  },
                ],
              },
              'fallback_used': false,
              'fallback_reason': null,
              'limits': {
                'rate_limited': false,
                'budget_blocked': false,
                'provider_timeout_ms': 12000,
                'retry_after': null,
              },
              'evaluation_context': {
                'matched_cwd': '/Users/tangxiaolu/project/remote-control',
              },
            },
          }),
        ].join('\n');

        return http.StreamedResponse(
          Stream.value(utf8.encode(lines)),
          200,
          headers: const {'content-type': 'application/x-ndjson'},
        );
      });
      final service = RuntimeDeviceService(
        serverUrl: 'ws://localhost:8888',
        client: client,
      );
      final progress = <AssistantPlanProgressEvent>[];

      final result = await service.createAssistantPlanStream(
        'token',
        'mbp-01',
        intent: '进入 remote-control 并打开 Claude',
        conversationId: 'conv-1',
        messageId: 'msg-1',
        onProgress: progress.add,
      );

      expect(progress, hasLength(5));
      expect(progress.first.assistantMessage?.text, contains('读取当前设备上下文'));
      expect(progress[1].traceItem?.title, '读取上下文');
      expect(progress[2].assistantDelta?.textDelta, '正在生成命令步骤...');
      expect(progress[3].toolCall?.toolName, 'scan_projects');
      expect(progress[4].statusUpdate?.title, '命令草案已生成');
      expect(result.commandSequence.summary, '进入项目并启动 Claude');
      expect(result.evaluationContext['matched_cwd'],
          '/Users/tangxiaolu/project/remote-control');
    });
  });
}
