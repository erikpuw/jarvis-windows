import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../theme/tokens.dart';
import 'chat_models.dart';
import 'lucide_glyphs.dart';
import 'morph_icon.dart';

// icons.ts STATUS_ICON + style.css .flow-ring / .flow-completed / .flow-failed / .flow-pending
const _ring = Color(0xFF0EA5E9);
const _completed = Color(0xFF4ADE80);
const _failed = Color(0xFFEF4444);
const _pending = Color(0x26FFFFFF);

/// setStatusIcon (icons.ts): the pill's status glyph - spinner / check / x - kept mounted across updates so a status change
/// morphs in place (a rebuilt glyph would pop). `.flow-status-icon` is 10px, the spinner turns once in 1.2 s.
class StatusGlyph extends StatefulWidget {
  const StatusGlyph({super.key, required this.status, this.size = 10});
  final String status;
  final double size;

  @override
  State<StatusGlyph> createState() => _StatusGlyphState();
}

class _StatusGlyphState extends State<StatusGlyph>
    with SingleTickerProviderStateMixin {
  late final AnimationController _spin = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 1200),
  );

  @override
  void initState() {
    super.initState();
    if (widget.status == 'active') _spin.repeat();
  }

  @override
  void didUpdateWidget(StatusGlyph old) {
    super.didUpdateWidget(old);
    if (widget.status == 'active') {
      if (!_spin.isAnimating) _spin.repeat();
    } else {
      _spin
        ..stop()
        ..value = 0;
    }
  }

  @override
  void dispose() {
    _spin.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final (glyph, color) = switch (widget.status) {
      'active' => (loaderCircleGlyph, _ring),
      'completed' => (checkGlyph, _completed),
      'failed' => (xGlyph, _failed),
      _ => (circleDashedGlyph, _pending),
    };
    return TweenAnimationBuilder<Color?>(
      tween: ColorTween(end: color),
      duration: const Duration(milliseconds: 200), // transition: all .2s
      builder: (context, c, _) => RotationTransition(
        turns: _spin,
        child: MorphIcon(
          icon: glyph,
          color: c ?? color,
          size: widget.size,
          strokeWidth: 2.5,
        ),
      ),
    );
  }
}

/// `.island-step` rows (the timeline): a dot per step with a connector to the next, the step name and its detail after "· ".
class IslandSteps extends StatelessWidget {
  const IslandSteps({super.key, required this.steps, required this.maxHeight});
  final List<FlowStep> steps;
  final double maxHeight;

  @override
  Widget build(BuildContext context) {
    return ConstrainedBox(
      constraints: BoxConstraints(maxHeight: maxHeight),
      child: SingleChildScrollView(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            for (var i = 0; i < steps.length; i++)
              // keyed by step id so a status change patches the row in place (the dot transitions)
              _Row(
                key: ValueKey(steps[i].id),
                step: steps[i],
                last: i == steps.length - 1,
              ),
          ],
        ),
      ),
    );
  }
}

class _Row extends StatelessWidget {
  const _Row({super.key, required this.step, required this.last});
  final FlowStep step;
  final bool last;

