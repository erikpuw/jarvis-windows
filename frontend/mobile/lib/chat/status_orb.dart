// The status orb of the command hub: a Dart port of the thinking-orbs engine (MIT, (c) 2026 Jakub Antalik, https://github.com/Jakubantalik/Libraries.dev; see THIRD_PARTY_NOTICES.md)
// frames used by JARVIS (orbits, wave, web, rubik, ribbon at size 32) and of frontend/src/status-orb.ts: the JARVIS state picks an
// orb state and speed, a state change morphs the dots over 700 ms (easeInOutCubic, paired by angle rank, spare dots fade by
// alpha, lines cross-fade). Not ported: the modes JARVIS never selects (globe, braid, ring, morph) and the 20/64 presets.
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter/scheduler.dart';

import 'chat_models.dart';

class OrbDot {
  OrbDot(this.x, this.y, this.z, this.r, this.white, [this.a]);
  double x, y, z, r, white;
  double? a;
}

class OrbLine {
  OrbLine(this.x1, this.y1, this.x2, this.y2, this.white, this.a, this.w);
  final double x1, y1, x2, y2, white, a, w;
  OrbLine withAlpha(double alpha) => OrbLine(x1, y1, x2, y2, white, alpha, w);
}

class OrbFrame {
  OrbFrame(this.dots, this.lines);
  final List<OrbDot> dots;
  final List<OrbLine> lines;
}

typedef _Opts = Map<String, double>;
typedef _Proj = (double, double, double) Function(double, double, double);

double _lerp(double a, double b, double f) => a + (b - a) * f;
double _frac(double x) => x - x.floorToDouble();

double _hashD(double a, double b) {
  final h = math.sin(a * 12.9898 + b * 78.233) * 43758.5453;
  return h - h.floorToDouble();
}

double _vnoise(double x, double y) {
  final xi = x.floorToDouble(), yi = y.floorToDouble();
  var fx = x - xi, fy = y - yi;
  fx = fx * fx * (3 - 2 * fx);
  fy = fy * fy * (3 - 2 * fy);
  final a = _hashD(xi, yi), b = _hashD(xi + 1, yi);
  final c = _hashD(xi, yi + 1), d = _hashD(xi + 1, yi + 1);
  return a + (b - a) * fx + (c - a) * fy + (a - b - c + d) * fx * fy;
}

(double, double, double) _fibDir(int i, int n) {
  final golden = math.pi * (3 - math.sqrt(5));
  final y = 1 - 2 * (i + 0.5) / n;
  final rad = math.sqrt(1 - y * y);
  final a = i * golden;
  return (rad * math.cos(a), y, rad * math.sin(a));
}

_Proj _makeProj(double yaw, double tilt, double cx, double cy, double scale) {
  final st = math.sin(tilt), ct = math.cos(tilt);
  final sy = math.sin(yaw), cyw = math.cos(yaw);
  return (x, y, z) {
    final x1 = x * cyw + z * sy;
    final z1 = -x * sy + z * cyw;
    final y1 = y * ct - z1 * st;
    final z2 = y * st + z1 * ct;
    return (cx + x1 * scale, cy - y1 * scale, z2);
  };
}

double _radiusScale(double size, double pow) =>
    math.pow(size / 300, pow).toDouble();

/// engine finalizeFrame: drop invisible dots, enforce the minimum radius, paint far to near.
OrbFrame _finalize(
  List<OrbDot> dots,
  List<OrbLine> lines, [
  double rMin = 0.3,
]) {
  final visible = <OrbDot>[];
  for (final d in dots) {
    if ((d.a ?? 1) < 0.02) continue;
    d.r = math.max(rMin, d.r);
    visible.add(d);
  }
  final order = {for (var i = 0; i < visible.length; i++) visible[i]: i};
  visible.sort((a, b) {
    final c = a.z.compareTo(b.z);
    return c != 0 ? c : order[a]!.compareTo(order[b]!); // JS sort is stable
  });
  return OrbFrame(visible, [
    for (final l in lines)
      if (l.a >= 0.02) l,
  ]);
}

