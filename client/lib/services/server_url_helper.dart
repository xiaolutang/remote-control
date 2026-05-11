// 兼容旧 import：JSON 工具函数已迁移到 utils/json_helpers.dart
export '../utils/json_helpers.dart' show readIntFromJson, readStringFromJson;

String serverUrlToHttpBase(String serverUrl) {
  if (serverUrl.startsWith('ws://')) {
    return serverUrl.replaceFirst('ws://', 'http://');
  }
  if (serverUrl.startsWith('wss://')) {
    return serverUrl.replaceFirst('wss://', 'https://');
  }
  return serverUrl;
}

bool requiresApplicationLayerEncryption(String serverUrl) {
  return serverUrl.startsWith('ws://');
}
