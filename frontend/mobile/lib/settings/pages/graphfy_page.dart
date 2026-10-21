import 'dart:convert';
import 'dart:math' as math;
import 'dart:ui' show MaskFilter, BlurStyle, PathMetric, PointMode;

import 'package:flutter/material.dart';
import 'package:flutter/scheduler.dart' show Ticker;
import 'package:jarvis_mobile/net/api_client.dart';
import 'package:jarvis_mobile/settings/graphfy_layout.dart';
import 'package:jarvis_mobile/settings/mem_widgets.dart';
import 'package:jarvis_mobile/settings/page_scaffold.dart';
import 'package:jarvis_mobile/settings/pages.dart';
import 'package:jarvis_mobile/settings/sd_widgets.dart';
import 'package:jarvis_mobile/theme/tokens.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

const double _mapW =
    gfViewW + 20; // web viewBox: -10 -6 (VIEW_W+20) (height+12)
const double _mapPadH = 12;
const double _initialScale =
    0.76; // web: .gf-map min-width 900px for the 1180px viewBox
const double _maxScale = 2.5;

/// Bản đồ mã (pages.ts graphfyPage + graphfy.ts): the structure map from /api/graphfy as a pannable, zoomable canvas with
/// draggable nodes (positions in shared_preferences under the web's key), the hub-edge toggle and the default-layout reset.
class GraphfyPage extends StatefulWidget {
  const GraphfyPage({super.key});

  @override
  State<GraphfyPage> createState() => _GraphfyPageState();
}

class _GraphfyPageState extends State<GraphfyPage> {
  late final ApiClient _api = context.read<ApiClient>();
  GraphfyModel? _model;
  String? _error;
  bool _showAll = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final res = await _api.get<Map<String, dynamic>>('/api/graphfy');
      final prefs = await SharedPreferences.getInstance();
      var saved = <String, dynamic>{};
      try {
        final raw = jsonDecode(prefs.getString(gfPosKey) ?? '{}');
        if (raw is Map<String, dynamic>) saved = raw;
      } catch (_) {}
      if (!mounted) return;
      setState(() {
        _model = GraphfyModel(_maps(res['nodes']), _maps(res['edges']), saved)
          ..showAll = _showAll;
        _error = null;
      });
    } catch (e) {
      if (mounted) setState(() => _error = '$e');
    }
  }

  List<Map<String, dynamic>> _maps(Object? v) => v is List
      ? [
          for (final x in v)
            if (x is Map<String, dynamic>) x,
        ]
      : const [];

  Future<void> _reset() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(gfPosKey);
    if (!mounted) return;
    final m = _model;
    if (m == null) return;
    setState(() => _model = m.reset()..showAll = _showAll);
  }

  void _toggleAll() => setState(() {
    _showAll = !_showAll;
    _model?.showAll = _showAll;
    _model?.touch();
  });

  Future<void> _savePositions() async {
    final m = _model;
    if (m == null) return;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(
      gfPosKey,
      jsonEncode({
        for (final n in m.nodes) n.id: [n.x, n.y],
      }),
    );
  }

  Widget _legend(Color c, String text) => Row(
    mainAxisSize: MainAxisSize.min,
    children: [
      Container(
        width: 18,
        height: 3,
        decoration: BoxDecoration(
          color: c,
          borderRadius: BorderRadius.circular(2),
        ),
      ),
      const SizedBox(width: 6),
      Flexible(
        child: Text(
          text,
          style: const TextStyle(
            fontSize: JTokens.fsSmall,
            color: JTokens.muted,
          ),
        ),
      ),
    ],
  );

  Widget _toolbar() => Wrap(
    spacing: 16,
    runSpacing: 8,
    crossAxisAlignment: WrapCrossAlignment.center,
    children: [
      _legend(gfLane('input').color, 'Import giữa module (màu theo làn nguồn)'),
      _legend(gfLane('llm').color, 'Gọi LLM'),
      const Text(
        'Tự sinh từ code · đường tới server, tools, UIUX ẩn bớt · chạm một module để xem đường và file · kéo thả để sắp xếp',
        style: TextStyle(fontSize: JTokens.fsSmall, color: JTokens.muted),
      ),
      MemButton(
        key: const Key('gf-all'),
        label: _showAll ? 'Ẩn bớt' : 'Hiện tất cả',
        onPressed: _toggleAll,
      ),
      MemButton(
        key: const Key('gf-reset'),
        label: 'Bố cục mặc định',
        onPressed: _reset,
      ),
    ],
  );

  Widget _body() {
    if (_error != null) {
      return Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16),
        child: SdEmpty('Không dựng được sơ đồ: $_error'),
      );
    }
    final m = _model;
    if (m == null) {
      return const Padding(
        padding: EdgeInsets.symmetric(horizontal: 16),
        child: SdEmpty('Đang dựng sơ đồ…'),
      );
    }
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
      child: Container(
        decoration: BoxDecoration(
          color: JTokens.surface,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: JTokens.border),
        ),
        clipBehavior: Clip.antiAlias,
        child: GraphfyMap(model: m, onDragEnd: _savePositions),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final page = settingsPages.firstWhere((p) => p.id == 'graphfy');
    return PageScaffold(
      page: page,
      toolbar: _toolbar(),
      scrollable: false,
      body: _body(),
    );
  }
}

