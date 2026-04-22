import 'package:flutter_test/flutter_test.dart';
import 'package:rc_client/models/project_context_settings.dart';

void main() {
  group('PlannerRuntimeConfigModel', () {
    test('defaults to enabled Claude CLI planner', () {
      const config = PlannerRuntimeConfigModel();

      expect(config.provider, 'claude_cli');
      expect(config.llmEnabled, isTrue);
      expect(config.requiresExplicitOptIn, isFalse);
    });

    test('fromJson uses enabled smart planner defaults when fields are missing',
        () {
      final config = PlannerRuntimeConfigModel.fromJson(
        const <String, dynamic>{},
      );

      expect(config.provider, 'claude_cli');
      expect(config.llmEnabled, isTrue);
      expect(config.requiresExplicitOptIn, isFalse);
    });
  });
}
