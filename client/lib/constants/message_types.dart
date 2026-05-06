/// 三端共享的 WS 消息类型常量定义。
///
/// server / agent / client 三端必须保持同步。
/// 新增消息类型时，必须三端同时更新。
///
/// PLAINTEXT_MSG_TYPES: 不加密传输的消息类型集合（协议握手/心跳）。
/// 不在 PLAINTEXT_MSG_TYPES 中的消息必须加密传输。
class MessageType {
  MessageType._();

  // ---- 协议握手 / 心跳（PLAINTEXT） ----
  static const String auth = 'auth';
  static const String connected = 'connected';
  static const String ping = 'ping';
  static const String pong = 'pong';

  // ---- 终端数据 ----
  static const String data = 'data';
  static const String output = 'output';

  // ---- 终端控制 ----
  static const String resize = 'resize';
  static const String createTerminal = 'create_terminal';
  static const String closeTerminal = 'close_terminal';
  static const String terminalCreated = 'terminal_created';
  static const String terminalClosed = 'terminal_closed';
  static const String terminalsChanged = 'terminals_changed';

  // ---- 快照 ----
  static const String snapshot = 'snapshot';
  static const String snapshotStart = 'snapshot_start';
  static const String snapshotChunk = 'snapshot_chunk';
  static const String snapshotComplete = 'snapshot_complete';
  static const String snapshotRequest = 'snapshot_request';
  static const String snapshotData = 'snapshot_data';

  // ---- 执行命令 ----
  static const String executeCommand = 'execute_command';
  static const String executeCommandResult = 'execute_command_result';

  // ---- 知识库 / 工具 ----
  static const String lookupKnowledge = 'lookup_knowledge';
  static const String lookupKnowledgeResult = 'lookup_knowledge_result';
  static const String toolCall = 'tool_call';
  static const String toolResult = 'tool_result';
  static const String toolCatalogSnapshot = 'tool_catalog_snapshot';

  // ---- Agent 元数据 ----
  static const String agentMetadata = 'agent_metadata';

  // ---- 在线状态 ----
  static const String presence = 'presence';

  // ---- 连接管理 ----
  static const String deviceKicked = 'device_kicked';
  static const String error = 'error';
}

/// 不加密的控制消息类型（协议握手/心跳）
const Set<String> plaintextMsgTypes = {
  MessageType.auth,
  MessageType.connected,
  MessageType.ping,
  MessageType.pong,
};

/// 判断消息类型是否需要加密
bool shouldEncrypt(String msgType) {
  return !plaintextMsgTypes.contains(msgType);
}
