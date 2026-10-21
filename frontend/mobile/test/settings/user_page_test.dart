// Người dùng (pages.ts userPage + index.ts loadPreferences / btn-save-prefs): the body is user_name, honorific, calendar_accounts.
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:jarvis_mobile/chat/lucide_glyphs.dart';
import 'package:jarvis_mobile/chat/morph_icon.dart';
import 'package:jarvis_mobile/settings/pages/user_page.dart';

import '../chat/fakes.dart';
import 'fixtures.dart';

Future<List<http.Request>> _pump(
  WidgetTester t, {
  Map<String, http.Response Function(http.Request)> extra = const {},
}) async {
  final calls = <http.Request>[];
  await pumpPage(
    t,
    const UserPage(),
    routed({
      'GET /api/settings/preferences': (_) => jsonOk({
        'user_name': 'Erik',
        'honorific': 'Boss',
        'calendar_accounts': 'e@gmail.com',
      }),
      'POST /api/settings/preferences': (_) => jsonOk({'success': true}),
      ...extra,
    }, calls: calls),
  );
  await t.pump(const Duration(milliseconds: 50));
  return calls;
}

String _text(WidgetTester t, String key) => t
    .widget<TextField>(
      find.descendant(
        of: find.byKey(Key(key)),
        matching: find.byType(TextField),
      ),
    )
    .controller!
    .text;

void main() {
  testWidgets('the three fields of the web page, filled from the preferences', (
    t,
  ) async {
    await _pump(t);
    for (final s in [
      'Hồ sơ người dùng & Tương tác',
      'Tên hiển thị của bạn',
      'Cách JARVIS xưng hô với bạn',
      'Tài khoản Google Calendar đồng bộ',
      'Lưu thông tin cá nhân',
    ]) {
      expect(find.text(s), findsOneWidget, reason: s);
    }
    expect(_text(t, 'field:user_name'), 'Erik');
    expect(_text(t, 'field:honorific'), 'Boss');
    expect(_text(t, 'field:calendar_accounts'), 'e@gmail.com');
  });

  testWidgets(
    'null preferences leave the fields empty with the web placeholders',
    (t) async {
      await _pump(
        t,
        extra: {
          'GET /api/settings/preferences': (_) => jsonOk({
            'user_name': null,
            'honorific': null,
            'calendar_accounts': null,
          }),
        },
      );
      expect(_text(t, 'field:user_name'), '');
      expect(find.text('Ví dụ: Erik'), findsOneWidget);
      expect(find.text('Ví dụ: Bạn, Anh, Boss...'), findsOneWidget);
      expect(find.text('email@gmail.com'), findsOneWidget);
    },
  );

  testWidgets(
    'save posts user_name, honorific and calendar_accounts (trimmed), not user_manner',
    (t) async {
      final calls = await _pump(t);
      await t.enterText(
        find.descendant(
          of: find.byKey(const Key('field:user_name')),
          matching: find.byType(TextField),
        ),
        '  Linh ',
      );
      expect(byGlyph(saveGlyph), findsOneWidget);
      final icon = t.state(byGlyph(saveGlyph));
      await t.tap(find.text('Lưu thông tin cá nhân'));
      await t.pump();
      await t.pump(const Duration(milliseconds: 100));
      final c = calls.singleWhere((c) => c.method == 'POST');
      expect(c.url.path, '/api/settings/preferences');
      expect(jsonDecode(c.body), {
        'user_name': 'Linh',
        'honorific': 'Boss',
        'calendar_accounts': 'e@gmail.com',
      });
      // one morph icon: idle -> spinner -> check; the text is runAction's okText
      expect(find.text('Đã lưu'), findsOneWidget);
      expect(identical(t.state(find.byType(MorphIcon).first), icon), isTrue);
      await t.pump(const Duration(seconds: 2));
      expect(byGlyph(saveGlyph), findsOneWidget);
    },
  );

  testWidgets('a failed save shows the x and the error', (t) async {
    await _pump(
      t,
      extra: {
        'POST /api/settings/preferences': (_) =>
            jsonOk({'success': false, 'error': 'Giá trị không hợp lệ'}, 400),
      },
    );
    await t.tap(find.text('Lưu thông tin cá nhân'));
    await t.pump();
    await t.pump(const Duration(milliseconds: 100));
    expect(byGlyph(xGlyph), findsOneWidget);
    expect(find.text('Giá trị không hợp lệ'), findsOneWidget);
    await t.pump(const Duration(seconds: 2));
  });

  testWidgets('loading the preferences failing is shown', (t) async {
    await _pump(
      t,
      extra: {
        'GET /api/settings/preferences': (_) => jsonOk({'error': 'boom'}, 500),
      },
    );
    expect(find.text('Không tải được thông tin: boom'), findsOneWidget);
  });
}
