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
      final raw = json[key] as String?;
      return raw == null ? null : DateTime.tryParse(raw);
    }

    return ProjectContextCandidate(
      candidateId: json['candidate_id'] as String? ?? '',
      deviceId: json['device_id'] as String? ?? '',
      label: json['label'] as String? ?? '',
      cwd: json['cwd'] as String? ?? '',
      source: json['source'] as String? ?? 'recent_terminal',
      toolHints: ((json['tool_hints'] as List<dynamic>?) ?? const [])
          .whereType<String>()
          .toList(growable: false),
      updatedAt: parseDate('updated_at'),
      lastUsedAt: parseDate('last_used_at'),
      requiresConfirmation: json['requires_confirmation'] as bool? ?? false,
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
      deviceId: json['device_id'] as String? ?? '',
      generatedAt: DateTime.tryParse(json['generated_at'] as String? ?? '') ??
          DateTime.fromMillisecondsSinceEpoch(0),
      candidates: ((json['candidates'] as List<dynamic>?) ?? const [])
          .whereType<Map<String, dynamic>>()
          .map(ProjectContextCandidate.fromJson)
          .toList(growable: false),
    );
  }
}
