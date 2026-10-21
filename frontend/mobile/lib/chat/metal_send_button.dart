// The send button of the command bar: a liquid-metal ring (frontend/src/metal-ring.ts, Paper Shaders' liquid metal as a
// FragmentProgram, shaders/liquid_metal.frag) with the metal-fx halo (frontend/src/metal-halo.ts) and the morphing paper plane
// -> check -> paper plane (morph_icon.dart). Licences: THIRD_PARTY_NOTICES.md.
//
// Halo recipe (metal-halo.ts): a short streak along the ring stroked four times (wide -> thin) with a blur each, plus a small hot
// core just outside it; full strength on the ring's outer band, half strength outside the ring, nothing inside the button; the
// halo takes the metal's colour (sampled from the live ring), the core stays white. A 3 s beat: 1 s fading in, 1 s lit, 1 s
// fading out, then a new spot at least 60 degrees away. Not ported (also not in the web): picking the brightest spot.
import 'dart:async';
import 'dart:math' as math;
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/scheduler.dart';

import 'morph_icon.dart';

// metal-fx GLOW_DEFAULTS
const _halo = [
  (stroke: 26.4, blur: 8.4, opacity: 0.385),
  (stroke: 15.6, blur: 4.8, opacity: 0.595),
  (stroke: 7.2, blur: 2.1, opacity: 0.7),
  (stroke: 3.0, blur: 0.9, opacity: 0.7),
];
const _core = [
  (stroke: 4 / 3, blur: 2 / 3, opacity: 0.85),
  (stroke: 2 / 3, blur: 1.35 / 3, opacity: 1.0),
];
const _haloHalfLen = 7.8;
const _coreHalfLen = 9.13952 / 3;
const _coreFadeR = 13 / 3;
const _inset = 1.5; // streak centre this far inside the ring's outer edge
const _coreOutward = 1.0;
const _ringPx = 2.0; // band drawn at full strength
const _refPerim =
    2 * 100 +
    0 +
    2 * math.pi * 20; // metal-fx scales arc lengths to a 140x40 r20 pill
const _haloAlpha = 0.6; // min(1, GLOW_OPACITY * 2) with GLOW_OPACITY 0.3
const _coreAlpha = 0.3;
const _tintFallback = Color(0xFF9BE7FF);
const _beatSeconds = 3.0;
const _recolour = Duration(milliseconds: 400);
const _ease = 0.5;
const _minJump = math.pi / 3;
const _shaderSpeed = 0.5;
const _haloMargin = 60.0;
const _haloBounds = Rect.fromLTRB(
  -_haloMargin,
  -_haloMargin,
  MetalSendButton.size + _haloMargin,
  MetalSendButton.size + _haloMargin,
);

class MetalSendButton extends StatefulWidget {
  const MetalSendButton({
    super.key,
    required this.sent,
    required this.active,
    required this.onTap,
  });

  /// The paper plane is a check for a second after a send (#cmd-send.sent).
  final bool sent;

  /// False while the command bar is hidden: the shader, halo and their loop stop (anim-gate `onBarGate`).
  final bool active;
  final VoidCallback onTap;

  static const size = 34.0; // #cmd-send-wrap on phones

  @override
  State<MetalSendButton> createState() => _MetalSendButtonState();
}

