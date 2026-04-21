import 'dart:async';

import '../models/runtime_device.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'auth_service.dart';
import 'desktop_agent_manager.dart';
import 'runtime_device_service.dart';

enum AppStartupDestination {
  login,
  workspace,
}

class AppStartupResult {
  const AppStartupResult.login()
      : destination = AppStartupDestination.login,
        token = null,
        initialDevices = const <RuntimeDevice>[];

  const AppStartupResult.workspace({
    required this.token,
    this.initialDevices = const <RuntimeDevice>[],
  }) : destination = AppStartupDestination.workspace;

  final AppStartupDestination destination;
  final String? token;
  final List<RuntimeDevice> initialDevices;
}

class AppStartupCoordinator {
  AppStartupCoordinator({
    required this.serverUrl,
    AuthService? authService,
    RuntimeDeviceService? runtimeService,
  })  : _authService = authService ?? AuthService(serverUrl: serverUrl),
        _runtimeService =
            runtimeService ?? RuntimeDeviceService(serverUrl: serverUrl);

  final String serverUrl;
  final AuthService _authService;
  final RuntimeDeviceService _runtimeService;

  Future<AppStartupResult> restore({
    required DesktopAgentManager agentManager,
  }) async {
    final prefs = await SharedPreferences.getInstance();
    final savedUsername = prefs.getString('rc_username') ?? '';
    Map<String, String>? savedSession;

    try {
      savedSession = await _authService.getSavedSession(
        includeRefreshToken: false,
      );
    } catch (_) {
      savedSession = null;
    }

    if (savedSession != null && savedUsername.isNotEmpty) {
      final token = savedSession['token']!;
      final sessionId = savedSession['session_id']!;

      try {
        final devices = await _runtimeService.listDevices(token);
        _restoreAgentInBackground(
          agentManager,
          token: token,
          username: savedUsername,
          deviceId: sessionId,
        );
        return AppStartupResult.workspace(
          token: token,
          initialDevices: devices,
        );
      } on AuthException {
        // Saved session invalid; fall through to password auto-login.
      } catch (_) {
        return const AppStartupResult.login();
      }
    }

    Map<String, String>? savedCredentials;
    try {
      savedCredentials = await _authService.getSavedCredentials();
    } catch (_) {
      return const AppStartupResult.login();
    }

    if (savedCredentials == null) {
      return const AppStartupResult.login();
    }

    try {
      final result = await _authService.login(
        savedCredentials['username']!,
        savedCredentials['password']!,
      );
      final token = result['token'] as String;
      final sessionId = result['session_id'] as String?;
      if (sessionId != null && sessionId.isNotEmpty) {
        _restoreAgentInBackground(
          agentManager,
          token: token,
          username: savedCredentials['username']!,
          deviceId: sessionId,
        );
      }
      return AppStartupResult.workspace(token: token);
    } catch (_) {
      return const AppStartupResult.login();
    }
  }

  void _restoreAgentInBackground(
    DesktopAgentManager agentManager, {
    required String token,
    required String username,
    required String deviceId,
  }) {
    unawaited(
      agentManager
          .onAppStart(
            serverUrl: serverUrl,
            token: token,
            username: username,
            deviceId: deviceId,
          )
          .catchError((_) {}),
    );
  }
}