// ---------------------------------------------------------------- frames

OrbFrame _frameOrbits(double size, double t, _Opts o) {
  final cx = size / 2, cy = size / 2, r = size / 2 * 0.82;
  final pt = _makeProj(t * 0.12, 0.3, cx, cy, 1);
  final rs = _radiusScale(size, o['rsPow'] ?? 0.6);
  final dots = <OrbDot>[];
  final orbitN = (o['orbitN'] ?? 12).round();
  final ghostN = (o['ghostN'] ?? 40).round();
  final particles = (o['particles'] ?? 3).round();
  for (var orb = 0; orb < orbitN; orb++) {
    final h1 = _hashD(orb.toDouble(), 1.7);
    final h2 = _hashD(orb.toDouble(), 5.2);
    final h3 = _hashD(orb.toDouble(), 8.9);
    final ro = r * (0.45 + 0.52 * h1);
    final th = h1 * 2 * math.pi;
    final phi = math.acos(2 * h2 - 1);
    final nx = math.sin(phi) * math.cos(th);
    final ny = math.cos(phi);
    final nz = math.sin(phi) * math.sin(th);
    var ux = -ny, uy = nx;
    const uz = 0.0;
    final ul = math.max(1e-6, math.sqrt(ux * ux + uy * uy));
    ux /= ul;
    uy /= ul;
    final vx = ny * uz - nz * uy;
    final vy = nz * ux - nx * uz;
    final vz = nx * uy - ny * ux;
    final speed = (0.25 + 0.55 * h3) * (h3 > 0.5 ? 1 : -1);
    (double, double, double) onOrbit(double a) => pt(
      (ux * math.cos(a) + vx * math.sin(a)) * ro,
      (uy * math.cos(a) + vy * math.sin(a)) * ro,
      (uz * math.cos(a) + vz * math.sin(a)) * ro,
    );
    for (var k = 0; k < ghostN; k++) {
      final (px, py, z) = onOrbit(k / ghostN * 2 * math.pi);
      final depth = (z / ro + 1) / 2;
      dots.add(
        OrbDot(
          px,
          py,
          z,
          (o['ghostR'] ?? 0.9) * rs,
          0.72,
          (o['ghostA'] ?? 0.5) * (0.4 + 0.6 * depth),
        ),
      );
    }
    for (var m = 0; m < particles; m++) {
      final a = t * speed + m / particles * 2 * math.pi + h2 * 6;
      final (px, py, z) = onOrbit(a);
      final depth = (z / ro + 1) / 2;
      dots.add(
        OrbDot(
          px,
          py,
          z,
          ((o['partR'] ?? 1.2) + (o['partRDepth'] ?? 1.6) * depth) * rs,
          0.3 - 0.22 * depth,
        ),
      );
    }
  }
  return _finalize(dots, [], o['rMin'] ?? 0.3);
}

OrbFrame _frameWave(double size, double t, _Opts o) {
  final cx = size / 2, cy = size / 2, r = size / 2 * 0.874;
  final pt = _makeProj(t * 0.18, 0.38, cx, cy, 1);
  final rs = _radiusScale(size, o['rsPow'] ?? 0.6);
  final dots = <OrbDot>[];
  final rings = (o['rings'] ?? 15).round();
  final lonDensity = (o['lonDensity'] ?? 40).round();
  for (var ri = 0; ri <= rings; ri++) {
    final lat = -math.pi / 2 + ri / rings * math.pi;
    final cosLat = math.cos(lat), sinLat = math.sin(lat);
    final w =
        0.62 * math.sin(t * 2.1 - ri * 0.52) +
        0.38 * math.sin(t * 1.27 + ri * 0.83);
    final rr = r * (0.88 + 0.105 * w);
    final lonCount = math.max(1, (cosLat.abs() * lonDensity).round());
    for (var lj = 0; lj < lonCount; lj++) {
      final lon = lj / lonCount * 2 * math.pi;
      final (px, py, z) = pt(
        cosLat * math.cos(lon) * rr,
        sinLat * rr,
        cosLat * math.sin(lon) * rr,
      );
      final depth = (z / r + 1) / 2;
      final crest = math.max(0.0, w);
      dots.add(
        OrbDot(
          px,
          py,
          z,
          ((o['rBase'] ?? 0.6) + (o['rDepth'] ?? 1.7) * depth) *
              (1 + 0.4 * crest) *
              rs,
          0.66 - 0.56 * depth - 0.1 * crest,
        ),
      );
    }
  }
  return _finalize(dots, [], o['rMin'] ?? 0.3);
}

