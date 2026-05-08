import 'dart:developer' as developer;
import 'dart:io' show Platform;

import 'package:flutter/foundation.dart';

/// Application-wide unified logger.
///
/// Replaces raw `debugPrint` calls in business code with structured,
/// tag-based log output using `dart:developer.log`.
///
/// Usage:
/// ```dart
/// import 'app_logger.dart';
///
/// final _log = AppLogger('MyModule');
///
/// _log.info('something happened');
/// _log.warning('unexpected state');
/// _log.error('operation failed: $e');
/// ```
class AppLogger {
  final String tag;

  const AppLogger(this.tag);

  /// Debug-level message. Only emitted in debug mode.
  void debug(String message) {
    if (!kDebugMode) return;
    _emit('DEBUG', message);
  }

  /// Informational message.
  void info(String message) {
    _emit('INFO', message);
  }

  /// Warning message.
  void warning(String message) {
    _emit('WARN', message);
  }

  /// Error message.
  void error(String message) {
    _emit('ERROR', message);
  }

  void _emit(String level, String message) {
    if (Platform.environment.containsKey('FLUTTER_TEST')) return;
    developer.log(
      '[$level] [$tag] $message',
      name: tag,
      level: _levelValue(level),
    );
  }

  static int _levelValue(String level) {
    switch (level) {
      case 'DEBUG':
        return 500;
      case 'INFO':
        return 800;
      case 'WARN':
        return 900;
      case 'ERROR':
        return 1000;
      default:
        return 800;
    }
  }
}
