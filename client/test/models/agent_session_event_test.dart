import 'package:flutter_test/flutter_test.dart';
import 'package:rc_client/models/agent_session_event.dart';

void main() {
  group('AgentResultEvent.fromJson', () {
    test('parses response_type=message correctly', () {
      final json = {
        'summary': 'hello',
        'steps': <Map<String, dynamic>>[],
        'provider': 'agent',
        'source': 'recommended',
        'need_confirm': false,
        'aliases': <String, String>{},
        'response_type': 'message',
      };
      final event = AgentResultEvent.fromJson(json);
      expect(event.responseType, 'message');
      expect(event.aiPrompt, '');
      expect(event.summary, 'hello');
      expect(event.steps, isEmpty);
    });

    test('parses response_type=ai_prompt with ai_prompt field', () {
      final json = {
        'summary': 'run deploy',
        'steps': <Map<String, dynamic>>[],
        'provider': 'agent',
        'source': 'recommended',
        'need_confirm': false,
        'aliases': <String, String>{},
        'response_type': 'ai_prompt',
        'ai_prompt': 'kubectl apply -f deployment.yaml',
      };
      final event = AgentResultEvent.fromJson(json);
      expect(event.responseType, 'ai_prompt');
      expect(event.aiPrompt, 'kubectl apply -f deployment.yaml');
    });

    test('defaults response_type to command when missing', () {
      final json = {
        'summary': 'some result',
        'steps': <Map<String, dynamic>>[],
        'provider': 'agent',
        'source': 'recommended',
        'need_confirm': true,
        'aliases': <String, String>{},
      };
      final event = AgentResultEvent.fromJson(json);
      expect(event.responseType, 'command');
      expect(event.aiPrompt, '');
    });

    test('defaults response_type to command when null', () {
      final json = {
        'summary': 'some result',
        'steps': <Map<String, dynamic>>[],
        'provider': 'agent',
        'source': 'recommended',
        'need_confirm': true,
        'aliases': <String, String>{},
        'response_type': null,
      };
      final event = AgentResultEvent.fromJson(json);
      expect(event.responseType, 'command');
    });

    test('defaults ai_prompt to empty string when missing', () {
      final json = {
        'summary': 'test',
        'steps': <Map<String, dynamic>>[],
        'provider': 'agent',
        'source': 'recommended',
        'need_confirm': false,
        'aliases': <String, String>{},
        'response_type': 'ai_prompt',
      };
      final event = AgentResultEvent.fromJson(json);
      expect(event.aiPrompt, '');
    });

    test('trims whitespace from response_type and ai_prompt', () {
      final json = {
        'summary': 'test',
        'steps': <Map<String, dynamic>>[],
        'provider': 'agent',
        'source': 'recommended',
        'need_confirm': false,
        'aliases': <String, String>{},
        'response_type': '  message  ',
        'ai_prompt': '  echo hello  ',
      };
      final event = AgentResultEvent.fromJson(json);
      expect(event.responseType, 'message');
      expect(event.aiPrompt, 'echo hello');
    });

    test('constructor defaults responseType to command', () {
      final event = AgentResultEvent(
        summary: 'test',
        steps: const [],
        provider: 'agent',
        source: 'recommended',
        needConfirm: false,
        aliases: const {},
      );
      expect(event.responseType, 'command');
      expect(event.aiPrompt, '');
    });

    test('constructor accepts custom responseType and aiPrompt', () {
      final event = AgentResultEvent(
        summary: 'test',
        steps: const [],
        provider: 'agent',
        source: 'recommended',
        needConfirm: false,
        aliases: const {},
        responseType: 'message',
        aiPrompt: 'some prompt text',
      );
      expect(event.responseType, 'message');
      expect(event.aiPrompt, 'some prompt text');
    });
  });

  group('AgentAssistantMessageEvent', () {
    test('parses content from json', () {
      final json = {'content': '我来帮你检查一下当前目录结构...'};
      final event = AgentAssistantMessageEvent.fromJson(json);
      expect(event.content, '我来帮你检查一下当前目录结构...');
    });

    test('defaults content to empty string when missing', () {
      final json = <String, dynamic>{};
      final event = AgentAssistantMessageEvent.fromJson(json);
      expect(event.content, '');
    });

    test('trims whitespace from content', () {
      final json = {'content': '  hello world  '};
      final event = AgentAssistantMessageEvent.fromJson(json);
      expect(event.content, 'hello world');
    });

    test('handles null content gracefully', () {
      final json = {'content': null};
      final event = AgentAssistantMessageEvent.fromJson(json);
      expect(event.content, '');
    });

    test('constructor accepts content', () {
      const event = AgentAssistantMessageEvent(content: 'test message');
      expect(event.content, 'test message');
    });
  });
}