/// Everything the painter draws: nodes (moved by drag), their edge paths (rebuilt only for the edges of a moved node), the
/// focused node (web: hover) and the view transform. Listenable, so only the canvas repaints on change.
class GraphfyModel extends ChangeNotifier {
  GraphfyModel(this._rawNodes, this._rawEdges, Map<String, dynamic> saved) {
    final lay = gfLayout(_rawNodes);
    nodes = lay.nodes;
    height = lay.height;
    titles = lay.titles;
    gfApplyPositions(nodes, height, saved);
    byId = {for (final n in nodes) n.id: n};
    edges = [
      for (final (idx, e) in _rawEdges.indexed)
        if (byId.containsKey(e['from']) && byId.containsKey(e['to']))
          GfEdge('${e['from']}', '${e['to']}', '${e['kind']}', idx),
    ];
    paths = [for (final e in edges) _pathOf(e)];
    _metrics = List.filled(edges.length, null);
    dots = _grid();
  }

  final List<Map<String, dynamic>> _rawNodes;
  final List<Map<String, dynamic>> _rawEdges;
  late List<GfNode> nodes;
  late double height;
  late List<GfTitle> titles;
  late Map<String, GfNode> byId;
  late List<GfEdge> edges;
  late List<Path> paths;
  late List<PathMetric?> _metrics;
  late List<Offset> dots;
  bool showAll = false;

  String? _focus;
  Set<String> _near = const {};
  double scale = _initialScale;
  Offset offset = Offset.zero;
  Size viewport = Size.zero;
  bool _placed = false;

  String? get focus => _focus;

  /// A fresh map with the default layout (the web re-renders without the saved positions).
  GraphfyModel reset() => GraphfyModel(_rawNodes, _rawEdges, const {});

  void touch() => notifyListeners();

  Path _pathOf(GfEdge e) {
    final p = gfEdgePoints(byId[e.from]!, byId[e.to]!);
    return Path()
      ..moveTo(p[0].dx, p[0].dy)
      ..cubicTo(p[1].dx, p[1].dy, p[2].dx, p[2].dy, p[3].dx, p[3].dy);
  }

  List<Offset> _grid() => [
    for (var y = 1.0; y <= height + 6; y += 24)
      for (var x = 1.0; x <= gfViewW + 10; x += 24) Offset(x, y),
  ];

  /// Is edge [i] drawn: hub edges only with "Hiện tất cả" or while one of their nodes is focused.
  bool shown(int i) {
    final e = edges[i];
    if (!e.isHub) return true;
    return showAll || (_focus != null && (e.from == _focus || e.to == _focus));
  }

  /// Length table of edge [i] for the LLM pulses, rebuilt lazily after the edge moved.
  PathMetric? metric(int i) =>
      _metrics[i] ??= paths[i].computeMetrics().firstOrNull;

  bool incident(int i) => edges[i].from == _focus || edges[i].to == _focus;

