import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rc_client/navigation/account_menu_actions.dart';

Future<void> openAccountMenuAndExpectCommonEntries(
  WidgetTester tester,
) async {
  await tester.tap(find.byType(PopupMenuButton<AccountMenuAction>));
  await tester.pumpAndSettle();

  expect(find.text('个人信息'), findsOneWidget);
  expect(find.text('问题反馈'), findsOneWidget);
  expect(find.text('退出登录'), findsOneWidget);
}
