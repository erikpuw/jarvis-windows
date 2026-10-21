import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../theme/tokens.dart';
import 'chat_models.dart';
import 'status_orb.dart';

/// style.css `.status-ghost.status-*` busy colours (idle and speaking stay plain).
Color? _busyColor(JState s) => switch (s) {
  JState.thinking => const Color(0xFF6EC4FF),
  JState.working => const Color(0xFFFFAA00),
  JState.listening => const Color(0xFF4ADE80),
  _ => null,
};

/// The status row above the command bar (index.html #status-row): a small orb and the state label.
/// The label shimmers while busy (status-sheen 2.2s), slides when its text changes, and after 10s of idle it
/// slides away to the left until the next state change or touch (status-label.ts).
class StatusRow extends StatefulWidget {
  const StatusRow({
    super.key,
    required this.state,
    required this.text,
    this.centered = false,
    this.activity,
  });

  final JState state;
  final String text;

  /// The command bar is hidden: the row sits in the middle instead of the left (css `#command-container:not(.visible) #status-row`).
  final bool centered;

  /// Fires on any touch/key: wakes a label that rolled away.
  final Listenable? activity;

  @override
  State<StatusRow> createState() => _StatusRowState();
}

class _StatusRowState extends State<StatusRow> with TickerProviderStateMixin {
  static const _quietAfter = Duration(seconds: 10);
  // mask-reveal-up (status-label.ts): the old text leaves in 200 ms (ease-in, 9 px), the new one starts 90 ms in and
  // settles over 547 ms (ease-out, 12 px)
  static const _outMs = 200.0, _inMs = 547.0, _inDelayMs = 90.0;
  static const _outPx = 9.0, _inPx = 12.0;
  static const _easeOut = Cubic(0.22, 1, 0.36, 1);
  static const _easeIn = Cubic(0.64, 0, 0.78, 0);
  static const _width = Cubic(0.3, 0.7, 0.2, 1);
  late final AnimationController _sheen = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 2200),
  );
  // `transition: all 0.5s cubic-bezier(.16,1,.3,1)` on #status-text: idle <-> busy ink cross-fade
  static const _inkCurve = Cubic(0.16, 1, 0.3, 1);
  late final AnimationController _ink = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 500),
    value: 1,
  );
  late final AnimationController _slide = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 637),
    value: 1,
  );
  // 0 = shown, 1 = rolled away: 0.4 s out, 0.6 s back (style.css `#status-text`)
  late final AnimationController _roll = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 400),
    reverseDuration: const Duration(milliseconds: 600),
  );
  // status-label.ts mountStatusRowFade: 250 ms, the row fades out shrinking to 0.85 where it was, then fades in from 0.85 where it
  // now is. Never a slide: the position flips at the half, when it is invisible.
  late final AnimationController _move = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 250),
    value: 1,
  )..addListener(_moveTick);
  late bool _shownCentered = widget.centered;
  Timer? _quietTimer;
  bool _quiet = false;
  int _dir = 1; // +1 = the new text comes from below, -1 = from above; random on every state change
  ({String text, JState state})? _ghost;
  final _rng = math.Random();

  @override
  void initState() {
    super.initState();
    widget.activity?.addListener(_wake);
    _syncSheen();
    _arm();
  }

  @override
  void didUpdateWidget(StatusRow old) {
    super.didUpdateWidget(old);
    if (old.activity != widget.activity) {
      old.activity?.removeListener(_wake);
      widget.activity?.addListener(_wake);
    }
    if (old.centered != widget.centered) _move.forward(from: 0);
    final stateChanged = old.state != widget.state;
    final wasQuiet = _quiet; // status-label.ts: no slide while the row is quiet
    if ((_busyColor(old.state) == null) != (_busyColor(widget.state) == null)) {
      _ink.forward(from: 0);
    }
    if (stateChanged) {
      _dir = _rng.nextBool() ? 1 : -1;
      _setQuiet(false);
      _syncSheen();
    }
    if (old.text != widget.text && old.text.isNotEmpty && !wasQuiet) {
      _ghost = (text: old.text, state: old.state);
      _slide.forward(from: 0);
    }
    if (stateChanged || old.text != widget.text) _arm();
  }

  void _syncSheen() {
    if (_busyColor(widget.state) != null) {
      _sheen.repeat();
    } else {
      _sheen.stop();
    }
  }

  void _setQuiet(bool q) {
    if (_quiet == q) return;
    _quiet = q;
    q ? _roll.forward() : _roll.reverse();
  }

  /// Only an idle row rolls away; busy states always show what JARVIS is doing.
  void _arm() {
    _quietTimer?.cancel();
    if (widget.state == JState.idle) {
      _quietTimer = Timer(_quietAfter, () {
        if (mounted) _setQuiet(true);
      });
    }
  }

  void _wake() {
    if (mounted) _setQuiet(false);
    _arm();
  }

  @override
  void dispose() {
    widget.activity?.removeListener(_wake);
    _quietTimer?.cancel();
    _sheen.dispose();
    _ink.dispose();
    _slide.dispose();
    _roll.dispose();
    _move.dispose();
    super.dispose();
  }

  void _moveTick() {
    final c = _move.value < 0.5 ? _shownCentered : widget.centered;
    if (c != _shownCentered) setState(() => _shownCentered = c);
  }

  /// One label face (the live text or the leaving ghost); busy states shimmer (status-sheen).
  Widget _face(String text, JState state, {bool live = false, bool crossFade = false}) {
    const base = TextStyle(
      fontSize: JTokens.fsSmall,
      letterSpacing: 0.3,
      fontWeight: FontWeight.normal,
      height: 1.2, // css line-height normal; the theme's 1.5 would not fit the 18 px the row leaves
      color: Color(0xBFB9D4F8),
    );
    final busy = _busyColor(state);
    Text plain(TextStyle style) => Text(
      text,
      maxLines: 1,
      softWrap: false,
      overflow: TextOverflow.clip, // overflow:hidden on #status-text, no fade
      style: style,
    );
    if (busy == null) {
      if (!live || !crossFade) return plain(base);
      // busy -> idle when text doesn't slide: idle ink fades in from transparent
      return AnimatedBuilder(
        animation: _ink,
        builder: (context, _) => Opacity(
          opacity: _inkCurve.transform(_ink.value),
          child: plain(base),
        ),
      );
    }
    // background-clip:text: the glyphs themselves are painted with the gradient (no saveLayer / mask compositing)
    final sheen = SheenText(text: text, style: base, busy: busy, sheen: _sheen);
    if (!live || !crossFade) return sheen;
    // idle -> busy when text doesn't slide: the sheen is there at once, the idle ink fades out over it
    return AnimatedBuilder(
      animation: _ink,
      builder: (context, _) => _ink.value >= 1
          ? sheen
          : Stack(
              children: [
                sheen,
                Opacity(
                  opacity: 1 - _inkCurve.transform(_ink.value),
                  child: plain(base),
                ),
              ],
            ),
    );
  }

  Widget _label() => AnimatedBuilder(
    animation: _slide,
    builder: (context, _) {
      final ms = _slide.value * 637;
      final ghost = _ghost;
      final inP = _easeOut.transform(
        ((ms - _inDelayMs) / _inMs).clamp(0.0, 1.0),
      );
      final outP = _easeIn.transform((ms / _outMs).clamp(0.0, 1.0));
      const pad = EdgeInsets.symmetric(vertical: 3);
      // the label is the mask (overflow:hidden); the ghost is a child of the row and is not clipped
      return Stack(
        clipBehavior: Clip.none,
        children: [
          Opacity(
            opacity: inP,
            child: Transform.translate(
              key: const Key('status-label'),
              offset: Offset(0, _dir * _inPx * (1 - inP)),
              child: Padding(
                padding: pad,
                child: _face(widget.text, widget.state, live: true, crossFade: ghost == null || _slide.value >= 1),
              ),
            ),
          ),
          if (ghost != null && outP < 1)
            Positioned(
              left: 0,
              top: 0,
              child: Opacity(
                opacity: 1 - outP,
                child: Transform.translate(
                  key: const Key('status-ghost'),
                  offset: Offset(0, -_dir * _outPx * outP),
                  child: Padding(
                    padding: pad,
                    child: _face(ghost.text, ghost.state),
                  ),
                ),
              ),
            ),
        ],
      );
    },
  );

  /// The label (with its 6px gap) collapses and rolls to the left: going away width/opacity/x take 0.4 s (x ease-in);
  /// coming back width takes 0.4 s of the 0.6 s, opacity 0.5 s, x the whole 0.6 s (ease-out).
  Widget _rolling(Widget child) => AnimatedBuilder(
    animation: _roll,
    builder: (context, child) {
      final back = _roll.status == AnimationStatus.reverse;
      final shown = 1 - _roll.value;
      final width = _width.transform(
        back ? (shown * 1.5).clamp(0.0, 1.0) : shown,
      );
      final opacity = Curves.ease.transform(
        back ? (shown * 1.2).clamp(0.0, 1.0) : shown,
      );
      final x = (back ? _easeOut : _easeIn).transform(shown);
      return Opacity(
        opacity: opacity,
        child: Transform.translate(
          key: const Key('status-quiet'),
          offset: Offset(-16 * (1 - x), 0),
          // clipped only while it collapses, so the sliding ghost may leave the row's box
          child: ClipRect(
            clipBehavior: shown >= 1 ? Clip.none : Clip.hardEdge,
            child: Align(
              alignment: Alignment.centerLeft,
              widthFactor: width,
              child: child,
            ),
          ),
        ),
      );
    },
    child: child,
  );

  @override
  Widget build(BuildContext context) {
    final row = Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        // #status-orb: a 28x28 box with margin -2px 0 holding the 32 px canvas at its top-left, so the label starts
        // 28 px in and the picture hangs 4 px past the box and 2 px above the row's centre line
        SizedBox(
          width: 28,
          height: 24,
          child: OverflowBox(
            alignment: Alignment.topLeft,
            minWidth: 32,
            maxWidth: 32,
            minHeight: 32,
            maxHeight: 32,
            child: Transform.translate(
              offset: const Offset(0, -2),
              child: RepaintBoundary(child: StatusOrb(state: widget.state)),
            ),
          ),
        ),
        _rolling(
          Padding(
            padding: const EdgeInsets.only(left: 6),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 280),
              child: _label(),
            ),
          ),
        ),
      ],
    );
    return SizedBox(
      height: 24,
      child: Align(
        alignment: _shownCentered ? Alignment.center : Alignment.centerLeft,
        child: AnimatedBuilder(
          animation: _move,
          builder: (_, child) {
            final v = _move.value;
            final p = v < 0.5
                ? Curves.easeIn.transform(v * 2)
                : Curves.easeOut.transform((v - 0.5) * 2);
            final shown = v < 0.5 ? 1 - p : p;
            return Opacity(
              opacity: shown,
              child: Transform.scale(scale: 0.85 + 0.15 * shown, child: child),
            );
          },
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 6),
            child: row,
          ),
        ),
      ),
    );
  }
}

