import 'dart:async';

import '../models/terminal_launch_plan.dart';
import 'terminal_session_manager.dart';
import 'websocket_service.dart';

class PreparedTerminalLaunchSession {
  const PreparedTerminalLaunchSession({
    required this.service,
    required this.connected,
    required this.bootstrapPrepared,
    required this.bootstrapDispatched,
    required this.observedOutputSummary,
  });

  final WebSocketService service;
  final bool connected;
  final bool bootstrapPrepared;
  final bool bootstrapDispatched;
  final String? observedOutputSummary;
}

class TerminalLaunchSessionService {
  const TerminalLaunchSessionService({
    Duration bootstrapInputDelay = const Duration(milliseconds: 250),
    Duration initialOutputObservationTimeout = const Duration(seconds: 1),
  })  : _bootstrapInputDelay = bootstrapInputDelay,
        initialOutputObservationTimeout = initialOutputObservationTimeout;

  final Duration _bootstrapInputDelay;
  final Duration initialOutputObservationTimeout;

  Future<PreparedTerminalLaunchSession> prepareConnectedSession({
    required TerminalSessionManager sessionManager,
    required String? deviceId,
    required String terminalId,
    required WebSocketService Function() serviceFactory,
    TerminalLaunchPlan? plan,
    FutureOr<void> Function()? onBootstrapDispatched,
  }) async {
    final service = sessionManager.getOrCreate(
      deviceId,
      terminalId,
      serviceFactory,
    );
    final connected = await service.connect();
    if (!connected || service.status != ConnectionStatus.connected) {
      return PreparedTerminalLaunchSession(
        service: service,
        connected: false,
        bootstrapPrepared: false,
        bootstrapDispatched: false,
        observedOutputSummary: null,
      );
    }

    if (plan == null) {
      return PreparedTerminalLaunchSession(
        service: service,
        connected: true,
        bootstrapPrepared: false,
        bootstrapDispatched: false,
        observedOutputSummary: null,
      );
    }

    var dispatched = false;
    final outputFuture = _observeFirstMeaningfulOutput(service);
    final completer = Completer<void>();
    ensureSession(
      sessionManager: sessionManager,
      deviceId: deviceId,
      terminalId: terminalId,
      serviceFactory: serviceFactory,
      plan: plan,
      onBootstrapDispatched: () async {
        dispatched = true;
        if (onBootstrapDispatched != null) {
          await onBootstrapDispatched();
        }
        if (!completer.isCompleted) {
          completer.complete();
        }
      },
    );
    try {
      await completer.future.timeout(
        _bootstrapInputDelay + const Duration(seconds: 1),
      );
    } on TimeoutException {
      // 留给终端页继续接管，不把“未在等待窗口内收到回调”视为硬失败。
    }

    String? observedOutputSummary;
    if (dispatched) {
      try {
        observedOutputSummary =
            await outputFuture.timeout(initialOutputObservationTimeout);
      } on TimeoutException {
        observedOutputSummary = null;
      }
    }

    return PreparedTerminalLaunchSession(
      service: service,
      connected: true,
      bootstrapPrepared: true,
      bootstrapDispatched: dispatched,
      observedOutputSummary: observedOutputSummary,
    );
  }

  Future<String?> _observeFirstMeaningfulOutput(WebSocketService service) async {
    await for (final chunk in service.outputStream) {
      final summary = _summarizeOutput(chunk);
      if (summary != null) {
        return summary;
      }
    }
    return null;
  }

  String? _summarizeOutput(String raw) {
    final normalized = raw
        .replaceAll(RegExp(r'\x1B\[[0-9;?]*[ -/]*[@-~]'), ' ')
        .replaceAll(RegExp(r'[\x00-\x08\x0B-\x1F\x7F]'), ' ')
        .replaceAll(RegExp(r'\s+'), ' ')
        .trim();
    if (normalized.isEmpty) {
      return null;
    }
    if (normalized.length <= 120) {
      return normalized;
    }
    return '${normalized.substring(0, 120)}...';
  }

  WebSocketService ensureSession({
    required TerminalSessionManager sessionManager,
    required String? deviceId,
    required String terminalId,
    required WebSocketService Function() serviceFactory,
    TerminalLaunchPlan? plan,
    FutureOr<void> Function()? onBootstrapDispatched,
  }) {
    final service = sessionManager.getOrCreate(
      deviceId,
      terminalId,
      serviceFactory,
    );
    if (plan != null) {
      _schedulePostCreateBootstrap(
        service,
        plan,
        onBootstrapDispatched: onBootstrapDispatched,
      );
    }
    return service;
  }

  void _schedulePostCreateBootstrap(
      WebSocketService service, TerminalLaunchPlan plan,
      {FutureOr<void> Function()? onBootstrapDispatched}) {
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
          if (onBootstrapDispatched != null) {
            unawaited(Future<void>.sync(onBootstrapDispatched));
          }
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
