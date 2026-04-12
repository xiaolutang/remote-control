/// Agent 所有权信息
///
/// 用于判断 Agent 是否属于当前登录用户
class AgentOwnershipInfo {
  const AgentOwnershipInfo({
    required this.serverUrl,
    required this.username,
    required this.deviceId,
  });

  final String serverUrl;
  final String username;
  final String deviceId;

  /// 从 JSON 反序列化
  factory AgentOwnershipInfo.fromJson(Map<String, dynamic> json) {
    return AgentOwnershipInfo(
      serverUrl: json['server_url'] as String? ?? '',
      username: json['username'] as String? ?? '',
      deviceId: json['device_id'] as String? ?? '',
    );
  }

  /// 序列化为 JSON
  Map<String, dynamic> toJson() {
    return {
      'server_url': serverUrl,
      'username': username,
      'device_id': deviceId,
    };
  }

  /// 判断是否与另一个所有权信息匹配
  bool matches(AgentOwnershipInfo other) {
    return serverUrl == other.serverUrl &&
           username == other.username &&
           deviceId == other.deviceId;
  }

  @override
  String toString() {
    return 'AgentOwnershipInfo(serverUrl=$serverUrl, username=$username, deviceId=$deviceId)';
  }

  @override
  bool operator ==(Object other) {
    if (identical(this, other)) return true;
    return other is AgentOwnershipInfo &&
        other.serverUrl == serverUrl &&
        other.username == username &&
        other.deviceId == deviceId;
  }

  @override
  int get hashCode => Object.hash(serverUrl, username, deviceId);
}
