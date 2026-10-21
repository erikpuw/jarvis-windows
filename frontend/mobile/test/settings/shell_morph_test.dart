// Settings shell icons are morphicons (settings/index.ts makeIcon + switchPage + setDrawer).
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jarvis_mobile/chat/lucide_glyphs.dart';
import 'package:jarvis_mobile/net/api_client.dart';
import 'package:jarvis_mobile/net/server_config.dart';
import 'package:jarvis_mobile/settings/settings_shell.dart';
import 'package:jarvis_mobile/theme/app_theme.dart';
import 'package:provider/provider.dart';

import '../chat/fakes.dart';

Future<void> _pump(WidgetTester t) async {
  final cfg = ServerConfig();
  await t.pumpWidget(
    MultiProvider(
      providers: [
        ChangeNotifierProvider.value(value: cfg),
        Provider<ApiClient>.value(value: ApiClient(cfg)),
      ],
      child: MaterialApp(
        theme: buildAppTheme(),
        home: const SettingsShell(initialPageId: 'overview'),
      ),
    ),
  );
  await t.pumpAndSettle();
}

void main() {
  testWidgets(
    'the menu button is a house that morphs to an x with the drawer',
    (t) async {
      await _pump(t);
      expect(byGlyph(houseGlyph), findsOneWidget);
      final house = t.state(byGlyph(houseGlyph));
      await t.tap(byGlyph(houseGlyph));
      await t.pump(const Duration(milliseconds: 50));
      expect(identical(t.state(byGlyph(xGlyph).first), house), isTrue);
      await t.pumpAndSettle();
    },
  );

  testWidgets('a nav item morphs to its active icon and back', (t) async {
    await _pump(t);
    await t.tap(byGlyph(houseGlyph));
    await t.pumpAndSettle();
    expect(byGlyph(layoutGridGlyph), findsOneWidget); // overview is the page
    expect(byGlyph(keyRoundGlyph), findsOneWidget); // connect is not
    final overview = t.state(byGlyph(layoutGridGlyph));
    final connect = t.state(byGlyph(keyRoundGlyph));
    await t.tap(find.byKey(const Key('nav-connect')));
    await t.pump(
      const Duration(milliseconds: 50),
    ); // the drawer is still sliding out
    expect(identical(t.state(byGlyph(keyGlyph)), connect), isTrue);
    expect(identical(t.state(byGlyph(layoutDashboardGlyph)), overview), isTrue);
    await t.pumpAndSettle();
  });
}