class _MetalSendButtonState extends State<MetalSendButton>
    with SingleTickerProviderStateMixin {
  static const _size = MetalSendButton.size;
  static const _r = _size / 2;
  static final _k = 2 * math.pi * _r / _refPerim;

  ui.FragmentShader? _shader;
  late final Ticker _ticker = createTicker(_tick);
  final _repaint = ValueNotifier<int>(0);
  Duration _last = Duration.zero;
  double _time = 0; // shader seconds (speed 0.5)
  double _beat = 0;
  double _angle = math.Random().nextDouble() * 2 * math.pi;
  Color _tint = _tintFallback;
  Timer? _recolourTimer;
  bool _sampling = false;
  bool _still = false; // reduced motion (metal-halo.ts `still`): no loop, halo held at full opacity
  double _dpr = 3;
  ui.Image? _haloImage; // the halo baked on a beat or a recolour; per frame it is only blitted with the beat's opacity

  @override
  void initState() {
    super.initState();
    unawaited(_load());
    _syncGate();
  }

  Future<void> _load() async {
    try {
      final p = await ui.FragmentProgram.fromAsset('shaders/liquid_metal.frag');
      if (!mounted) return;
      _shader = p.fragmentShader();
      _repaint.value++;
      _recolourTimer = Timer.periodic(_recolour, (_) => _retint());
      _syncGate();
      unawaited(_retint(jump: true));
    } catch (e) {
      debugPrint(
        '[metal] shader unavailable, no ring: $e',
      ); // web: data-metal="off", the button simply has no ring
    }
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    _dpr = MediaQuery.devicePixelRatioOf(context);
    final still = MediaQuery.disableAnimationsOf(context);
    if (still != _still) {
      _still = still;
      _syncGate();
      _repaint.value++;
    }
  }

  @override
  void didUpdateWidget(MetalSendButton old) {
    super.didUpdateWidget(old);
    if (old.active != widget.active) _syncGate();
  }

  /// anim-gate onBarGate: no frames while the bar is hidden.
  void _syncGate() {
    if (_shader == null) return;
    if (widget.active && !_still) {
      if (!_ticker.isActive) {
        _last = Duration.zero;
        _ticker.start();
      }
    } else {
      _ticker.stop();
    }
  }

  void _tick(Duration elapsed) {
    final dt = ((elapsed - _last).inMicroseconds / 1e6).clamp(0.0, 0.1);
    _last = elapsed;
    _time += dt * _shaderSpeed;
    _beat += dt;
    if (_beat >= _beatSeconds) {
      _beat -= _beatSeconds;
      _angle +=
          _minJump + math.Random().nextDouble() * (2 * math.pi - 2 * _minJump);
      _bakeHalo();
      unawaited(
        _retint(jump: true),
      ); // a new spot starts dark, so its colour can jump
    }
    _repaint.value++;
  }

  /// The halo's opacity over one beat: dark, ease in to 1 at 1 s, hold to 2 s, ease out to dark at 3 s.
  double get _envelope {
    if (_still) return 1;
    final t = _beat / _beatSeconds;
    if (t < 0.01) return 0;
    if (t < 0.333) {
      return Curves.easeInOut.transform((t - 0.01) / (0.333 - 0.01));
    }
    if (t < 0.667) return 1;
    return 1 - Curves.easeInOut.transform((t - 0.667) / (1 - 0.667));
  }

  /// metal-halo.ts ringColour: the live metal at the ring's outer band at the spot, normalised to full brightness. The ring is
  /// rendered to an image and a 3 px patch is read back (the web reads its shader canvas).
  Future<void> _retint({bool jump = false}) async {
    final shader = _shader;
    // A frozen loop (hidden bar, Settings or media on top, app in the background) must not keep reading the GPU back.
    if (shader == null ||
        _sampling ||
        (!jump && (!_ticker.isTicking || _envelope < 0.05))) {
      return;
    }
    _sampling = true;
    try {
      const scale = 3.0;
      final rec = ui.PictureRecorder();
      final c = Canvas(rec)..scale(scale);
      _paintRing(c);
      final img = await rec.endRecording().toImage(
        (_size * scale).ceil(),
        (_size * scale).ceil(),
      );
      final data = await img.toByteData();
      final w = img.width;
      img.dispose();
      if (data == null) {
        return;
      }
      final r = (_r - 1) * scale;
      final cx = w / 2 + r * math.cos(_angle),
          cy = w / 2 + r * math.sin(_angle);
      var sr = 0.0, sg = 0.0, sb = 0.0;
      final half = (1.5 * scale).round();
      for (var y = cy.round() - half; y < cy.round() + half; y++) {
        for (var x = cx.round() - half; x < cx.round() + half; x++) {
          if (x < 0 || y < 0 || x >= w || y >= w) continue;
          final o = (y * w + x) * 4;
          sr += data.getUint8(o);
          sg += data.getUint8(o + 1);
          sb += data.getUint8(o + 2);
        }
      }
      final n = (2 * half) * (2 * half) / 9; // the web sums a 3x3 downscale
      sr /= n;
      sg /= n;
      sb /= n;
      final m = math.max(sr, math.max(sg, sb));
      if (m < 24) {
        if (jump) _tint = _tintFallback;
      } else {
        final target = [sr, sg, sb].map((v) => (255 * v / m).round()).toList();
        final cur = [
          _tint.r,
          _tint.g,
          _tint.b,
        ].map((v) => (v * 255).round()).toList();
        final next = jump
            ? target
            : [
                for (var i = 0; i < 3; i++)
                  (cur[i] + (target[i] - cur[i]) * _ease).round(),
              ];
        _tint = Color.fromARGB(255, next[0], next[1], next[2]);
      }
      _bakeHalo();
    } catch (_) {
      // keep the last tint
    } finally {
      _sampling = false;
    }
  }

  /// Records the halo at device-pixel scale into an image covering [_haloBounds].
  void _bakeHalo() {
    if (!mounted) return;
    try {
      final rec = ui.PictureRecorder();
      final c = Canvas(rec)
        ..scale(_dpr)
        ..translate(-_haloBounds.left, -_haloBounds.top);
      _MetalPainter.paintHalo(c, _angle, _tint);
      final img = rec.endRecording().toImageSync(
        (_haloBounds.width * _dpr).ceil(),
        (_haloBounds.height * _dpr).ceil(),
      );
      _haloImage?.dispose();
      _haloImage = img;
      _repaint.value++;
    } catch (e) {
      debugPrint('[metal] halo bake failed: $e');
    }
  }

  void _paintRing(Canvas canvas) {
    final s = _shader;
    if (s == null) return;
    s
      ..setFloat(0, _size)
      ..setFloat(1, _size)
      ..setFloat(2, _time)
      // u_colorBack #0b1220
      ..setFloat(3, 0x0b / 255)
      ..setFloat(4, 0x12 / 255)
      ..setFloat(5, 0x20 / 255)
      ..setFloat(6, 1)
      // u_colorTint #9be7ff
      ..setFloat(7, 0x9b / 255)
      ..setFloat(8, 0xe7 / 255)
      ..setFloat(9, 0xff / 255)
      ..setFloat(10, 1)
      ..setFloat(11, 0.15) // u_softness
      ..setFloat(12, 2) // u_repetition
      ..setFloat(13, 0.35) // u_shiftRed
      ..setFloat(14, 0.35) // u_shiftBlue
      ..setFloat(15, 0.08) // u_distortion
      ..setFloat(16, 0.5) // u_contour
      ..setFloat(17, 70); // u_angle
    canvas.drawRect(
      const Rect.fromLTWH(0, 0, _size, _size),
      Paint()..shader = s,
    );
  }

  @override
  void dispose() {
    _recolourTimer?.cancel();
    _ticker.dispose();
    _haloImage?.dispose();
    _shader?.dispose();
    _repaint.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      behavior: HitTestBehavior.opaque,
      onTap: widget.onTap,
      child: SizedBox.square(
        dimension: _size,
        child: Stack(
          clipBehavior: Clip.none,
          alignment: Alignment.center,
          children: [
            RepaintBoundary(
              child: CustomPaint(
                size: const Size.square(_size),
                painter: _MetalPainter(this, _repaint),
              ),
            ),
            MorphIcon(
              icon: widget.sent ? checkGlyph : sendGlyph,
              color: widget.sent
                  ? const Color(0xFF4ADE80)
                  : const Color(0xFFF0FBFF),
              size: 14,
            ),
          ],
        ),
      ),
    );
  }
}