OrbFrame _frameWeb(double size, double t, _Opts o) {
  final cx = size / 2, cy = size / 2;
  final r = size / 2 * 0.8 * (o['spread'] ?? 1);
  final pt = _makeProj(t * 0.12, 0.32, cx, cy, r);
  final rs = _radiusScale(size, o['rsPow'] ?? 0.6);
  final nodeN = (o['nodeN'] ?? 30).round();
  final thr = o['thr'] ?? 0.72;
  final nodeR = o['nodeR'] ?? 1.4;
  final nodeRDepth = o['nodeRDepth'] ?? 1.8;
  final nodes = <(double, double, double)>[];
  for (var i = 0; i < nodeN; i++) {
    final d = _fibDir(i, nodeN);
    final x = d.$1 + 0.3 * (_vnoise(i * 0.31 + 9, t * 0.24) - 0.5) * 2;
    final y = d.$2 + 0.3 * (_vnoise(i * 0.53 + 27, t * 0.21) - 0.5) * 2;
    final z = d.$3 + 0.3 * (_vnoise(i * 0.77 + 55, t * 0.27) - 0.5) * 2;
    final l = math.sqrt(x * x + y * y + z * z);
    nodes.add((x / l, y / l, z / l));
  }
  final lines = <OrbLine>[];
  final dots = <OrbDot>[];
  for (var i = 0; i < nodeN; i++) {
    for (var j = i + 1; j < nodeN; j++) {
      final dx = nodes[i].$1 - nodes[j].$1;
      final dy = nodes[i].$2 - nodes[j].$2;
      final dz = nodes[i].$3 - nodes[j].$3;
      final dist = math.sqrt(dx * dx + dy * dy + dz * dz);
      if (dist >= thr) continue;
      final (x1, y1, z1) = pt(nodes[i].$1, nodes[i].$2, nodes[i].$3);
      final (x2, y2, z2) = pt(nodes[j].$1, nodes[j].$2, nodes[j].$3);
      final depth = ((z1 + z2) / 2 + 1) / 2;
      lines.add(
        OrbLine(
          x1,
          y1,
          x2,
          y2,
          0.42,
          (1 - dist / thr) * (0.3 + 0.55 * depth),
          math.max(0.6, (o['lineW'] ?? 0.8) * rs),
        ),
      );
    }
  }
  for (var i = 0; i < nodeN; i++) {
    final (px, py, z) = pt(nodes[i].$1, nodes[i].$2, nodes[i].$3);
    final depth = (z + 1) / 2;
    final pulse = 1 + 0.25 * math.sin(t * 1.4 + i * 2.7);
    dots.add(
      OrbDot(
        px,
        py,
        z,
        (nodeR + nodeRDepth * depth) * pulse * rs,
        0.55 - 0.45 * depth,
      ),
    );
  }
  final signals = (o['signals'] ?? 5).round();
  for (var s = 0; s < signals; s++) {
    final seg = (t * 0.55 + s * 7.31).floorToDouble();
    final a = (_hashD(seg, s * 3.1 + 1.7) * nodeN).floor();
    final b = (_hashD(seg, s * 5.7 + 4.2) * nodeN).floor();
    if (a == b) continue;
    final f = _frac(t * 0.55 + s * 7.31);
    final x = _lerp(nodes[a].$1, nodes[b].$1, f);
    final y = _lerp(nodes[a].$2, nodes[b].$2, f);
    final z = _lerp(nodes[a].$3, nodes[b].$3, f);
    final l = math.max(1e-6, math.sqrt(x * x + y * y + z * z));
    final (px, py, zr) = pt(x / l, y / l, z / l);
    final depth = (zr + 1) / 2;
    dots.add(
      OrbDot(
        px,
        py,
        zr,
        (nodeR * 1.5 + nodeRDepth * depth) * rs,
        0.05,
        0.5 + 0.5 * depth,
      ),
    );
  }
  return _finalize(dots, lines, o['rMin'] ?? 0.3);
}

