import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:jarvis_mobile/auth/auth_controller.dart';
import 'package:jarvis_mobile/auth/auth_user.dart';
import 'package:jarvis_mobile/auth/login_screen.dart';
import 'package:jarvis_mobile/net/api_client.dart';
import 'package:jarvis_mobile/net/server_config.dart';
import 'package:jarvis_mobile/theme/app_theme.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  group('AuthUser', () {
    test('parses from and to json', () {
      final json = {
        'id': 'usr_123',
        'username': 'erik',
        'display_name': 'Erik Puw',
        'role': 'member',
        'tts_voice_id': 'vi-VN-HoaiMyNeural',
        'user_pronoun': 'anh',
        'ai_pronoun': 'em',
      };
      final user = AuthUser.fromJson(json);
      expect(user.id, 'usr_123');
      expect(user.username, 'erik');
      expect(user.displayName, 'Erik Puw');
      expect(user.role, 'member');
      expect(user.isAdmin, isFalse);
      expect(user.ttsVoiceId, 'vi-VN-HoaiMyNeural');

      final adminJson = {'id': 'admin', 'username': 'admin', 'role': 'admin'};
      final admin = AuthUser.fromJson(adminJson);
      expect(admin.isAdmin, isTrue);

      final out = user.toJson();
      expect(out['username'], 'erik');
      expect(out['role'], 'member');
    });
  });

  group('AuthController', () {
    late ServerConfig cfg;

    setUp(() {
      SharedPreferences.setMockInitialValues({});
      cfg = ServerConfig();
    });

    test('init restores valid session from /api/auth/me', () async {
      SharedPreferences.setMockInitialValues({
        'jarvis_token': 'saved_token_123',
        'jarvis_user': jsonEncode({'id': 'u1', 'username': 'alice', 'role': 'member'}),
      });

      final mockClient = MockClient((req) async {
        if (req.url.path == '/api/auth/me') {
          expect(req.headers['X-Memory-Token'], 'saved_token_123');
          expect(req.headers['Authorization'], 'Bearer saved_token_123');
          return http.Response(
            jsonEncode({
              'success': true,
              'user': {'id': 'u1', 'username': 'alice', 'role': 'member'},
            }),
            200,
            headers: {'content-type': 'application/json'},
          );
        }
        return http.Response('Not Found', 404);
      });

      final api = ApiClient(cfg, client: mockClient);
      final auth = AuthController(api);
      await auth.init();

      expect(auth.isAuthenticated, isTrue);
      expect(auth.currentUser?.username, 'alice');
      expect(auth.currentUser?.isAdmin, isFalse);
      expect(api.memoryToken, 'saved_token_123');
    });

    test('init clears invalid session when /api/auth/me fails', () async {
      SharedPreferences.setMockInitialValues({
        'jarvis_token': 'expired_token',
      });

      final mockClient = MockClient((req) async {
        return http.Response('{"success": false, "error": "Token expired"}', 401);
      });

      final api = ApiClient(cfg, client: mockClient);
      final auth = AuthController(api);
      await auth.init();

      expect(auth.isAuthenticated, isFalse);
      expect(auth.currentUser, isNull);
      expect(api.memoryToken, isEmpty);
      final prefs = await SharedPreferences.getInstance();
      expect(prefs.getString('jarvis_token'), isNull);
    });

    test('loginMember sends username and stores session', () async {
      final mockClient = MockClient((req) async {
        if (req.url.path == '/api/auth/login') {
          final body = jsonDecode(req.body);
          expect(body['username'], 'bob');
          return http.Response(
            jsonEncode({
              'success': true,
              'token': 'tok_bob_456',
              'user': {'id': 'u2', 'username': 'bob', 'role': 'member'},
            }),
            200,
            headers: {'content-type': 'application/json'},
          );
        }
        return http.Response('Not Found', 404);
      });

      final api = ApiClient(cfg, client: mockClient);
      final auth = AuthController(api);

      await auth.loginMember('bob');

      expect(auth.isAuthenticated, isTrue);
      expect(auth.currentUser?.username, 'bob');
      expect(api.memoryToken, 'tok_bob_456');

      final prefs = await SharedPreferences.getInstance();
      expect(prefs.getString('jarvis_token'), 'tok_bob_456');
    });

    test('refreshUser syncs updated profile fields from /api/auth/me', () async {
      final mockClient = MockClient((req) async {
        if (req.url.path == '/api/auth/me') {
          return http.Response(
            jsonEncode({
              'success': true,
              'user': {
                'id': 'u1',
                'username': 'erik',
                'display_name': 'Erik Boss',
                'role': 'member',
                'user_pronoun': 'Anh',
              },
            }),
            200,
            headers: {'content-type': 'application/json'},
          );
        }
        return http.Response('Not Found', 404);
      });

      final api = ApiClient(cfg, client: mockClient);
      api.memoryToken = 'valid_tok';
      final auth = AuthController(api);
      await auth.refreshUser();

      expect(auth.currentUser?.displayName, 'Erik Boss');
      expect(auth.currentUser?.userPronoun, 'Anh');
      expect(auth.currentUser?.role, 'member');
    });

    test('loginAdmin sends admin credentials', () async {
      final mockClient = MockClient((req) async {
        if (req.url.path == '/api/auth/login') {
          final body = jsonDecode(req.body);
          expect(body['username'], 'admin');
          expect(body['password'], 'secret123');
          return http.Response(
            jsonEncode({
              'success': true,
              'token': 'tok_admin_789',
              'user': {'id': 'admin', 'username': 'admin', 'role': 'admin'},
            }),
            200,
            headers: {'content-type': 'application/json'},
          );
        }
        return http.Response('Not Found', 404);
      });

      final api = ApiClient(cfg, client: mockClient);
      final auth = AuthController(api);

      await auth.loginAdmin('secret123');

      expect(auth.isAuthenticated, isTrue);
      expect(auth.currentUser?.isAdmin, isTrue);
      expect(api.memoryToken, 'tok_admin_789');
    });

    test('logout calls server and clears storage', () async {
      SharedPreferences.setMockInitialValues({
        'jarvis_token': 'active_token',
        'jarvis_user': jsonEncode({'id': 'admin', 'username': 'admin', 'role': 'admin'}),
      });

      var logoutCalled = false;
      final mockClient = MockClient((req) async {
        if (req.url.path == '/api/auth/logout') {
          logoutCalled = true;
          return http.Response('{"success": true}', 200);
        }
        return http.Response('OK', 200);
      });

      final api = ApiClient(cfg, client: mockClient)..memoryToken = 'active_token';
      final auth = AuthController(api);
      await auth.init();

      await auth.logout();

      expect(logoutCalled, isTrue);
      expect(auth.isAuthenticated, isFalse);
      expect(auth.currentUser, isNull);
      expect(api.memoryToken, isEmpty);

      final prefs = await SharedPreferences.getInstance();
      expect(prefs.getString('jarvis_token'), isNull);
      expect(prefs.getString('jarvis_user'), isNull);
    });
  });

  group('LoginScreen UI', () {
    late ServerConfig cfg;

    setUp(() {
      SharedPreferences.setMockInitialValues({});
      cfg = ServerConfig();
    });

    testWidgets('renders tabs, switches fields and submits member login', (tester) async {
      var memberLoginCalled = false;
      final mockClient = MockClient((req) async {
        if (req.url.path == '/api/auth/login') {
          final body = jsonDecode(req.body);
          if (body['username'] == 'Erik') {
            memberLoginCalled = true;
            return http.Response(
              jsonEncode({
                'success': true,
                'token': 'tok_erik',
                'user': {'id': 'u1', 'username': 'Erik', 'role': 'member'},
              }),
              200,
              headers: {'content-type': 'application/json'},
            );
          }
        }
        return http.Response('Not Found', 404);
      });

      final api = ApiClient(cfg, client: mockClient);
      final auth = AuthController(api);

      await tester.pumpWidget(
        MaterialApp(
          theme: buildAppTheme(),
          home: MultiProvider(
            providers: [
              ChangeNotifierProvider.value(value: auth),
              Provider.value(value: api),
            ],
            child: const LoginScreen(),
          ),
        ),
      );
      await tester.pumpAndSettle();

      expect(find.text('Đăng nhập JARVIS'), findsOneWidget);
      expect(find.text('Thành viên'), findsOneWidget);
      expect(find.text('Quản trị'), findsOneWidget);
      expect(find.text('Tên hiển thị'), findsOneWidget);

      // Nhập tên thành viên và submit
      await tester.enterText(find.byType(TextField), 'Erik');
      await tester.tap(find.widgetWithText(ElevatedButton, 'Tiếp tục'));
      await tester.pumpAndSettle();

      expect(memberLoginCalled, isTrue);
      expect(auth.isAuthenticated, isTrue);
    });

    testWidgets('switching to admin tab requires password', (tester) async {
      final mockClient = MockClient((req) async {
        if (req.url.path == '/api/auth/login') {
          final body = jsonDecode(req.body);
          if (body['username'] == 'admin' && body['password'] == 'wrong') {
            return http.Response(
              '{"success": false, "error": "Sai mật khẩu"}',
              401,
              headers: {'content-type': 'application/json'},
            );
          }
        }
        return http.Response('Not Found', 404);
      });

      final api = ApiClient(cfg, client: mockClient);
      final auth = AuthController(api);

      await tester.pumpWidget(
        MaterialApp(
          theme: buildAppTheme(),
          home: MultiProvider(
            providers: [
              ChangeNotifierProvider.value(value: auth),
              Provider.value(value: api),
            ],
            child: const LoginScreen(),
          ),
        ),
      );
      await tester.pumpAndSettle();

      // Bấm tab Quản trị
      await tester.tap(find.text('Quản trị'));
      await tester.pumpAndSettle();

      expect(find.text('Mật khẩu quản trị'), findsOneWidget);

      // Nhập sai mật khẩu
      await tester.enterText(find.byType(TextField), 'wrong');
      await tester.tap(find.widgetWithText(ElevatedButton, 'Tiếp tục'));
      await tester.pumpAndSettle();

      expect(find.text('Sai mật khẩu'), findsOneWidget);
      expect(auth.isAuthenticated, isFalse);
    });
  });
}
