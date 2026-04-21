import 'package:flutter/material.dart';
import '../services/user_info_service.dart';

/// 用户信息页面
///
/// 显示用户名、登录时间、平台信息。
class UserProfileScreen extends StatefulWidget {
  const UserProfileScreen({super.key});

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
      title: Text(title,
          style: theme.textTheme.bodySmall?.copyWith(
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
}
