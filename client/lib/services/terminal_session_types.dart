part of 'terminal_session_manager.dart';

/// Recovery 超时时间：如果 snapshot_complete 未在此时间内到达，
/// 自动 finishRecovery 以防止终端永久卡在 recovering 状态。
const Duration _recoveryTimeout = Duration(seconds: 5);
const Duration _postInterruptReplyHold = Duration(milliseconds: 350);
const Duration _postRecoveryReplyDrop = Duration(seconds: 2);
const bool _enableTerminalTransitionLogs = false;

enum _TerminalReplyGuardMode {
  none,
  interrupt,
  recovery,
}

bool _shouldSuppressAutoResponse(
  _TerminalReplyGuardMode mode,
  TerminalAutoResponseKind kind,
) {
  switch (mode) {
    case _TerminalReplyGuardMode.none:
      return false;
    case _TerminalReplyGuardMode.interrupt:
      return true;
    case _TerminalReplyGuardMode.recovery:
      return kind == TerminalAutoResponseKind.statusReport ||
          kind == TerminalAutoResponseKind.cursorReport;
  }
}

/// Terminal session 状态机枚举（F072）
enum TerminalSessionState {
  idle,
  connecting,
  recovering,
  live,
  reconnecting,
  error,
}
