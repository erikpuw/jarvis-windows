// Kết nối & API (pages.ts connectPage + index.ts bindActions: save keys, test LLM / TTS, save URL, restart).
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:jarvis_mobile/chat/lucide_glyphs.dart';
import 'package:jarvis_mobile/settings/pages/connect_page.dart';

import '../chat/fakes.dart';

import 'fixtures.dart';

Map<String, dynamic> _body(http.Request r) =>
    jsonDecode(r.body) as Map<String, dynamic>;

/// The text field of the form group with this label.
Finder _field(String label) => find.byKey(Key('field:$label'));

Future<List<http.Request>> _pump(
  WidgetTester t, {
  Map<String, http.Response Function(http.Request)> extra = const {},
}) async {
  final calls = <http.Request>[];
  await pumpPage(
    t,
    const ConnectPage(),
    routed({
      'GET /api/settings/status': (_) => jsonOk(statusJson()),
      'POST /api/settings/keys': (_) => jsonOk({'success': true}),
      'POST /api/settings/test-llm': (_) => jsonOk({'valid': true}),
      'POST /api/settings/test-tts': (_) => jsonOk({'valid': true}),
      'POST /api/restart': (_) => jsonOk({'status': 'restarting'}),
      ...extra,
    }, calls: calls),
  );
  await t.pump(const Duration(milliseconds: 50));
  return calls;
}

Future<void> _tap(WidgetTester t, String label) async {
  await t.ensureVisible(find.text(label));
  await t.tap(find.text(label));
  await t.pump();
  await t.pump(const Duration(milliseconds: 100));
}

