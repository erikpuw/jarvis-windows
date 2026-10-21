import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:jarvis_mobile/auth/auth_controller.dart';
import 'package:jarvis_mobile/auth/auth_user.dart';
import 'package:jarvis_mobile/net/api_client.dart';
import 'package:jarvis_mobile/net/server_config.dart';
import 'package:jarvis_mobile/settings/pages/logs_page.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

Widget buildLogsPage({
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
      home: Scaffold(body: LogsPage()),
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

  testWidgets('member only sees history tab and sessions sub-view', (t) async {
    t.view.physicalSize = const Size(1170, 2532);
    t.view.devicePixelRatio = 3;
    addTearDown(t.view.reset);

    final api = ApiClient(
      cfg,
      client: MockClient((req) async {
        if (req.url.path == '/api/conversations/sessions') {
          return http.Response(
            jsonEncode({
              'success': true,
              'sessions': [
                {
                  'session_id': 's1',
                  'created_at': 1700000000,
                  'last_activity': 1700000000,
                  'message_count': 2,
                  'source': 'web',
                }
              ],
            }),
            200,
          );
        }
        return http.Response('{"success": true, "history": []}', 200);
      }),
    );
    final auth = AuthController(api)
      ..setAuthenticatedForTesting(
        const AuthUser(id: 'u1', username: 'alice', role: 'member'),
      );

    await t.pumpWidget(buildLogsPage(cfg: cfg, api: api, auth: auth));
    await t.pumpAndSettle();

    expect(find.text('Lịch sử chat'), findsWidgets);
    expect(find.text('Jarvis log'), findsNothing);
    expect(find.text('Log bảo mật'), findsNothing);
    expect(find.text('Log TTS'), findsNothing);
    expect(find.text('Toàn bộ'), findsNothing);
  });

  testWidgets('delete session confirms and calls DELETE API', (t) async {
    t.view.physicalSize = const Size(1170, 2532);
    t.view.devicePixelRatio = 3;
    addTearDown(t.view.reset);

    var deleted = false;
    final api = ApiClient(
      cfg,
      client: MockClient((req) async {
        if (req.method == 'DELETE' && req.url.path == '/api/conversations/session/s1') {
          deleted = true;
          return http.Response(jsonEncode({'success': true}), 200);
        }
        if (req.url.path == '/api/conversations/sessions') {
          return http.Response(
            jsonEncode({
              'success': true,
              'sessions': deleted ? [] : [
                {
                  'session_id': 's1',
                  'created_at': 1700000000,
                  'last_activity': 1700000000,
                  'message_count': 2,
                  'source': 'web',
                }
              ],
            }),
            200,
          );
        }
        if (req.url.path == '/api/conversations/session/s1') {
          return http.Response(
            jsonEncode({
              'success': true,
              'messages': [
                {'role': 'user', 'content': 'hi', 'created_at': 1700000000}
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
        const AuthUser(id: 'u1', username: 'alice', role: 'member'),
      );

    await t.pumpWidget(buildLogsPage(cfg: cfg, api: api, auth: auth));
    await t.pumpAndSettle();

    // Tap session s1
    expect(find.text('s1'), findsOneWidget);
    await t.tap(find.text('s1'));
    await t.pumpAndSettle();

    // Delete button appears
    expect(find.byKey(const Key('history-delete-session-btn')), findsOneWidget);
    await t.tap(find.byKey(const Key('history-delete-session-btn')));
    await t.pumpAndSettle();

    // Dialog appears
    expect(find.text('Xóa phiên chat'), findsOneWidget);
    await t.tap(find.byKey(const Key('delete-session-confirm-btn')));
    await t.pumpAndSettle();

    expect(deleted, isTrue);
    expect(find.text('Chưa có phiên chat nào.'), findsOneWidget);
  });

  testWidgets('logs tab and view mode are remembered in SharedPreferences', (t) async {
    t.view.physicalSize = const Size(1170, 2532);
    t.view.devicePixelRatio = 3;
    addTearDown(t.view.reset);

    SharedPreferences.setMockInitialValues({
      'jarvis.settings.logs_tab': 'jarvis',
      'jarvis.settings.logs_view': 'all',
    });

    final api = ApiClient(
      cfg,
      client: MockClient((req) async {
        if (req.url.path == '/api/logs') {
          return http.Response('{"success": true, "logs": "jarvis log line"}', 200);
        }
        return http.Response('{"success": true}', 200);
      }),
    );
    final auth = AuthController(api)
      ..setAuthenticatedForTesting(
        const AuthUser(id: 'admin', username: 'admin', role: 'admin'),
      );

    await t.pumpWidget(buildLogsPage(cfg: cfg, api: api, auth: auth));
    await t.pumpAndSettle();

    expect(find.text('jarvis log line'), findsOneWidget);
  });
}
