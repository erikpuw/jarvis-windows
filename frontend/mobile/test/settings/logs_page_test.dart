// logs.ts: session list, owner filter, reader and the three log files.
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:jarvis_mobile/chat/lucide_glyphs.dart';
import 'package:jarvis_mobile/settings/pages/logs_page.dart';

import '../chat/fakes.dart';
import 'fixtures.dart';

Map<String, http.Response Function(http.Request)> _base() => {
  'GET /api/logs': (_) => jsonOk(logsJson()),
  'GET /api/logs/security': (_) =>
      jsonOk({'success': true, 'logs': 'SEC alert one'}),
  'GET /api/logs/tts': (_) => jsonOk({'success': true, 'logs': 'TTS spoke'}),
  'GET /api/conversations/sessions': (_) => jsonOk(sessionsJson()),
  'GET /api/conversations/session/web-ab12cd34': (_) => jsonOk({
    'success': true,
    'messages': [
      {'id': 1, 'role': 'user', 'content': 'Mở nhạc', 'created_at': 1760000000},
      {
        'id': 2,
        'role': 'assistant',
        'content': 'Đã mở.',
        'created_at': 1760000010,
      },
    ],
  }),
};

Future<List<http.Request>> _pump(
  WidgetTester t, {
  Map<String, http.Response Function(http.Request)> extra = const {},
}) async {
  final calls = <http.Request>[];
  await pumpPage(
    t,
    const LogsPage(),
    routed({..._base(), ...extra}, calls: calls),
  );
  await t.pumpAndSettle();
  return calls;
}

Iterable<http.Request> _to(List<http.Request> c, String path) =>
    c.where((r) => r.url.path == path);

Color? _colorOf(WidgetTester t, String text) =>
    t.widget<Text>(find.text(text)).style?.color;

