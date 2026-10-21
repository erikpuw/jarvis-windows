import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:jarvis_mobile/auth/auth_controller.dart';
import 'package:jarvis_mobile/auth/auth_user.dart';
import 'package:jarvis_mobile/net/api_client.dart';
import 'package:jarvis_mobile/net/server_config.dart';
import 'package:jarvis_mobile/settings/settings_shell.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

Widget buildShell({
  required ApiClient api,
  required AuthController auth,
  String initialPage = 'overview',
}) {
  return MultiProvider(
    providers: [
      Provider.value(value: api),
      ChangeNotifierProvider.value(value: auth),
    ],
    child: MaterialApp(
      home: SettingsShell(initialPageId: initialPage),
    ),
  );
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  late ServerConfig cfg;
  late ApiClient api;
  late AuthController auth;

  setUp(() {
    SharedPreferences.setMockInitialValues({});
    cfg = ServerConfig();
    api = ApiClient(cfg, client: MockClient((req) async => http.Response('{}', 200)));
    auth = AuthController(api);
  });

  testWidgets('admin sees prompts in nav', (t) async {
    t.view.physicalSize = const Size(1170, 2532);
    t.view.devicePixelRatio = 3;
    addTearDown(t.view.reset);

    auth.setAuthenticatedForTesting(
      const AuthUser(id: 'admin', username: 'admin', role: 'admin'),
    );

    await t.pumpWidget(buildShell(api: api, auth: auth));
    await t.pumpAndSettle();

    // Open nav
    await t.tap(find.byType(GestureDetector).first);
    await t.pumpAndSettle();

    expect(find.byKey(const Key('nav-prompts')), findsOneWidget);
  });

  testWidgets('member does NOT see prompts in nav and redirects if on prompts', (t) async {
    t.view.physicalSize = const Size(1170, 2532);
    t.view.devicePixelRatio = 3;
    addTearDown(t.view.reset);

    auth.setAuthenticatedForTesting(
      const AuthUser(id: 'u1', username: 'alice', role: 'member'),
    );

    await t.pumpWidget(buildShell(api: api, auth: auth, initialPage: 'prompts'));
    await t.pumpAndSettle();

    // Open nav
    await t.tap(find.byType(GestureDetector).first);
    await t.pumpAndSettle();

    expect(find.byKey(const Key('nav-prompts')), findsNothing);
  });

  testWidgets('logout button opens confirm dialog and calls logout', (t) async {
    t.view.physicalSize = const Size(1170, 2532);
    t.view.devicePixelRatio = 3;
    addTearDown(t.view.reset);

    auth.setAuthenticatedForTesting(
      const AuthUser(id: 'admin', username: 'admin', role: 'admin'),
    );

    await t.pumpWidget(buildShell(api: api, auth: auth));
    await t.pumpAndSettle();

    // Open nav
    await t.tap(find.byType(GestureDetector).first);
    await t.pumpAndSettle();

    expect(find.byKey(const Key('btn-user-logout')), findsOneWidget);
    await t.tap(find.byKey(const Key('btn-user-logout')));
    await t.pumpAndSettle();

    // Dialog appears
    expect(find.text('Đăng xuất'), findsWidgets);
    expect(find.text('Bạn có chắc chắn muốn đăng xuất khỏi hệ thống không?'), findsOneWidget);

    // Confirm logout
    await t.tap(find.byKey(const Key('logout-confirm-btn')));
    await t.pumpAndSettle();

    expect(auth.isAuthenticated, isFalse);
  });

  testWidgets('last page is remembered in SharedPreferences', (t) async {
    t.view.physicalSize = const Size(1170, 2532);
    t.view.devicePixelRatio = 3;
    addTearDown(t.view.reset);

    SharedPreferences.setMockInitialValues({
      'jarvis.settings.last_page': 'voice',
    });

    auth.setAuthenticatedForTesting(
      const AuthUser(id: 'admin', username: 'admin', role: 'admin'),
    );

    await t.pumpWidget(buildShell(api: api, auth: auth));
    await t.pumpAndSettle();

    // The shell restored 'voice' page
    expect(find.text('Chọn giọng đọc và tạo giọng clone.'), findsOneWidget);

    // Switch to another tab, e.g. user
    await t.tap(find.byType(GestureDetector).first);
    await t.pumpAndSettle();

    await t.tap(find.byKey(const Key('nav-user')));
    await t.pumpAndSettle();

    final prefs = await SharedPreferences.getInstance();
    expect(prefs.getString('jarvis.settings.last_page'), 'user');
  });
}
