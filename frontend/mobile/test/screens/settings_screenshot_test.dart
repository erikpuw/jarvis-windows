@Tags(['screens'])
library;

// Review artifacts, not goldens (skipped by default, see dart_test.yaml; run: flutter test test/screens --run-skipped): every Settings
// page inside the shell on a 390x844 phone @3x with fake data shaped like the backend's answers -> mobile/build/screens/settings_<id>.png.
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:jarvis_mobile/chat/lucide_glyphs.dart';
import 'package:jarvis_mobile/net/api_client.dart';
import 'package:jarvis_mobile/net/server_config.dart';
import 'package:jarvis_mobile/settings/settings_shell.dart';
import 'package:jarvis_mobile/theme/app_theme.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../chat/fakes.dart';
import '../settings/catalog_fixtures.dart';
import '../settings/fixtures.dart';
import 'screen_support.dart';

Future<GlobalKey> _open(
  WidgetTester t,
  String id,
  Map<String, http.Response Function(http.Request)> routes, {
  bool unlocked = false,
}) async {
  t.view
    ..physicalSize = const Size(1170, 2532)
    ..devicePixelRatio = 3;
  addTearDown(t.view.reset);
  final cfg = ServerConfig();
  final key = GlobalKey();
  await t.pumpWidget(
    RepaintBoundary(
      key: key,
      child: MultiProvider(
        providers: [
          ChangeNotifierProvider.value(value: cfg),
          Provider<ApiClient>.value(
            value: ApiClient(cfg, client: routed(routes))
              ..memoryToken = unlocked ? 'tok' : '',
          ),
        ],
        child: MaterialApp(
          debugShowCheckedModeBanner: false,
          theme: buildAppTheme(),
          home: SettingsShell(initialPageId: id),
        ),
      ),
    ),
  );
  await advance(t, 600);
  return key;
}

Map<String, http.Response Function(http.Request)> _routes() => {
  'GET /api/settings/status': (_) => jsonOk(statusJson()),
  'GET /api/health/detailed': (_) => jsonOk(healthJson()),
  'GET /api/tts/voices': (_) => jsonOk(voicesJson()),
  'GET /api/settings/preferences': (_) => jsonOk({
    'user_name': 'Erik',
    'honorific': 'Anh',
    'calendar_accounts': 'erik@gmail.com',
  }),
  'GET /api/memory-lock/status': (_) => jsonOk({'configured': true}),
  'GET /api/memory-control/summary': (_) => jsonOk(memorySummaryJson()),
  'GET /api/learnings/list': (_) => jsonOk(learningsJson()),
  'GET /api/history': (_) => jsonOk(historyJson()),
  'GET /api/logs': (_) => jsonOk(logsJson()),
  'GET /api/conversations/sessions': (_) => jsonOk(sessionsJson()),
  'GET /api/settings/catalog': (_) => jsonOk(catalogJson()),
  'GET /api/mcp/servers': (_) => jsonOk(mcpServersJson()),
  'GET /api/system/readme': (_) => jsonOk(readmeJson()),
  'GET /api/graphfy': (_) => jsonOk(graphfyJson()),
};

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  testWidgets('settings screenshots', (t) async {
    await t.runAsync(loadScreenFonts);

    var key = await _open(t, 'overview', _routes());
    await shot(t, key, 'settings_overview');
    await t.tap(byGlyph(houseGlyph));
    await advance(t, 400);
    await shot(t, key, 'settings_nav_rail');
    await t.tap(find.byKey(const Key('settings-sidebar-toggle')));
    await advance(t, 400);
    await shot(t, key, 'settings_nav_open');

    key = await _open(t, 'connect', _routes());
    await shot(t, key, 'settings_connect');

    key = await _open(t, 'voice', _routes());
    await shot(t, key, 'settings_voice');

    key = await _open(t, 'user', _routes());
    await shot(t, key, 'settings_user');

    key = await _open(t, 'system', _routes());
    await shot(t, key, 'settings_system');

    key = await _open(t, 'memory', _routes());
    await shot(t, key, 'settings_lock');

    key = await _open(t, 'memory', _routes(), unlocked: true);
    await shot(t, key, 'settings_memory');
    await t.tap(find.byKey(const Key('rec:42')));
    await advance(t, 400);
    await shot(t, key, 'settings_memory_detail');

    key = await _open(t, 'logs', _routes(), unlocked: true);
    await shot(t, key, 'settings_logs');

    for (final id in ['agents', 'hooks', 'skills', 'commands', 'plugins']) {
      key = await _open(t, id, _routes());
      await shot(t, key, 'settings_$id');
    }

    key = await _open(t, 'prompts', _routes());
    await shot(t, key, 'settings_prompts');
    await t.tap(find.text('Xem nội dung prompt'));
    await advance(t, 400);
    await shot(t, key, 'settings_prompts_editor');

    key = await _open(t, 'mcp', _routes());
    await shot(t, key, 'settings_mcp');

    key = await _open(t, 'graphfy', _routes());
    await shot(t, key, 'settings_graphfy');

    key = await _open(t, 'info', _routes());
    await shot(t, key, 'settings_info');
  });
}
