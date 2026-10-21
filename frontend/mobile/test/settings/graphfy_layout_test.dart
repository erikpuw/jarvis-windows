// Graphfy layout rules (graphfy.ts layout / edgePath), checked on a small map worked out by hand.

import 'package:flutter_test/flutter_test.dart';
import 'package:jarvis_mobile/settings/graphfy_layout.dart';

Map<String, dynamic> _n(String id, String lane) => {
  'id': id,
  'label': id,
  'lane': lane,
};

void main() {
  final lay = gfLayout([
    _n('server', 'input'),
    _n('tools', 'turn'),
    _n('server/llm_server', 'llm'),
    _n('server/tts_manager', 'output'),
    _n('core/memory', 'memory'),
    _n('core/rag_engine', 'ingestion'),
  ]);
  GfNode node(String id) => lay.nodes.firstWhere((n) => n.id == id);

  test('top band lanes are columns of 290px, bottom band lies under it', () {
    expect(node('server').x, 70);
    expect(node('server').y, 34);
    expect(node('tools').x, 360);
    expect(node('server/tts_manager').x, 940);
    // top band: 34 + max(1 row * 40, 120 + 10) = 164; bottom band starts 40 lower, 2 lanes of 580px
    expect(node('core/memory').y, 164 + 40 + 34);
    expect(node('core/memory').x, 215);
    expect(lay.height, 164 + 40 + 34 + 40);
  });

  test('the LLM node is a 114x120 brain centred in its column', () {
    final b = node('server/llm_server');
    expect((b.w, b.h), (114, 120));
    expect(b.x, 650 + 18);
    expect(b.y, 34 + 5);
  });

  test('lane titles follow the placed lanes', () {
    expect(lay.titles.map((t) => t.lane.id), [
      'input',
      'turn',
      'llm',
      'output',
      'memory',
      'ingestion',
    ]);
    expect(lay.titles.first.y, 16);
  });

  test('edges: same column bows right, forward goes side to side', () {
    final a = GfNode('a', 'a', 'input', 70, 34, 150, 30);
    final b = GfNode('b', 'b', 'input', 70, 114, 150, 30);
    final bow = gfEdgePoints(a, b);
    expect(bow.first, const Offset(220, 49));
    expect(bow[1].dx, 220 + 30 + 20); // 30 + min(60, 80 / 4)
    final c = GfNode('c', 'c', 'turn', 360, 34, 150, 30);
    final fwd = gfEdgePoints(a, c);
    expect(fwd.first, const Offset(220, 49));
    expect(fwd.last, const Offset(360, 49));
    expect(fwd[1], const Offset(220 + 70, 49)); // max(40, 140 * .5)
  });

  test('callers below the brain plug into its low pin', () {
    final brain = node('server/llm_server');
    final caller = GfNode('x', 'x', 'memory', 505, 238, 150, 30);
    final p = gfEdgePoints(caller, brain);
    expect(p.first, const Offset(580, 238));
    expect(p.last, Offset(brain.x + 57, brain.y + 120 * 0.92));
  });

  test('saved positions are clamped into the map and unknown ids ignored', () {
    final n = node('server');
    gfApplyPositions(lay.nodes, lay.height, {
      'server': [5000, -20],
      'ghost': [1, 1],
    });
    expect((n.x, n.y), (gfViewW - 150, 0));
  });

  test('hub edges are the import edges that touch server, tools, UIUX', () {
    expect(const GfEdge('server', 'x', 'import').isHub, isTrue);
    expect(const GfEdge('x', 'tools', 'import').isHub, isTrue);
    expect(const GfEdge('x', 'y', 'import').isHub, isFalse);
    expect(const GfEdge('server', 'y', 'llm').isHub, isFalse);
  });
}
