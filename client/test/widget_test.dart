import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rc_client/main.dart';
import 'package:rc_client/services/environment_service.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues({});
    EnvironmentService.setInstance(
      EnvironmentService(debugModeProvider: () => true),
    );
  });

  testWidgets('App starts with splash screen', (WidgetTester tester) async {
    await tester.pumpWidget(const RemoteControlApp());

    // 验证启动页显示
    expect(find.byIcon(Icons.terminal), findsOneWidget);
    expect(find.byType(CircularProgressIndicator), findsOneWidget);
    expect(find.text('正在加载...'), findsOneWidget);
  });

  testWidgets('App has correct title', (WidgetTester tester) async {
    await tester.pumpWidget(const RemoteControlApp());

    // 验证 MaterialApp 标题
    final app = tester.widget<MaterialApp>(find.byType(MaterialApp));
    expect(app.title, 'Remote Control');
  });

  testWidgets('App uses Material 3', (WidgetTester tester) async {
    await tester.pumpWidget(const RemoteControlApp());

    final app = tester.widget<MaterialApp>(find.byType(MaterialApp));
    expect(app.theme?.useMaterial3, isTrue);
    expect(app.darkTheme?.useMaterial3, isTrue);
  });
}
