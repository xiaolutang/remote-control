import 'package:flutter_test/flutter_test.dart';
import 'package:rc_client/widgets/agent_panel_types.dart';
import 'package:rc_client/models/agent_session_event.dart';

void main() {
  group('AgentPhase', () {
    test('has all expected values', () {
      expect(AgentPhase.values, containsAll([
        AgentPhase.idle,
        AgentPhase.thinking,
        AgentPhase.exploring,
        AgentPhase.analyzing,
        AgentPhase.responding,
        AgentPhase.confirming,
        AgentPhase.result,
        AgentPhase.error,
      ]));
    });

    test('has exactly 8 values', () {
      expect(AgentPhase.values.length, 8);
    });
  });

  group('TurnEventType', () {
    test('has answer and assistantMessage', () {
      expect(TurnEventType.values, containsAll([
        TurnEventType.answer,
        TurnEventType.assistantMessage,
      ]));
    });
  });

  group('AgentAnswerEntry', () {
    test('stores question and answer', () {
      const entry = AgentAnswerEntry(
        question: 'Which project?',
        answer: 'dayknow',
      );
      expect(entry.question, 'Which project?');
      expect(entry.answer, 'dayknow');
    });
  });

  group('AgentHistoryEntry', () {
    test('stores intent and traces', () {
      final entry = AgentHistoryEntry(
        intent: '进入日知项目',
        traces: [
          ToolStepEvent(
            toolName: 'read_file',
            description: 'Read config',
            status: ToolStepStatus.done,
          ),
        ],
        turnEventOrder: [TurnEventType.answer],
        assistantMessages: [],
        answers: [
          const AgentAnswerEntry(question: 'Q', answer: 'A'),
        ],
      );
      expect(entry.intent, '进入日知项目');
      expect(entry.traces.length, 1);
      expect(entry.turnEventOrder.length, 1);
      expect(entry.answers.length, 1);
      expect(entry.result, isNull);
      expect(entry.error, isNull);
    });
  });

  group('AgentRenderState', () {
    test('stores all fields correctly', () {
      final state = AgentRenderState(
        state: AgentPhase.exploring,
        phaseDescription: '正在执行工具调用...',
        history: [],
        intent: '部署项目',
        traces: [],
        turnEventOrder: [],
        assistantMessages: [],
        answers: [],
        resultEventId: 'evt_123',
      );
      expect(state.state, AgentPhase.exploring);
      expect(state.phaseDescription, '正在执行工具调用...');
      expect(state.intent, '部署项目');
      expect(state.resultEventId, 'evt_123');
      expect(state.errorEventId, isNull);
    });

    test('defaults optional fields to null/empty', () {
      final state = AgentRenderState(
        state: AgentPhase.idle,
        history: [],
        traces: [],
        turnEventOrder: [],
        assistantMessages: [],
        answers: [],
      );
      expect(state.phaseDescription, '');
      expect(state.intent, isNull);
      expect(state.currentQuestion, isNull);
      expect(state.result, isNull);
      expect(state.error, isNull);
      expect(state.resultEventId, isNull);
      expect(state.errorEventId, isNull);
    });
  });
}
