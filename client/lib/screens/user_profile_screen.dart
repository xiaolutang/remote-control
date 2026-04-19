import 'package:flutter/material.dart';
import 'feedback_screen.dart';
import '../services/user_info_service.dart';
import '../services/logout_helper.dart';
import 'login_screen.dart';

/// 用户信息页面
///
/// 显示用户名、登录时间、平台信息。
/// 提供反馈问题入口和退出登录入口。
class UserProfileScreen extends StatefulWidget {
  final String serverUrl;
  final String token;
  final String sessionId;

  const UserProfileScreen({
    super.key,
    required this.serverUrl,
    required this.token,
    required this.sessionId,
  });

  @override
  State<UserProfileScreen> createState() => _UserProfileScreenState();
}

class _UserProfileScreenState extends State<UserProfileScreen> {
  UserInfo? _userInfo;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _loadUserInfo();
  }

  Future<void> _loadUserInfo() async {
    final info = await UserInfoService().getUserInfo();
    if (!mounted) return;
    setState(() {
      _userInfo = info;
      _loading = false;
    });
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colorScheme = theme.colorScheme;

    return Scaffold(
      appBar: AppBar(
        title: const Text('个人信息'),
      ),
      body: SafeArea(
        child: _loading
            ? const Center(child: CircularProgressIndicator())
            : SingleChildScrollView(
                padding: const EdgeInsets.all(24),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    // 用户信息区
                    _buildInfoTile(
                      icon: Icons.person_outline,
                      title: '用户名',
                      value: _userInfo?.username ?? '-',
                    ),
                    const SizedBox(height: 8),
                    _buildInfoTile(
                      icon: Icons.access_time_outlined,
                      title: '登录时间',
                      value: _formatLoginTime(_userInfo?.loginTime),
                    ),
                    const SizedBox(height: 8),
                    _buildInfoTile(
                      icon: Icons.devices_outlined,
                      title: '平台',
                      value: _userInfo?.platform ?? '-',
                    ),

                    const SizedBox(height: 32),
                    Divider(color: colorScheme.outlineVariant),
                    const SizedBox(height: 16),

                    // 操作区
                    Text(
                      '操作',
                      style: theme.textTheme.titleSmall?.copyWith(
                        color: colorScheme.onSurfaceVariant,
                      ),
                    ),
                    const SizedBox(height: 8),

                    // 反馈问题入口
                    ListTile(
                      leading: const Icon(Icons.feedback_outlined),
                      title: const Text('反馈问题'),
                      trailing: const Icon(Icons.chevron_right),
                      onTap: () => _navigateToFeedback(context),
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(12),
                      ),
                    ),

                    const SizedBox(height: 4),

                    // 退出登录入口
                    ListTile(
                      leading: Icon(Icons.logout, color: colorScheme.error),
                      title: Text('退出登录', style: TextStyle(color: colorScheme.error)),
                      trailing: Icon(Icons.chevron_right, color: colorScheme.error),
                      onTap: () => _handleLogout(context),
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(12),
                      ),
                    ),
                  ],
                ),
              ),
      ),
    );
  }

  Widget _buildInfoTile({
    required IconData icon,
    required String title,
    required String value,
  }) {
    final theme = Theme.of(context);
    return ListTile(
      leading: Icon(icon),
      title: Text(title, style: theme.textTheme.bodySmall?.copyWith(
        color: theme.colorScheme.onSurfaceVariant,
      )),
      subtitle: Text(value, style: theme.textTheme.bodyLarge),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(12),
      ),
    );
  }

  String _formatLoginTime(String? isoTime) {
    if (isoTime == null) return '-';
    try {
      final dt = DateTime.parse(isoTime);
      return '${dt.year}-${_pad(dt.month)}-${_pad(dt.day)} '
          '${_pad(dt.hour)}:${_pad(dt.minute)}';
    } catch (_) {
      return '-';
    }
  }

  String _pad(int n) => n.toString().padLeft(2, '0');

  void _navigateToFeedback(BuildContext context) {
    Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => FeedbackScreen(
          serverUrl: widget.serverUrl,
          token: widget.token,
          sessionId: widget.sessionId,
        ),
      ),
    );
  }

  Future<void> _handleLogout(BuildContext context) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('退出登录'),
        content: const Text('确定要退出登录吗？'),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(false),
            child: const Text('取消'),
          ),
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(true),
            child: Text(
              '退出',
              style: TextStyle(color: Theme.of(ctx).colorScheme.error),
            ),
          ),
        ],
      ),
    );

    if (confirmed != true || !context.mounted) return;

    await logoutAndNavigate(
      context: context,
      destinationBuilder: (_) => const LoginScreen(),
    );
  }
}
