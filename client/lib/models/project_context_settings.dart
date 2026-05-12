import '../utils/json_helpers.dart';

class PinnedProject {
  const PinnedProject({
    required this.label,
    required this.cwd,
  });

  final String label;
  final String cwd;

  PinnedProject copyWith({
    String? label,
    String? cwd,
  }) {
    return PinnedProject(
      label: label ?? this.label,
      cwd: cwd ?? this.cwd,
    );
  }

  Map<String, dynamic> toJson() => {
        'label': label,
        'cwd': cwd,
      };

  factory PinnedProject.fromJson(Map<String, dynamic> json) {
    return PinnedProject(
      label: readStringFromJson(json['label']),
      cwd: readStringFromJson(json['cwd']),
    );
  }
}

class ApprovedScanRoot {
  const ApprovedScanRoot({
    required this.rootPath,
    this.scanDepth = 2,
    this.enabled = true,
  });

  final String rootPath;
  final int scanDepth;
  final bool enabled;

  ApprovedScanRoot copyWith({
    String? rootPath,
    int? scanDepth,
    bool? enabled,
  }) {
    return ApprovedScanRoot(
      rootPath: rootPath ?? this.rootPath,
      scanDepth: scanDepth ?? this.scanDepth,
      enabled: enabled ?? this.enabled,
    );
  }

  Map<String, dynamic> toJson() => {
        'root_path': rootPath,
        'scan_depth': scanDepth,
        'enabled': enabled,
      };

  factory ApprovedScanRoot.fromJson(Map<String, dynamic> json) {
    return ApprovedScanRoot(
      rootPath: readStringFromJson(json['root_path']),
      scanDepth: readIntFromJson(json['scan_depth']) == 0
          ? 2
          : readIntFromJson(json['scan_depth']),
      enabled: readBoolFromJson(json['enabled'], defaultValue: true),
    );
  }
}

class PlannerRuntimeConfigModel {
  const PlannerRuntimeConfigModel({
    this.provider = 'claude_cli',
    this.llmEnabled = true,
    this.endpointProfile = 'openai_compatible',
    this.credentialsMode = 'client_secure_storage',
    this.requiresExplicitOptIn = false,
  });

  final String provider;
  final bool llmEnabled;
  final String endpointProfile;
  final String credentialsMode;
  final bool requiresExplicitOptIn;

  PlannerRuntimeConfigModel copyWith({
    String? provider,
    bool? llmEnabled,
    String? endpointProfile,
    String? credentialsMode,
    bool? requiresExplicitOptIn,
  }) {
    return PlannerRuntimeConfigModel(
      provider: provider ?? this.provider,
      llmEnabled: llmEnabled ?? this.llmEnabled,
      endpointProfile: endpointProfile ?? this.endpointProfile,
      credentialsMode: credentialsMode ?? this.credentialsMode,
      requiresExplicitOptIn:
          requiresExplicitOptIn ?? this.requiresExplicitOptIn,
    );
  }

  Map<String, dynamic> toJson() => {
        'provider': provider,
        'llm_enabled': llmEnabled,
        'endpoint_profile': endpointProfile,
        'credentials_mode': credentialsMode,
        'requires_explicit_opt_in': requiresExplicitOptIn,
      };

  factory PlannerRuntimeConfigModel.fromJson(Map<String, dynamic> json) {
    return PlannerRuntimeConfigModel(
      provider: readStringFromJson(json['provider']).isEmpty
          ? 'claude_cli'
          : readStringFromJson(json['provider']),
      llmEnabled: readBoolFromJson(json['llm_enabled'], defaultValue: true),
      endpointProfile: readStringFromJson(json['endpoint_profile']).isEmpty
          ? 'openai_compatible'
          : readStringFromJson(json['endpoint_profile']),
      credentialsMode: readStringFromJson(json['credentials_mode']).isEmpty
          ? 'client_secure_storage'
          : readStringFromJson(json['credentials_mode']),
      requiresExplicitOptIn: readBoolFromJson(json['requires_explicit_opt_in']),
    );
  }
}

class ProjectContextSettings {
  const ProjectContextSettings({
    required this.deviceId,
    this.pinnedProjects = const [],
    this.approvedScanRoots = const [],
    this.plannerConfig = const PlannerRuntimeConfigModel(),
  });

  final String deviceId;
  final List<PinnedProject> pinnedProjects;
  final List<ApprovedScanRoot> approvedScanRoots;
  final PlannerRuntimeConfigModel plannerConfig;

  ProjectContextSettings copyWith({
    String? deviceId,
    List<PinnedProject>? pinnedProjects,
    List<ApprovedScanRoot>? approvedScanRoots,
    PlannerRuntimeConfigModel? plannerConfig,
  }) {
    return ProjectContextSettings(
      deviceId: deviceId ?? this.deviceId,
      pinnedProjects: pinnedProjects ?? this.pinnedProjects,
      approvedScanRoots: approvedScanRoots ?? this.approvedScanRoots,
      plannerConfig: plannerConfig ?? this.plannerConfig,
    );
  }

  Map<String, dynamic> toJson() => {
        'device_id': deviceId,
        'pinned_projects': pinnedProjects.map((item) => item.toJson()).toList(),
        'approved_scan_roots':
            approvedScanRoots.map((item) => item.toJson()).toList(),
        'planner_config': plannerConfig.toJson(),
      };

  factory ProjectContextSettings.fromJson(Map<String, dynamic> json) {
    return ProjectContextSettings(
      deviceId: readStringFromJson(json['device_id']),
      pinnedProjects: readListFromJson(
          json['pinned_projects'], PinnedProject.fromJson),
      approvedScanRoots: readListFromJson(
          json['approved_scan_roots'], ApprovedScanRoot.fromJson),
      plannerConfig: PlannerRuntimeConfigModel.fromJson(
        json['planner_config'] is Map<String, dynamic>
            ? json['planner_config'] as Map<String, dynamic>
            : const <String, dynamic>{},
      ),
    );
  }
}
