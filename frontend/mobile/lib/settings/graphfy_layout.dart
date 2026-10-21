// Layout rules of the Graphfy map, ported 1:1 from frontend/src/settings/graphfy.ts (lanes, sizes, edge routing).
import 'dart:ui';

const double gfW = 150;
const double gfH = 30;
const double gfRow = 40;
const double gfHead = 34; // lane title height
const double gfViewW = 1160;
const double gfBandGap = 40;
// the LLM hub is drawn as a circuit brain, not a box
const double gfBrainW = 114;
const double gfBrainH = 120;
// the outline sits inside the box: side edges attach where the lobes are widest
const double gfBrainInset = 16;
const double gfBrainSideY = 0.45;

/// Bump when the layout model changes, so positions saved for an old map are dropped (same key as the web).
const String gfPosKey = 'jarvis.graphfy.positions.v4';

class GfLane {
  const GfLane(this.id, this.title, this.color);
  final String id;
  final String title;
  final Color color;
}

const gfLanes = <GfLane>[
  GfLane('input', 'Đầu vào', Color(0xFF38BDF8)),
  GfLane('turn', 'Xử lý lượt', Color(0xFFF59E0B)),
  GfLane('llm', 'LLM', Color(0xFFC084FC)),
  GfLane('output', 'Phản hồi', Color(0xFF4ADE80)),
  GfLane('memory', 'Bộ nhớ · học', Color(0xFFF472B6)),
  GfLane('ingestion', 'Nạp tài liệu', Color(0xFF22D3EE)),
  GfLane('background', 'Chạy nền', Color(0xFF94A3B8)),
  GfLane('support', 'Hỗ trợ', Color(0xFF64748B)),
  GfLane('other', 'Khác (chưa gán làn)', Color(0xFFEAB308)),
];
const _top = ['input', 'turn', 'llm', 'output'];
const _bottom = ['memory', 'ingestion', 'background', 'support', 'other'];

/// Imported by nearly every module: their edges only show with "Hiện tất cả" or while one of their nodes is focused.
const gfHubs = {'server', 'tools', 'UIUX'};

GfLane gfLane(String id) =>
    gfLanes.firstWhere((l) => l.id == id, orElse: () => gfLanes.last);

class GfNode {
  GfNode(this.id, this.label, this.lane, this.x, this.y, this.w, this.h);
  final String id;
  final String label;
  final String lane;
  double x, y;
  final double w, h;

  Rect get rect => Rect.fromLTWH(x, y, w, h);
}

class GfEdge {
  const GfEdge(this.from, this.to, this.kind, [this.idx = 0]);
  final String from;
  final String to;
  final String kind; // import | llm
  final int
  idx; // position in the API list (the pulse timing of the web depends on it)

  bool get isHub =>
      kind == 'import' && (gfHubs.contains(from) || gfHubs.contains(to));
}

class GfTitle {
  const GfTitle(this.lane, this.x, this.y);
  final GfLane lane;
  final double x, y;
}

class GfLayout {
  const GfLayout(this.nodes, this.height, this.titles);
  final List<GfNode> nodes;
  final double height;
  final List<GfTitle> titles;
}

/// The file a node stands for (the web's tooltip).
String gfFileOf(String id) => id == 'server'
    ? 'server.py'
    : id.contains('/')
    ? 'engine/$id.py'
    : 'engine/$id/';

double _round(double v) => (v + 0.5).floorToDouble();

