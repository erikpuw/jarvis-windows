import 'dart:math' as math;
import 'dart:ui';

import 'package:flutter/material.dart';

import '../theme/tokens.dart';

/// Size of the loader's box between `stream_start` and the first text (`.chat-bubble.assistant.typing-loader`: min-width 48,
/// one line of text high).
Size get streamLoaderBox => Size(48, JTokens.bubbleFont * 1.5 + 14);

/// The host's place inside that box while it spins (6px padding, the 22x14 host centred in the content box) and while it
/// collapses (`.stream-bubble-host.collapsing { top: 8px; left: 12px }`).
const streamLoaderSpinAt = Offset(13, 11.25);
const streamLoaderCollapseAt = Offset(12, 8);

/// The loader of an answer (frontend/src/stream-loader.css, "sticky goo metaballs", commit 5402d0e): four blobs circling pinned
/// pivots, goo filter (blur 2.2 + alpha "18 -7"; the web uses 2.8, 2.2 is the user's on-device choice, 2026-10-19) and a slow hue drift. [collapsing]: the first text has arrived - the cluster
/// shrinks to its centre and fades in 300 ms (the blobs keep flying). The widget is the 22x14 host only; the caller places it.
class StreamLoader extends StatefulWidget {
  const StreamLoader({super.key, this.collapsing = false});

  final bool collapsing;

  @override
  State<StreamLoader> createState() => _StreamLoaderState();
}

class _StreamLoaderState extends State<StreamLoader>
    with TickerProviderStateMixin {
  static const _spinS = 2.2;
  static const _driftS = 6.6; // stream-colorize
  late final AnimationController _c = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 6600),
  )..repeat();
  late final AnimationController _collapse = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 300),
  );

  @override
  void didUpdateWidget(StreamLoader old) {
    super.didUpdateWidget(old);
    if (widget.collapsing && !old.collapsing) _collapse.forward();
  }

  @override
  void dispose() {
    _c.dispose();
    _collapse.dispose();
    super.dispose();
  }

  // size, left=top in the 66x66 layer, pivot (css transform-origin), direction, delay seconds, fill
  static const _teal = Color(0xFF00F5D4);
  static const _sky = Color(0xFF38BDF8);
  static const _blobs = [
    (
      16.0,
      11.0,
      Alignment(0, 1.1), // 50% 105%
      -1.0,
      0.0,
      LinearGradient(
        begin: Alignment.topLeft,
        end: Alignment.bottomRight,
        stops: [0.2, 0.8],
        colors: [_teal, _sky],
      ),
    ),
    (
      15.0,
      11.5,
      Alignment(0, -1.1), // 50% -5%
      1.0,
      0.73,
      LinearGradient(
        begin: Alignment.topLeft,
        end: Alignment.bottomRight,
        stops: [0.2, 0.8],
        colors: [_sky, _teal],
      ),
    ),
    (
      13.0,
      12.5,
      Alignment(-1.1, 0), // -5% 50%
      -1.0,
      1.22,
      LinearGradient(colors: [_teal, _teal]),
    ),
    (
      13.0,
      12.5,
      Alignment(1.1, 0), // 105% 50%
      1.0,
      1.46,
      LinearGradient(colors: [_sky, _sky]),
    ),
  ];

  // goo: the blurred layer, then alpha*18 - 7 (css units 0..1; Flutter's matrix offset is 0..255)
  static const _goo = ColorFilter.matrix(<double>[
    1, 0, 0, 0, 0, //
    0, 1, 0, 0, 0,
    0, 0, 1, 0, 0,
    0, 0, 0, 18, -7 * 255,
  ]);

  /// stream-colorize: hue-rotate 0, 35, -25, 45, 0 deg at 0/25/50/75/100%, ease-in-out between the keyframes.
  static double hueDegrees(double p) {
    const keys = [0.0, 35.0, -25.0, 45.0, 0.0];
    final x = (p % 1) * 4;
    final i = x.floor().clamp(0, 3);
    final t = const Cubic(0.42, 0, 0.58, 1).transform(x - i);
    return keys[i] + (keys[i + 1] - keys[i]) * t;
  }

  /// CSS `hue-rotate()` as a colour matrix.
  static ColorFilter hueFilter(double degrees) {
    final a = degrees * math.pi / 180;
    final c = math.cos(a), s = math.sin(a);
    return ColorFilter.matrix(<double>[
      0.213 + c * 0.787 - s * 0.213, 0.715 - c * 0.715 - s * 0.715,
      0.072 - c * 0.072 + s * 0.928, 0, 0, //
      0.213 - c * 0.213 + s * 0.143, 0.715 + c * 0.285 + s * 0.140,
      0.072 - c * 0.072 - s * 0.283, 0, 0, //
      0.213 - c * 0.213 - s * 0.787, 0.715 - c * 0.715 + s * 0.715,
      0.072 + c * 0.928 + s * 0.072, 0, 0, //
      0, 0, 0, 1, 0,
    ]);
  }

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: 22,
      height: 14,
      child: AnimatedBuilder(
        animation: _collapse,
        builder: (context, child) {
          final k = const Cubic(0.45, 0, 0.25, 1).transform(_collapse.value);
          return Opacity(
            opacity: 1 - k,
            child: Transform.scale(
              scale: 0.77 + (0.02 - 0.77) * k,
              child: child,
            ),
          );
        },
        child: OverflowBox(
          alignment: Alignment.topLeft,
          maxWidth: 66,
          maxHeight: 66,
          // the blobs circle the host's centre (11,7), which is (19,19) in the 66px layer
          child: Transform.translate(
            offset: const Offset(-8, -12),
            child: SizedBox(
              width: 66,
              height: 66,
              child: AnimatedBuilder(
                animation: _c,
                builder: (context, _) => ColorFiltered(
                  colorFilter: hueFilter(hueDegrees(_c.value)),
                  child: ColorFiltered(
                    colorFilter: _goo,
                    child: ImageFiltered(
                      imageFilter: ImageFilter.blur(sigmaX: 2.2, sigmaY: 2.2),
                      child: Stack(
                        children: [
                          for (final (size, left, pivot, dir, delay, fill)
                              in _blobs)
                            Positioned(
                              left: left,
                              top: left,
                              child: Transform.rotate(
                                angle:
                                    dir *
                                    2 *
                                    math.pi *
                                    ((_c.value * (_driftS / _spinS) +
                                            delay / _spinS) %
                                        1),
                                alignment: pivot,
                                child: Container(
                                  width: size,
                                  height: size,
                                  decoration: BoxDecoration(
                                    gradient: fill,
                                    borderRadius: BorderRadius.circular(
                                      size * 0.43,
                                    ),
                                  ),
                                ),
                              ),
                            ),
                        ],
                      ),
                    ),
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
