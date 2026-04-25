import 'package:flutter/material.dart';

import '../navigation/account_menu_actions.dart';
import '../screens/feedback_screen.dart';
import '../screens/skill_config_screen.dart';
import '../screens/user_profile_screen.dart';
import 'auth_service.dart';
import 'logout_helper.dart';

Future<void> handleAccountMenuAction(
  BuildContext context, {
  required AccountMenuAction action,
  required String serverUrl,
  required String token,
  required WidgetBuilder logoutDestinationBuilder,
  Future<void> Function()? onTheme,
}) async {
  switch (action) {
    case AccountMenuAction.knowledgeConfig:
      await _openKnowledgeConfig(context);
      return;
    case AccountMenuAction.theme:
      if (onTheme != null) {
        await onTheme();
      }
      return;
    case AccountMenuAction.profile:
      await _openUserProfile(context);
      return;
    case AccountMenuAction.feedback:
      await _openFeedback(
        context,
        serverUrl: serverUrl,
        token: token,
      );
      return;
    case AccountMenuAction.logout:
      await _confirmAndLogout(
        context,
        destinationBuilder: logoutDestinationBuilder,
      );
      return;
  }
}

Future<String> _loadSessionId(String serverUrl) async {
  final session = await AuthService(serverUrl: serverUrl).getSavedSession();
  return session?['session_id'] ?? '';
}

Future<void> _openUserProfile(BuildContext context) async {
  if (!context.mounted) {
    return;
  }
  await Navigator.of(context).push(
    MaterialPageRoute(
      builder: (_) => const UserProfileScreen(),
    ),
  );
}

Future<void> _openFeedback(
  BuildContext context, {
  required String serverUrl,
  required String token,
}) async {
  final sessionId = await _loadSessionId(serverUrl);
  if (!context.mounted) {
    return;
  }
  await Navigator.of(context).push(
    MaterialPageRoute(
      builder: (_) => FeedbackScreen(
        serverUrl: serverUrl,
        token: token,
        sessionId: sessionId,
      ),
    ),
  );
}

Future<void> _confirmAndLogout(
  BuildContext context, {
  required WidgetBuilder destinationBuilder,
}) async {
  final confirmed = await showDialog<bool>(
    context: context,
    builder: (dialogContext) => AlertDialog(
      title: const Text('退出登录'),
      content: const Text('确定要退出登录吗？'),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(dialogContext).pop(false),
          child: const Text('取消'),
        ),
        TextButton(
          onPressed: () => Navigator.of(dialogContext).pop(true),
          child: Text(
            '退出',
            style: TextStyle(color: Theme.of(dialogContext).colorScheme.error),
          ),
        ),
      ],
    ),
  );

  if (confirmed != true || !context.mounted) {
    return;
  }

  await logoutAndNavigate(
    context: context,
    destinationBuilder: destinationBuilder,
  );
}

Future<void> _openKnowledgeConfig(BuildContext context) async {
  if (!context.mounted) return;
  await Navigator.of(context).push(
    MaterialPageRoute(
      builder: (_) => const SkillConfigScreen(),
    ),
  );
}
