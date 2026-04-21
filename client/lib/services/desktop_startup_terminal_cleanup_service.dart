import 'dart:io';

import 'config_service.dart';
import 'desktop_exit_policy_service.dart';
import 'runtime_device_service.dart';

class DesktopStartupTerminalCleanupService {
  DesktopStartupTerminalCleanupService({
    String serverUrl = '',
    RuntimeDeviceService? runtimeService,
    ConfigService? configService,
    DesktopExitPolicyService? exitPolicyService,
    bool? isDesktopPlatform,
  })  : _runtimeService =
            runtimeService ?? RuntimeDeviceService(serverUrl: serverUrl),
        _exitPolicyService = exitPolicyService ??
            DesktopExitPolicyService(configService: configService),
        _isDesktopPlatform = isDesktopPlatform ??
            (Platform.isMacOS || Platform.isLinux || Platform.isWindows);

  final RuntimeDeviceService _runtimeService;
  final DesktopExitPolicyService _exitPolicyService;
  final bool _isDesktopPlatform;

  Future<void> cleanup({
    required String token,
    required String deviceId,
  }) async {
    if (!_isDesktopPlatform) {
      return;
    }

    if (await _exitPolicyService.keepAgentRunningInBackground()) {
      return;
    }

    final terminals = await _runtimeService.listTerminals(token, deviceId);
    for (final terminal in terminals) {
      if (terminal.isClosed) {
        continue;
      }
      try {
        await _runtimeService.closeTerminal(
            token, deviceId, terminal.terminalId);
      } catch (_) {
        // Best effort: stale terminal cleanup must not block startup restore.
      }
    }
  }
}
