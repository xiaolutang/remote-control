import '../models/agent_session_event.dart';

/// Agent 面板 Phase 驱动状态
enum AgentPhase {
  /// 空闲/初始状态
  idle,

  /// THINKING 阶段：正在思考
  thinking,

  /// EXPLORING 阶段：执行工具调用
  exploring,

  /// ANALYZING 阶段：分析结果
  analyzing,

  /// RESPONDING 阶段：流式文本输出
  responding,

  /// CONFIRMING 阶段：ask_user 等待确认
  confirming,

  /// RESULT 阶段：显示结果卡片
  result,

  /// 错误
  error,
}

/// Agent 历史条目模型
class AgentHistoryEntry {
  const AgentHistoryEntry({
    required this.intent,
    required this.traces,
    required this.turnEventOrder,
    this.assistantMessages = const [],
    this.answers = const [],
    this.result,
    this.error,
  });

  final String intent;
  final List<ToolStepEvent> traces;
  final List<TurnEventType> turnEventOrder;
  final List<StreamingTextEvent> assistantMessages;
  final List<AgentAnswerEntry> answers;
  final AgentResultEvent? result;
  final AgentErrorEvent? error;
}

/// Agent 问答条目
class AgentAnswerEntry {
  const AgentAnswerEntry({required this.question, required this.answer});
  final String question;
  final String answer;
}

/// 轮次事件类型
enum TurnEventType { answer, assistantMessage }

/// Agent 渲染状态（从 conversation events 推导出的聚合状态）
class AgentRenderState {
  const AgentRenderState({
    required this.state,
    required this.history,
    required this.traces,
    required this.turnEventOrder,
    required this.assistantMessages,
    required this.answers,
    this.phaseDescription = '',
    this.intent,
    this.currentQuestion,
    this.result,
    this.error,
    this.resultEventId,
    this.errorEventId,
  });

  final AgentPhase state;
  final String phaseDescription;
  final List<AgentHistoryEntry> history;
  final String? intent;
  final List<ToolStepEvent> traces;
  final List<TurnEventType> turnEventOrder;
  final List<StreamingTextEvent> assistantMessages;
  final List<AgentAnswerEntry> answers;
  final AgentQuestionEvent? currentQuestion;
  final AgentResultEvent? result;
  final AgentErrorEvent? error;
  final String? resultEventId;
  final String? errorEventId;
}