  bool nodeDim(GfNode n) => _focus != null && !_near.contains(n.id);

  void setFocus(String? id) {
    if (id == _focus) return;
    _focus = id;
    _near = id == null
        ? const {}
        : {
            id,
            for (final e in edges)
              if (e.from == id || e.to == id) ...[e.from, e.to],
          };
    notifyListeners();
  }

  void moveNode(GfNode n, double x, double y) {
    n.x = x.clamp(0, gfViewW - n.w).toDouble();
    n.y = y.clamp(0, height - n.h).toDouble();
    for (var i = 0; i < edges.length; i++) {
      if (edges[i].from == n.id || edges[i].to == n.id) {
        paths[i] = _pathOf(edges[i]);
        _metrics[i] = null;
      }
    }
    notifyListeners();
  }

  // --- view transform: screen = offset + (point + (10, 6)) * scale ---

  Offset sceneToScreen(Offset p) => offset + (p + const Offset(10, 6)) * scale;

  Offset screenToScene(Offset s) => (s - offset) / scale - const Offset(10, 6);

  GfNode? hit(Offset screen) {
    final p = screenToScene(screen);
    for (final n in nodes.reversed) {
      if (n.rect.inflate(4).contains(p)) return n;
    }
    return null;
  }

  double get _minScale => math.min(
    viewport.width / _mapW,
    (viewport.height - _mapPadH) / (height + _mapPadH),
  );

  /// First layout pass: the web's 900px-wide map, left/top aligned (xMidYMin).
  void fit(Size size) {
    if (size == viewport) return;
    viewport = size;
    if (!_placed) {
      _placed = true;
      scale = math.max(_initialScale, _minScale);
      offset = Offset.zero;
    }
    zoomTo(scale, Offset.zero, offset);
  }

  /// Scale to [s] keeping the scene point that sat under [anchor] (at [from] offset/scale) still.
  void zoomTo(double s, Offset anchor, Offset from, {double? fromScale}) {
    final s0 = fromScale ?? scale;
    final next = s.clamp(math.min(_minScale, _initialScale), _maxScale);
    final scenePt = (anchor - from) / s0;
    scale = next.toDouble();
    offset = _clamp(anchor - scenePt * scale);
    notifyListeners();
  }

  void panTo(Offset o) {
    offset = _clamp(o);
    notifyListeners();
  }

  Offset _clamp(Offset o) {
    // xMidYMin: content narrower than the view is centred across, stuck to the top
    double axis(double v, double view, double content, bool mid) =>
        content <= view
        ? (mid ? (view - content) / 2 : 0.0)
        : v.clamp(view - content, 0.0).toDouble();
    return Offset(
      axis(o.dx, viewport.width, _mapW * scale, true),
      axis(o.dy, viewport.height, (height + _mapPadH) * scale, false),
    );
  }
}

class GraphfyMap extends StatefulWidget {
  const GraphfyMap({super.key, required this.model, required this.onDragEnd});

  final GraphfyModel model;
  final VoidCallback onDragEnd;

  @override
  State<GraphfyMap> createState() => _GraphfyMapState();
}