class _Move {
  _Move(this.axis, this.lo, this.hi, this.ang);
  final int axis;
  final double lo, hi, ang;
}

List<_Move> _makeMoves(int count) => [
  for (var i = 0; i < count; i++)
    () {
      final axis = math.min(2, (_hashD(i.toDouble(), 2.3) * 3).floor());
      final lo =
          -1 + 0.5 * math.min(3, (_hashD(i.toDouble(), 5.9) * 4).floor());
      final dir = _hashD(i.toDouble(), 7.7) < 0.5 ? 1 : -1;
      return _Move(axis, lo, lo + 0.5, dir * math.pi / 2);
    }(),
];

({List<double> amount, int active}) _solveCycle(
  double time,
  int count,
  double slotDur,
  double rest,
) {
  final cyc = 2 * count * slotDur + rest;
  final tc = time % cyc;
  final amount = List<double>.filled(count, 0);
  var active = -1;
  if (tc < 2 * count * slotDur) {
    final slot = (tc / slotDur).floor();
    final p = (tc - slot * slotDur) / slotDur;
    final cl = math.min(1.0, p / 0.7);
    final ep = 1 - math.pow(1 - cl, 3);
    if (slot < count) {
      for (var i = 0; i < slot; i++) {
        amount[i] = 1;
      }
      amount[slot] = ep.toDouble();
      active = slot;
    } else {
      final u = 2 * count - 1 - slot;
      for (var i = 0; i < u; i++) {
        amount[i] = 1;
      }
      amount[u] = 1 - ep.toDouble();
      active = u;
    }
  }
  return (amount: amount, active: active);
}

(double, double, double, bool) _applyMoves(
  (double, double, double) p3,
  List<_Move> moves,
  ({List<double> amount, int active}) sc,
) {
  var (x, y, z) = p3;
  var inActive = false;
  for (var i = 0; i < moves.length; i++) {
    if (sc.amount[i] <= 0) continue;
    final mv = moves[i];
    final coord = mv.axis == 0 ? x : (mv.axis == 1 ? y : z);
    if (coord < mv.lo || coord >= mv.hi) continue;
    if (i == sc.active) inActive = true;
    final a = mv.ang * sc.amount[i];
    final ca = math.cos(a), sa = math.sin(a);
    if (mv.axis == 0) {
      final y2 = y * ca - z * sa;
      z = y * sa + z * ca;
      y = y2;
    } else if (mv.axis == 1) {
      final x2 = x * ca + z * sa;
      z = -x * sa + z * ca;
      x = x2;
    } else {
      final x2 = x * ca - y * sa;
      y = x * sa + y * ca;
      x = x2;
    }
  }
  return (x, y, z, inActive);
}

