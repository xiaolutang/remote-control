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
