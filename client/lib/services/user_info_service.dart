import 'dart:io' show Platform;
import 'package:shared_preferences/shared_preferences.dart';

/// 用户信息
class UserInfo {
  final String username;
  final String? loginTime; // ISO 8601
  final String platform;

  UserInfo({required this.username, this.loginTime, required this.platform});
}

/// 用户信息本地存储服务
///
/// username 从 SharedPreferences 的 rc_username 读取（登录请求参数持久化值）。
/// loginTime 仅在显式登录/注册时记录，自动登录不覆写。
/// platform 从 Platform API 自动采集。
class UserInfoService {
  static const _loginTimeKey = 'rc_login_time';

  /// 获取用户信息
  Future<UserInfo?> getUserInfo() async {
    final prefs = await SharedPreferences.getInstance();
    final username = prefs.getString('rc_username');
    if (username == null) return null;

    final loginTime = prefs.getString(_loginTimeKey);
    final platform = _getPlatform();

    return UserInfo(
      username: username,
      loginTime: loginTime,
      platform: platform,
    );
  }

  /// 保存登录时间（仅在 rc_login_time 不存在时写入，保留首次显式登录时间）
  Future<void> saveLoginTime() async {
    final prefs = await SharedPreferences.getInstance();
    final existing = prefs.getString(_loginTimeKey);
    if (existing == null) {
      await prefs.setString(
        _loginTimeKey,
        DateTime.now().toUtc().toIso8601String(),
      );
    }
  }

  /// 清除登录时间（logout 时调用）
  Future<void> clearLoginTime() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_loginTimeKey);
  }

  String _getPlatform() {
    if (Platform.isAndroid) return 'android';
    if (Platform.isIOS) return 'ios';
    if (Platform.isMacOS) return 'macos';
    if (Platform.isWindows) return 'windows';
    if (Platform.isLinux) return 'linux';
    return 'unknown';
  }
}
