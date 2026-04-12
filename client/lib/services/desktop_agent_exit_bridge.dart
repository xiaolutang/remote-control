import 'dart:io';

import 'package:flutter/services.dart';

class DesktopAgentExitBridge {
  static const MethodChannel _channel =
      MethodChannel('rc_client/desktop_agent_lifecycle');

  static Future<void> syncKeepRunningInBackground(bool keepRunning) async {
    if (!_supported) return;
    try {
      await _channel.invokeMethod<void>(
        'setKeepRunningInBackground',
        <String, dynamic>{'value': keepRunning},
      );
    } catch (_) {
      // Best-effort sync for native shutdown handling.
    }
  }

  static Future<void> syncManagedAgentPid(int? pid) async {
    if (!_supported) return;
    try {
      if (pid == null) {
        await _channel.invokeMethod<void>('clearManagedAgentPid');
      } else {
        await _channel.invokeMethod<void>(
          'setManagedAgentPid',
          <String, dynamic>{'pid': pid},
        );
      }
    } catch (_) {
      // Best-effort sync for native shutdown handling.
    }
  }

  static bool get _supported => Platform.isMacOS;
}
