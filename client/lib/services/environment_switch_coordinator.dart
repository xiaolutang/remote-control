import 'package:flutter/widgets.dart';

import '../models/app_environment.dart';
import 'auth_service.dart';
import 'environment_service.dart';
import 'logout_helper.dart';

/// 统一编排环境切换的副作用，避免散落在 UI 层。
class EnvironmentSwitchCoordinator {
  const EnvironmentSwitchCoordinator();

  Future<void> switchEnvironment({
    required BuildContext context,
    required AppEnvironment newEnv,
    AuthService Function(String serverUrl)? authServiceBuilder,
  }) async {
    if (newEnv == EnvironmentService.instance.currentEnvironment) {
      return;
    }

    await performSessionTeardown(
      context: context,
      authServiceBuilder: authServiceBuilder,
    );

    await EnvironmentService.instance.switchEnvironment(newEnv);
  }
}
