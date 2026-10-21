// Tổng quan (pages.ts overviewPage + index.ts loadStatus / loadDetailedHealth / fillRuntime / renderAppBadges).
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:jarvis_mobile/settings/pages/overview_page.dart';

import 'fixtures.dart';

Map<String, http.Response Function(http.Request)> _ok({
  Map<String, dynamic>? status,
  Map<String, dynamic>? health,
}) => {
  'GET /api/settings/status': (_) => jsonOk(status ?? statusJson()),
  'GET /api/health/detailed': (_) => jsonOk(health ?? healthJson()),
};

void main() {
  testWidgets('loads status (apps=true) and health, shows the figures', (
    t,
  ) async {
    final calls = <http.Request>[];
    await pumpPage(t, const OverviewPage(), routed(_ok(), calls: calls));
    await t.pump(const Duration(milliseconds: 50));
    expect(
      calls.map((c) => '${c.method} ${c.url.path}?${c.url.query}'),
      containsAll([
        'GET /api/settings/status?apps=true',
        'GET /api/health/detailed?',
      ]),
    );
    expect(find.text('Tất cả dịch vụ hoạt động'), findsOneWidget);
    // hardware row
    expect(find.text('12.5%'), findsOneWidget); // CPU
    expect(find.text('47%'), findsOneWidget); // RAM
    expect(find.text('7.5 / 16 GB'), findsOneWidget);
    expect(find.text('38%'), findsOneWidget); // VRAM 4700 / 12288
    expect(
      find.text('GeForce RTX 4070 · 5GB'),
      findsOneWidget,
    ); // "NVIDIA " cut, MB -> GB
    expect(find.text('1h 1m 5s'), findsOneWidget);
    expect(find.text('Cổng máy chủ 8340'), findsOneWidget);
    // sections
    expect(find.text('Qwen3-8B'), findsOneWidget);
    expect(find.text('embeddinggemma-300m'), findsOneWidget);
    expect(find.text('VieNeu · Ngoc Huyen'), findsOneWidget);
    expect(find.text('2 / 3'), findsOneWidget);
    expect(find.text('12 · 40'), findsOneWidget);
    expect(find.text('1.234'), findsOneWidget); // vi-VN thousands
    expect(find.text('15.400'), findsOneWidget);
    expect(find.text('12.000'), findsOneWidget);
    expect(find.text('3.400'), findsOneWidget);
    for (final a in ['Code', 'Chrome', 'Spotify']) {
      expect(find.text(a), findsOneWidget);
    }
    // service rows
    expect(find.text('Lõi trí tuệ'), findsOneWidget);
    expect(find.text('Sẵn sàng'), findsWidgets);
    expect(find.text('Trung tâm hệ thống'), findsOneWidget);
  });

  testWidgets(
    'a failed service is named in the summary, a switched-off TTS is not',
    (t) async {
      final s = statusJson()
        ..['intelligence_core_ok'] = false
        ..['llm_server_ok'] = false
        ..['tts_server_ok'] = false;
      await pumpPage(t, const OverviewPage(), routed(_ok(status: s)));
      await t.pump(const Duration(milliseconds: 50));
      expect(
        find.text('2 dịch vụ lỗi: Lõi trí tuệ, Máy chủ LLM'),
        findsOneWidget,
      );
      expect(find.text('Chưa bật'), findsOneWidget);
      expect(find.text('Lỗi kết nối'), findsNWidgets(2));
    },
  );

  testWidgets('the infra rows follow /api/health/detailed', (t) async {
    await pumpPage(
      t,
      const OverviewPage(),
      routed(_ok(health: healthJson(llm: false, rag: false))),
    );
    await t.pump(const Duration(milliseconds: 50));
    expect(find.text('Mất kết nối'), findsOneWidget); // LLM
    expect(find.text('Không hoạt động'), findsOneWidget); // RAG
    expect(find.text('Lỗi'), findsNothing); // the database is fine
    expect(find.text('3 dịch vụ lỗi: Dịch vụ LLM, RAG'), findsNothing);
    expect(find.text('2 dịch vụ lỗi: Dịch vụ LLM, RAG'), findsOneWidget);
  });

  testWidgets('no GPU and no apps say so', (t) async {
    final s = statusJson();
    (s['system'] as Map)['gpus'] = [];
    s['open_apps'] = [];
    await pumpPage(t, const OverviewPage(), routed(_ok(status: s)));
    await t.pump(const Duration(milliseconds: 50));
    expect(find.text('Không phát hiện GPU chuyên dụng'), findsOneWidget);
    expect(find.text('Không có ứng dụng đáng chú ý.'), findsOneWidget);
  });

  testWidgets('before the answers: checking text and scanning', (t) async {
    await pumpPage(
      t,
      const OverviewPage(),
      routed({'GET /api/settings/status': (_) => throw Exception('slow')}),
    );
    expect(find.text('Đang quét…'), findsOneWidget);
  });

  testWidgets('an HTTP failure is shown, not swallowed', (t) async {
    await pumpPage(
      t,
      const OverviewPage(),
      routed({
        'GET /api/settings/status': (_) => jsonOk({'error': 'boom'}, 500),
        'GET /api/health/detailed': (_) => jsonOk(healthJson()),
      }),
    );
    await t.pump(const Duration(milliseconds: 50));
    expect(find.text('Không tải được trạng thái: boom'), findsOneWidget);
  });

  testWidgets('polls every 5 s while the page is open', (t) async {
    final calls = <http.Request>[];
    await pumpPage(t, const OverviewPage(), routed(_ok(), calls: calls));
    final first = calls
        .where((c) => c.url.path == '/api/settings/status')
        .length;
    await t.pump(const Duration(seconds: 5));
    await t.pump(const Duration(milliseconds: 50));
    expect(
      calls.where((c) => c.url.path == '/api/settings/status').length,
      first + 1,
    );
  });
}