OrbFrame _frameRubik(double size, double t, _Opts o) {
  final cx = size / 2, cy = size / 2, r = size / 2 * 0.82;
  final pt = _makeProj(t * 0.55, 0.35 + 0.1 * math.sin(t * 0.9), cx, cy, r);
  final rs = _radiusScale(size, o['rsPow'] ?? 0.6);
  final moveCount = (o['moveCount'] ?? 14).round();
  final moves = _makeMoves(moveCount);
  final sc = _solveCycle(t, moveCount, 0.42, 1.2);
  final dots = <OrbDot>[];
  final latRings = (o['latRings'] ?? 15).round();
  final lonDensity = (o['lonDensity'] ?? 40).round();
  for (var li = 0; li <= latRings; li++) {
    final lat = -math.pi / 2 + li / latRings * math.pi;
    final cosLat = math.cos(lat), sinLat = math.sin(lat);
    final lonCount = math.max(1, (cosLat.abs() * lonDensity).round());
    for (var lj = 0; lj < lonCount; lj++) {
      final lon = lj / lonCount * 2 * math.pi;
      final (x, y, z, inActive) = _applyMoves(
        (cosLat * math.cos(lon), sinLat, cosLat * math.sin(lon)),
        moves,
        sc,
      );
      final (px, py, zr) = pt(x, y, z);
      final depth = (zr + 1) / 2;
      dots.add(
        OrbDot(
          px,
          py,
          zr,
          ((o['rBase'] ?? 0.6) +
                  (o['rDepth'] ?? 1.7) * depth +
                  (inActive ? (o['rActive'] ?? 0.3) : 0)) *
              rs,
          (o['inkFar'] ?? 0.62) -
              (o['inkSpan'] ?? 0.54) * depth -
              (inActive ? 0.14 : 0),
        ),
      );
    }
  }
  return _finalize(dots, [], o['rMin'] ?? 0.3);
}

OrbFrame _frameRibbon(double size, double t, _Opts o) {
  final cx = size / 2, cy = size / 2, r = size / 2 * 0.78;
  final spin = o['spin'] ?? 1;
  const camTilt = 0.3;
  final pt = _makeProj(t * 0.1 * spin, camTilt, cx, cy, 1);
  final rs = _radiusScale(size, o['rsPow'] ?? 0.6);
  final dots = <OrbDot>[];
  final ghostN = (o['ghostN'] ?? 150).round();
  for (var i = 0; i < ghostN; i++) {
    final d = _fibDir(i, ghostN);
    final (px, py, z) = pt(d.$1 * r, d.$2 * r, d.$3 * r);
    final depth = (z / r + 1) / 2;
    dots.add(OrbDot(px, py, z, 0.8 * rs, 0.78, 0.1 + 0.22 * depth));
  }
  final ya = t * 0.24 * spin;
  final faceOn = (o['faceOn'] ?? 0) != 0;
  final ta = faceOn ? -camTilt : 0.55 + 0.3 * math.sin(t * 0.18) * spin;
  final ux = math.cos(ya);
  const uy = 0.0;
  final uz = math.sin(ya);
  final vx = -uz * math.sin(ta);
  final vy = math.cos(ta);
  final vz = ux * math.sin(ta);
  final nx = uy * vz - uz * vy;
  final ny = uz * vx - ux * vz;
  final nz = ux * vy - uy * vx;
  final wobMul = o['wobMul'] ?? 1;
  final wobAmp = 0.23 * wobMul;
  final baseR = faceOn ? r / (1 + 0.85 * wobAmp) : r;
  final baseLanes = o['lanes'] ?? 5;
  final segs = (o['segs'] ?? 88).round();
  final lanes = math.max(1, (baseLanes * (o['bandMul'] ?? 1)).round());
  for (var w = 0; w < lanes; w++) {
    final laneOff = (w - (lanes - 1) / 2) * 0.075;
    final edge = (w - (lanes - 1) / 2).abs() / math.max(1, (lanes - 1) / 2);
    for (var k = 0; k < segs; k++) {
      final a = k / segs * 2 * math.pi;
      final wob =
          (0.16 * math.sin(a * 3 - t * 1.7 + w * 0.22) +
              0.07 * math.sin(a * 5 + t * 1.1)) *
          wobMul;
      final radial = faceOn ? 1 + wob : 1.0;
      final off = faceOn ? laneOff : laneOff + wob;
      final x = ux * math.cos(a) + vx * math.sin(a) + nx * off;
      final y = uy * math.cos(a) + vy * math.sin(a) + ny * off;
      final z = uz * math.cos(a) + vz * math.sin(a) + nz * off;
      final l = math.sqrt(x * x + y * y + z * z);
      final rr = baseR * radial;
      final (px, py, zr) = pt(x / l * rr, y / l * rr, z / l * rr);
      final depth = (zr / r + 1) / 2;
      dots.add(
        OrbDot(
          px,
          py,
          zr,
          ((o['rBase'] ?? 1.1) + (o['rDepth'] ?? 1.7) * depth) *
              (1 - 0.25 * edge) *
              rs,
          0.52 - 0.44 * depth + 0.18 * edge,
          0.4 + 0.6 * depth,
        ),
      );
    }
  }
  return _finalize(dots, [], o['rMin'] ?? 0.3);
}

