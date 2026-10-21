// Giọng đọc (pages.ts voicePage + index.ts loadVoices / fillVoiceSelect / fillRuntime / bindActions: save voice, clone upload).
import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:jarvis_mobile/settings/pages/voice_page.dart';

import 'fixtures.dart';

Future<List<http.Request>> _pump(
  WidgetTester t, {
  Map<String, http.Response Function(http.Request)> extra = const {},
  Future<String?> Function()? pick,
}) async {
  final calls = <http.Request>[];
  await pumpPage(
    t,
    VoicePage(pickAudio: pick),
    routed({
      'GET /api/settings/status': (_) => jsonOk(statusJson()),
      'GET /api/tts/voices': (_) => jsonOk(voicesJson()),
      'POST /api/tts/voice': (r) => jsonOk({'success': true, 'voice': 'x'}),
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

/// The upload reads a real file: let real I/O finish between fake-async pumps.
Future<void> _settleIo(WidgetTester t) async {
  for (var i = 0; i < 6; i++) {
    await t.runAsync(
      () => Future<void>.delayed(const Duration(milliseconds: 80)),
    );
    await t.pump(const Duration(milliseconds: 50));
  }
}

void main() {
  testWidgets(
    'engine rows come from status.runtime, the select from /api/tts/voices',
    (t) async {
      final calls = await _pump(t);
      expect(
        calls.map((c) => '${c.url.path}?${c.url.query}'),
        containsAll(['/api/settings/status?apps=true', '/api/tts/voices?']),
      );
      expect(find.text('Engine đang chạy'), findsOneWidget);
      expect(find.text('VieNeu TTS'), findsOneWidget);
      expect(find.text('Ngoc Huyen · đang chạy'), findsOneWidget);
      expect(find.text('Edge-TTS'), findsOneWidget);
      expect(find.text('vi-VN-HoaiMyNeural'), findsOneWidget);
      expect(find.text('Giọng VieNeu'), findsOneWidget);
      expect(find.text('Chọn giọng nói'), findsOneWidget);
      expect(
        find.text('Giọng được áp dụng ngay cho phản hồi âm thanh tiếp theo.'),
        findsOneWidget,
      );
      expect(
        find.text('Ngọc Huyền (nữ miền Bắc)'),
        findsOneWidget,
      ); // current voice selected
    },
  );

  testWidgets('the menu groups presets and clones', (t) async {
    await _pump(t);
    await t.tap(find.byKey(const Key('voice-select')));
    await t.pumpAndSettle();
    expect(find.text('Giọng có sẵn'), findsOneWidget);
    expect(find.text('Giọng clone của bạn'), findsOneWidget);
    expect(find.text('Bình (nam miền Bắc)'), findsOneWidget);
    expect(find.text('Giong cua toi'), findsOneWidget);
  });

  testWidgets('Lưu giọng posts the chosen voice', (t) async {
    final calls = await _pump(t);
    await t.tap(find.byKey(const Key('voice-select')));
    await t.pumpAndSettle();
    await t.tap(find.text('Bình (nam miền Bắc)').last);
    await t.pumpAndSettle();
    await _tap(t, 'Lưu giọng');
    final c = calls.singleWhere((c) => c.method == 'POST');
    expect(c.url.path, '/api/tts/voice');
    expect(jsonDecode(c.body), {'voice': 'Binh'});
    expect(find.text('Đã lưu'), findsOneWidget);
    await t.pump(const Duration(seconds: 2));
  });

  testWidgets('a refused voice shows the backend error', (t) async {
    await _pump(
      t,
      extra: {
        'POST /api/tts/voice': (_) =>
            jsonOk({'success': false, 'error': 'Invalid voice name'}),
      },
    );
    await _tap(t, 'Lưu giọng');
    expect(find.text('Invalid voice name'), findsOneWidget);
    await t.pump(const Duration(seconds: 2));
  });

  testWidgets('another engine hides the select and says so', (t) async {
    await _pump(
      t,
      extra: {
        'GET /api/tts/voices': (_) => jsonOk({
          'engine': 'edge',
          'default': '',
          'voices': [],
          'current': '',
        }),
      },
    );
    expect(find.text('Chọn giọng nói'), findsNothing);
    expect(
      find.text('Engine TTS hiện tại không hỗ trợ chọn giọng ở đây.'),
      findsOneWidget,
    );
  });

  testWidgets('the voice list failing is not swallowed', (t) async {
    await _pump(
      t,
      extra: {
        'GET /api/tts/voices': (_) => jsonOk({'error': 'boom'}, 503),
      },
    );
    expect(
      find.text('Không lấy được danh sách giọng (boom). Kiểm tra TTS server.'),
      findsOneWidget,
    );
  });

  testWidgets('the engine status failing is shown', (t) async {
    await _pump(
      t,
      extra: {
        'GET /api/settings/status': (_) => jsonOk({'error': 'nope'}, 500),
      },
    );
    expect(find.text('Không tải được trạng thái: nope'), findsOneWidget);
  });

  testWidgets('clone needs a name and a file first', (t) async {
    final calls = await _pump(t);
    await _tap(t, 'Tải lên & Huấn luyện');
    expect(find.text('Nhập tên giọng và chọn file mẫu trước'), findsOneWidget);
    expect(calls.where((c) => c.method == 'POST'), isEmpty);
    await t.pump(const Duration(seconds: 2));
  });

  testWidgets('clone uploads name + file, refills the select and hints', (
    t,
  ) async {
    final dir = Directory.systemTemp.createTempSync('voice_test');
    addTearDown(() => dir.deleteSync(recursive: true));
    final file = File('${dir.path}/mau.wav')..writeAsBytesSync([1, 2, 3, 4]);
    final calls = await _pump(
      t,
      pick: () async => file.path,
      extra: {
        'POST /api/tts/voices/clone': (_) => jsonOk({
          'success': true,
          'voices': [
            ...voicesJson()['voices'] as List,
            {'name': 'Giong moi', 'label': 'Giong moi', 'kind': 'clone'},
          ],
        }),
      },
    );
    await t.enterText(
      find.byKey(const Key('field:Tên giọng clone')),
      ' Giong moi ',
    );
    await _tap(t, 'Chọn tệp');
    await t.pump(const Duration(milliseconds: 50));
    expect(find.text('mau.wav'), findsOneWidget);
    await t.ensureVisible(find.text('Tải lên & Huấn luyện'));
    await t.tap(find.text('Tải lên & Huấn luyện'));
    await _settleIo(t);
    final c = calls.singleWhere((c) => c.url.path == '/api/tts/voices/clone');
    expect(c.headers['content-type'], startsWith('multipart/form-data'));
    expect(c.body, contains('name="name"'));
    expect(c.body, contains('Giong moi'));
    expect(c.body, contains('name="file"'));
    expect(c.body, contains('filename="mau.wav"'));
    expect(find.text('Đã tải mẫu'), findsOneWidget);
    expect(
      find.text('Đã thêm giọng "Giong moi". Bấm "Lưu giọng" để dùng.'),
      findsOneWidget,
    );
    await t.pump(const Duration(seconds: 2));
  });

  testWidgets('a refused clone shows the server text', (t) async {
    final dir = Directory.systemTemp.createTempSync('voice_test');
    addTearDown(() => dir.deleteSync(recursive: true));
    final file = File('${dir.path}/mau.wav')..writeAsBytesSync([1]);
    await _pump(
      t,
      pick: () async => file.path,
      extra: {
        'POST /api/tts/voices/clone': (_) => jsonOk({
          'success': false,
          'error': 'Mẫu quá lớn (tối đa 10MB)',
        }, 413),
      },
    );
    await t.enterText(find.byKey(const Key('field:Tên giọng clone')), 'A');
    await _tap(t, 'Chọn tệp');
    await t.pump(const Duration(milliseconds: 50));
    await t.ensureVisible(find.text('Tải lên & Huấn luyện'));
    await t.tap(find.text('Tải lên & Huấn luyện'));
    await _settleIo(t);
    expect(find.text('Mẫu quá lớn (tối đa 10MB)'), findsOneWidget);
    await t.pump(const Duration(seconds: 2));
  });
}
