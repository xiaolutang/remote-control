import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rc_client/navigation/account_menu_actions.dart';

Future<void> openAccountMenuAndExpectCommonEntries(
  WidgetTester tester,
) async {
  // Desktop header bar uses settings_outlined; mobile PopupMenuButton
  // defaults to more_vert. Try settings_outlined first (covers desktop
  // workspace with both AccountMenuAction and _DesktopSettingsAction),
  // then fallback to more_vert (mobile screens without explicit icon).
  final settingsIcon = find.byIcon(Icons.settings_outlined);
  if (settingsIcon.evaluate().isNotEmpty) {
    await tester.tap(settingsIcon.first);
  } else {
    await tester.tap(find.byIcon(Icons.more_vert).first);
  }
  await tester.pumpAndSettle();

  expect(find.text('个人信息'), findsOneWidget);
  expect(find.text('问题反馈'), findsOneWidget);
  expect(find.text('退出登录'), findsOneWidget);
}
