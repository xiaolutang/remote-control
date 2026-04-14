/// 应用运行环境
enum AppEnvironment {
  /// 本地 Docker 环境：ws://{host}:{port}/rc
  local,

  /// 线上环境：wss://xiaolutang.top/rc（固定）
  production,
}
