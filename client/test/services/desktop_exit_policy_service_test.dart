import 'package:flutter_test/flutter_test.dart';
import 'package:rc_client/models/config.dart';
import 'package:rc_client/services/config_service.dart';
import 'package:rc_client/services/desktop/desktop_exit_policy_service.dart';
import 'package:rc_client/services/environment_service.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues({});
    EnvironmentService.setInstance(
      EnvironmentService(debugModeProvider: () => true),
    );
  });

  test('defaults to stopAgentOnExit', () async {
    final service = DesktopExitPolicyService();

    expect(await service.loadPolicy(), DesktopExitPolicy.stopAgentOnExit);
    expect(await service.keepAgentRunningInBackground(), isFalse);
  });

  test('setKeepAgentRunningInBackground persists keep-running policy',
      () async {
    final configService = ConfigService();
    final service = DesktopExitPolicyService(configService: configService);

    await service.setKeepAgentRunningInBackground(true);
    final restored = await configService.loadConfig();

    expect(
      restored.desktopExitPolicy,
      DesktopExitPolicy.keepAgentRunningInBackground,
    );
    expect(await service.keepAgentRunningInBackground(), isTrue);
  });

  test('savePolicy is idempotent when policy is unchanged', () async {
    final configService = ConfigService();
    await configService.saveConfig(const AppConfig(
      desktopExitPolicy: DesktopExitPolicy.keepAgentRunningInBackground,
      preferredDeviceId: 'device-1',
    ));
    final service = DesktopExitPolicyService(configService: configService);

    final restored = await service.savePolicy(
      DesktopExitPolicy.keepAgentRunningInBackground,
    );

    expect(
      restored.desktopExitPolicy,
      DesktopExitPolicy.keepAgentRunningInBackground,
    );
    expect(restored.preferredDeviceId, 'device-1');
  });
}
