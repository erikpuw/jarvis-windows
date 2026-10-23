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
import 'package:jarvis_mobile/settings/settings_shell.dart';
import 'package:jarvis_mobile/chat/chat_controller.dart';
import 'package:jarvis_mobile/chat/sessions_controller.dart';

import '../chat/fakes.dart';

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
    child: const MaterialApp(home: Scaffold(body: LogsPage())),
  );
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  late ServerConfig cfg;

  setUp(() {
    SharedPreferences.setMockInitialValues({});
    cfg = ServerConfig();
  });

  testWidgets('member cannot enter logs even through a saved page', (t) async {
    t.view.physicalSize = const Size(1170, 2532);
    t.view.devicePixelRatio = 3;
    addTearDown(t.view.reset);
    SharedPreferences.setMockInitialValues({
      'jarvis.settings.last_page': 'logs',
    });
    final requests = <String>[];
    final api = ApiClient(
      cfg,
      client: MockClient((req) async {
        requests.add(req.url.path);
        return http.Response('{}', 200);
      }),
    );
    final auth = AuthController(api)
      ..setAuthenticatedForTesting(
        const AuthUser(id: 'u1', username: 'alice', role: 'member'),
      );
    await t.pumpWidget(
      MultiProvider(
        providers: [
          Provider.value(value: api),
          ChangeNotifierProvider.value(value: auth),
        ],
        child: const MaterialApp(home: SettingsShell(initialPageId: 'logs')),
      ),
    );
    await t.pumpAndSettle();
    expect(find.byType(LogsPage), findsNothing);
    expect(requests.any((p) => p.startsWith('/api/conversations')), isFalse);
  });

  testWidgets('deleting the session open on the main screen starts a new one', (
    t,
  ) async {
    t.view.physicalSize = const Size(1170, 2532);
    t.view.devicePixelRatio = 3;
    addTearDown(t.view.reset);

    var deleted = false;
    final api = ApiClient(
      cfg,
      client: MockClient((req) async {
        if (req.method == 'DELETE' &&
            req.url.path == '/api/conversations/session/s1') {
          deleted = true;
          return http.Response(jsonEncode({'success': true}), 200);
        }
        if (req.url.path == '/api/conversations/sessions') {
          return http.Response(
            jsonEncode({
              'success': true,
              'sessions': deleted
                  ? []
                  : [
                      {
                        'session_id': 's1',
                        'created_at': 1700000000,
                        'last_activity': 1700000000,
                        'message_count': 2,
                        'source': 'web',
                      },
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
                {'role': 'user', 'content': 'hi', 'created_at': 1700000000},
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

    final socket = FakeSocket()..confirmed = 's1';
    final chat = ChatController(socket, FakeApi());
    final sessions = SessionsController(socket, FakeApi(), chat);
    addTearDown(() {
      sessions.dispose();
      chat.dispose();
      socket.dispose();
    });
    await t.pumpWidget(
      ChangeNotifierProvider.value(
        value: sessions,
        child: buildLogsPage(cfg: cfg, api: api, auth: auth),
      ),
    );
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
    expect(socket.switched, [null]);
    expect(find.text('Chưa có phiên chat nào.'), findsOneWidget);
  });

  testWidgets('the logs tab is remembered in SharedPreferences', (t) async {
    t.view.physicalSize = const Size(1170, 2532);
    t.view.devicePixelRatio = 3;
    addTearDown(t.view.reset);

    SharedPreferences.setMockInitialValues({
      'jarvis.settings.logs_tab': 'jarvis',
    });

    final api = ApiClient(
      cfg,
      client: MockClient((req) async {
        if (req.url.path == '/api/logs') {
          return http.Response(
            '{"success": true, "logs": "jarvis log line"}',
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

    await t.pumpWidget(buildLogsPage(cfg: cfg, api: api, auth: auth));
    await t.pumpAndSettle();

    expect(find.text('jarvis log line'), findsOneWidget);
  });
}