// -------------------------------------------------------------- presets

const _base = <String, _Opts>{
  'orbits': {
    'orbitN': 12,
    'ghostN': 40,
    'ghostR': 0.9,
    'ghostA': 0.5,
    'particles': 3,
    'partR': 1.2,
    'partRDepth': 1.6,
    'rsPow': 0.6,
    'rMin': 0.3,
  },
  'rubik': {
    'latRings': 15,
    'lonDensity': 40,
    'moveCount': 14,
    'rBase': 0.6,
    'rDepth': 1.7,
    'rActive': 0.3,
    'inkFar': 0.62,
    'inkSpan': 0.54,
    'rsPow': 0.6,
    'rMin': 0.3,
  },
  'wave': {
    'rings': 15,
    'lonDensity': 40,
    'rBase': 0.6,
    'rDepth': 1.7,
    'rsPow': 0.6,
    'rMin': 0.3,
  },
  'web': {
    'nodeN': 30,
    'thr': 0.72,
    'signals': 5,
    'nodeR': 1.4,
    'nodeRDepth': 1.8,
    'lineW': 0.8,
    'rsPow': 0.6,
    'rMin': 0.3,
  },
  'ribbon': {
    'lanes': 5,
    'segs': 88,
    'ghostN': 150,
    'rBase': 1.1,
    'rDepth': 1.7,
    'rsPow': 0.6,
    'rMin': 0.3,
  },
};

/// thinking-orbs PRESETS at size 32: speed, count scale, radius scale, extra options.
const _presets32 =
    <String, ({double speed, double count, double size, _Opts extra})>{
      'orbits': (speed: 2.9072, count: 0.4251, size: 1.6849, extra: {}),
      'rubik': (speed: 1.8964, count: 0.1537, size: 1.4951, extra: {}),
      'wave': (speed: 4.1512, count: 0.169, size: 1.3232, extra: {}),
      'web': (speed: 5.0104, count: 0.4942, size: 1.2571, extra: {}),
      'ribbon': (
        speed: 2.7776,
        count: 0.0969,
        size: 0.9766,
        extra: {'spin': 0, 'bandMul': 4.49, 'wobMul': 1},
      ),
    };

const _countPairs = [
  ['latRings', 'lonDensity'],
  ['rings', 'lonDensity'],
  ['lanes', 'segs'],
];
const _countKeys = ['orbitN', 'ghostN', 'nodeN', 'strandN', 'signals'];
const _radiusKeys = [
  'rBase',
  'rDepth',
  'rActive',
  'rDot',
  'ghostR',
  'partR',
  'partRDepth',
  'nodeR',
  'nodeRDepth',
];

_Opts _scaleCounts(_Opts opts, double scale) {
  final out = {...opts};
  final done = <String>{};
  final rt = math.sqrt(scale);
  for (final [a, b] in _countPairs) {
    final va = out[a], vb = out[b];
    if (va != null && vb != null && !done.contains(a) && !done.contains(b)) {
      out[a] = math.max(2, (va * rt).round()).toDouble();
      out[b] = math.max(2, (vb * rt).round()).toDouble();
      done
        ..add(a)
        ..add(b);
    }
  }
  for (final k in _countKeys) {
    final v = out[k];
    if (v != null && v != 0 && !done.contains(k)) {
      out[k] = math.max(1, (v * scale).round()).toDouble();
    }
  }
  return out;
}

_Opts _scaleRadii(_Opts opts, double scale) {
  final out = {...opts};
  for (final k in _radiusKeys) {
    final v = out[k];
    if (v != null) out[k] = v * scale;
  }
  out['rSizeMul'] = (out['rSizeMul'] ?? 1) * scale;
  return out;
}