class _GraphfyMapState extends State<GraphfyMap>
    with SingleTickerProviderStateMixin {
  final _clock = GfClock();
  late final Ticker _ticker = createTicker(
    (d) => _clock.tick(d.inMicroseconds / 1e6),
  );
  GfNode? _drag;
  Offset _grab = Offset.zero;
  Offset _startOffset = Offset.zero;
  double _startScale = 1;
  Offset _startFocal = Offset.zero;

  GraphfyModel get _m => widget.model;

  TextStyle _base(BuildContext context) =>
      Theme.of(context).textTheme.bodyMedium ?? const TextStyle();

  // the ticker is muted by TickerMode (page hidden) and stopped for reduced motion (web: prefers-reduced-motion)
  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final still = MediaQuery.disableAnimationsOf(context);
    _clock.setAnimate(!still);
    // only the LLM lane (brain, pulses along its edges) moves: a map without it needs no frames
    final moves =
        _m.nodes.any((n) => n.lane == 'llm') ||
        _m.edges.any((e) => e.kind == 'llm');
    if (still || !moves) {
      if (_ticker.isActive) _ticker.stop();
    } else if (!_ticker.isActive) {
      _ticker.start();
    }
  }

  @override
  void dispose() {
    _ticker.dispose();
    _clock.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, c) {
        final size = Size(c.maxWidth, c.maxHeight);
        // placed after this frame: the model is a Listenable, notifying inside build is not allowed
        WidgetsBinding.instance.addPostFrameCallback((_) {
          if (mounted) _m.fit(size);
        });
        return GestureDetector(
          behavior: HitTestBehavior.opaque,
          onTapUp: (d) => _m.setFocus(_m.hit(d.localPosition)?.id),
          onScaleStart: (d) {
            _startOffset = _m.offset;
            _startScale = _m.scale;
            _startFocal = d.localFocalPoint;
            final n = d.pointerCount == 1 ? _m.hit(d.localFocalPoint) : null;
            _drag = n;
            if (n != null) {
              _grab = _m.screenToScene(d.localFocalPoint) - Offset(n.x, n.y);
              _m.setFocus(n.id);
            }
          },
          onScaleUpdate: (d) {
            final n = _drag;
            if (n != null) {
              final p = _m.screenToScene(d.localFocalPoint) - _grab;
              _m.moveNode(n, p.dx, p.dy);
            } else if (d.pointerCount > 1) {
              _m.zoomTo(
                _startScale * d.scale,
                d.localFocalPoint,
                _startOffset + (d.localFocalPoint - _startFocal),
                fromScale: _startScale,
              );
            } else {
              _m.panTo(_startOffset + (d.localFocalPoint - _startFocal));
            }
          },
          onScaleEnd: (_) {
            if (_drag != null) widget.onDragEnd();
            _drag = null;
          },
          child: SizedBox(
            width: size.width,
            height: size.height,
            // the still layer repaints only when the model changes; the clock repaints just the moving parts above it
            child: Stack(
              children: [
                RepaintBoundary(
                  child: CustomPaint(
                    painter: GraphfyPainter(
                      _m,
                      _clock,
                      _base(context),
                      live: false,
                    ),
                    size: size,
                  ),
                ),
                CustomPaint(
                  key: const Key('gf-map'),
                  painter: GraphfyPainter(
                    _m,
                    _clock,
                    _base(context),
                    live: true,
                  ),
                  size: size,
                ),
              ],
            ),
          ),
        );
      },
    );
  }
}

/// One map in two layers: [live] false draws everything that only changes with the model, [live] true the LLM pulses and the
/// brain, which also change with the clock.
class GraphfyPainter extends CustomPainter {
  GraphfyPainter(this.model, this.clock, this.base, {required this.live})
    : super(repaint: live ? Listenable.merge([model, clock]) : model);

  final bool live;

  final GfClock clock;

  final TextStyle base;

  final GraphfyModel model;

  static final _pulseDot = Paint();
  static final _pulseGlow = Paint()
    ..maskFilter = const MaskFilter.blur(BlurStyle.normal, 2);
  static const _violet = Color(0xFFA78BFA);
  static const _padFill = Color(0xFF05070B);
  static final _grid = Paint()
    ..color = const Color(0x1F94A3B8)
    ..strokeWidth = 2
    ..strokeCap = StrokeCap.round;
  static final _brainOutline = [
    _svgPath(
      'M96 18 C82 10 66 14 60 26 C44 24 34 40 38 54 C24 60 22 80 32 90 C22 100 26 122 40 126 C40 142 56 152 70 146 C76 158 92 158 96 150 Z',
    ),
    _svgPath(
      'M52 42 C60 46 62 58 56 64 M40 76 C52 74 62 80 62 92 M44 108 C54 104 66 108 68 120 M76 28 C80 40 74 48 80 58 M82 72 C74 80 78 92 88 94 M78 114 C86 120 84 132 76 136',
    ),
    _svgPath(
      'M104 18 C118 10 134 14 140 26 C156 24 166 40 162 54 C176 60 178 80 168 90 C178 100 174 122 160 126 C160 142 144 152 130 146 C124 158 108 158 104 150 Z',
    ),
    _svgPath(
      'M104 34 H122 V28 M104 56 H132 M104 76 H116 V68 H140 M104 96 H150 M104 116 H124 V126 H142 M104 136 H118',
    ),
  ];
  static final _brainStem = _svgPath(
    'M90 152 V170 M100 152 V180 M110 152 V170',
  );
  static final _brainTraces = [
    for (final d in const [
      "M104 34 H122 V28",
      "M104 56 H132",
      "M104 76 H116 V68 H140",
      "M104 96 H150",
      "M104 116 H124 V126 H142",
    ])
      _svgPath(d).computeMetrics().first,
  ];
  static final _stemTrace = _svgPath("M100 180 V152").computeMetrics().first;
  static const _pads = <(double, double)>[
    (122, 24),
    (136, 56),
    (144, 68),
    (154, 96),
    (146, 126),
    (122, 136),
  ];

