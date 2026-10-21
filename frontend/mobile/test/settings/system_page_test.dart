// Hệ thống (pages.ts systemPage + index.ts loadStatus / loadDetailedHealth / renderGpuList / renderAppBadges).
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:jarvis_mobile/chat/lucide_glyphs.dart';
import 'package:jarvis_mobile/settings/pages/system_page.dart';

import '../chat/fakes.dart';
import 'fixtures.dart';

Map<String, http.Response Function(http.Request)> _ok({
  Map<String, dynamic>? status,
  Map<String, dynamic>? health,
}) => {
  'GET /api/settings/status': (_) => jsonOk(status ?? statusJson()),
  'GET /api/health/detailed': (_) => jsonOk(health ?? healthJson()),
};

void main() {
  testWidgets('resources, GPU and NPU, service rows and apps', (t) async {
    final calls = <http.Request>[];
    await pumpPage(t, const SystemPage(), routed(_ok(), calls: calls));
    await t.pump(const Duration(milliseconds: 50));
    expect(
      calls.map((c) => '${c.url.path}?${c.url.query}'),
      containsAll(['/api/settings/status?apps=true', '/api/health/detailed?']),
    );
    for (final s in [
      'Tài nguyên máy chủ',
      'Vi xử lý CPU',
      '12.5%',
      'Bộ nhớ RAM',
      '47%',
      'Đã dùng 7.5 GB trên tổng số 16 GB (47%)',
      'Card đồ họa & Bộ tăng tốc (GPU / NPU)',
      'NVIDIA GeForce RTX 4070', // the name is not cut here
      'Intel(R) AI Boost',
      'Bộ tăng tốc trí tuệ nhân tạo NPU',
      'Trạng thái chi tiết dịch vụ nội bộ',
      'llama.cpp / Mô hình suy luận',
      '42.5ms',
      'SQLite Memory Storage',
      '2048.5 KB',
      'ChromaDB / Vector Search Engine',
      '320 chunks',
      'Ứng dụng Desktop đang phát hiện',
      'Code',
      'Chrome',
      'Spotify',
    ]) {
      expect(find.text(s), findsOneWidget, reason: s);
    }
    expect(find.textContaining('Bộ nhớ: 4700 MB / 12288 MB'), findsOneWidget);
    expect(find.textContaining('Nhiệt độ: 54°C'), findsOneWidget);
    expect(
      byGlyph(refreshCwGlyph),
      findsNothing,
    ); // the web's system page has no Restart
  });

  testWidgets('offline services say so', (t) async {
    await pumpPage(
      t,
      const SystemPage(),
      routed(_ok(health: healthJson(llm: false, rag: false, db: false))),
    );
    await t.pump(const Duration(milliseconds: 50));
    expect(find.text('chờ kết nối'), findsOneWidget); // llm.status
    expect(find.text('không hoạt động'), findsOneWidget);
    expect(find.text('offline'), findsNothing);
    expect(
      find.text('2048.5 KB'),
      findsOneWidget,
    ); // size_kb wins over the flag
  });

  testWidgets('no GPU, NPU or apps', (t) async {
    final s = statusJson();
    (s['system'] as Map)
      ..['gpus'] = []
      ..['npus'] = [];
    s['open_apps'] = [];
    await pumpPage(t, const SystemPage(), routed(_ok(status: s)));
    await t.pump(const Duration(milliseconds: 50));
    expect(
      find.text('Không phát hiện GPU/NPU rời. Chạy trên CPU.'),
      findsOneWidget,
    );
    expect(
      find.text('Không phát hiện ứng dụng desktop đang chạy.'),
      findsOneWidget,
    );
  });

  testWidgets('before the answers the cards say they are scanning', (t) async {
    await pumpPage(
      t,
      const SystemPage(),
      routed({'GET /api/settings/status': (_) => throw Exception('slow')}),
    );
    expect(find.text('Đang tải thông số…'), findsOneWidget);
    expect(find.text('Đang quét phần cứng tăng tốc…'), findsOneWidget);
    expect(find.text('Đang quét ứng dụng chạy nền…'), findsOneWidget);
    expect(find.text('Đang kiểm tra…'), findsNWidgets(3));
  });

  testWidgets('an HTTP failure is shown, not swallowed', (t) async {
    await pumpPage(
      t,
      const SystemPage(),
      routed({
        'GET /api/settings/status': (_) => jsonOk({'error': 'boom'}, 500),
        'GET /api/health/detailed': (_) => jsonOk({'error': 'bang'}, 500),
      }),
    );
    await t.pump(const Duration(milliseconds: 50));
    expect(find.text('Không tải được trạng thái: boom'), findsOneWidget);
    expect(find.text('Không kiểm tra được dịch vụ: bang'), findsOneWidget);
  });

  testWidgets('polls every 5 s', (t) async {
    final calls = <http.Request>[];
    await pumpPage(t, const SystemPage(), routed(_ok(), calls: calls));
    final first = calls
        .where((c) => c.url.path == '/api/health/detailed')
        .length;
    await t.pump(const Duration(seconds: 5));
    await t.pump(const Duration(milliseconds: 50));
    expect(
      calls.where((c) => c.url.path == '/api/health/detailed').length,
      first + 1,
    );
  });
}
