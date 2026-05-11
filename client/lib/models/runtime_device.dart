import '../utils/json_helpers.dart';

class RuntimeDevice {
  const RuntimeDevice({
    required this.deviceId,
    required this.name,
    required this.owner,
    required this.agentOnline,
    this.platform = '',
    this.hostname = '',
    required this.maxTerminals,
    required this.activeTerminals,
    this.lastHeartbeatAt,
  });

  final String deviceId;
  final String name;
  final String owner;
  final bool agentOnline;
  final String platform;
  final String hostname;
  final int maxTerminals;
  final int activeTerminals;
  final DateTime? lastHeartbeatAt;

  bool get canCreateTerminal => agentOnline && activeTerminals < maxTerminals;

  RuntimeDevice copyWith({
    String? deviceId,
    String? name,
    String? owner,
    bool? agentOnline,
    String? platform,
    String? hostname,
    int? maxTerminals,
    int? activeTerminals,
    DateTime? lastHeartbeatAt,
  }) {
    return RuntimeDevice(
      deviceId: deviceId ?? this.deviceId,
      name: name ?? this.name,
      owner: owner ?? this.owner,
      agentOnline: agentOnline ?? this.agentOnline,
      platform: platform ?? this.platform,
      hostname: hostname ?? this.hostname,
      maxTerminals: maxTerminals ?? this.maxTerminals,
      activeTerminals: activeTerminals ?? this.activeTerminals,
      lastHeartbeatAt: lastHeartbeatAt ?? this.lastHeartbeatAt,
    );
  }

  factory RuntimeDevice.fromJson(Map<String, dynamic> json) {
    return RuntimeDevice(
      deviceId: readStringFromJson(json['device_id']),
      name: readStringFromJson(json['name']),
      owner: readStringFromJson(json['owner']),
      agentOnline: json['agent_online'] as bool? ?? false,
      platform: readStringFromJson(json['platform']),
      hostname: readStringFromJson(json['hostname']),
      maxTerminals: json['max_terminals'] as int? ?? 3,
      activeTerminals: readIntFromJson(json['active_terminals']),
      lastHeartbeatAt: json['last_heartbeat_at'] == null
          ? null
          : DateTime.tryParse(json['last_heartbeat_at'] as String),
    );
  }
}
