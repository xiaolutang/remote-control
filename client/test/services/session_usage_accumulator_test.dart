import 'package:flutter_test/flutter_test.dart';
import 'package:rc_client/services/session_usage_accumulator.dart';

void main() {
  group('SessionUsageAccumulator', () {
    late SessionUsageAccumulator acc;

    setUp(() {
      acc = SessionUsageAccumulator();
    });

    test('single event: properties match input values', () {
      acc.accumulate({
        'input_tokens': 100,
        'output_tokens': 50,
        'total_tokens': 150,
        'requests': 2,
      });

      expect(acc.inputTokens, 100);
      expect(acc.outputTokens, 50);
      expect(acc.totalTokens, 150);
      expect(acc.requests, 2);
    });

    test('multiple events: values accumulate correctly', () {
      acc.accumulate({
        'input_tokens': 100,
        'output_tokens': 50,
        'total_tokens': 150,
        'requests': 1,
      });
      acc.accumulate({
        'input_tokens': 200,
        'output_tokens': 80,
        'total_tokens': 280,
        'requests': 2,
      });
      acc.accumulate({
        'input_tokens': 300,
        'output_tokens': 120,
        'total_tokens': 420,
        'requests': 3,
      });

      expect(acc.inputTokens, 600);
      expect(acc.outputTokens, 250);
      expect(acc.totalTokens, 850);
      expect(acc.requests, 6);
    });

    test('reset: all fields return to zero', () {
      acc.accumulate({
        'input_tokens': 100,
        'output_tokens': 50,
        'total_tokens': 150,
        'requests': 1,
      });
      expect(acc.inputTokens, greaterThan(0));

      acc.reset();

      expect(acc.inputTokens, 0);
      expect(acc.outputTokens, 0);
      expect(acc.totalTokens, 0);
      expect(acc.requests, 0);
    });

    test('null/missing usage fields: skip without affecting totals', () {
      acc.accumulate({
        'input_tokens': 100,
        'output_tokens': 50,
        'total_tokens': 150,
        'requests': 1,
      });

      // null usage
      acc.accumulate(null);

      expect(acc.inputTokens, 100);
      expect(acc.outputTokens, 50);
      expect(acc.totalTokens, 150);
      expect(acc.requests, 1);

      // missing fields
      acc.accumulate(<String, dynamic>{});

      expect(acc.inputTokens, 100);
      expect(acc.outputTokens, 50);
      expect(acc.totalTokens, 150);
      expect(acc.requests, 1);
    });

    test('all-zero usage event: does not alter existing values', () {
      acc.accumulate({
        'input_tokens': 100,
        'output_tokens': 50,
        'total_tokens': 150,
        'requests': 1,
      });

      acc.accumulate({
        'input_tokens': 0,
        'output_tokens': 0,
        'total_tokens': 0,
        'requests': 0,
      });

      expect(acc.inputTokens, 100);
      expect(acc.outputTokens, 50);
      expect(acc.totalTokens, 150);
      expect(acc.requests, 1);
    });

    test('large values: no overflow in accumulation', () {
      const big = 0x7FFFFFFFFFFFFFFF; // max int64

      acc.accumulate({
        'input_tokens': big,
        'output_tokens': big,
        'total_tokens': big,
        'requests': 1,
      });

      // Dart int is 64-bit; adding to max will overflow but should not crash.
      expect(acc.inputTokens, isA<int>());
      expect(acc.requests, 1);

      // Single large value without further addition should be exact.
      acc.reset();
      acc.accumulate({
        'input_tokens': 999999999999,
        'output_tokens': 888888888888,
        'total_tokens': 777777777777,
        'requests': 123456789,
      });

      expect(acc.inputTokens, 999999999999);
      expect(acc.outputTokens, 888888888888);
      expect(acc.totalTokens, 777777777777);
      expect(acc.requests, 123456789);
    });

    test('toSummary returns correct snapshot', () {
      acc.accumulate({
        'input_tokens': 100,
        'output_tokens': 50,
        'total_tokens': 150,
        'requests': 2,
      });

      final summary = acc.toSummary();

      expect(summary['input_tokens'], 100);
      expect(summary['output_tokens'], 50);
      expect(summary['total_tokens'], 150);
      expect(summary['requests'], 2);
    });
  });
}
