import 'package:flutter/animation.dart';
import 'package:flutter/scheduler.dart';

/// Motion for the notification island (island-shape.ts): Sileo's spring, the two CSS curves and a tweener that moves named
/// values to their targets, each with its own curve and duration.

// Sileo's spring (bounce 0.25, 600 ms), the same points as its CSS linear() easing: (progress, time %)
const _springPoints = <(double, double)>[
  (0, 0),
  (0.002, 0.6),
  (0.007, 1.2),
  (0.015, 1.8),
  (0.026, 2.4),
  (0.041, 3.1),
  (0.06, 3.8),
  (0.108, 5.3),
  (0.157, 6.6),
  (0.214, 8),
  (0.467, 13.7),
  (0.577, 16.3),
  (0.631, 17.7),
  (0.682, 19.1),
  (0.73, 20.5),
  (0.771, 21.8),
  (0.808, 23.1),
  (0.844, 24.5),
  (0.874, 25.8),
  (0.903, 27.2),
  (0.928, 28.6),
  (0.952, 30.1),
  (0.972, 31.6),
  (0.988, 33.1),
  (1.01, 35.7),
  (1.025, 38.5),
  (1.034, 41.6),
  (1.038, 45),
  (1.035, 50.1),
  (1.012, 64.2),
  (1.003, 73),
  (0.999, 83.7),
  (1, 100),
];

class _Spring extends Curve {
  const _Spring();
  @override
  double transformInternal(double t) {
    final p = t * 100;
    for (var i = 1; i < _springPoints.length; i++) {
      final (v1, t1) = _springPoints[i];
      if (p <= t1) {
        final (v0, t0) = _springPoints[i - 1];
        return v0 + (v1 - v0) * (p - t0) / (t1 - t0);
      }
    }
    return 1;
  }
}

const Curve spring = _Spring();
const Curve easeOut = Cubic(0.4, 0, 0.2, 1);
const Curve pop = Cubic(0.34, 1.2, 0.64, 1);

class _Tween {
  _Tween(this.from, this.to, this.start, this.ms, this.ease);
  final double from, to;
  final Duration start;
  final int ms;
  final Curve ease;
}

class Tweener {
  Tweener(TickerProvider vsync, Map<String, double> initial, this.onFrame)
    : cur = {...initial} {
    _ticker = vsync.createTicker(_tick);
  }

  /// The current values; read them inside [onFrame] or after.
  final Map<String, double> cur;
  final void Function() onFrame;
  late final Ticker _ticker;
  final _tweens = <String, _Tween>{};
  Duration _now = Duration.zero;

  void _tick(Duration elapsed) {
    _now = elapsed;
    for (final key in _tweens.keys.toList()) {
      final tw = _tweens[key]!;
      final x = tw.ms <= 0
          ? 1.0
          : ((elapsed - tw.start).inMicroseconds / (tw.ms * 1000)).clamp(
              0.0,
              1.0,
            );
      cur[key] = tw.from + (tw.to - tw.from) * tw.ease.transform(x);
      if (x >= 1) {
        cur[key] = tw.to;
        _tweens.remove(key);
      }
    }
    onFrame();
    if (_tweens.isEmpty) _ticker.stop();
  }

  void to(String key, double value, int ms, Curve ease, {int delayMs = 0}) {
    final tw = _tweens[key];
    if (tw != null ? tw.to == value : cur[key] == value) return;
    if (!_ticker.isActive) _now = Duration.zero;
    _tweens[key] = _Tween(
      cur[key]!,
      value,
      _now + Duration(milliseconds: delayMs),
      ms,
      ease,
    );
    if (!_ticker.isActive) _ticker.start();
  }

  /// True while any value is still moving.
  bool get animating => _tweens.isNotEmpty;

  void dispose() => _ticker.dispose();
}