class _MetalPainter extends CustomPainter {
  _MetalPainter(this.s, Listenable repaint) : super(repaint: repaint);
  final _MetalSendButtonState s;

  static const _r = _MetalSendButtonState._r;
  static const _c = Offset(_r, _r);
  static final _outside = Path.combine(
    PathOperation.difference,
    Path()..addRect(_haloBounds),
    Path()..addOval(Rect.fromCircle(center: _c, radius: _r)),
  );
  static final _band = Path.combine(
    PathOperation.difference,
    Path()..addOval(Rect.fromCircle(center: _c, radius: _r)),
    Path()..addOval(Rect.fromCircle(center: _c, radius: _r - _ringPx)),
  );

  @override
  void paint(Canvas canvas, Size size) {
    if (s._shader == null) return; // no shader: no ring, no halo
    s._paintRing(canvas);
    final env = s._envelope;
    final halo = s._haloImage;
    if (env <= 0 || halo == null) return;
    // the whole glow fades with the beat: one image blit
    canvas.drawImageRect(
      halo,
      Rect.fromLTWH(0, 0, halo.width.toDouble(), halo.height.toDouble()),
      _haloBounds,
      Paint()
        ..color = Color.fromRGBO(255, 255, 255, env)
        ..filterQuality = FilterQuality.low,
    );
  }