/// [raw] are the API nodes (`{id, label, lane}`).
GfLayout gfLayout(List<Map<String, dynamic>> raw) {
  List<Map<String, dynamic>> byLane(String l) =>
      raw.where((n) => n['lane'] == l).toList();
  var topRows = 1;
  for (final l in _top) {
    if (byLane(l).length > topRows) topRows = byLane(l).length;
  }
  final topH =
      gfHead +
      (topRows * gfRow > gfBrainH + 10 ? topRows * gfRow : gfBrainH + 10);
  final bottomLanes = _bottom.where((l) => byLane(l).isNotEmpty).toList();
  var bottomRows = 0;
  for (final l in bottomLanes) {
    if (byLane(l).length > bottomRows) bottomRows = byLane(l).length;
  }
  final out = <GfNode>[];
  final titles = <GfTitle>[];

  GfNode node(Map<String, dynamic> n, double x, double y, double w, double h) =>
      GfNode(
        '${n['id']}',
        '${n['label'] ?? n['id']}',
        '${n['lane']}',
        x,
        y,
        w,
        h,
      );

  void place(List<String> lanes, double y0, double bandH) {
    final step = gfViewW / lanes.length;
    for (var i = 0; i < lanes.length; i++) {
      final l = lanes[i];
      final x = _round(i * step + (step - gfW) / 2);
      final col = byLane(l);
      titles.add(GfTitle(gfLane(l), x, y0 + 16));
      // the LLM column holds one node: centre it so every caller's edge converges on it
      if (l == 'llm') {
        final bx = x + _round((gfW - gfBrainW) / 2);
        final by =
            y0 + gfHead + _round((bandH - gfHead - col.length * gfBrainH) / 2);
        for (var r = 0; r < col.length; r++) {
          out.add(node(col[r], bx, by + r * gfBrainH, gfBrainW, gfBrainH));
        }
        continue;
      }
      for (var r = 0; r < col.length; r++) {
        out.add(node(col[r], x, y0 + gfHead + r * gfRow, gfW, gfH));
      }
    }
  }

  place(_top, 0, topH);
  if (bottomLanes.isNotEmpty) {
    place(bottomLanes, topH + gfBandGap, gfHead + bottomRows * gfRow);
  }
  final height =
      topH +
      (bottomLanes.isNotEmpty ? gfBandGap + gfHead + bottomRows * gfRow : 0);
  return GfLayout(out, height, titles);
}

/// The cubic Bézier of an edge as [start, control1, control2, end].
List<Offset> gfEdgePoints(GfNode a, GfNode b) {
  if (b.lane == 'llm' && a.y > b.y + b.h) {
    // callers below the brain plug into its signal pins
    final x1 = a.x + a.w / 2, y1 = a.y;
    final x2 = b.x + b.w / 2, y2 = b.y + b.h * 0.92;
    final dy = ((y1 - y2) * 0.5).clamp(40, double.infinity).toDouble();
    return [
      Offset(x1, y1),
      Offset(x1, y1 - dy),
      Offset(x2, y2 + dy),
      Offset(x2, y2),
    ];
  }
  final ac = a.x + a.w / 2, bc = b.x + b.w / 2;
  if ((ac - bc).abs() < gfW) {
    // same column: bow out to the right
    final x1 = a.x + a.w, x2 = b.x + b.w;
    final y1 = a.y + a.h / 2, y2 = b.y + b.h / 2;
    final bow = 30 + ((y2 - y1).abs() / 4).clamp(0, 60);
    return [
      Offset(x1, y1),
      Offset(x1 + bow, y1),
      Offset(x2 + bow, y2),
      Offset(x2, y2),
    ];
  }
  final forward = bc > ac;
  final inA = a.lane == 'llm' ? gfBrainInset : 0.0;
  final inB = b.lane == 'llm' ? gfBrainInset : 0.0;
  final x1 = forward ? a.x + a.w - inA : a.x + inA;
  final x2 = forward ? b.x + inB : b.x + b.w - inB;
  final y1 = a.y + a.h * (inA != 0 ? gfBrainSideY : 0.5);
  final y2 = b.y + b.h * (inB != 0 ? gfBrainSideY : 0.5);
  final dx =
      ((x2 - x1).abs() * 0.5).clamp(40, double.infinity).toDouble() *
      (forward ? 1 : -1);
  return [
    Offset(x1, y1),
    Offset(x1 + dx, y1),
    Offset(x2 - dx, y2),
    Offset(x2, y2),
  ];
}

/// Positions saved by a drag, clamped into the map like the web does.
void gfApplyPositions(
  List<GfNode> nodes,
  double height,
  Map<String, dynamic> saved,
) {
  for (final n in nodes) {
    final pos = saved[n.id];
    if (pos is List && pos.length == 2 && pos[0] is num && pos[1] is num) {
      n.x = (pos[0] as num).toDouble().clamp(0, gfViewW - n.w).toDouble();
      n.y = (pos[1] as num).toDouble().clamp(0, height - n.h).toDouble();
    }
  }
}
