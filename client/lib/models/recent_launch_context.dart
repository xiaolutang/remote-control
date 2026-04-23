import 'terminal_launch_plan.dart';

class RecentLaunchContext {
  const RecentLaunchContext({
    required this.deviceId,
    required this.lastTool,
    required this.lastCwd,
    required this.lastSuccessfulPlan,
    required this.updatedAt,
  });

  final String deviceId;
  final TerminalLaunchTool lastTool;
  final String lastCwd;
  final TerminalLaunchPlan lastSuccessfulPlan;
  final DateTime updatedAt;

  Map<String, dynamic> toJson() {
    return {
      'device_id': deviceId,
      'last_tool': TerminalLaunchToolCodec.toJson(lastTool),
      'last_cwd': lastCwd,
      'last_successful_plan': lastSuccessfulPlan.toJson(),
      'updated_at': updatedAt.toIso8601String(),
    };
  }

  RecentLaunchContext copyWith({
    String? deviceId,
    TerminalLaunchTool? lastTool,
    String? lastCwd,
    TerminalLaunchPlan? lastSuccessfulPlan,
    DateTime? updatedAt,
  }) {
    return RecentLaunchContext(
      deviceId: deviceId ?? this.deviceId,
      lastTool: lastTool ?? this.lastTool,
      lastCwd: lastCwd ?? this.lastCwd,
      lastSuccessfulPlan: lastSuccessfulPlan ?? this.lastSuccessfulPlan,
      updatedAt: updatedAt ?? this.updatedAt,
    );
  }

  static RecentLaunchContext? tryFromJson(
    Map<String, dynamic>? json, {
    String? fallbackDeviceId,
  }) {
    if (json == null) {
      return null;
    }
    final deviceId = TerminalLaunchPlan.normalizedString(json['device_id']) ??
        TerminalLaunchPlan.normalizedString(fallbackDeviceId);
    if (deviceId == null) {
      return null;
    }

    final lastCwd = TerminalLaunchPlan.normalizedString(json['last_cwd']) ?? '~';
    final rawLastTool =
        TerminalLaunchToolCodec.fromJson(json['last_tool'] as String?);

    final rawPlan = json['last_successful_plan'];
    final lastSuccessfulPlan = rawPlan is Map
        ? TerminalLaunchPlan.fromJson(Map<String, dynamic>.from(rawPlan))
        : _fallbackPlan(rawLastTool ?? TerminalLaunchTool.shell, lastCwd);
    final lastTool = rawLastTool ?? lastSuccessfulPlan.tool;

    final updatedAt =
        DateTime.tryParse((json['updated_at'] as String?) ?? '') ??
            DateTime.fromMillisecondsSinceEpoch(0);

    return RecentLaunchContext(
      deviceId: deviceId,
      lastTool: lastTool,
      lastCwd: lastSuccessfulPlan.cwd.trim().isEmpty
          ? lastCwd
          : lastSuccessfulPlan.cwd,
      lastSuccessfulPlan: lastSuccessfulPlan,
      updatedAt: updatedAt,
    );
  }

  static TerminalLaunchPlan _fallbackPlan(
    TerminalLaunchTool tool,
    String cwd,
  ) {
    final defaults = TerminalLaunchPlanDefaults.forTool(tool);
    return TerminalLaunchPlan(
      tool: tool,
      title: TerminalLaunchPlanDefaults.titleFor(tool, cwd),
      cwd: cwd,
      command: defaults.command,
      entryStrategy: defaults.entryStrategy,
      postCreateInput: defaults.postCreateInput,
      source: TerminalLaunchPlanSource.recommended,
    );
  }
}
