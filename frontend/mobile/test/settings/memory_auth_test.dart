import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:jarvis_mobile/auth/auth_controller.dart';
import 'package:jarvis_mobile/auth/auth_user.dart';
import 'package:jarvis_mobile/net/api_client.dart';
import 'package:jarvis_mobile/net/server_config.dart';
import 'package:jarvis_mobile/settings/pages/memory_page.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

Widget buildMemoryPage({
  required ServerConfig cfg,
  required ApiClient api,
  required AuthController auth,
}) {
  return MultiProvider(
    providers: [
      ChangeNotifierProvider.value(value: cfg),
      Provider.value(value: api),
      ChangeNotifierProvider.value(value: auth),
    ],
    child: const MaterialApp(
      home: Scaffold(body: MemoryPage()),
    ),
  );
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  late ServerConfig cfg;

  setUp(() {
    SharedPreferences.setMockInitialValues({});
    cfg = ServerConfig();
  });

  testWidgets('admin sees all 8 categories including Người dùng', (t) async {
    t.view.physicalSize = const Size(1170, 2532);
    t.view.devicePixelRatio = 3;
    addTearDown(t.view.reset);

    final api = ApiClient(
      cfg,
      client: MockClient((req) async {
        if (req.url.path == '/api/memory-control/summary') {
          return http.Response(jsonEncode({'success': true, 'counts': {}}), 200);
        }
        if (req.url.path == '/api/learnings/list') {
          return http.Response(jsonEncode({'success': true, 'learnings': []}), 200);
        }
        return http.Response('{"success": true}', 200);
      }),
    );
    final auth = AuthController(api)
      ..setAuthenticatedForTesting(
        const AuthUser(id: 'admin', username: 'admin', role: 'admin'),
      );

    await t.pumpWidget(buildMemoryPage(cfg: cfg, api: api, auth: auth));
    await t.pumpAndSettle();

    expect(find.text('Người dùng'), findsOneWidget);
    expect(find.text('Learnings'), findsOneWidget);
    expect(find.text('Workflows'), findsOneWidget);
    expect(find.text('Outcomes'), findsOneWidget);
  });

  testWidgets('member only sees 4 categories (conversation, learning, evolution, gym)', (t) async {
    t.view.physicalSize = const Size(1170, 2532);
    t.view.devicePixelRatio = 3;
    addTearDown(t.view.reset);

    final api = ApiClient(
      cfg,
      client: MockClient((req) async {
        if (req.url.path == '/api/memory-control/summary') {
          return http.Response(jsonEncode({'success': true, 'counts': {}}), 200);
        }
        if (req.url.path == '/api/conversations') {
          return http.Response(jsonEncode({'success': true, 'conversations': []}), 200);
        }
        return http.Response('{"success": true}', 200);
      }),
    );
    final auth = AuthController(api)
      ..setAuthenticatedForTesting(
        const AuthUser(id: 'u1', username: 'alice', role: 'member'),
      );

    await t.pumpWidget(buildMemoryPage(cfg: cfg, api: api, auth: auth));
    await t.pumpAndSettle();

    expect(find.text('Conversations'), findsOneWidget);
    expect(find.text('Learnings'), findsOneWidget);
    expect(find.text('Evolution'), findsOneWidget);
    expect(find.text('Gym Memory'), findsOneWidget);
    expect(find.text('Người dùng'), findsNothing);
    expect(find.text('Workflows'), findsNothing);
    expect(find.text('Outcomes'), findsNothing);
    expect(find.text('Sửa công cụ'), findsNothing);
  });

  testWidgets('admin category user lists accounts and deletes regular user via /api/users/delete', (t) async {
    t.view.physicalSize = const Size(1170, 2532);
    t.view.devicePixelRatio = 3;
    addTearDown(t.view.reset);

    SharedPreferences.setMockInitialValues({
      'jarvis.settings.memory_kind': 'user',
    });

    var deletedId = '';
    final api = ApiClient(
      cfg,
      client: MockClient((req) async {
        if (req.url.path == '/api/memory-control/summary') {
          return http.Response(jsonEncode({'success': true, 'counts': {}}), 200);
        }
        if (req.method == 'DELETE' && req.url.path == '/api/users/delete') {
          deletedId = req.url.queryParameters['id'] ?? '';
          return http.Response(jsonEncode({'success': true}), 200);
        }
        if (req.url.path == '/api/users/list') {
          return http.Response(
            jsonEncode({
              'success': true,
              'items': [
                {
                  'id': 'u10',
                  'username': 'bob',
                  'display_name': 'Bob Smith',
                  'role': 'member',
                  'user_pronoun': 'anh',
                  'ai_pronoun': 'em',
                },
                {
                  'id': 'admin',
                  'username': 'admin',
                  'display_name': 'Administrator',
                  'role': 'admin',
                },
              ],
            }),
            200,
          );
        }
        return http.Response('{"success": true}', 200);
      }),
    );
    final auth = AuthController(api)
      ..setAuthenticatedForTesting(
        const AuthUser(id: 'admin', username: 'admin', role: 'admin'),
      );

    await t.pumpWidget(buildMemoryPage(cfg: cfg, api: api, auth: auth));
    await t.pumpAndSettle();

    expect(find.text('Bob Smith'), findsOneWidget);
    expect(find.text('Administrator'), findsOneWidget);

    // Open Bob Smith detail
    await t.tap(find.text('Bob Smith'));
    await t.pumpAndSettle();

    // Bob Smith is regular member -> delete button is shown
    expect(find.text('Xóa'), findsOneWidget);
    await t.tap(find.text('Xóa'));
    await t.pump();
    await t.pump(const Duration(milliseconds: 400));

    // Confirm dialog
    expect(find.text('Xóa người dùng: Bob Smith?'), findsOneWidget);
    await t.tap(find.byKey(const Key('confirm-ok')));
    await t.pumpAndSettle(const Duration(seconds: 2));

    expect(deletedId, 'u10');
  });

  testWidgets('admin record hides delete button for admin user', (t) async {
    t.view.physicalSize = const Size(1170, 2532);
    t.view.devicePixelRatio = 3;
    addTearDown(t.view.reset);

    SharedPreferences.setMockInitialValues({
      'jarvis.settings.memory_kind': 'user',
    });

    final api = ApiClient(
      cfg,
      client: MockClient((req) async {
        if (req.url.path == '/api/memory-control/summary') {
          return http.Response(jsonEncode({'success': true, 'counts': {}}), 200);
        }
        if (req.url.path == '/api/users/list') {
          return http.Response(
            jsonEncode({
              'success': true,
              'items': [
                {
                  'id': 'admin',
                  'username': 'admin',
                  'display_name': 'Administrator',
                  'role': 'admin',
                },
              ],
            }),
            200,
          );
        }
        return http.Response('{"success": true}', 200);
      }),
    );
    final auth = AuthController(api)
      ..setAuthenticatedForTesting(
        const AuthUser(id: 'admin', username: 'admin', role: 'admin'),
      );

    await t.pumpWidget(buildMemoryPage(cfg: cfg, api: api, auth: auth));
    await t.pumpAndSettle();

    // Open Administrator detail
    await t.tap(find.text('Administrator'));
    await t.pumpAndSettle();

    // Admin account -> delete button is hidden
    expect(find.text('Xóa'), findsNothing);
  });
}
