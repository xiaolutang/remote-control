/// 应用运行环境
enum AppEnvironment {
  /// 本地开发环境：ws://{host}:{port}
  local,

  /// 线上直连：ws://{host}:{port}（绕过 TLS，应用层加密保障安全）
  direct,

  /// 线上环境：wss://rc.xiaolutang.top/rc（走 TLS）
  production,
}