  // text layouts survive repaints; rebuilt when the dim state of the labels changes
  final Map<String, TextPainter> _labels = {};
  final Map<String, TextPainter> _titles = {};
  String? _labelFocus;

  TextPainter _text(String s, TextStyle style) => TextPainter(
    text: TextSpan(text: s, style: base.merge(style)),
    textDirection: TextDirection.ltr,
    maxLines: 1,
  )..layout();

  @override
  void paint(Canvas canvas, Size size) {
    final m = model;
    canvas.save();
    canvas.translate(m.offset.dx + 10 * m.scale, m.offset.dy + 6 * m.scale);
    canvas.scale(m.scale);

    if (live) {
      _paintPulses(canvas, m);
      for (final n in m.nodes) {
        if (n.lane == 'llm') _paintBrain(canvas, n, m);
      }
      canvas.restore();
      return;
    }

    canvas.drawPoints(PointMode.points, m.dots, _grid);

    for (final t in m.titles) {
      final tp = _titles.putIfAbsent(
        t.lane.id,
        () => _text(
          t.lane.title,
          TextStyle(
            fontSize: JTokens.fsSmall,
            fontWeight: FontWeight.w600,
            letterSpacing: 0.3,
            color: t.lane.color,
          ),
        ),
      );
      tp.paint(
        canvas,
        Offset(
          t.x,
          t.y +
              16 -
              tp.computeDistanceToActualBaseline(TextBaseline.alphabetic),
        ),
      );
    }

    _paintEdges(canvas, m);
    if (_labelFocus != m.focus) {
      _labels.clear();
      _labelFocus = m.focus;
    }
    for (final n in m.nodes) {
      if (n.lane != 'llm') _paintNode(canvas, n, m);
    }
    canvas.restore();
  }

  void _paintEdges(Canvas canvas, GraphfyModel m) {
    final focused = m.focus != null;
    final line = Paint()
      ..style = PaintingStyle.stroke
      ..strokeCap = StrokeCap.butt;
    for (var i = 0; i < m.edges.length; i++) {
      if (!m.shown(i)) continue;
      final e = m.edges[i];
      final a = m.byId[e.from]!, b = m.byId[e.to]!;
      final support = a.lane == 'support' || b.lane == 'support';
      final inc = focused && m.incident(i);
      // .gf-link (group): support 0.3, dimmed 0.08; .gf-edge: 0.08 import / 0.4 llm, 0.9 for the lit ones
      final group = focused && !inc ? 0.08 : (support ? 0.3 : 1.0);
      final edge = inc ? 0.9 : (e.kind == 'llm' ? 0.4 : 0.08);
      line
        ..color = (e.kind == 'llm' ? gfLane('llm').color : gfLane(a.lane).color)
            .withValues(alpha: group * edge)
        ..strokeWidth = inc ? 1.6 : 1.2;
      canvas.drawPath(m.paths[i], line);
    }
  }

