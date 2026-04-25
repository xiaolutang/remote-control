import 'package:flutter/material.dart';

enum AccountMenuAction { theme, skillConfig, profile, feedback, logout }

List<PopupMenuEntry<AccountMenuAction>> buildAccountMenuEntries({
  bool includeTheme = true,
  bool includeSkillConfig = false,
}) {
  return [
    if (includeTheme)
      const PopupMenuItem<AccountMenuAction>(
        value: AccountMenuAction.theme,
        child: Row(
          children: [
            Icon(Icons.palette_outlined, size: 20),
            SizedBox(width: 12),
            Text('主题'),
          ],
        ),
      ),
    if (includeSkillConfig)
      const PopupMenuItem<AccountMenuAction>(
        value: AccountMenuAction.skillConfig,
        child: Row(
          children: [
            Icon(Icons.build_circle_outlined, size: 20),
            SizedBox(width: 12),
            Text('技能管理'),
          ],
        ),
      ),
    if (includeTheme) const PopupMenuDivider(),
    const PopupMenuItem<AccountMenuAction>(
      value: AccountMenuAction.profile,
      child: Row(
        children: [
          Icon(Icons.person_outline, size: 20),
          SizedBox(width: 12),
          Text('个人信息'),
        ],
      ),
    ),
    const PopupMenuItem<AccountMenuAction>(
      value: AccountMenuAction.feedback,
      child: Row(
        children: [
          Icon(Icons.feedback_outlined, size: 20),
          SizedBox(width: 12),
          Text('问题反馈'),
        ],
      ),
    ),
    const PopupMenuDivider(),
    const PopupMenuItem<AccountMenuAction>(
      value: AccountMenuAction.logout,
      child: Row(
        children: [
          Icon(Icons.logout, size: 20),
          SizedBox(width: 12),
          Text('退出登录'),
        ],
      ),
    ),
  ];
}
