import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rc_client/screens/user_profile_screen.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues({
      'rc_username': 'tester',
      'rc_login_time': '2026-04-22T10:30:00.000Z',
    });
  });

  testWidgets('profile screen only shows read-only account info',
      (tester) async {
    await tester.pumpWidget(
      const MaterialApp(
        home: UserProfileScreen(),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('个人信息'), findsOneWidget);
    expect(find.text('用户名'), findsOneWidget);
    expect(find.text('登录时间'), findsOneWidget);
    expect(find.text('平台'), findsOneWidget);
    expect(find.text('反馈问题'), findsNothing);
    expect(find.text('问题反馈'), findsNothing);
    expect(find.text('退出登录'), findsNothing);
    expect(find.text('操作'), findsNothing);
  });
}
