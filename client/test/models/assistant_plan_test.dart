import 'package:flutter_test/flutter_test.dart';
import 'package:rc_client/models/assistant_plan.dart';

void main() {
  group('AssistantPlanProgressEvent', () {
    test('parses assistant delta event', () {
      final event = AssistantPlanProgressEvent.fromJson(const {
        'type': 'assistant_delta',
        'assistant_delta': {
          'type': 'assistant',
          'text_delta': '正在读取项目上下文...',
          'replace': false,
        },
      });

      expect(event.type, 'assistant_delta');
      expect(event.assistantDelta?.textDelta, '正在读取项目上下文...');
      expect(event.assistantDelta?.replace, isFalse);
      expect(event.derivedTraceItem, isNull);
    });

    test('derives trace item from tool call and status update', () {
      final toolEvent = AssistantPlanProgressEvent.fromJson(const {
        'type': 'tool_call',
        'tool_call': {
          'id': 'tool-1',
          'tool_name': 'scan_projects',
          'status': 'running',
          'summary': '正在扫描项目目录',
          'input_summary': 'device=mbp-01',
        },
      });
      final statusEvent = AssistantPlanProgressEvent.fromJson(const {
        'type': 'status',
        'status': {
          'stage': 'planner',
          'status': 'completed',
          'title': '生成最终命令',
          'summary': '已输出 4 条命令步骤',
        },
      });

      expect(toolEvent.derivedTraceItem?.stage, 'tool');
      expect(toolEvent.derivedTraceItem?.title, 'scan_projects');
      expect(toolEvent.derivedTraceItem?.summary, contains('正在扫描项目目录'));
      expect(statusEvent.derivedTraceItem?.stage, 'planner');
      expect(statusEvent.derivedTraceItem?.title, '生成最终命令');
      expect(statusEvent.derivedTraceItem?.status, 'completed');
    });
  });
}
