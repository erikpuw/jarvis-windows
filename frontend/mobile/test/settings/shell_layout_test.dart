// The Settings shell on a phone (settings/styles.css <=768px + pages.ts buildSettingsHTML): the 60px icon rail with groups,
// its collapse button, the footer, the fixed page head with the close button, the lock card under the head.

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

class _Harness {
  _Harness(this.paths);
  final List<String> paths;

  http.Response handle(http.Request req) {
    paths.add('${req.method} ${req.url.path}');
    return http.Response('{}', 200);
  }
}

Future<void> _pump(
  WidgetTester t,
  _Harness h, {
  String page = 'overview',
}) async {
  final cfg = ServerConfig();
  await t.pumpWidget(
    MultiProvider(
      providers: [
        ChangeNotifierProvider.value(value: cfg),
        Provider<ApiClient>.value(
          value: ApiClient(cfg, client: MockClient((r) async => h.handle(r))),
        ),
      ],
      child: MaterialApp(
        theme: buildAppTheme(),
        home: Builder(
          builder: (ctx) => Scaffold(
            body: Center(
              child: TextButton(
                onPressed: () => Navigator.push(
                  ctx,
                  MaterialPageRoute<void>(
                    builder: (_) => SettingsShell(initialPageId: page),
                  ),
                ),
                child: const Text('open'),
              ),
            ),
          ),
        ),
      ),
    ),
  );
  await t.tap(find.text('open'));
  await t.pumpAndSettle();
}

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  testWidgets(
    'the drawer is the 60px icon rail; its collapse button opens the names',
    (t) async {
      await _pump(t, _Harness([]));
      await t.tap(byGlyph(houseGlyph));
      await t.pumpAndSettle();
      expect(t.getSize(find.byKey(const Key('settings-nav'))).width, 60);
      expect(byGlyph(panelLeftGlyph), findsOneWidget);
      await t.tap(find.byKey(const Key('settings-sidebar-toggle')));
      await t.pumpAndSettle();
      expect(t.getSize(find.byKey(const Key('settings-nav'))).width, 200);
      expect(byGlyph(panelLeftCloseGlyph), findsOneWidget);
      for (final g in ['Chung', 'Dữ liệu', 'Công cụ']) {
        expect(find.text(g), findsOneWidget);
      }
      expect(find.text('Hệ thống'), findsNWidgets(2)); // the group and the page
      expect(find.text('Bảng điều khiển'), findsOneWidget);
      // web order inside the groups (pages.ts NAV_GROUPS)
      final ys = [
        for (final l in [
          'Tổng quan',
          'Người dùng',
          'Giọng đọc',
          'Kết nối & API',
          'Bộ nhớ',
          'Nhật ký',
        ])
          t
              .getTopLeft(
                find.descendant(
                  of: find.byKey(const Key('settings-nav')),
                  matching: find.text(l),
                ),
              )
              .dy,
      ];
      expect(ys, [...ys]..sort());
      // the choice is kept on the phone's own key
      final prefs = await SharedPreferences.getInstance();
      expect(prefs.getBool('jarvis.settings.sidebar_collapsed_phone'), isFalse);
    },
  );

  testWidgets(
    'the footer: green dot, JARVIS only when the names are shown, version',
    (t) async {
      await _pump(t, _Harness([]));
      await t.tap(byGlyph(houseGlyph));
      await t.pumpAndSettle();
      expect(find.text('JARVIS'), findsNothing); // the rail hides the name
      expect(find.text('v$appVersion'), findsOneWidget);
      await t.tap(find.byKey(const Key('settings-sidebar-toggle')));
      await t.pumpAndSettle();
      expect(find.text('JARVIS'), findsOneWidget);
      expect(find.byKey(const Key('version-dot')), findsOneWidget);
    },
  );

  testWidgets('a saved expanded choice is restored', (t) async {
    SharedPreferences.setMockInitialValues({
      'jarvis.settings.sidebar_collapsed_phone': false,
    });
    await _pump(t, _Harness([]));
    await t.tap(byGlyph(houseGlyph));
    await t.pumpAndSettle();
    expect(t.getSize(find.byKey(const Key('settings-nav'))).width, 200);
  });

  testWidgets(
    'the page head shows title and description; the close button leaves',
    (t) async {
      await _pump(t, _Harness([]));
      expect(find.text('Tổng quan'), findsOneWidget);
      expect(
        find.text('Tình trạng phần cứng, dịch vụ và dữ liệu của JARVIS.'),
        findsOneWidget,
      );
      await t.tap(find.byKey(const Key('settings-close')));
      await t.pumpAndSettle();
      expect(find.text('open'), findsOneWidget);
    },
  );

  testWidgets(
    'tapping the current page in the menu closes Settings (index.ts:1239)',
    (t) async {
      await _pump(t, _Harness([]));
      await t.tap(byGlyph(houseGlyph));
      await t.pumpAndSettle();
      await t.tap(find.byKey(const Key('nav-overview')));
      await t.pumpAndSettle();
      expect(find.text('open'), findsOneWidget);
    },
  );

  testWidgets(
    'memory page keeps its head and opens directly without password lock',
    (t) async {
      final paths = <String>[];
      await _pump(t, _Harness(paths), page: 'memory');
      expect(find.text('Bộ nhớ'), findsOneWidget); // the head
      expect(find.text('Memory Control đang khóa'), findsNothing);
      expect(find.text('Nhập mật khẩu để mở.'), findsNothing);
    },
  );

  testWidgets(
    'logs page keeps its head and opens directly without password lock',
    (t) async {
      final paths = <String>[];
      await _pump(t, _Harness(paths), page: 'logs');
      expect(find.text('Nhật ký'), findsOneWidget); // the head
      expect(find.text('Nhật ký đang khóa'), findsNothing);
      expect(find.text('Nhập mật khẩu để mở.'), findsNothing);
    },
  );
}