void main() {
  testWidgets('the cards, labels and notes of the web page', (t) async {
    final calls = await _pump(t);
    expect(
      calls.map((c) => '${c.url.path}?${c.url.query}'),
      contains('/api/settings/status?apps=true'),
    );
    for (final s in [
      'Restart',
      'Mô hình ngôn ngữ (LLM API)',
      'Server API Key (LOCAL_API_KEY)',
      'Endpoint máy chủ LLM (LOCAL_URL)',
      'Kiểm tra',
      'Lưu URL',
      'Fish Audio / VieNeu API Key',
      'Kiểm tra TTS',
      'Lưu toàn bộ cài đặt kết nối',
      'Đang sử dụng VieNeu TTS Engine nội bộ (cục bộ).',
      'Đã cấu hình khoá và URL máy chủ.', // from status.env_keys_set.llama
      'Địa chỉ server', // the app-only field
    ]) {
      await t.ensureVisible(find.text(s));
      expect(find.text(s), findsOneWidget, reason: s);
    }
  });

  testWidgets('no key configured says so', (t) async {
    final s = statusJson();
    (s['env_keys_set'] as Map)['llama'] = false;
    await _pump(t, extra: {'GET /api/settings/status': (_) => jsonOk(s)});
    expect(find.text('Chưa cấu hình khoá.'), findsOneWidget);
  });

  testWidgets('status HTTP failure is not swallowed', (t) async {
    await _pump(
      t,
      extra: {
        'GET /api/settings/status': (_) => jsonOk({'error': 'boom'}, 500),
      },
    );
    expect(find.text('Không tải được trạng thái: boom'), findsOneWidget);
  });

  testWidgets(
    'Kiểm tra posts the typed key to the LLM test and says the result',
    (t) async {
      final calls = await _pump(t);
      await t.enterText(_field('Server API Key (LOCAL_API_KEY)'), ' k1 ');
      await _tap(t, 'Kiểm tra');
      final c = calls.firstWhere((c) => c.url.path == '/api/settings/test-llm');
      expect(_body(c), {'key_value': 'k1'});
      // runAction's okText: the web shows this, not the text setFeedback wrote before it
      expect(find.text('Đã lưu'), findsOneWidget);
      await t.pump(const Duration(seconds: 2));
    },
  );

  testWidgets('an invalid key shows the server text', (t) async {
    final calls = await _pump(
      t,
      extra: {
        'POST /api/settings/test-llm': (_) =>
            jsonOk({'valid': false, 'error': 'bad key'}),
      },
    );
    await _tap(t, 'Kiểm tra');
    expect(
      _body(calls.firstWhere((c) => c.url.path == '/api/settings/test-llm')),
      isEmpty,
    );
    expect(find.text('bad key'), findsOneWidget);
    await t.pump(const Duration(seconds: 2));
  });

  testWidgets(
    'Kiểm tra TTS posts to the TTS test; a failure with no text says Invalid TTS key',
    (t) async {
      final calls = await _pump(
        t,
        extra: {
          'POST /api/settings/test-tts': (_) => jsonOk({'valid': false}),
        },
      );
      await t.enterText(_field('Fish Audio / VieNeu API Key'), 'f');
      await _tap(t, 'Kiểm tra TTS');
      expect(
        _body(calls.firstWhere((c) => c.url.path == '/api/settings/test-tts')),
        {'key_value': 'f'},
      );
      expect(find.text('Invalid TTS key'), findsOneWidget);
      await t.pump(const Duration(seconds: 2));
    },
  );

  testWidgets('Lưu URL needs a url, then saves LOCAL_URL', (t) async {
    final calls = await _pump(t);
    await _tap(t, 'Lưu URL');
    expect(find.text('Nhập URL máy chủ'), findsOneWidget);
    expect(calls.where((c) => c.url.path == '/api/settings/keys'), isEmpty);
    await t.pump(const Duration(seconds: 2));
    await t.enterText(
      _field('Endpoint máy chủ LLM (LOCAL_URL)'),
      ' http://h:8080/v1 ',
    );
    await _tap(t, 'Lưu URL');
    final c = calls.singleWhere((c) => c.url.path == '/api/settings/keys');
    expect(_body(c), {
      'key_name': 'LOCAL_URL',
      'key_value': 'http://h:8080/v1',
    });
    await t.pump(const Duration(seconds: 2));
  });

  testWidgets(
    'save all: the LLM key is required, then LOCAL_API_KEY and TTS_LOCAL_KEY, then status reloads',
    (t) async {
      final calls = await _pump(t);
      await _tap(t, 'Lưu toàn bộ cài đặt kết nối');
      expect(find.text('Missing Server API Key'), findsOneWidget);
      await t.pump(const Duration(seconds: 2));
      await t.enterText(_field('Server API Key (LOCAL_API_KEY)'), 'abc');
      await t.enterText(_field('Fish Audio / VieNeu API Key'), 'tts');
      final before = calls
          .where((c) => c.url.path == '/api/settings/status')
          .length;
      await _tap(t, 'Lưu toàn bộ cài đặt kết nối');
      final posts = calls
          .where((c) => c.url.path == '/api/settings/keys')
          .map(_body)
          .toList();
      expect(posts, [
        {'key_name': 'LOCAL_API_KEY', 'key_value': 'abc'},
        {'key_name': 'TTS_LOCAL_KEY', 'key_value': 'tts'},
      ]);
      expect(
        calls.where((c) => c.url.path == '/api/settings/status').length,
        before + 1,
      );
      await t.pump(const Duration(seconds: 2));
    },
  );

  testWidgets('a refused save shows the backend error', (t) async {
    await _pump(
      t,
      extra: {
        'POST /api/settings/keys': (_) =>
            jsonOk({'success': false, 'error': 'Invalid key name'}, 400),
      },
    );
    await t.enterText(_field('Server API Key (LOCAL_API_KEY)'), 'abc');
    await _tap(t, 'Lưu toàn bộ cài đặt kết nối');
    expect(find.text('Invalid key name'), findsOneWidget);
    await t.pump(const Duration(seconds: 2));
  });

  testWidgets('Restart posts /api/restart', (t) async {
    final calls = await _pump(t);
    expect(
      byGlyph(refreshCwGlyph),
      findsOneWidget,
    ); // decorateActionButton(btn, "refresh")
    await _tap(t, 'Restart');
    expect(
      calls.any((c) => c.method == 'POST' && c.url.path == '/api/restart'),
      isTrue,
    );
    await t.pump(const Duration(seconds: 2));
  });
}
