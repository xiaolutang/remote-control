import '../models/app_environment.dart';
import 'auth_service.dart';
import 'desktop/desktop_agent_manager.dart';
import 'environment_service.dart';
import 'logout_helper.dart';
import 'terminal_session_manager.dart';

/// 统一编排环境切换的副作用，避免散落在 UI 层。
class EnvironmentSwitchCoordinator {
  const EnvironmentSwitchCoordinator();

  Future<void> switchEnvironment({
    required AppEnvironment newEnv,
    required DesktopAgentManager agentManager,
    required TerminalSessionManager sessionManager,
    AuthService Function(String serverUrl)? authServiceBuilder,
  }) async {
    if (newEnv == EnvironmentService.instance.currentEnvironment) {
      return;
    }

    await performSessionTeardown(
      agentManager: agentManager,
      sessionManager: sessionManager,
      authServiceBuilder: authServiceBuilder,
    );

    await EnvironmentService.instance.switchEnvironment(newEnv);
  }
}
