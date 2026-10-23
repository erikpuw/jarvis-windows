import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jarvis_mobile/auth/auth_user.dart';
import 'package:jarvis_mobile/chat/lucide_glyphs.dart';
import 'package:jarvis_mobile/chat/morph_icon.dart';
import 'package:jarvis_mobile/settings/sd_widgets.dart';
import 'package:jarvis_mobile/settings/settings_shell.dart';
import 'package:provider/provider.dart';

import 'shell_auth_test.dart' show buildShell;

import 'package:jarvis_mobile/auth/auth_controller.dart';
import 'package:jarvis_mobile/net/api_client.dart';
import 'package:jarvis_mobile/net/server_config.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  late ApiClient api;
  late AuthController auth;
  setUp(() {
    SharedPreferences.setMockInitialValues({});
    api = ApiClient(
      ServerConfig(),
      client: MockClient((_) async => http.Response('{}', 200)),
    );
    auth = AuthController(api)..setAuthenticatedForTesting();
  });
  Future<void> size(WidgetTester t) async {
    t.view.physicalSize = const Size(1170, 2532);
    t.view.devicePixelRatio = 3;
    addTearDown(t.view.reset);
  }

  MorphIcon icon(WidgetTester t) => t.widget<MorphIcon>(
    find.descendant(
      of: find.byType(RoundMenuButton),
      matching: find.byType(MorphIcon),
    ),
  );
  testWidgets(
    'the top-left button is a gear while a page is open and an X while the menu is out',
    (t) async {
      await size(t);
      await t.pumpWidget(buildShell(api: api, auth: auth));
      await t.pumpAndSettle();
      expect(icon(t).icon, settingsGlyph);
      await t.tap(find.byType(RoundMenuButton));
      await t.pumpAndSettle();
      expect(icon(t).icon, xGlyph);
      await t.tap(find.byType(RoundMenuButton));
      await t.pumpAndSettle();
      expect(icon(t).icon, settingsGlyph);
    },
  );
  testWidgets('openMenu opens the Dashboard with its menu out', (t) async {
    await size(t);
    await t.pumpWidget(
      MultiProvider(
        providers: [
          Provider.value(value: api),
          ChangeNotifierProvider.value(value: auth),
        ],
        child: const MaterialApp(home: SettingsShell(openMenu: true)),
      ),
    );
    await t.pumpAndSettle();
    expect(find.byKey(const Key('settings-nav')), findsOneWidget);
    expect(icon(t).icon, xGlyph);
  });
  for (final admin in [false, true]) {
    testWidgets(
      'a ${admin ? 'admin' : 'member'} sees the permitted menu pages',
      (t) async {
        await size(t);
        auth.setAuthenticatedForTesting(
          AuthUser(id: 'u', username: 'u', role: admin ? 'admin' : 'member'),
        );
        await t.pumpWidget(
          buildShell(api: api, auth: auth, initialPage: 'logs'),
        );
        await t.pumpAndSettle();
        await t.tap(find.byType(RoundMenuButton));
        await t.pumpAndSettle();
        expect(
          find.byKey(const Key('nav-logs')),
          admin ? findsOneWidget : findsNothing,
        );
        expect(
          find.byKey(const Key('nav-prompts')),
          admin ? findsOneWidget : findsNothing,
        );
      },
    );
  }
}