  /// The simulated flow along the LLM edges.
  void _paintPulses(Canvas canvas, GraphfyModel m) {
    if (!clock.animate) return;
    final focused = m.focus != null;
    for (var i = 0; i < m.edges.length; i++) {
      final e = m.edges[i];
      if (e.kind != 'llm' || !m.shown(i)) continue;
      final a = m.byId[e.from]!, b = m.byId[e.to]!;
      final support = a.lane == 'support' || b.lane == 'support';
      final inc = focused && m.incident(i);
      final group = focused && !inc ? 0.08 : (support ? 0.3 : 1.0);
      // simulated flow: dur 2.8 + (i % 7) * 0.4 s, begin = -(i * 0.37 % dur) so each pulse starts mid-flight
      final mt = m.metric(i);
      if (mt != null) {
        final dur = 2.8 + (e.idx % 7) * 0.4;
        final f = ((clock.t + (e.idx * 0.37) % dur) % dur) / dur;
        final pos = mt.getTangentForOffset(mt.length * f)?.position;
        if (pos != null) {
          final c = gfLane('llm').color.withValues(alpha: group);
          canvas.drawCircle(pos, 2.4, _pulseGlow..color = c);
          canvas.drawCircle(pos, 2.4, _pulseDot..color = c);
        }
      }
    }
  }

  void _paintNode(Canvas canvas, GfNode n, GraphfyModel m) {
    final c = gfLane(n.lane).color;
    final op = m.nodeDim(n) ? 0.08 : 1.0;
    final box = RRect.fromRectAndRadius(n.rect, const Radius.circular(7));
    canvas.drawRRect(
      box,
      Paint()..color = JTokens.surface.withValues(alpha: op),
    );
    canvas.drawRRect(
      box,
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 1
        ..color = c.withValues(alpha: (m.focus == n.id ? 1.0 : 0.45) * op),
    );
    canvas.drawRRect(
      RRect.fromRectAndRadius(
        Rect.fromLTWH(n.x, n.y + 6, 3, gfH - 12),
        const Radius.circular(1.5),
      ),
      Paint()..color = c.withValues(alpha: op),
    );
    final label = n.label.length > 19
        ? '${n.label.substring(0, 18)}…'
        : n.label;
    final tp = _labels.putIfAbsent(
      n.id,
      () => _text(
        label,
        TextStyle(
          fontSize: JTokens.fsSmall,
          fontWeight: FontWeight.w500,
          color: JTokens.text.withValues(alpha: op),
        ),
      ),
    );
    // baseline at y + H/2 + 4.5 like the SVG text
    tp.paint(
      canvas,
      Offset(
        n.x + 12,
        n.y +
            gfH / 2 +
            4.5 -
            tp.computeDistanceToActualBaseline(TextBaseline.alphabetic),
      ),
    );
  }

  // CSS keyframes `50% {x}` with ease-in-out per half; before a positive delay nothing moves
  static double _blink(double t, double delay, double period) {
    if (t < delay) return 0;
    final p = ((t - delay) / period) % 1;
    return Curves.easeInOut.transform(p < 0.5 ? p * 2 : (1 - p) * 2);
  }

  /// stroke-dasharray `dash gap` marching along [mt] (stroke-dashoffset 0 -> -period over one cycle).
  void _dashes(
    Canvas canvas,
    PathMetric mt,
    double phase,
    double period,
    double dash,
    Paint paint,
  ) {
    for (var d = phase * period - period; d < mt.length; d += period) {
      final a = math.max(0.0, d), b = math.min(mt.length, d + dash);
      if (b <= a) continue;
      canvas.drawLine(
        mt.getTangentForOffset(a)!.position,
        mt.getTangentForOffset(b)!.position,
        paint,
      );
    }
  }

