import 'package:flutter_test/flutter_test.dart';
import 'package:rc_client/models/config.dart';
import 'package:rc_client/services/config_service.dart';
import 'package:rc_client/services/desktop_exit_policy_service.dart';
import 'package:rc_client/services/desktop_termination_snapshot_service.dart';
import 'package:rc_client/services/environment_service.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues({});
    EnvironmentService.setInstance(
      EnvironmentService(debugModeProvider: () => true),
    );
  });

  test('syncCurrentSnapshot uses stored policy and pid by default', () async {
    final configService = ConfigService();
    await configService.saveConfig(const AppConfig(
      desktopExitPolicy: DesktopExitPolicy.keepAgentRunningInBackground,
    ));
    final prefs = await SharedPreferences.getInstance();
    await prefs.setInt(
      DesktopTerminationSnapshotService.managedAgentPidPreferenceKey,
      321,
    );

    bool? keepRunningValue;
    int? pidValue;
    final service = DesktopTerminationSnapshotService(
      exitPolicyService: DesktopExitPolicyService(configService: configService),
      syncSnapshot: ({
        required bool keepRunningInBackground,
        int? managedAgentPid,
      }) async {
        keepRunningValue = keepRunningInBackground;
        pidValue = managedAgentPid;
      },
    );

    await service.syncCurrentSnapshot();

    expect(keepRunningValue, isTrue);
    expect(pidValue, 321);
  });

  test('saveManagedAgentPid persists pid and syncs full snapshot', () async {
    final configService = ConfigService();
    await configService.saveConfig(const AppConfig(
      desktopExitPolicy: DesktopExitPolicy.stopAgentOnExit,
    ));

    bool? keepRunningValue;
    int? pidValue;
    final service = DesktopTerminationSnapshotService(
      exitPolicyService: DesktopExitPolicyService(configService: configService),
      syncSnapshot: ({
        required bool keepRunningInBackground,
        int? managedAgentPid,
      }) async {
        keepRunningValue = keepRunningInBackground;
        pidValue = managedAgentPid;
      },
    );

    await service.saveManagedAgentPid(654);

    final prefs = await SharedPreferences.getInstance();
    expect(
      prefs.getInt(
          DesktopTerminationSnapshotService.managedAgentPidPreferenceKey),
      654,
    );
    expect(keepRunningValue, isFalse);
    expect(pidValue, 654);
  });

  test('clearManagedAgentPid removes pid and syncs null pid snapshot',
      () async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setInt(
      DesktopTerminationSnapshotService.managedAgentPidPreferenceKey,
      777,
    );

    int markerPid = -1;
    final service = DesktopTerminationSnapshotService(
      syncSnapshot: ({
        required bool keepRunningInBackground,
        int? managedAgentPid,
      }) async {
        markerPid = managedAgentPid ?? 0;
      },
    );

    await service.clearManagedAgentPid();

    expect(
      prefs.getInt(
          DesktopTerminationSnapshotService.managedAgentPidPreferenceKey),
      isNull,
    );
    expect(markerPid, 0);
  });
}
