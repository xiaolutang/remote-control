import 'package:flutter_test/flutter_test.dart';
import 'package:rc_client/models/scheduled_task.dart';

void main() {
  group('ScheduledTaskRepeatType', () {
    test('fromString: once -> once', () {
      expect(ScheduledTaskRepeatType.fromString('once'),
          ScheduledTaskRepeatType.once);
    });

    test('fromString: daily -> daily', () {
      expect(ScheduledTaskRepeatType.fromString('daily'),
          ScheduledTaskRepeatType.daily);
    });

    test('fromString: unknown value degrades to once', () {
      expect(ScheduledTaskRepeatType.fromString('unknown'),
          ScheduledTaskRepeatType.once);
    });

    test('fromString: null degrades to once', () {
      expect(ScheduledTaskRepeatType.fromString(null),
          ScheduledTaskRepeatType.once);
    });

    test('fromString: empty string degrades to once', () {
      expect(ScheduledTaskRepeatType.fromString(''),
          ScheduledTaskRepeatType.once);
    });

    test('toApiString: once -> "once"', () {
      expect(ScheduledTaskRepeatType.once.toApiString(), 'once');
    });

    test('toApiString: daily -> "daily"', () {
      expect(ScheduledTaskRepeatType.daily.toApiString(), 'daily');
    });

    test('displayLabel: once -> 单次', () {
      expect(ScheduledTaskRepeatType.once.displayLabel, '单次');
    });

    test('displayLabel: daily -> 每天', () {
      expect(ScheduledTaskRepeatType.daily.displayLabel, '每天');
    });
  });
}