typedef OrbPreset = ({String mode, double speed, _Opts opts});

/// thinking-orbs resolvePreset(state, 32) for the five orb states JARVIS uses.
OrbPreset resolvePreset(String mode) {
  final p = _presets32[mode]!;
  var opts = {..._base[mode]!};
  if (p.count != 1) opts = _scaleCounts(opts, p.count);
  if (p.size != 1) opts = _scaleRadii(opts, p.size);
  opts = {...opts, ...p.extra};
  return (mode: mode, speed: p.speed, opts: opts);
}

OrbFrame orbFrame(OrbPreset p, double size, double t) => switch (p.mode) {
  'orbits' => _frameOrbits(size, t, p.opts),
  'rubik' => _frameRubik(size, t, p.opts),
  'wave' => _frameWave(size, t, p.opts),
  'web' => _frameWeb(size, t, p.opts),
  _ => _frameRibbon(size, t, p.opts),
};

/// status-orb.ts MAP: JARVIS state -> orb mode and speed (idle keeps a slow orb so the hub never looks dead).
({String mode, double speed}) orbFor(JState s) => switch (s) {
  JState.idle => (mode: 'orbits', speed: 0.6),
  JState.listening => (mode: 'wave', speed: 1),
  JState.thinking => (mode: 'web', speed: 1),
  JState.working => (mode: 'rubik', speed: 1),
  JState.speaking => (mode: 'ribbon', speed: 1),
};

// --------------------------------------------------------------- morph

double _ease(double k) =>
    k < 0.5 ? 4 * k * k * k : 1 - math.pow(-2 * k + 2, 3) / 2; // easeInOutCubic

/// status-orb.ts blendFrames: mid-way frame between two orb frames. Dots are ranked by angle round the centre and paired by
/// rank; when the counts differ the spare dots fade in/out in place; lines cross-fade.
OrbFrame blendFrames(OrbFrame a, OrbFrame b, double k, double size) {
  final c = size / 2;
  List<OrbDot> byAngle(OrbFrame f) => [...f.dots]
    ..sort(
      (p, q) =>
          math.atan2(p.y - c, p.x - c).compareTo(math.atan2(q.y - c, q.x - c)),
    );
  final aa = byAngle(a), bb = byAngle(b);
  final n = math.max(aa.length, bb.length);
  final seenA = <int>{}, seenB = <int>{};
  ({OrbDot d, bool real})? pick(List<OrbDot> s, int i, Set<int> seen) {
    if (s.isEmpty) return null;
    final j = math.min(s.length - 1, (i * s.length / n).floor());
    final real = !seen.contains(
      j,
    ); // a repeated pick is a spare copy: it starts/ends invisible
    seen.add(j);
    return (d: s[j], real: real);
  }

  final dots = <OrbDot>[];
  for (var i = 0; i < n; i++) {
    final pa = pick(aa, i, seenA), pb = pick(bb, i, seenB);
    final da = (pa ?? pb)!.d, db = (pb ?? pa)!.d;
    dots.add(
      OrbDot(
        _lerp(da.x, db.x, k),
        _lerp(da.y, db.y, k),
        _lerp(da.z, db.z, k),
        _lerp(da.r, db.r, k),
        _lerp(da.white, db.white, k),
        _lerp(
          pa?.real == true ? (da.a ?? 1) : 0,
          pb?.real == true ? (db.a ?? 1) : 0,
          k,
        ),
      ),
    );
  }
  final lines = [
    for (final l in a.lines) l.withAlpha(l.a * (1 - k)),
    for (final l in b.lines) l.withAlpha(l.a * k),
  ];
  return _finalize(dots, lines);
}

// -------------------------------------------------------------- widget

const _drawSize =
    32.0; // hand-tuned scale 32; the canvas is shown a little smaller
const _showPx = 32.0;
const _morphMs = 700;

/// status-orb.ts mountStatusOrb. [paused] is the anim gate (app in the background): the loop stops, the picture stays.
class StatusOrb extends StatefulWidget {
  const StatusOrb({super.key, required this.state});
  final JState state;

