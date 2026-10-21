// Bản đồ mã (graphfy.ts renderGraphfy / toggleGraphfyAll / resetGraphfyLayout): endpoint, nodes drawn, error text,
// drag saved under the web's key, hub toggle, reset.
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:jarvis_mobile/settings/graphfy_layout.dart';
import 'package:jarvis_mobile/settings/pages/graphfy_page.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'fixtures.dart';

Map<String, dynamic> _small() => {
  'success': true,
  'nodes': [
    {'id': 'server', 'label': 'server', 'lane': 'input'},
    {'id': 'tools', 'label': 'tools', 'lane': 'turn'},
    {'id': 'server/llm_server', 'label': 'llm_server', 'lane': 'llm'},
    {'id': 'core/memory', 'label': 'memory', 'lane': 'memory'},
  ],
  'edges': [
    {'from': 'tools', 'to': 'server/llm_server', 'kind': 'llm'},
    {'from': 'core/memory', 'to': 'server/llm_server', 'kind': 'llm'},
    {'from': 'core/memory', 'to': 'tools', 'kind': 'import'},
    {'from': 'server', 'to': 'tools', 'kind': 'import'},
  ],
};

// a point at the bottom of the canvas, below the drawn map
Offset _empty(WidgetTester t) =>
    t.getBottomLeft(find.byKey(const Key('gf-map'))) + const Offset(40, -8);

GraphfyModel _model(WidgetTester t) =>
    (t.widget<CustomPaint>(find.byKey(const Key('gf-map'))).painter!
            as GraphfyPainter)
        .model;

int _shown(GraphfyModel m) =>
    [for (var i = 0; i < m.edges.length; i++) m.shown(i)]
        .where((x) => x)
        .length;

Future<List<http.Request>> _pump(
  WidgetTester t, {
  http.Response Function(http.Request)? graph,
}) async {
  final calls = <http.Request>[];
  await pumpPage(
    t,
    const GraphfyPage(),
    routed({
      'GET /api/graphfy': graph ?? (_) => jsonOk(_small()),
    }, calls: calls),
  );
  await t.pump(const Duration(milliseconds: 100));
  await t.pump(const Duration(milliseconds: 100));
  return calls;
}

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));
  _animation();

  testWidgets('loads /api/graphfy and draws the nodes and edges', (t) async {
    final calls = await _pump(t);
    expect(calls.where((c) => c.url.path == '/api/graphfy').length, 1);
    expect(find.text('Bản đồ mã'), findsOneWidget);
    expect(find.text('Gọi LLM'), findsOneWidget);
    expect(find.text('Hiện tất cả'), findsOneWidget);
    expect(find.text('Bố cục mặc định'), findsOneWidget);
    final m = _model(t);
    expect(m.nodes.map((n) => n.id).toSet(), {
      'server',
      'tools',
      'server/llm_server',
      'core/memory',
    });
    expect(m.edges.length, 4);
  });

  testWidgets('HTTP failure shows the web error text', (t) async {
    await _pump(t, graph: (_) => jsonOk({'detail': 'boom'}, 500));
    expect(find.text('Không dựng được sơ đồ: boom'), findsOneWidget);
    expect(find.byKey(const Key('gf-map')), findsNothing);
  });

  testWidgets(
    'dragging a node moves it and saves positions under the web key',
    (t) async {
      await _pump(t);
      final m = _model(t);
      final n = m.byId['tools']!;
      final before = Offset(n.x, n.y);
      final origin = t.getTopLeft(find.byKey(const Key('gf-map')));
      final start = origin + m.sceneToScreen(n.rect.center);
      await t.dragFrom(start, const Offset(60, 40));
      await t.pump(const Duration(milliseconds: 50));
      final moved = Offset(n.x, n.y);
      expect(moved.dx, greaterThan(before.dx + 30));
      expect(moved.dy, greaterThan(before.dy + 20));
      final prefs = await SharedPreferences.getInstance();
      final saved = jsonDecode(prefs.getString(gfPosKey)!) as Map;
      expect(gfPosKey, 'jarvis.graphfy.positions.v4');
      expect(saved['tools'], [moved.dx, moved.dy]);
      expect(saved.keys, containsAll(['server', 'core/memory']));
    },
  );

  testWidgets('saved positions are applied on load', (t) async {
    SharedPreferences.setMockInitialValues({
      gfPosKey: jsonEncode({
        'tools': [400, 60],
      }),
    });
    await _pump(t);
    final n = _model(t).byId['tools']!;
    expect((n.x, n.y), (400, 60));
  });

  testWidgets('dragging empty canvas pans, nodes stay', (t) async {
    await _pump(t);
    final m = _model(t);
    final x0 = m.byId['tools']!.x;
    final before = m.offset;
    await t.dragFrom(_empty(t), const Offset(-80, -30));
    await t.pump(const Duration(milliseconds: 50));
    expect(m.byId['tools']!.x, x0);
    expect(m.offset.dx, lessThan(before.dx));
  });

  testWidgets('hub toggle shows the edges to server / tools', (t) async {
    await _pump(t);
    final m = _model(t);
    // tools->llm and memory->llm are llm edges; memory->tools and server->tools are hub imports
    expect(_shown(m), 2);
    await t.tap(find.byKey(const Key('gf-all')));
    await t.pump();
    expect(find.text('Ẩn bớt'), findsOneWidget);
    expect(_shown(m), 4);
    await t.tap(find.byKey(const Key('gf-all')));
    await t.pump();
    expect(find.text('Hiện tất cả'), findsOneWidget);
    expect(_shown(m), 2);
  });

  testWidgets('tapping a node lights its hub edges, tapping empty clears', (
    t,
  ) async {
    await _pump(t);
    final m = _model(t);
    final origin = t.getTopLeft(find.byKey(const Key('gf-map')));
    final n = m.byId['server']!;
    await t.tapAt(origin + m.sceneToScreen(n.rect.center));
    await t.pump(const Duration(milliseconds: 50));
    expect(m.focus, 'server');
    expect(_shown(m), 3);
    await t.tapAt(_empty(t));
    await t.pump(const Duration(milliseconds: 50));
    expect(m.focus, isNull);
  });

  testWidgets('"Bố cục mặc định" drops saved positions', (t) async {
    SharedPreferences.setMockInitialValues({
      gfPosKey: jsonEncode({
        'tools': [400, 60],
      }),
    });
    await _pump(t);
    expect(_model(t).byId['tools']!.x, 400);
    await t.tap(find.byKey(const Key('gf-reset')));
    await t.pump(const Duration(milliseconds: 100));
    await t.pump(const Duration(milliseconds: 100));
    expect(_model(t).byId['tools']!.x, 360);
    final prefs = await SharedPreferences.getInstance();
    expect(prefs.getString(gfPosKey), isNull);
  });
}

