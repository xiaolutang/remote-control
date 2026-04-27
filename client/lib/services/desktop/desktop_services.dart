/// Desktop services barrel file.
///
/// Re-exports all desktop-specific services so downstream code can
/// import from a single entry point.
library;

export 'desktop_agent_bootstrap_service.dart';
export 'desktop_agent_exit_bridge.dart';
export 'desktop_agent_http_client.dart';
export 'desktop_agent_manager.dart';
export 'desktop_agent_supervisor.dart';
export 'desktop_exit_policy_service.dart';
export 'desktop_startup_terminal_cleanup_service.dart';
export 'desktop_termination_snapshot_service.dart';
export 'desktop_workspace_controller.dart';
