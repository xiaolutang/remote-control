/// 应用运行环境
enum AppEnvironment {
  /// 本地网关环境：默认 wss://localhost/rc，填端口时走本地直连
  local,

  /// 线上直连：ws://{host}:{port}（绕过 TLS，应用层加密保障安全）
  direct,

  /// 线上环境：wss://rc.xiaolutang.top/rc（走 TLS）
  production,
}
