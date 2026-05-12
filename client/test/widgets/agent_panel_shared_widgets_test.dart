import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rc_client/widgets/agent_panel_shared_widgets.dart';
import 'package:rc_client/models/agent_session_event.dart';

void main() {
  group('SidePanelStagePill', () {
    Widget buildPill(String stage) {
      return MaterialApp(
        home: Scaffold(
          body: SidePanelStagePill(stage: stage),
        ),
      );
    }

    testWidgets('renders tool label for tool stage', (tester) async {
      await tester.pumpWidget(buildPill('tool'));
      expect(find.text('工具'), findsOneWidget);
    });

    testWidgets('renders error label for error stage', (tester) async {
      await tester.pumpWidget(buildPill('error'));
      expect(find.text('错误'), findsOneWidget);
    });

    testWidgets('renders default label for unknown stage', (tester) async {
      await tester.pumpWidget(buildPill('unknown_stage'));
      expect(find.text('处理'), findsOneWidget);
    });

    testWidgets('renders 思考 for plan stage', (tester) async {
      await tester.pumpWidget(buildPill('plan'));
      expect(find.text('思考'), findsOneWidget);
    });

    testWidgets('renders 完成 for done stage', (tester) async {
      await tester.pumpWidget(buildPill('done'));
      expect(find.text('完成'), findsOneWidget);
    });
  });

  group('BlinkingCursor', () {
    testWidgets('renders a container with primary color', (tester) async {
      await tester.pumpWidget(MaterialApp(
        home: Scaffold(
          body: Builder(
            builder: (context) => BlinkingCursor(
              colorScheme: Theme.of(context).colorScheme,
            ),
          ),
        ),
      ));
      // Cursor should be a container of width 2, height 14
      final container = tester.widget<Container>(find.byType(Container).first);
      expect(container.constraints, isNotNull);
    });

    testWidgets('animates opacity via AnimationController', (tester) async {
      await tester.pumpWidget(MaterialApp(
        home: Scaffold(
          body: Builder(
            builder: (context) => BlinkingCursor(
              colorScheme: Theme.of(context).colorScheme,
            ),
          ),
        ),
      ));
      // BlinkingCursor has a repeating animation so pumpAndSettle would timeout.
      // Just verify it stays in the tree after a manual pump.
      await tester.pump(const Duration(milliseconds: 400));
      expect(find.byType(BlinkingCursor), findsOneWidget);
      await tester.pump(const Duration(milliseconds: 400));
      expect(find.byType(BlinkingCursor), findsOneWidget);
    });
  });

  group('ToolStepCard', () {
    Widget buildCard(ToolStepEvent step) {
      return MaterialApp(
        home: Scaffold(
          body: Builder(
            builder: (context) => ToolStepCard(
              step: step,
              colorScheme: Theme.of(context).colorScheme,
            ),
          ),
        ),
      );
    }

    testWidgets('shows tool name', (tester) async {
      final step = ToolStepEvent(
        toolName: 'read_file',
        description: 'Reading config.yaml',
        status: ToolStepStatus.done,
      );
      await tester.pumpWidget(buildCard(step));
      expect(find.text('read_file'), findsOneWidget);
    });

    testWidgets('shows description when non-empty', (tester) async {
      final step = ToolStepEvent(
        toolName: 'read_file',
        description: 'Reading config.yaml',
        status: ToolStepStatus.done,
      );
      await tester.pumpWidget(buildCard(step));
      expect(find.text('Reading config.yaml'), findsOneWidget);
    });

    testWidgets('shows running indicator when status is running', (tester) async {
      final step = ToolStepEvent(
        toolName: 'search',
        description: 'Searching files',
        status: ToolStepStatus.running,
      );
      await tester.pumpWidget(buildCard(step));
      expect(find.byType(CircularProgressIndicator), findsOneWidget);
    });

    testWidgets('shows expand icon when resultSummary is present', (tester) async {
      final step = ToolStepEvent(
        toolName: 'search',
        description: 'Searching files',
        status: ToolStepStatus.done,
        resultSummary: 'Found 3 files',
      );
      await tester.pumpWidget(buildCard(step));
      expect(find.byIcon(Icons.expand_more), findsOneWidget);
    });

    testWidgets('tapping expand icon reveals result summary', (tester) async {
      final step = ToolStepEvent(
        toolName: 'search',
        description: 'Searching files',
        status: ToolStepStatus.done,
        resultSummary: 'Found 3 files matching the pattern',
      );
      await tester.pumpWidget(buildCard(step));
      // Initially collapsed
      expect(find.text('Found 3 files matching the pattern'), findsNothing);
      // Tap to expand
      await tester.tap(find.byIcon(Icons.expand_more));
      await tester.pumpAndSettle();
      expect(find.text('Found 3 files matching the pattern'), findsOneWidget);
    });

    testWidgets('shows error icon when status is error', (tester) async {
      final step = ToolStepEvent(
        toolName: 'failing_tool',
        description: 'This tool failed',
        status: ToolStepStatus.error,
      );
      await tester.pumpWidget(buildCard(step));
      expect(find.byIcon(Icons.error), findsOneWidget);
    });
  });
}
