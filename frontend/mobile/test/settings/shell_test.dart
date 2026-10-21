
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:jarvis_mobile/chat/lucide_glyphs.dart';
import 'package:jarvis_mobile/net/api_client.dart';
import 'package:jarvis_mobile/net/server_config.dart';
import 'package:jarvis_mobile/settings/pages.dart';
import 'package:jarvis_mobile/settings/settings_shell.dart';
import 'package:jarvis_mobile/theme/app_theme.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../chat/fakes.dart';
import 'catalog_fixtures.dart';
import 'fixtures.dart';

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  test('16 pages in web order', () {
    expect(settingsPages.map((p) => p.id).toList(), [
      'overview',
      'connect',
      'voice',
      'user',
      'system',
      'memory',
      'logs',
      'agents',
      'hooks',
      'skills',
      'prompts',
      'commands',
      'plugins',
      'mcp',
      'graphfy',
      'info',
    ]);
  });

  test(
    'no pages require password in settings (auth gate handles session)',
    () {
      expect(settingsPages.where((p) => p.needsKey), isEmpty);
    },
  );

  testWidgets('leaving a page preserves memoryToken and does not lock', (t) async {
    final cfg = ServerConfig();
    final locks = <String>[];
    final api = ApiClient(
      cfg,
      client: MockClient((req) async {
        if (req.url.path == '/api/memory-lock/lock') {
          locks.add(req.headers['X-Memory-Token'] ?? '');
        }
        return http.Response('{}', 200);
      }),
    )..memoryToken = 'tok';
    await t.pumpWidget(
      MultiProvider(
        providers: [
          ChangeNotifierProvider.value(value: cfg),
          Provider<ApiClient>.value(value: api),
        ],
        child: MaterialApp(
          theme: buildAppTheme(),
          home: const SettingsShell(initialPageId: 'memory'),
        ),
      ),
    );
    await t.pumpAndSettle();
    expect(find.text('Nhập mật khẩu để mở.'), findsNothing);
    Future<void> goTo(String id) async {
      await t.tap(byGlyph(houseGlyph));
      await t.pumpAndSettle();
      await t.tap(find.byKey(Key('nav-$id')));
      await t.pumpAndSettle();
    }

    await goTo('overview');
    expect(api.memoryToken, 'tok');
    expect(locks, isEmpty);
  });

  testWidgets('switching between catalog pages shows the own list of each', (
    t,
  ) async {
    t.view
      ..physicalSize = const Size(1170, 2532)
      ..devicePixelRatio = 3;
    addTearDown(t.view.reset);
    final cfg = ServerConfig();
    final api = ApiClient(
      cfg,
      client: MockClient(
        (req) async => req.url.path == '/api/settings/catalog'
            ? jsonOk(catalogJson())
            : http.Response('{}', 200),
      ),
    );
    await t.pumpWidget(
      MultiProvider(
        providers: [
          ChangeNotifierProvider.value(value: cfg),
          Provider<ApiClient>.value(value: api),
        ],
        child: MaterialApp(
          theme: buildAppTheme(),
          home: const SettingsShell(initialPageId: 'skills'),
        ),
      ),
    );
    await t.pumpAndSettle();
    Future<void> goTo(String id) async {
      await t.tap(byGlyph(houseGlyph));
      await t.pumpAndSettle();
      await t.tap(find.byKey(Key('nav-$id')));
      await t.pumpAndSettle();
    }

    expect(find.text('git-helper'), findsOneWidget);
    await goTo('plugins');
    expect(find.text('spotify'), findsOneWidget);
    expect(find.text('git-helper'), findsNothing);
    await goTo('skills');
    expect(find.text('git-helper'), findsOneWidget);
    expect(find.text('spotify'), findsNothing);
  });

  testWidgets('memory opens directly without asking for password', (t) async {
    final cfg = ServerConfig();
    final mockClient = MockClient((req) async {
      return http.Response('{}', 200);
    });

    final api = ApiClient(cfg, client: mockClient)..memoryToken = 'tok_valid';

    await t.pumpWidget(
      MultiProvider(
        providers: [
          ChangeNotifierProvider.value(value: cfg),
          Provider<ApiClient>.value(value: api),
        ],
        child: MaterialApp(
          theme: buildAppTheme(),
          home: const SettingsShell(initialPageId: 'memory'),
        ),
      ),
    );
    await t.pumpAndSettle();

    expect(find.text('Nhập mật khẩu để mở.'), findsNothing);
    expect(find.text('Mở khóa'), findsNothing);
    expect(find.text('Bộ nhớ'), findsOneWidget);
  });

  testWidgets('server url field rejects bad url and saves valid url', (
    t,
  ) async {
    final cfg = ServerConfig();
    final mockClient = MockClient((_) async => http.Response('{}', 200));
    final api = ApiClient(cfg, client: mockClient);

    await t.pumpWidget(
      MultiProvider(
        providers: [
          ChangeNotifierProvider.value(value: cfg),
          Provider<ApiClient>.value(value: api),
        ],
        child: MaterialApp(
          theme: buildAppTheme(),
          home: const SettingsShell(initialPageId: 'connect'),
        ),
      ),
    );
    await t.pumpAndSettle();

    final input = find.byKey(const Key('server_url_input'));
    expect(input, findsOneWidget);

    // Enter bad url
    await t.enterText(input, 'not-a-valid-url');
    await t.testTextInput.receiveAction(TextInputAction.done);
    await t.pumpAndSettle();

    expect(find.text('Địa chỉ URL không hợp lệ'), findsOneWidget);

    // Enter good url
    await t.enterText(input, 'https://jarvis.tail8b8885.ts.net:8340');
    await t.testTextInput.receiveAction(TextInputAction.done);
    await t.pumpAndSettle();

    expect(find.text('Địa chỉ URL không hợp lệ'), findsNothing);
    expect(cfg.baseUrl, 'https://jarvis.tail8b8885.ts.net:8340');
  });
}
