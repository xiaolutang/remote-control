import 'dart:async';
import 'dart:io';

import '../app_logger.dart';
import 'desktop_agent_manager.dart';
import 'desktop_agent_supervisor.dart';
import '../runtime_device_service.dart';

final AppLogger _log = AppLogger('BootstrapAction');

class DesktopAgentBootstrapService {
  DesktopAgentBootstrapService({
    RuntimeDeviceService? runtimeService,
    DesktopAgentSupervisor? supervisor,
  })  : _runtimeService = runtimeService,
        _supervisor = supervisor;

  final RuntimeDeviceService? _runtimeService;
  final DesktopAgentSupervisor? _supervisor;

  bool get supported =>
      !Platform.isAndroid && !Platform.isIOS;

  Future<DesktopAgentState> loadAgentState({
    required String serverUrl,
    required String token,
    required String deviceId,
  }) {
    final manager = DesktopAgentManager(
      serverUrl: serverUrl,
      token: token,
      deviceId: deviceId,
      supervisor: _supervisor ?? DesktopAgentSupervisor(runtimeService: _runtimeService),
    );
    return manager.loadState();
  }

  Future<DesktopAgentState> startAgent({
    required String serverUrl,
    required String token,
    required String deviceId,
    Duration timeout = const Duration(seconds: 12),
  }) {
    _log.info('startAgent request device=$deviceId');
    final manager = DesktopAgentManager(
      serverUrl: serverUrl,
      token: token,
      deviceId: deviceId,
      supervisor: _supervisor ?? DesktopAgentSupervisor(runtimeService: _runtimeService),
    );
    return manager.startAgent(timeout: timeout).then((state) {
      _log.info(
        'startAgent result device=$deviceId kind=${state.kind.name}',
      );
      return state;
    });
  }

  Future<bool> ensureAgentOnline({
    required String serverUrl,
    required String token,
    required String deviceId,
    Duration timeout = const Duration(seconds: 12),
  }) async {
    final state = await startAgent(
      serverUrl: serverUrl,
      token: token,
      deviceId: deviceId,
      timeout: timeout,
    );
    return state.online;
  }

  Future<DesktopAgentStatus> getStatus({
    required String serverUrl,
    required String token,
    required String deviceId,
  }) async {
    final supervisor =
        _supervisor ??
        DesktopAgentSupervisor(runtimeService: _runtimeService);
    return supervisor.getStatus(
      serverUrl: serverUrl,
      token: token,
      deviceId: deviceId,
    );
  }

  Future<bool> stopManagedAgent({
    required String serverUrl,
    required String token,
    required String deviceId,
    Duration timeout = const Duration(seconds: 8),
  }) async {
    final supervisor =
        _supervisor ??
        DesktopAgentSupervisor(runtimeService: _runtimeService);
    return supervisor.stopManagedAgent(
      serverUrl: serverUrl,
      token: token,
      deviceId: deviceId,
      timeout: timeout,
    );
  }

  Future<void> clearManagedOwnership() async {
    final supervisor =
        _supervisor ??
        DesktopAgentSupervisor(runtimeService: _runtimeService);
    await supervisor.clearManagedOwnership();
  }

  Future<void> syncNativeTerminationState({
    required bool keepRunningInBackground,
  }) async {
    final supervisor =
        _supervisor ??
        DesktopAgentSupervisor(runtimeService: _runtimeService);
    await supervisor.syncNativeTerminationState(
      keepRunningInBackground: keepRunningInBackground,
    );
  }

  Future<bool> handleDesktopExit({
    required bool keepRunningInBackground,
    required String serverUrl,
    required String token,
    required String deviceId,
    Duration timeout = const Duration(seconds: 8),
  }) async {
    final supervisor =
        _supervisor ??
        DesktopAgentSupervisor(runtimeService: _runtimeService);
    return supervisor.handleDesktopExit(
      keepRunningInBackground: keepRunningInBackground,
      serverUrl: serverUrl,
      token: token,
      deviceId: deviceId,
      timeout: timeout,
    );
  }
}