void main() {
  testWidgets('the four tabs draw morphicons', (t) async {
    await _pump(t);
    for (final g in [
      messagesSquareGlyph,
      scrollTextGlyph,
      shieldAlertGlyph,
      audioLinesGlyph,
    ]) {
      expect(byGlyph(g), findsOneWidget);
    }
  });

  testWidgets('history shows session titles and owners, with no Toàn bộ view', (
    t,
  ) async {
    final calls = await _pump(t);
    expect(
      _to(calls, '/api/conversations/sessions').single.url.queryParameters,
      {'limit': '50', 'user': ''},
    );
    expect(find.text('Mở nhạc buổi sáng'), findsOneWidget);
    expect(find.text('web-ab12cd34'), findsNothing);
    expect(find.text('Lan'), findsWidgets);
    expect(find.text('Toàn bộ'), findsNothing);
    expect(find.text('Phiên chat'), findsNothing);
  });

  testWidgets('the owner filter reloads with user=', (t) async {
    final calls = await _pump(t);
    await t.tap(find.byKey(const Key('history-owner-filter')));
    await t.pumpAndSettle();
    await t.tap(find.text('Lan').last);
    await t.pumpAndSettle();
    expect(
      _to(
        calls,
        '/api/conversations/sessions',
      ).last.url.queryParameters['user'],
      'usr_1',
    );
  });

  testWidgets(
    'each log tab reads its own file with 300 lines and colours the levels',
    (t) async {
      final calls = await _pump(t);
      await t.ensureVisible(find.byKey(const Key('cat:jarvis')));
      await t.tap(find.byKey(const Key('cat:jarvis')));
      await t.pumpAndSettle();
      expect(_to(calls, '/api/logs').single.url.queryParameters, {
        'lines': '300',
      });
      expect(
        _colorOf(t, '2026-10-19 10:00:00 INFO server started'),
        const Color(0xFF38BDF8),
      );
      expect(
        _colorOf(t, '2026-10-19 10:00:01 WARNING slow reply'),
        const Color(0xFFF59E0B),
      );
      expect(
        _colorOf(t, '2026-10-19 10:00:02 ERROR llm down'),
        const Color(0xFFEF4444),
      );
      expect(_colorOf(t, 'plain line'), const Color(0xA6FFFFFF));
      await t.ensureVisible(find.byKey(const Key('cat:security')));
      await t.tap(find.byKey(const Key('cat:security')));
      await t.pumpAndSettle();
      expect(find.text('SEC alert one'), findsOneWidget);
      expect(_to(calls, '/api/logs/security').single.url.queryParameters, {
        'lines': '300',
      });
      await t.ensureVisible(find.byKey(const Key('cat:tts')));
      await t.tap(find.byKey(const Key('cat:tts')));
      await t.pumpAndSettle();
      expect(find.text('TTS spoke'), findsOneWidget);
      expect(_to(calls, '/api/logs/tts'), hasLength(1));
      expect(
        find.text('Toàn bộ'),
        findsNothing,
      ); // sub-views belong to the history tab only
    },
  );

  testWidgets('Làm mới reads the open tab again', (t) async {
    final calls = await _pump(t);
    await t.tap(find.text('Làm mới'));
    await t.pumpAndSettle();
    expect(_to(calls, '/api/conversations/sessions'), hasLength(2));
  });

  testWidgets('success:false shows the web text with the tab name', (t) async {
    await _pump(
      t,
      extra: {
        'GET /api/logs': (_) =>
            jsonOk({'success': false, 'error': 'Không tìm thấy jarvis.log'}),
      },
    );
    await t.ensureVisible(find.byKey(const Key('cat:jarvis')));
    await t.tap(find.byKey(const Key('cat:jarvis')));
    await t.pumpAndSettle();
    expect(
      find.text('Không tải được Jarvis log: Không tìm thấy jarvis.log'),
      findsOneWidget,
    );
  });

  testWidgets('an HTTP failure shows the connection error line', (t) async {
    await _pump(
      t,
      extra: {
        'GET /api/conversations/sessions': (_) => jsonOk({'detail': 'x'}, 500),
      },
    );
    expect(find.text('Lỗi kết nối khi tải.'), findsOneWidget);
  });

  testWidgets('session list empty note', (t) async {
    await _pump(
      t,
      extra: {
        'GET /api/conversations/sessions': (_) =>
            jsonOk({'success': true, 'sessions': [], 'users': []}),
      },
    );
    expect(find.text('Chưa có phiên chat nào.'), findsOneWidget);
  });

  testWidgets(
    'Phiên chat lists sessions with source / device; a tap opens the reader, back returns',
    (t) async {
      final calls = await _pump(t);
      expect(
        _to(calls, '/api/conversations/sessions').single.url.queryParameters,
        {'limit': '50', 'user': ''},
      );
      for (final s in [
        'Web · iOS',
        'Mở nhạc buổi sáng',
        'Telegram',
        'Hỏi thời tiết',
        'Cũ',
        'legacy',
      ]) {
        expect(find.text(s), findsOneWidget, reason: s);
      }
      expect(find.textContaining('12 tin · Hôm nay'), findsOneWidget);
      expect(find.textContaining('3 tin · Hôm qua'), findsOneWidget);
      expect(
        find.text('Chào Jarvis'),
        findsNothing,
      ); // the list OR the reader, never both on a phone

      await t.tap(find.text('Mở nhạc buổi sáng'));
      await t.pumpAndSettle();
      expect(
        _to(calls, '/api/conversations/session/web-ab12cd34'),
        hasLength(1),
      );
      expect(find.text('Mở nhạc'), findsOneWidget);
      expect(find.text('← Danh sách phiên chat'), findsOneWidget);
      expect(find.text('Web · web-ab12cd34'), findsOneWidget);
      expect(
        find.text('Làm mới'),
        findsNothing,
      ); // reading: only the back bar and the messages
      expect(find.text('Toàn bộ'), findsNothing);

      await t.tap(find.text('← Danh sách phiên chat'));
      await t.pumpAndSettle();
      expect(find.text('Mở nhạc buổi sáng'), findsOneWidget);
      expect(find.text('Mở nhạc'), findsNothing);
      expect(find.text('Làm mới'), findsOneWidget);
    },
  );

  testWidgets(
    'legacy session id is requested as written; a session error is shown',
    (t) async {
      final calls = await _pump(
        t,
        extra: {
          'GET /api/conversations/session/legacy': (_) =>
              jsonOk({'success': false, 'error': 'db_busy'}),
        },
      );
      await t.tap(find.text('legacy'));
      await t.pumpAndSettle();
      expect(_to(calls, '/api/conversations/session/legacy'), hasLength(1));
      expect(find.text('Không tải được phiên chat: db_busy'), findsOneWidget);
      expect(find.text('Cũ (chưa có phiên) · legacy'), findsOneWidget);
    },
  );

  testWidgets('session list failure and empty list notes', (t) async {
    await _pump(
      t,
      extra: {
        'GET /api/conversations/sessions': (_) =>
            jsonOk({'success': false, 'error': 'nope'}),
      },
    );
    expect(
      find.text('Không tải được danh sách phiên chat: nope'),
      findsOneWidget,
    );
  });
}