  /// The circuit brain (190x200 artwork squeezed to 90% width and scaled to the node box): outline lines, traces with the
  /// flowing dashes (gf-brain-flow 1.4s, 0.3s stagger), blinking pads (gf-brain-blink 2.4s, 0.4s stagger), breathing aura
  /// (gf-brain-glow 3s). The outline/trace strokes are non-scaling like the web's vector-effect (screen px).
  void _paintBrain(Canvas canvas, GfNode n, GraphfyModel m) {
    final op = m.nodeDim(n) ? 0.08 : 1.0;
    final t = clock.animate ? clock.t : 0.0;
    final s = gfBrainH / 200;
    final px = 1 / (m.scale * s); // one screen pixel in artwork units
    final line = Paint()
      ..style = PaintingStyle.stroke
      ..strokeCap = StrokeCap.round
      ..strokeJoin = StrokeJoin.round
      ..color = (m.focus == n.id ? const Color(0xFFC4B5FD) : _violet)
          .withValues(alpha: op);
    canvas.save();
    canvas.translate(n.x, n.y);
    canvas.scale(s);
    canvas.translate(-(100 - (gfBrainW / s) / 2), 0);
    canvas.drawOval(
      Rect.fromCenter(center: const Offset(100, 86), width: 132, height: 160),
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 6
        ..color = _violet.withValues(
          alpha: (0.18 + 0.42 * _blink(t, 0, 3)) * op,
        ),
    );
    canvas.save();
    canvas.translate(100, 0);
    canvas.scale(0.9, 1);
    canvas.translate(-100, 0);
    line.strokeWidth = 2.4 * px;
    for (final p in _brainOutline) {
      canvas.drawPath(p, line);
    }
    final trace = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.6 * px
      ..color = const Color(0xFFF5F3FF).withValues(alpha: op);
    for (var i = 0; i < _brainTraces.length; i++) {
      final delay = i * 0.3;
      final phase = t < delay ? 0.0 : ((t - delay) / 1.4) % 1;
      _dashes(canvas, _brainTraces[i], phase, 20 * px, 2 * px, trace);
    }
    canvas.restore();
    line.strokeWidth = 2.4;
    canvas.drawPath(_brainStem, line);
    trace.strokeWidth = 1.6;
    _dashes(canvas, _stemTrace, (t / 1.4) % 1, 20, 2, trace);
    final padStroke = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 2.4
      ..color = _violet.withValues(alpha: op);
    final padFill = Paint();
    for (var i = 0; i < _pads.length; i++) {
      final (x, y) = _pads[i];
      final c = Offset(100 + (x - 100) * 0.9, y);
      padFill.color = Color.lerp(
        _padFill,
        const Color(0xFFE9D5FF),
        _blink(t, i * 0.4, 2.4),
      )!.withValues(alpha: op);
      canvas.drawCircle(c, 5, padFill);
      canvas.drawCircle(c, 5, padStroke);
    }
    padFill.color = _padFill.withValues(alpha: op);
    for (final c in const [
      Offset(90, 174),
      Offset(100, 184),
      Offset(110, 174),
    ]) {
      canvas.drawCircle(c, 4, padFill);
      canvas.drawCircle(c, 4, padStroke);
    }
    canvas.restore();
  }

  @override
  bool shouldRepaint(GraphfyPainter old) =>
      old.model != model || old.clock != clock || old.live != live;
}

/// Minimal SVG path reader: absolute M / C / H / V / Z, the only commands the brain artwork uses.
Path _svgPath(String d) {
  final path = Path();
  final tokens = RegExp(r'[MCHVZ]|-?\d+(?:\.\d+)?')
      .allMatches(d)
      .map((m) => m.group(0)!)
      .toList();
  var i = 0;
  double num_() => double.parse(tokens[i++]);
  var x = 0.0, y = 0.0;
  while (i < tokens.length) {
    final cmd = tokens[i++];
    switch (cmd) {
      case 'M':
        x = num_();
        y = num_();
        path.moveTo(x, y);
      case 'C':
        final x1 = num_(), y1 = num_(), x2 = num_(), y2 = num_();
        x = num_();
        y = num_();
        path.cubicTo(x1, y1, x2, y2, x, y);
      case 'H':
        x = num_();
        path.lineTo(x, y);
      case 'V':
        y = num_();
        path.lineTo(x, y);
      case 'Z':
        path.close();
    }
  }
  return path;
}

/// Seconds since the map started animating; the painter repaints on every change. `animate` false = reduced motion
/// (web: pulses hidden, brain animations off).
class GfClock extends ChangeNotifier {
  double t = 0;
  bool animate = true;

  void tick(double seconds) {
    t = seconds;
    notifyListeners();
  }

  void setAnimate(bool v) {
    if (v == animate) return;
    animate = v;
    notifyListeners();
  }
}