  @override
  State<StatusOrb> createState() => _StatusOrbState();
}

class _StatusOrbState extends State<StatusOrb>
    with SingleTickerProviderStateMixin {
  late final Ticker _ticker = createTicker(_draw);
  final _repaint = ValueNotifier<int>(0);
  var _cur = orbFor(JState.idle);
  late var _preset = resolvePreset(_cur.mode);
  double _t = 1.5;
  Duration _last = Duration.zero;
  OrbFrame? _from;
  Duration _morphStart = Duration.zero;
  OrbFrame? shown;

  @override
  void initState() {
    super.initState();
    _set(widget.state, now: Duration.zero);
    shown = orbFrame(_preset, _drawSize, _t * _preset.speed * _cur.speed);
    _ticker.start();
  }

  void _set(JState s, {required Duration now}) {
    final next = orbFor(s);
    // morph from whatever is on screen right now, even mid-morph, so quick changes stay continuous
    if (shown != null && next.mode != _cur.mode) {
      _from = shown;
      _morphStart = now;
      _morphPending = true;
    }
    _cur = next;
    _preset = resolvePreset(_cur.mode);
  }

  bool _morphPending = false;

  @override
  void didUpdateWidget(StatusOrb old) {
    super.didUpdateWidget(old);
    if (old.state != widget.state) {
      _set(widget.state, now: _last);
      if (_still) _showStill();
    }
  }

  // status-orb.ts `still`: with reduced motion the orb is one static frame, no loop.
  bool _still = false;

  void _showStill() {
    _from = null;
    _morphPending = false;
    shown = orbFrame(_preset, _drawSize, _t * _preset.speed * _cur.speed);
    _repaint.value++;
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final still = MediaQuery.disableAnimationsOf(context);
    if (still == _still) return;
    _still = still;
    if (still) {
      _ticker.stop();
      _showStill();
    } else {
      _last = Duration.zero;
      _ticker.start();
    }
  }

  void _draw(Duration now) {
    final dt = ((now - _last).inMicroseconds / 1000).clamp(0.0, 100.0);
    _last = now;
    _t += dt / 1000;
    if (_morphPending) {
      _morphStart = now;
      _morphPending = false;
    }
    var frame = orbFrame(_preset, _drawSize, _t * _preset.speed * _cur.speed);
    final from = _from;
    if (from != null) {
      final k = (now - _morphStart).inMicroseconds / 1000 / _morphMs;
      if (k >= 1) {
        _from = null;
      } else {
        frame = blendFrames(from, frame, _ease(k), _drawSize);
      }
    }
    shown = frame;
    _repaint.value++;
  }

  @override
  void dispose() {
    _ticker.dispose();
    _repaint.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => SizedBox.square(
    dimension: _showPx,
    child: CustomPaint(painter: _OrbPainter(this, _repaint)),
  );
}

class _OrbPainter extends CustomPainter {
  _OrbPainter(this.s, Listenable repaint) : super(repaint: repaint);
  final _StatusOrbState s;

  @override
  void paint(Canvas canvas, Size size) {
    final f = s.shown;
    if (f == null) return;
    canvas.scale(size.width / _drawSize);
    Color ink(double white, double alpha) {
      final w = white.clamp(0.0, 1.0);
      final g = ((1 - w) * 255).round(); // paintFrame(ctx, frame, dark = true)
      return Color.fromRGBO(g, g, g, alpha);
    }

    for (final l in f.lines) {
      canvas.drawLine(
        Offset(l.x1, l.y1),
        Offset(l.x2, l.y2),
        Paint()
          ..color = ink(l.white, l.a)
          ..strokeWidth = l.w
          ..style = PaintingStyle.stroke,
      );
    }
    for (final d in f.dots) {
      canvas.drawCircle(
        Offset(d.x, d.y),
        d.r,
        Paint()..color = ink(d.white, d.a ?? 1),
      );
    }
  }

  @override
  bool shouldRepaint(_OrbPainter old) => false;
}