/// The busy label: glyphs painted with `linear-gradient(90deg, st 38%, white .95 50%, st 62%)` on a 250 % wide strip that
/// moves from background-position 100 % to 0 (status-sheen, ease-in-out). The gradient is the glyphs' own paint (a foreground
/// shader in this painter's coordinates), not a mask over a drawn text: nothing is composited, so nothing can wash grey.
class SheenText extends StatelessWidget {
  const SheenText({
    super.key,
    required this.text,
    required this.style,
    required this.busy,
    required this.sheen,
  });

  final String text;
  final TextStyle style;
  final Color busy;
  final Animation<double> sheen;

  @override
  Widget build(BuildContext context) {
    final merged = DefaultTextStyle.of(context).style.merge(style);
    final tp = TextPainter(
      text: TextSpan(text: text, style: merged),
      textDirection: TextDirection.ltr,
      textScaler: MediaQuery.textScalerOf(context),
      maxLines: 1,
    )..layout();
    return CustomPaint(
      size: tp.size,
      painter: _SheenPainter(text, merged, tp, busy, sheen),
    );
  }
}

class _SheenPainter extends CustomPainter {
  _SheenPainter(this.text, this.style, this.tp, this.busy, this.sheen)
    : super(repaint: sheen);

  final String text;
  final TextStyle style;
  final TextPainter tp;
  final Color busy;
  final Animation<double> sheen;

  @override
  void paint(Canvas canvas, Size size) {
    final e = Curves.easeInOut.transform(sheen.value);
    final strip = Rect.fromLTWH(
      -1.5 * size.width * (1 - e),
      0,
      2.5 * size.width,
      size.height,
    );
    final ink = Paint()
      ..shader = LinearGradient(
        colors: [busy, busy, const Color(0xF2FFFFFF), busy, busy],
        stops: const [0, 0.38, 0.5, 0.62, 1],
      ).createShader(strip);
    tp.text = TextSpan(
      text: text,
      // a TextStyle cannot drop its colour once merged with the theme's, so it is rebuilt without one
      style: TextStyle(
        inherit: false,
        fontFamily: style.fontFamily,
        fontFamilyFallback: style.fontFamilyFallback,
        fontSize: style.fontSize,
        fontWeight: style.fontWeight,
        letterSpacing: style.letterSpacing,
        height: style.height,
        foreground: ink,
      ),
    );
    tp.layout();
    tp.paint(canvas, Offset.zero);
  }

  @override
  bool shouldRepaint(_SheenPainter old) =>
      old.text != text || old.busy != busy || old.style != style;
}
