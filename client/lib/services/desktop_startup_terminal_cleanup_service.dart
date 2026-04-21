import 'dart:io';

import 'config_service.dart';
import 'runtime_device_service.dart';

class DesktopStartupTerminalCleanupService {
  DesktopStartupTerminalCleanupService({
    String serverUrl = '',
    RuntimeDeviceService? runtimeService,
    ConfigService? configService,
    bool? isDesktopPlatform,
  })  : _runtimeService =
            runtimeService ?? RuntimeDeviceService(serverUrl: serverUrl),
        _configService = configService ?? ConfigService(),
        _isDesktopPlatform = isDesktopPlatform ??
            (Platform.isMacOS || Platform.isLinux || Platform.isWindows);

  final RuntimeDeviceService _runtimeService;
  final ConfigService _configService;
  final bool _isDesktopPlatform;

  Future<void> cleanup({
    required String token,
    required String deviceId,
  }) async {
    if (!_isDesktopPlatform) {
      return;
    }

    final config = await _configService.loadConfig();
    if (config.keepAgentRunningInBackground) {
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
