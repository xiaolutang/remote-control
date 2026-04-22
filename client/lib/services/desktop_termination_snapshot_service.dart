import 'package:flutter/widgets.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'desktop_agent_exit_bridge.dart';
import 'desktop_exit_policy_service.dart';

typedef DesktopTerminationSnapshotSync = Future<void> Function({
  required bool keepRunningInBackground,
  int? managedAgentPid,
});

class DesktopTerminationSnapshotService {
  DesktopTerminationSnapshotService({
    DesktopExitPolicyService? exitPolicyService,
    DesktopTerminationSnapshotSync? syncSnapshot,
  })  : _exitPolicyService = exitPolicyService ?? DesktopExitPolicyService(),
        _syncSnapshot =
            syncSnapshot ?? DesktopAgentExitBridge.syncTerminationSnapshot;

  static const String managedAgentPidPreferenceKey = 'rc_managed_agent_pid';

  final DesktopExitPolicyService _exitPolicyService;
  final DesktopTerminationSnapshotSync _syncSnapshot;

  Future<int?> loadManagedAgentPid() async {
    WidgetsFlutterBinding.ensureInitialized();
    final prefs = await SharedPreferences.getInstance();
    return prefs.getInt(managedAgentPidPreferenceKey);
  }

  Future<void> saveManagedAgentPid(int pid) async {
    WidgetsFlutterBinding.ensureInitialized();
    final prefs = await SharedPreferences.getInstance();
    await prefs.setInt(managedAgentPidPreferenceKey, pid);
    await syncCurrentSnapshot(managedAgentPid: pid);
  }

  Future<void> clearManagedAgentPid() async {
    WidgetsFlutterBinding.ensureInitialized();
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(managedAgentPidPreferenceKey);
    await syncCurrentSnapshot(managedAgentPid: null);
  }

  Future<void> syncCurrentSnapshot({
    bool? keepRunningInBackground,
    int? managedAgentPid,
  }) async {
    final keepRunning = keepRunningInBackground ??
        await _exitPolicyService.keepAgentRunningInBackground();
    final pid = managedAgentPid ?? await loadManagedAgentPid();
    await _syncSnapshot(
      keepRunningInBackground: keepRunning,
      managedAgentPid: pid,
    );
  }
}
