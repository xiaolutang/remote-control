import 'package:flutter_test/flutter_test.dart';
import 'package:rc_client/models/command_sequence_draft.dart';
import 'package:rc_client/models/terminal_launch_plan.dart';

void main() {
  group('CommandSequenceDraft', () {
    test('claude-only mode normalizes non-custom planner output to claude', () {
      final draft = CommandSequenceDraft.fromLaunchPlan(
        const TerminalLaunchPlan(
          tool: TerminalLaunchTool.codex,
          title: 'Codex / remote-control',
          cwd: '/Users/demo/project/remote-control',
          command: '/bin/bash',
          entryStrategy: TerminalEntryStrategy.shellBootstrap,
          postCreateInput: 'codex\n',
          source: TerminalLaunchPlanSource.intent,
        ),
        provider: 'llm',
      );

      expect(draft.tool, TerminalLaunchTool.claudeCode);
      expect(draft.provider, 'claude_cli');
      expect(draft.steps.last.command, 'claude');
    });

    test('toLaunchPlan preserves user-edited command sequence', () {
      final plan = CommandSequenceDraft(
        summary: '进入目标目录并执行自定义命令',
        provider: 'local_rules',
        tool: TerminalLaunchTool.custom,
        title: 'Workspace Custom',
        cwd: '/tmp/workspace-custom',
        shellCommand: '/bin/zsh',
        source: TerminalLaunchPlanSource.custom,
        steps: const [
          CommandSequenceStep(
            id: 'step_1',
            label: '执行自定义命令',
            command: 'echo workspace',
          ),
        ],
      ).toLaunchPlan();

      expect(plan.tool, TerminalLaunchTool.custom);
      expect(plan.command, '/bin/zsh');
      expect(plan.entryStrategy, TerminalEntryStrategy.shellBootstrap);
      expect(plan.postCreateInput, 'echo workspace\n');
    });

    test('filtered step order stays stable after manual removal', () {
      final plan = CommandSequenceDraft(
        summary: '顺序执行命令',
        provider: 'local_rules',
        tool: TerminalLaunchTool.claudeCode,
        title: 'Claude / remote-control',
        cwd: '/Users/demo/project/remote-control',
        shellCommand: '/bin/bash',
        source: TerminalLaunchPlanSource.intent,
        steps: const [
          CommandSequenceStep(
            id: 'step_1',
            label: '进入项目目录',
            command: 'cd /Users/demo/project/remote-control',
          ),
          CommandSequenceStep(
            id: 'step_2',
            label: '已删除步骤',
            command: '',
          ),
          CommandSequenceStep(
            id: 'step_3',
            label: '启动 Claude Code',
            command: 'claude',
          ),
        ],
      ).toLaunchPlan();

      expect(plan.tool, TerminalLaunchTool.claudeCode);
      expect(
        plan.postCreateInput,
        'set -e\ncd /Users/demo/project/remote-control\nclaude\n',
      );
    });
  });
}
