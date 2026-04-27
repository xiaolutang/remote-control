import 'dart:io';

import 'package:flutter/services.dart';

class DesktopAgentExitBridge {
  static const MethodChannel _channel =
      MethodChannel('rc_client/desktop_agent_lifecycle');

  static Future<void> syncTerminationSnapshot({
    required bool keepRunningInBackground,
    int? managedAgentPid,
  }) async {
    if (!_supported) return;
    try {
      await _channel.invokeMethod<void>(
        'syncTerminationSnapshot',
        <String, dynamic>{
          'keepRunningInBackground': keepRunningInBackground,
          'managedAgentPid': managedAgentPid,
        },
      );
    } catch (_) {
      // Best-effort sync for native shutdown handling.
    }
  }

  static bool get _supported => Platform.isMacOS;
}
