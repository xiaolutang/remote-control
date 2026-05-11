// ignore_for_file: deprecated_member_use_from_same_package

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
      expect(event.responseType, AgentResponseType.message);
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
      expect(event.responseType, AgentResponseType.aiPrompt);
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
      expect(event.responseType, AgentResponseType.command);
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
      expect(event.responseType, AgentResponseType.command);
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
      expect(event.responseType, AgentResponseType.message);
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
      expect(event.responseType, AgentResponseType.command);
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
        responseType: AgentResponseType.message,
        aiPrompt: 'some prompt text',
      );
      expect(event.responseType, AgentResponseType.message);
      expect(event.aiPrompt, 'some prompt text');
    });

    test('toJson serializes responseType enum back to string', () {
      final event = AgentResultEvent(
        summary: 'test',
        steps: const [],
        provider: 'agent',
        source: 'recommended',
        needConfirm: false,
        aliases: const {},
        responseType: AgentResponseType.aiPrompt,
        aiPrompt: 'run this',
      );
      final json = event.toJson();
      expect(json['response_type'], 'ai_prompt');
      expect(json['ai_prompt'], 'run this');
    });

    test('unknown response_type falls back to command', () {
      final json = {
        'summary': 'test',
        'steps': <Map<String, dynamic>>[],
        'provider': 'agent',
        'source': 'recommended',
        'need_confirm': false,
        'aliases': <String, String>{},
        'response_type': 'future_type',
      };
      final event = AgentResultEvent.fromJson(json);
      expect(event.responseType, AgentResponseType.command);
    });
  });

  group('ToolStepEvent', () {
    test('parses status enum from string', () {
      final json = {
        'tool_name': 'bash',
        'description': 'run command',
        'status': 'done',
      };
      final event = ToolStepEvent.fromJson(json);
      expect(event.status, ToolStepStatus.done);
    });

    test('defaults status to running when missing', () {
      final json = {
        'tool_name': 'bash',
        'description': 'run command',
      };
      final event = ToolStepEvent.fromJson(json);
      expect(event.status, ToolStepStatus.running);
    });

    test('toJson serializes status enum back to string', () {
      const event = ToolStepEvent(
        toolName: 'bash',
        description: 'run command',
        status: ToolStepStatus.error,
      );
      final json = event.toJson();
      expect(json['status'], 'error');
    });
  });

  group('FeedbackType', () {
    test('fromJsonString parses all values', () {
      expect(FeedbackType.fromJsonString('helpful'), FeedbackType.helpful);
      expect(FeedbackType.fromJsonString('needs_improvement'), FeedbackType.needsImprovement);
      expect(FeedbackType.fromJsonString('error_report'), FeedbackType.errorReport);
      expect(FeedbackType.fromJsonString(null), FeedbackType.helpful);
      expect(FeedbackType.fromJsonString('unknown'), FeedbackType.helpful);
    });

    test('toJsonString converts back to wire format', () {
      expect(FeedbackType.helpful.toJsonString(), 'helpful');
      expect(FeedbackType.needsImprovement.toJsonString(), 'needs_improvement');
      expect(FeedbackType.errorReport.toJsonString(), 'error_report');
    });
  });

  group('ToolStepStatus', () {
    test('fromJsonString parses all values', () {
      expect(ToolStepStatus.fromJsonString('running'), ToolStepStatus.running);
      expect(ToolStepStatus.fromJsonString('done'), ToolStepStatus.done);
      expect(ToolStepStatus.fromJsonString('error'), ToolStepStatus.error);
      expect(ToolStepStatus.fromJsonString(null), ToolStepStatus.running);
      expect(ToolStepStatus.fromJsonString('unknown'), ToolStepStatus.running);
    });

    test('toJsonString converts back to wire format', () {
      expect(ToolStepStatus.running.toJsonString(), 'running');
      expect(ToolStepStatus.done.toJsonString(), 'done');
      expect(ToolStepStatus.error.toJsonString(), 'error');
    });
  });

  group('AgentResponseType', () {
    test('fromJsonString parses all values', () {
      expect(AgentResponseType.fromJsonString('message'), AgentResponseType.message);
      expect(AgentResponseType.fromJsonString('command'), AgentResponseType.command);
      expect(AgentResponseType.fromJsonString('ai_prompt'), AgentResponseType.aiPrompt);
      expect(AgentResponseType.fromJsonString(null), AgentResponseType.command);
      expect(AgentResponseType.fromJsonString('unknown'), AgentResponseType.command);
    });

    test('toJsonString converts back to wire format', () {
      expect(AgentResponseType.message.toJsonString(), 'message');
      expect(AgentResponseType.command.toJsonString(), 'command');
      expect(AgentResponseType.aiPrompt.toJsonString(), 'ai_prompt');
    });
  });
}
