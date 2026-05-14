import 'dart:io';

import '../app_logger.dart';
import '../config_service.dart';
import 'desktop_exit_policy_service.dart';
import '../runtime_device_service.dart';

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
    bool forceCleanup = false,
    bool agentOnline = false,
  }) async {
    if (!_isDesktopPlatform) {
      return;
    }

    if (!forceCleanup &&
        await _exitPolicyService.keepAgentRunningInBackground()) {
      return;
    }

    if (!forceCleanup && agentOnline) {
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
      } catch (e) {
        // Expected: best-effort stale terminal cleanup must not block startup restore.
        AppLogger('StartupCleanup').debug('closeTerminal failed for ${terminal.terminalId}: $e');
      }
    }
  }
}
