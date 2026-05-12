import '../utils/json_helpers.dart'
    show readBoolFromJson, readListFromJson, readStringFromJson;

class ProjectContextCandidate {
  const ProjectContextCandidate({
    required this.candidateId,
    required this.deviceId,
    required this.label,
    required this.cwd,
    required this.source,
    this.toolHints = const [],
    this.updatedAt,
    this.lastUsedAt,
    this.requiresConfirmation = false,
  });

  final String candidateId;
  final String deviceId;
  final String label;
  final String cwd;
  final String source;
  final List<String> toolHints;
  final DateTime? updatedAt;
  final DateTime? lastUsedAt;
  final bool requiresConfirmation;

  Map<String, dynamic> toJson() => {
        'candidate_id': candidateId,
        'device_id': deviceId,
        'label': label,
        'cwd': cwd,
        'source': source,
        'tool_hints': toolHints,
        if (updatedAt != null) 'updated_at': updatedAt!.toIso8601String(),
        if (lastUsedAt != null) 'last_used_at': lastUsedAt!.toIso8601String(),
        'requires_confirmation': requiresConfirmation,
      };

  factory ProjectContextCandidate.fromJson(Map<String, dynamic> json) {
    DateTime? parseDate(String key) {
      final raw = json[key];
      if (raw is! String) return null;
      return DateTime.tryParse(raw);
    }

    final source = readStringFromJson(json['source']);
    return ProjectContextCandidate(
      candidateId: readStringFromJson(json['candidate_id']),
      deviceId: readStringFromJson(json['device_id']),
      label: readStringFromJson(json['label']),
      cwd: readStringFromJson(json['cwd']),
      source: source.isEmpty ? 'recent_terminal' : source,
      toolHints: json['tool_hints'] is List
          ? (json['tool_hints'] as List).whereType<String>().toList(growable: false)
          : const <String>[],
      updatedAt: parseDate('updated_at'),
      lastUsedAt: parseDate('last_used_at'),
      requiresConfirmation: readBoolFromJson(json['requires_confirmation']),
    );
  }
}

class DeviceProjectContextSnapshot {
  const DeviceProjectContextSnapshot({
    required this.deviceId,
    required this.generatedAt,
    this.candidates = const [],
  });

  final String deviceId;
  final DateTime generatedAt;
  final List<ProjectContextCandidate> candidates;

  Map<String, dynamic> toJson() => {
        'device_id': deviceId,
        'generated_at': generatedAt.toIso8601String(),
        'candidates': candidates.map((item) => item.toJson()).toList(),
      };

  factory DeviceProjectContextSnapshot.fromJson(Map<String, dynamic> json) {
    return DeviceProjectContextSnapshot(
      deviceId: readStringFromJson(json['device_id']),
      generatedAt: DateTime.tryParse(
              json['generated_at'] is String ? json['generated_at'] as String : '') ??
          DateTime.fromMillisecondsSinceEpoch(0),
      candidates: readListFromJson(
          json['candidates'], ProjectContextCandidate.fromJson),
    );
  }
}