GraphfyPainter _painter(WidgetTester t) =>
    t.widget<CustomPaint>(find.byKey(const Key('gf-map'))).painter!
        as GraphfyPainter;

int _circles(WidgetTester t) {
  final canvas = TestRecordingCanvas();
  final size = t.getSize(find.byKey(const Key('gf-map')));
  _painter(t).paint(canvas, size);
  return canvas.invocations
      .where((i) => i.invocation.memberName == #drawCircle)
      .length;
}

void _animation() {
  testWidgets('the clock ticks and an LLM pulse is painted per llm edge', (
    t,
  ) async {
    await _pump(t);
    await t.pump(const Duration(milliseconds: 500));
    final p = _painter(t);
    expect(p.clock.animate, isTrue);
    expect(p.clock.t, greaterThan(0.3));
    // brain pads+pins (9 x fill+stroke) + 2 llm edges x (glow+dot)
    expect(_circles(t), 18 + 4);
  });

  testWidgets('hidden page (TickerMode off): the clock stands still', (
    t,
  ) async {
    await pumpPage(
      t,
      TickerMode(enabled: false, child: const GraphfyPage()),
      routed({'GET /api/graphfy': (_) => jsonOk(_small())}),
    );
    await t.pump(const Duration(milliseconds: 100));
    await t.pump(const Duration(milliseconds: 600));
    expect(_painter(t).clock.t, 0);
  });

  testWidgets('reduced motion: no ticking, no pulses', (t) async {
    await pumpPage(
      t,
      Builder(
        builder: (c) => MediaQuery(
          data: MediaQuery.of(c).copyWith(disableAnimations: true),
          child: const GraphfyPage(),
        ),
      ),
      routed({'GET /api/graphfy': (_) => jsonOk(_small())}),
    );
    await t.pump(const Duration(milliseconds: 100));
    await t.pump(const Duration(milliseconds: 600));
    final p = _painter(t);
    expect(p.clock.animate, isFalse);
    expect(p.clock.t, 0);
    expect(_circles(t), 18);
  });
}