  /// The halo for [angle] in [tint], drawn in the button's own coordinates inside [_haloBounds].
  static void paintHalo(Canvas canvas, double angle, Color tint) {
    final bounds = _haloBounds;
    final outside = _outside, band = _band;
    final k = _MetalSendButtonState._k;
    Offset at(double radius) =>
        _c + Offset(math.cos(angle), math.sin(angle)) * radius;

    // halo: coloured from the ring
    canvas.saveLayer(bounds, Paint());
    final hx = at(_r - _inset);
    for (final (clip, mul) in [(outside, 0.5), (band, 1.0)]) {
      canvas
        ..save()
        ..clipPath(clip);
      _streak(
        canvas,
        hx,
        angle + math.pi / 2,
        math.max(1, _haloHalfLen * k),
        _halo,
        _haloAlpha * mul,
        0,
      );
      canvas.restore();
    }
    canvas.drawRect(
      bounds,
      Paint()
        ..color = tint
        ..blendMode = BlendMode.srcIn,
    );
    canvas.restore();

    // core: white, with the radial falloff of metal-fx
    final ex = at(_r - _inset + _coreOutward * k);
    for (final (clip, mul) in [(outside, 0.5), (band, 1.0)]) {
      canvas
        ..save()
        ..clipPath(clip);
      _streak(
        canvas,
        ex,
        angle + math.pi / 2,
        math.max(0.6, _coreHalfLen * k),
        _core,
        _coreAlpha * mul,
        _coreFadeR,
      );
      canvas.restore();
    }
  }

  /// One metal-fx sprite at [p], rotated to [tangent]: the layers stroked wide -> thin, blurred, over each other.
  static void _streak(
    Canvas canvas,
    Offset p,
    double tangent,
    double half,
    List<({double stroke, double blur, double opacity})> layers,
    double alpha,
    double fadeR,
  ) {
    canvas
      ..save()
      ..translate(p.dx, p.dy)
      ..rotate(tangent);
    final box = Rect.fromCircle(center: Offset.zero, radius: half + 40);
    canvas.saveLayer(
      box,
      Paint()..color = Color.fromRGBO(255, 255, 255, alpha),
    );
    if (fadeR > 0) canvas.saveLayer(box, Paint());
    for (final l in layers) {
      canvas.drawLine(
        Offset(-half, 0),
        Offset(half, 0),
        Paint()
          ..color = Color.fromRGBO(255, 255, 255, l.opacity)
          ..strokeWidth = l.stroke
          ..strokeCap = StrokeCap.round
          ..style = PaintingStyle.stroke
          ..maskFilter = MaskFilter.blur(BlurStyle.normal, l.blur),
      );
    }
    if (fadeR > 0) {
      // the hot core falls off with the distance from its centre: 1 to 0.3, 1 -> 0.25 to 0.65, 0.25 -> 0 to 1
      canvas.drawRect(
        box,
        Paint()
          ..blendMode = BlendMode.dstIn
          ..shader = ui.Gradient.radial(
            Offset.zero,
            fadeR,
            const [
              Color(0xFFFFFFFF),
              Color(0xFFFFFFFF),
              Color(0x40FFFFFF),
              Color(0x00FFFFFF),
            ],
            const [0, 0.3, 0.65, 1],
          ),
      );
      canvas.restore();
    }
    canvas
      ..restore()
      ..restore();
  }

  @override
  bool shouldRepaint(_MetalPainter old) => false;
}