  @override
  Widget build(BuildContext context) {
    final (main, detail) = splitStepLabel(step.label);
    final active = step.status == 'active';
    final failed = step.status == 'failed';
    final pending = step.status == 'pending';
    const detailColor = Color(0xB394A3B8); // rgba(148,163,184,.7)
    return ConstrainedBox(
      constraints: const BoxConstraints(minHeight: 24),
      child: IntrinsicHeight(
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            SizedBox(
              width: 16,
              child: Column(
                children: [
                  Padding(
                    padding: const EdgeInsets.only(top: 1),
                    child: StepDot(status: step.status),
                  ),
                  if (!last)
                    Expanded(
                      child: ConstrainedBox(
                        constraints: const BoxConstraints(minHeight: 8),
                        child: Padding(
                          padding: const EdgeInsets.symmetric(vertical: 2),
                          child: AnimatedContainer(
                            key: const ValueKey('island-connector'),
                            duration: const Duration(milliseconds: 300),
                            width: 1.5,
                            decoration: BoxDecoration(
                              borderRadius: BorderRadius.circular(1),
                              color: step.status == 'completed'
                                  ? const Color(0x5910B981)
                                  : const Color(0x3394A3B8),
                            ),
                          ),
                        ),
                      ),
                    ),
                ],
              ),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: Padding(
                padding: EdgeInsets.only(bottom: last ? 0 : 5),
                // name and detail are spans of ONE paragraph: they share the alphabetic baseline (align-items: baseline) and wrap
                child: AnimatedDefaultTextStyle(
                  duration: const Duration(milliseconds: 250),
                  // merged into the inherited style: a bare TextStyle would lose the app font
                  style: DefaultTextStyle.of(context).style.merge(
                    TextStyle(
                      fontSize: JTokens.fsSmall,
                      height: 16 / JTokens.fsSmall,
                      fontWeight: active ? FontWeight.w600 : FontWeight.w500,
                      color: active
                          ? Colors.white
                          : failed
                          ? const Color(0xFFFCA5A5)
                          : pending
                          ? const Color(0xA694A3B8)
                          : const Color(0xE6F1F5F9),
                      shadows: active
                          ? const [
                              Shadow(color: Color(0x5938BDF8), blurRadius: 10),
                            ]
                          : null,
                    ),
                  ),
                  child: Text.rich(
                    TextSpan(
                      children: [
                        TextSpan(text: main),
                        if (detail.isNotEmpty) ...[
                          // gap: 6px (a baseline-aligned placeholder cannot be measured under IntrinsicHeight)
                          const WidgetSpan(child: SizedBox(width: 6)),
                          TextSpan(
                            text: '· ',
                            style: TextStyle(
                              fontSize: JTokens.fsLabel,
                              fontWeight: FontWeight.w400,
                              color: detailColor.withValues(
                                alpha: detailColor.a * 0.6,
                              ),
                              shadows: const [],
                            ),
                          ),
                          TextSpan(
                            text: detail,
                            style: const TextStyle(
                              fontSize: JTokens.fsLabel,
                              fontWeight: FontWeight.w400,
                              color: detailColor,
                              shadows: [],
                            ),
                          ),
                        ],
                      ],
                    ),
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// `.timeline-dot`: 15px circle. Active: a ring whose top arc is lit, spinning, a 5px dot inside. Completed / failed: solid
/// green / red with a white check / cross, popping in (morphicon-pop) when the status arrives.
class StepDot extends StatefulWidget {
  const StepDot({super.key, required this.status});
  final String status;

  @override
  State<StepDot> createState() => _StepDotState();
}

class _StepDotState extends State<StepDot> with TickerProviderStateMixin {
  late final AnimationController _spin = AnimationController(
    vsync: this,
    duration: const Duration(
      milliseconds: 850,
    ), // timeline-spin .85s linear infinite
  );
  late final AnimationController _pop = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 350),
  );
  // morphicon-pop: scale .7 -> 1.18 at 60% -> 1
  static final _popScale = TweenSequence<double>([
    TweenSequenceItem(tween: Tween(begin: 0.7, end: 1.18), weight: 60),
    TweenSequenceItem(tween: Tween(begin: 1.18, end: 1.0), weight: 40),
  ]);

  @override
  void initState() {
    super.initState();
    if (widget.status == 'active') _spin.repeat();
    _pop.value =
        1; // only a completed / failed dot pops in; the others sit at scale 1
    if (_solid(widget.status)) _pop.forward(from: 0);
  }

  @override
  void didUpdateWidget(StepDot old) {
    super.didUpdateWidget(old);
    if (old.status == widget.status) return;
    if (widget.status == 'active') {
      _spin.repeat();
    } else {
      _spin
        ..stop()
        ..value = 0;
    }
    if (_solid(widget.status)) _pop.forward(from: 0);
  }

  @override
  void dispose() {
    _spin.dispose();
    _pop.dispose();
    super.dispose();
  }

  static bool _solid(String s) => s == 'completed' || s == 'failed';

  @override
  Widget build(BuildContext context) {
    final s = widget.status;
    final (bg, border, glow) = switch (s) {
      'active' => (
        const Color(0x990F172A),
        const Color(0x4038BDF8),
        Colors.transparent,
      ),
      'completed' => (
        const Color(0xFF10B981),
        const Color(0xFF10B981),
        const Color(0x5910B981),
      ),
      'failed' => (
        const Color(0xFFEF4444),
        const Color(0xFFEF4444),
        const Color(0x59EF4444),
      ),
      _ => (
        const Color(0xD91E293B),
        const Color(0x5994A3B8),
        Colors.transparent,
      ),
    };
    return ScaleTransition(
      scale: _popScale.animate(_pop),
      child: RotationTransition(
        turns: _spin,
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 300),
          width: 15,
          height: 15,
          decoration: BoxDecoration(
            shape: BoxShape.circle,
            color: bg,
            border: Border.all(color: border, width: 1.5),
            boxShadow: [BoxShadow(color: glow, blurRadius: 8)],
          ),
          child: CustomPaint(painter: _DotPainter(s)),
        ),
      ),
    );
  }
}

class _DotPainter extends CustomPainter {
  _DotPainter(this.status);
  final String status;

  @override
  void paint(Canvas canvas, Size size) {
    final c = size.center(Offset.zero);
    const sky = Color(0xFF38BDF8);
    switch (status) {
      case 'active':
        // border-top-color: the top quarter of the ring (the corners of a circle's border split at 45 degrees)
        canvas.drawArc(
          Rect.fromCircle(center: c, radius: size.width / 2 - 0.75),
          -3 * math.pi / 4,
          math.pi / 2,
          false,
          Paint()
            ..style = PaintingStyle.stroke
            ..strokeWidth = 1.5
            ..color = sky,
        );
        canvas.drawCircle(c, 2.5, Paint()..color = sky);
      case 'completed' || 'failed':
        // the 12x12 svg at 7px, stroke 2.2, round caps and joins
        canvas
          ..save()
          ..translate(c.dx - 3.5, c.dy - 3.5)
          ..scale(7 / 12);
        final p = Path();
        if (status == 'completed') {
          p
            ..moveTo(2.5, 6.2)
            ..relativeLineTo(2.3, 2.3)
            ..lineTo(9.5, 3.5);
        } else {
          p
            ..moveTo(3, 3)
            ..lineTo(9, 9)
            ..moveTo(9, 3)
            ..lineTo(3, 9);
        }
        canvas
          ..drawPath(
            p,
            Paint()
              ..style = PaintingStyle.stroke
              ..strokeWidth = 2.2
              ..strokeCap = StrokeCap.round
              ..strokeJoin = StrokeJoin.round
              ..color = Colors.white,
          )
          ..restore();
    }
  }

  @override
  bool shouldRepaint(_DotPainter old) => old.status != status;
}

/// "Định tuyến → general" → ("Định tuyến", "general"); drops a trailing "..." / "…" (notify-island.ts splitStepLabel).
(String, String) splitStepLabel(String label) {
  final clean = label.replaceAll(RegExp(r'(\.{3}|…)\s*$'), '').trim();
  final i = clean.indexOf('→');
  return i < 0
      ? (clean, '')
      : (clean.substring(0, i).trim(), clean.substring(i + 1).trim());
}
