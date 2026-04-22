import 'dart:async';

import '../models/terminal_launch_plan.dart';
import 'terminal_session_manager.dart';
import 'websocket_service.dart';

class TerminalLaunchSessionService {
  const TerminalLaunchSessionService({
    Duration bootstrapInputDelay = const Duration(milliseconds: 250),
  }) : _bootstrapInputDelay = bootstrapInputDelay;

  final Duration _bootstrapInputDelay;

  WebSocketService ensureSession({
    required TerminalSessionManager sessionManager,
    required String? deviceId,
    required String terminalId,
    required WebSocketService Function() serviceFactory,
    TerminalLaunchPlan? plan,
  }) {
    final service = sessionManager.getOrCreate(
      deviceId,
      terminalId,
      serviceFactory,
    );
    if (plan != null) {
      _schedulePostCreateBootstrap(service, plan);
    }
    return service;
  }

  void _schedulePostCreateBootstrap(
    WebSocketService service,
    TerminalLaunchPlan plan,
  ) {
    if (plan.entryStrategy != TerminalEntryStrategy.shellBootstrap ||
        plan.postCreateInput.isEmpty) {
      return;
    }

    StreamSubscription<void>? subscription;
    var sent = false;

    void sendOnce() {
      if (sent) {
        return;
      }
      sent = true;
      unawaited(subscription?.cancel());
      unawaited(
        Future<void>.delayed(_bootstrapInputDelay, () {
          service.send(plan.postCreateInput);
        }),
      );
    }

    if (service.status == ConnectionStatus.connected) {
      sendOnce();
      return;
    }

    subscription = service.terminalConnectedStream.listen((_) {
      sendOnce();
    });
  }
}
