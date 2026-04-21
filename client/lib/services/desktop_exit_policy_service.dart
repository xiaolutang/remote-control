import '../models/config.dart';
import 'config_service.dart';

class DesktopExitPolicyService {
  DesktopExitPolicyService({
    ConfigService? configService,
  }) : _configService = configService ?? ConfigService();

  final ConfigService _configService;

  Future<DesktopExitPolicy> loadPolicy() async {
    final config = await _configService.loadConfig();
    return config.desktopExitPolicy;
  }

  Future<bool> keepAgentRunningInBackground() async {
    return (await loadPolicy()) ==
        DesktopExitPolicy.keepAgentRunningInBackground;
  }

  Future<AppConfig> savePolicy(DesktopExitPolicy policy) async {
    final config = await _configService.loadConfig();
    if (config.desktopExitPolicy == policy) {
      return config;
    }

    final updated = config.copyWith(desktopExitPolicy: policy);
    await _configService.saveConfig(updated);
    return updated;
  }

  Future<AppConfig> setKeepAgentRunningInBackground(bool value) {
    return savePolicy(
      value
          ? DesktopExitPolicy.keepAgentRunningInBackground
          : DesktopExitPolicy.stopAgentOnExit,
    );
  }
}
