// A Dart port of morphicons 1.7.1 (MIT, (c) Guillermo, https://github.com/guillermolg00/morphicons): parse -> cubics -> equal-arc
// resample -> Procrustes plan -> polar interpolation, driven by the "snappy" spring (k 420, c 30). Same constants and steps as
// the JS (src/core/{parse,normalize,resample,plan,interpolate,spring}.ts, src/dom), so the paper plane flies into the check
// exactly as in the web button. See THIRD_PARTY_NOTICES.md.
import 'dart:math' as math;
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter/scheduler.dart';

/// An icon as lucide's path data (the 24x24 grid). Compared by identity, like the JS icon nodes.
class MorphGlyph {
  const MorphGlyph(this.paths);
  final List<String> paths;
}

// lucide "send" and "check" (ISC, lucide.dev)
const sendGlyph = MorphGlyph([
  'M14.536 21.686a.5.5 0 0 0 .937-.024l6.5-19a.496.496 0 0 0-.635-.635l-19 6.5a.5.5 0 0 0-.024.937l7.93 3.18a2 2 0 0 1 1.112 1.11z',
  'm21.854 2.147-10.94 10.939',
]);
const checkGlyph = MorphGlyph(['M20 6 9 17l-5-5']);

// ---------------------------------------------------------------- parse

class _Seg {
  _Seg(this.t, this.v);
  final String t; // L C Q A
  final List<double> v;
}

class _Raw {
  _Raw(this.x0, this.y0);
  final double x0, y0;
  final segs = <_Seg>[];
  bool closed = false;
}

List<_Raw> _parsePath(String d) {
  final subs = <_Raw>[];
  final n = d.length;
  var i = 0;
  double cx = 0, cy = 0, sx = 0, sy = 0, px = 0, py = 0;
  _Raw? cur;
  var cmd = '';
  var prev = '';
  var started = false;
  const commands = 'MmLlHhVvCcSsQqTtAaZz';
  bool isDigit(int c) => c >= 48 && c <= 57;
  void skip() {
    while (i < n) {
      final c = d.codeUnitAt(i);
      if (c == 32 || c == 9 || c == 10 || c == 13 || c == 12 || c == 44) {
        i++;
      } else {
        break;
      }
    }
  }

  double num() {
    skip();
    final start = i;
    if (i < n && (d[i] == '+' || d[i] == '-')) i++;
    var dig = false;
    while (i < n && isDigit(d.codeUnitAt(i))) {
      i++;
      dig = true;
    }
    if (i < n && d[i] == '.') {
      i++;
      while (i < n && isDigit(d.codeUnitAt(i))) {
        i++;
        dig = true;
      }
    }
    if (!dig) throw FormatException('morphicons: expected number at d[$i]');
    if (i < n && (d[i] == 'e' || d[i] == 'E')) {
      final save = i;
      i++;
      if (i < n && (d[i] == '+' || d[i] == '-')) i++;
      var ed = false;
      while (i < n && isDigit(d.codeUnitAt(i))) {
        i++;
        ed = true;
      }
      if (!ed) i = save;
    }
    return double.parse(d.substring(start, i));
  }

  double flag() {
    skip();
    final c = d[i];
    if (c == '0' || c == '1') {
      i++;
      return c == '1' ? 1 : 0;
    }
    throw FormatException('morphicons: expected arc flag at d[$i]');
  }

  _Raw open() {
    if (!started) throw const FormatException('path must start with M/m');
    if (cur == null) {
      cur = _Raw(cx, cy);
      subs.add(cur!);
    }
    return cur!;
  }

  var rel = false;
  double nx() => num() + (rel ? cx : 0);
  double ny() => num() + (rel ? cy : 0);
  while (true) {
    skip();
    if (i >= n) break;
    final ch = d[i];
    if (commands.contains(ch)) {
      cmd = ch;
      i++;
    } else if (cmd == '') {
      throw const FormatException('path must start with M/m');
    } else if (cmd == 'M') {
      cmd = 'L';
    } else if (cmd == 'm') {
      cmd = 'l';
    } else if (cmd == 'Z' || cmd == 'z') {
      throw const FormatException('stray data after Z');
    }
    rel = cmd.codeUnitAt(0) >= 97;
    switch (rel ? cmd.toUpperCase() : cmd) {
      case 'M':
        started = true;
        final x = nx(), y = ny();
        cx = x;
        cy = y;
        sx = x;
        sy = y;
        cur = _Raw(x, y);
        subs.add(cur!);
        prev = '';
      case 'L':
        final x = nx(), y = ny();
        open().segs.add(_Seg('L', [x, y]));
        cx = x;
        cy = y;
        prev = '';
      case 'H':
        final x = nx();
        open().segs.add(_Seg('L', [x, cy]));
        cx = x;
        prev = '';
      case 'V':
        final y = ny();
        open().segs.add(_Seg('L', [cx, y]));
        cy = y;
        prev = '';
      case 'C' || 'S':
        double x1, y1;
        if (cmd == 'C' || cmd == 'c') {
          x1 = nx();
          y1 = ny();
        } else {
          x1 = prev == 'C' ? 2 * cx - px : cx;
          y1 = prev == 'C' ? 2 * cy - py : cy;
        }
        final x2 = nx(), y2 = ny(), x = nx(), y = ny();
        open().segs.add(_Seg('C', [x1, y1, x2, y2, x, y]));
        px = x2;
        py = y2;
        cx = x;
        cy = y;
        prev = 'C';
      case 'Q' || 'T':
        double x1, y1;
        if (cmd == 'Q' || cmd == 'q') {
          x1 = nx();
          y1 = ny();
        } else {
          x1 = prev == 'Q' ? 2 * cx - px : cx;
          y1 = prev == 'Q' ? 2 * cy - py : cy;
        }
        final x = nx(), y = ny();
        open().segs.add(_Seg('Q', [x1, y1, x, y]));
        px = x1;
        py = y1;
        cx = x;
        cy = y;
        prev = 'Q';
      case 'A':
        final rx = num(), ry = num(), rot = num();
        final large = flag(), sweep = flag();
        final x = nx(), y = ny();
        open().segs.add(_Seg('A', [rx, ry, rot, large, sweep, x, y]));
        cx = x;
        cy = y;
        prev = '';
      case 'Z':
        if (cur != null) {
          cur!.closed = true;
          cur = null;
        }
        cx = sx;
        cy = sy;
        prev = '';
      default:
        throw FormatException('unsupported command "$cmd"');
    }
  }
  return subs.where((s) => s.segs.isNotEmpty).toList();
}

// ------------------------------------------------------------ normalize

class _Cubic {
  _Cubic(this.pts, this.closed);
  final Float64List pts;
  final bool closed;
}

_Cubic? _lower(_Raw raw) {
  final pts = <double>[raw.x0, raw.y0];
  var cx = raw.x0, cy = raw.y0;
  void cubic(double x1, double y1, double x2, double y2, double x, double y) {
    pts.addAll([x1, y1, x2, y2, x, y]);
    cx = x;
    cy = y;
  }

  void line(double x, double y) {
    if ((x - cx).abs() < 1e-12 && (y - cy).abs() < 1e-12) return;
    cubic(
      cx + (x - cx) / 3,
      cy + (y - cy) / 3,
      cx + 2 * (x - cx) / 3,
      cy + 2 * (y - cy) / 3,
      x,
      y,
    );
  }

  void quad(double x1, double y1, double x, double y) => cubic(
    cx + 2 / 3 * (x1 - cx),
    cy + 2 / 3 * (y1 - cy),
    x + 2 / 3 * (x1 - x),
    y + 2 / 3 * (y1 - y),
    x,
    y,
  );

  void arc(
    double rx0,
    double ry0,
    double rotDeg,
    double large,
    double sweep,
    double x,
    double y,
  ) {
    final x1 = cx, y1 = cy;
    if ((x - x1).abs() < 1e-12 && (y - y1).abs() < 1e-12) return;
    var rx = rx0.abs(), ry = ry0.abs();
    if (rx < 1e-12 || ry < 1e-12) {
      line(x, y);
      return;
    }
    final phi = rotDeg * math.pi / 180;
    final cosP = math.cos(phi), sinP = math.sin(phi);
    final hx = (x1 - x) / 2, hy = (y1 - y) / 2;
    final x1p = cosP * hx + sinP * hy;
    final y1p = -sinP * hx + cosP * hy;
    final lam = x1p * x1p / (rx * rx) + y1p * y1p / (ry * ry);
    if (lam > 1) {
      final s = math.sqrt(lam);
      rx *= s;
      ry *= s;
    }
    final rx2 = rx * rx, ry2 = ry * ry, xp2 = x1p * x1p, yp2 = y1p * y1p;
    var rad = (rx2 * ry2 - rx2 * yp2 - ry2 * xp2) / (rx2 * yp2 + ry2 * xp2);
    if (rad < 0) rad = 0;
    final co = (large == sweep ? -1 : 1) * math.sqrt(rad);
    final cxp = co * rx * y1p / ry;
    final cyp = -co * ry * x1p / rx;
    final ccx = cosP * cxp - sinP * cyp + (x1 + x) / 2;
    final ccy = sinP * cxp + cosP * cyp + (y1 + y) / 2;
    final th1 = math.atan2((y1p - cyp) / ry, (x1p - cxp) / rx);
    var dth = math.atan2((-y1p - cyp) / ry, (-x1p - cxp) / rx) - th1;
    const tau = 2 * math.pi;
    if (sweep == 0 && dth > 0) {
      dth -= tau;
    } else if (sweep == 1 && dth < 0) {
      dth += tau;
    }
    final slices = math.max(1, (dth.abs() / (math.pi / 2) - 1e-9).ceil());
    final delta = dth / slices;
    final alpha = 4 / 3 * math.tan(delta / 4);
    double ex(double t) =>
        ccx + rx * math.cos(t) * cosP - ry * math.sin(t) * sinP;
    double ey(double t) =>
        ccy + rx * math.cos(t) * sinP + ry * math.sin(t) * cosP;
    double dx(double t) => -rx * math.sin(t) * cosP - ry * math.cos(t) * sinP;
    double dy(double t) => -rx * math.sin(t) * sinP + ry * math.cos(t) * cosP;
    var t0 = th1, p0x = x1, p0y = y1;
    for (var s = 1; s <= slices; s++) {
      final t1 = th1 + delta * s;
      final p1x = s == slices ? x : ex(t1);
      final p1y = s == slices ? y : ey(t1);
      cubic(
        p0x + alpha * dx(t0),
        p0y + alpha * dy(t0),
        p1x - alpha * dx(t1),
        p1y - alpha * dy(t1),
        p1x,
        p1y,
      );
      t0 = t1;
      p0x = p1x;
      p0y = p1y;
    }
  }

  for (final s in raw.segs) {
    final v = s.v;
    switch (s.t) {
      case 'L':
        line(v[0], v[1]);
      case 'C':
        cubic(v[0], v[1], v[2], v[3], v[4], v[5]);
      case 'Q':
        quad(v[0], v[1], v[2], v[3]);
      case 'A':
        arc(v[0], v[1], v[2], v[3], v[4], v[5], v[6]);
    }
  }
  if (raw.closed) line(pts[0], pts[1]);
  if (pts.length < 8) return null;
  return _Cubic(Float64List.fromList(pts), raw.closed);
}

List<_Cubic> _iconToCubics(MorphGlyph g) => [
  for (final d in g.paths)
    for (final s in _parsePath(d)) ?_lower(s),
];

// ------------------------------------------------------------- resample

const _cornerThreshold = math.pi / 8;
const _gx = [
  .18343464249564978,
  .525532409916329,
  .7966664774136267,
  .9602898564975363,
];
const _gw = [
  .362683783378362,
  .31370664587788727,
  .22238103445337448,
  .10122853629037626,
];

double _speed(Float64List p, int k, double t) {
  final i = 6 * k;
  final u = 1 - t;
  final c0 = 3 * u * u, c1 = 6 * u * t, c2 = 3 * t * t;
  final dx =
      c0 * (p[i + 2] - p[i]) +
      c1 * (p[i + 4] - p[i + 2]) +
      c2 * (p[i + 6] - p[i + 4]);
  final dy =
      c0 * (p[i + 3] - p[i + 1]) +
      c1 * (p[i + 5] - p[i + 3]) +
      c2 * (p[i + 7] - p[i + 5]);
  return math.sqrt(dx * dx + dy * dy);
}

double _segLen(Float64List p, int k, [double t1 = 1]) {
  final half = t1 / 2;
  var s = 0.0;
  for (var j = 0; j < 4; j++) {
    s +=
        _gw[j] *
        (_speed(p, k, half + half * _gx[j]) +
            _speed(p, k, half - half * _gx[j]));
  }
  return s * half;
}

void _point(Float64List p, int k, double t, Float64List out, int o) {
  final i = 6 * k;
  final u = 1 - t;
  final b0 = u * u * u, b1 = 3 * u * u * t, b2 = 3 * u * t * t, b3 = t * t * t;
  out[o] = b0 * p[i] + b1 * p[i + 2] + b2 * p[i + 4] + b3 * p[i + 6];
  out[o + 1] = b0 * p[i + 1] + b1 * p[i + 3] + b2 * p[i + 5] + b3 * p[i + 7];
}

(double, double)? _tangent(Float64List p, int k, bool atEnd) {
  final i = 6 * k;
  final b = atEnd ? i + 6 : i;
  final s = atEnd ? -1.0 : 1.0;
  for (final j in atEnd ? const [4, 2, 0] : const [2, 4, 6]) {
    final dx = s * (p[i + j] - p[b]);
    final dy = s * (p[i + j + 1] - p[b + 1]);
    if (dx * dx + dy * dy > 1e-18) return (dx, dy);
  }
  return null;
}

List<int> _detectCorners(_Cubic path) {
  final p = path.pts;
  final m = (p.length ~/ 2 - 1) ~/ 3;
  final active = <int>[
    for (var k = 0; k < m; k++)
      if (_segLen(p, k) > 1e-9) k,
  ];
  if (active.isEmpty) return [];
  final corners = <int>{};
  void test(int a, int b) {
    final u = _tangent(p, a, true), v = _tangent(p, b, false);
    if (u == null || v == null) return;
    if (math.atan2(u.$1 * v.$2 - u.$2 * v.$1, u.$1 * v.$1 + u.$2 * v.$2).abs() >
        _cornerThreshold) {
      corners.add(b);
    }
  }

  for (var j = 0; j + 1 < active.length; j++) {
    test(active[j], active[j + 1]);
  }
  if (path.closed && active.length > 1) test(active.last, active.first);
  return corners.toList()..sort();
}

double _invert(Float64List p, int k, double s, double ls) {
  if (s <= 0) return 0;
  if (s >= ls) return 1;
  var lo = 0.0, hi = 1.0, t = s / ls;
  for (var it = 0; it < 12; it++) {
    final f = _segLen(p, k, t) - s;
    if (f.abs() < 1e-10 * ls + 1e-14) break;
    if (f > 0) {
      hi = t;
    } else {
      lo = t;
    }
    final sp = _speed(p, k, t);
    var nt = sp > 1e-12 ? t - f / sp : (lo + hi) / 2;
    if (!(nt > lo && nt < hi)) nt = (lo + hi) / 2;
    t = nt;
  }
  return t;
}

Float64List _resamplePath(_Cubic path, [int n = 64]) {
  final p = path.pts;
  final m = (p.length ~/ 2 - 1) ~/ 3;
  final out = Float64List(2 * n);
  Float64List fill() {
    for (var i = 0; i < n; i++) {
      out[2 * i] = p[0];
      out[2 * i + 1] = p[1];
    }
    return out;
  }

  if (m < 1) return fill();
  final lens = List<double>.filled(m, 0);
  var total0 = 0.0;
  for (var k = 0; k < m; k++) {
    lens[k] = _segLen(p, k);
    total0 += lens[k];
  }
  if (total0 < 1e-12) return fill();
  final cs = _detectCorners(path);
  final List<int> anchors = path.closed
      ? (cs.isNotEmpty ? cs : [0])
      : ({0, ...cs, m}.toList()..sort());
  final runs = <(int, int)>[];
  if (path.closed) {
    for (var j = 0; j < anchors.length; j++) {
      final a = anchors[j];
      final b = j + 1 < anchors.length ? anchors[j + 1] : anchors[0] + m;
      runs.add((a, b));
    }
  } else {
    for (var j = 0; j + 1 < anchors.length; j++) {
      runs.add((anchors[j], anchors[j + 1]));
    }
  }
  final rl = [
    for (final (a, b) in runs)
      () {
        var s = 0.0;
        for (var k = a; k < b; k++) {
          s += lens[k % m];
        }
        return s;
      }(),
  ];
  final intervals = path.closed ? n : n - 1;
  final total = rl.fold(0.0, (a, b) => a + b);
  final ideal = [for (final l in rl) intervals * l / (total == 0 ? 1 : total)];
  final counts = [for (final q in ideal) math.max(1, q.floor())];
  var r = intervals - counts.fold(0, (a, b) => a + b);
  if (r > 0) {
    final order = [
      for (var i = 0; i < ideal.length; i++)
        ((ideal[i] - ideal[i].floor()) * 1e9).round() * 1000 + (999 - i),
    ];
    final idx = List<int>.generate(ideal.length, (i) => i)
      ..sort((a, b) => order[b].compareTo(order[a]));
    for (var j = 0; j < r; j++) {
      counts[idx[j % counts.length]]++;
    }
  }
  while (r < 0) {
    var bi = 0;
    for (var i = 1; i < counts.length; i++) {
      if (counts[i] > counts[bi]) bi = i;
    }
    if (counts[bi] <= 1) break;
    counts[bi]--;
    r++;
  }
  var w = 0;
  for (var ri = 0; ri < runs.length; ri++) {
    final (k0, k1) = runs[ri];
    final cnt = counts[ri];
    final lr = rl[ri];
    final vi = 6 * (k0 % m);
    out[2 * w] = p[vi];
    out[2 * w + 1] = p[vi + 1];
    w++;
    var seg = k0;
    var acc = 0.0;
    for (var j = 1; j < cnt; j++) {
      final target = lr * j / cnt;
      while (seg < k1 - 1 && acc + lens[seg % m] < target) {
        acc += lens[seg % m];
        seg++;
      }
      final k = seg % m;
      final ls = lens[k];
      _point(
        p,
        k,
        ls > 1e-12 ? _invert(p, k, target - acc, ls) : 0,
        out,
        2 * w,
      );
      w++;
    }
  }
  if (!path.closed) {
    final vi = 6 * m;
    out[2 * w] = p[vi];
    out[2 * w + 1] = p[vi + 1];
  }
  return out;
}

class _Sub {
  _Sub(this.pts, this.closed);
  final Float64List pts;
  final bool closed;
}

List<_Sub> _resampleIcon(MorphGlyph g) => [
  for (final c in _iconToCubics(g)) _Sub(_resamplePath(c), c.closed),
];

// ----------------------------------------------------------------- plan

const _lenWeight = .35;
const _lambda = .05;
const _globalEps = .005;
const _permMax = 8;
const _surjMax = 1e5;

(double, double) _centroid(Float64List p) {
  final n = p.length ~/ 2;
  var cx = 0.0, cy = 0.0;
  for (var i = 0; i < n; i++) {
    cx += p[2 * i];
    cy += p[2 * i + 1];
  }
  return (cx / n, cy / n);
}

double _polyLen(Float64List p) {
  final n = p.length ~/ 2;
  var l = 0.0;
  for (var i = 1; i < n; i++) {
    final dx = p[2 * i] - p[2 * i - 2], dy = p[2 * i + 1] - p[2 * i - 1];
    l += math.sqrt(dx * dx + dy * dy);
  }
  return l;
}

Float64List _reversePts(Float64List p) {
  final n = p.length ~/ 2;
  final out = Float64List(2 * n);
  for (var i = 0; i < n; i++) {
    out[2 * i] = p[2 * (n - 1 - i)];
    out[2 * i + 1] = p[2 * (n - 1 - i) + 1];
  }
  return out;
}

Float64List _rotatePts(Float64List p, int off) {
  final n = p.length ~/ 2;
  final out = Float64List(2 * n);
  for (var i = 0; i < n; i++) {
    final j = (i + off) % n;
    out[2 * i] = p[2 * j];
    out[2 * i + 1] = p[2 * j + 1];
  }
  return out;
}

class _Sim {
  _Sim(this.theta, this.sigma, this.res);
  final double theta, sigma, res;
}

_Sim _procrustes(
  Float64List a,
  Float64List b,
  (double, double) ca,
  (double, double) cb,
) {
  final n = a.length ~/ 2;
  var sxx = 0.0, sxy = 0.0, syx = 0.0, syy = 0.0, na = 0.0, nb = 0.0;
  for (var i = 0; i < n; i++) {
    final ax = a[2 * i] - ca.$1, ay = a[2 * i + 1] - ca.$2;
    final bx = b[2 * i] - cb.$1, by = b[2 * i + 1] - cb.$2;
    sxx += ax * bx;
    syy += ay * by;
    sxy += ax * by;
    syx += ay * bx;
    na += ax * ax + ay * ay;
    nb += bx * bx + by * by;
  }
  final theta = math.atan2(sxy - syx, sxx + syy);
  final num = math.cos(theta) * (sxx + syy) + math.sin(theta) * (sxy - syx);
  var sigma = na > 1e-12 ? num / na : 1.0;
  if (!(sigma > 1e-6)) sigma = 1e-6;
  final res2 = math.max(0.0, sigma * sigma * na - 2 * sigma * num + nb);
  final res = nb > 1e-12 ? math.sqrt(res2 / nb) : 0.0;
  return _Sim(theta, sigma, res);
}

class _Align {
  _Align(this.ca, this.cb, this.a, this.b, this.sim);
  final (double, double) ca, cb;
  final Float64List a, b;
  final _Sim sim;
}

_Align _alignPair(
  Float64List aPts,
  Float64List bPts,
  bool aClosed,
  bool bClosed,
) {
  final ca = _centroid(aPts), cb = _centroid(bPts);
  final varyA = aClosed && !bClosed;
  final base = varyA ? aPts : bPts;
  final offs = aClosed || bClosed ? base.length ~/ 2 : 1;
  var bestScore = double.infinity;
  var best = base;
  var sim = _Sim(0, 1, 0);
  for (var dir = 0; dir < 2; dir++) {
    final walk = dir == 1 ? _reversePts(base) : base;
    for (var off = 0; off < offs; off++) {
      final cand = off != 0 ? _rotatePts(walk, off) : walk;
      final s = varyA
          ? _procrustes(cand, bPts, ca, cb)
          : _procrustes(aPts, cand, ca, cb);
      final score = s.res + _lambda * s.theta.abs() / math.pi;
      if (score < bestScore) {
        bestScore = score;
        best = cand;
        sim = s;
      }
    }
  }
  return varyA
      ? _Align(ca, cb, best, bPts, sim)
      : _Align(ca, cb, aPts, best, sim);
}

List<List<double>> _costMatrix(List<Float64List> a, List<Float64List> b) {
  final cbs = b.map(_centroid).toList();
  final lbs = b.map(_polyLen).toList();
  return [
    for (final x in a)
      () {
        final ca = _centroid(x);
        final la = _polyLen(x);
        return [
          for (var j = 0; j < cbs.length; j++)
            math.sqrt(
                  math.pow(ca.$1 - cbs[j].$1, 2) +
                      math.pow(ca.$2 - cbs[j].$2, 2),
                ) +
                _lenWeight * (la - lbs[j]).abs(),
        ];
      }(),
  ];
}

List<int> _bestPermutation(List<List<double>> c) {
  final n = c.length;
  if (n > _permMax) {
    final pairs = <(double, int, int)>[
      for (var i = 0; i < n; i++)
        for (var j = 0; j < n; j++) (c[i][j], i, j),
    ]..sort((x, y) => x.$1.compareTo(y.$1));
    final out = List<int>.filled(n, -1);
    final used = List<bool>.filled(n, false);
    for (final (_, i, j) in pairs) {
      if (out[i] < 0 && !used[j]) {
        out[i] = j;
        used[j] = true;
      }
    }
    return out;
  }
  var best = List<int>.generate(n, (i) => i);
  var bc = double.infinity;
  void perm(List<int> arr, int k, double acc) {
    if (acc >= bc) return;
    if (k == n) {
      bc = acc;
      best = List.of(arr);
      return;
    }
    for (var i = k; i < n; i++) {
      var t = arr[k];
      arr[k] = arr[i];
      arr[i] = t;
      perm(arr, k + 1, acc + c[k][arr[k]]);
      t = arr[k];
      arr[k] = arr[i];
      arr[i] = t;
    }
  }

  perm(List<int>.generate(n, (i) => i), 0, 0);
  return best;
}

List<int> _bestSurjection(List<List<double>> c) {
  final b = c.length, s = c[0].length;
  if (math.pow(s, b) > _surjMax) {
    final f = [
      for (final row in c)
        () {
          var m = 0;
          for (var j = 1; j < row.length; j++) {
            if (row[j] < row[m]) m = j;
          }
          return m;
        }(),
    ];
    final mult = List<int>.filled(s, 0);
    for (final x in f) {
      mult[x]++;
    }
    for (var si = 0; si < s; si++) {
      if (mult[si] > 0) continue;
      var bi = -1;
      var bc = double.infinity;
      for (var i = 0; i < b; i++) {
        if (mult[f[i]] < 2) continue;
        final extra = c[i][si] - c[i][f[i]];
        if (extra < bc) {
          bc = extra;
          bi = i;
        }
      }
      mult[f[bi]]--;
      f[bi] = si;
      mult[si]++;
    }
    return f;
  }
  List<int>? best;
  var bc = double.infinity;
  final f = List<int>.filled(b, 0);
  final mult = List<int>.filled(s, 0);
  void rec(int i, double acc, int covered) {
    if (acc >= bc || s - covered > b - i) return;
    if (i == b) {
      bc = acc;
      best = List.of(f);
      return;
    }
    for (var si = 0; si < s; si++) {
      f[i] = si;
      mult[si]++;
      rec(i + 1, acc + c[i][si], covered + (mult[si] == 1 ? 1 : 0));
      mult[si]--;
    }
  }

  rec(0, 0, 0);
  if (best == null) throw StateError('morphicons: no valid surjection (B < S)');
  return best!;
}

class _Item {
  _Item({
    required this.a,
    required this.aC,
    required this.bT,
    required this.bO,
    required this.ca,
    required this.cb,
    required this.theta,
    required this.lnSigma,
    required this.closed,
  });
  final Float64List a, aC, bT, bO;
  final (double, double) ca, cb;
  double theta, lnSigma;
  final bool closed;
  ((double, double), (double, double))? block; // (off, drift)
}

class _Plan {
  _Plan(this.items, this.n);
  final List<_Item> items;
  final int n;
}

void _applyGlobal(List<_Item> items, int n) {
  final t = items.length * n;
  final ga = Float64List(2 * t), gb = Float64List(2 * t);
  for (var k = 0; k < items.length; k++) {
    ga.setAll(2 * n * k, items[k].a);
    gb.setAll(2 * n * k, items[k].bO);
  }
  final gca = _centroid(ga);
  final g = _procrustes(ga, gb, gca, _centroid(gb));
  if (g.res >= _globalEps) return;
  final cos = math.cos(-g.theta), sin = math.sin(-g.theta);
  for (final it in items) {
    for (var i = 0; i < n; i++) {
      final bx = it.bO[2 * i] - it.cb.$1, by = it.bO[2 * i + 1] - it.cb.$2;
      it.bT[2 * i] = (bx * cos - by * sin) / g.sigma;
      it.bT[2 * i + 1] = (bx * sin + by * cos) / g.sigma;
    }
    it.theta = g.theta;
    it.lnSigma = math.log(g.sigma);
    final s1 = math.exp(it.lnSigma);
    final c1 = math.cos(it.theta) * s1, n1 = math.sin(it.theta) * s1;
    final ox = it.ca.$1 - gca.$1, oy = it.ca.$2 - gca.$2;
    final rx = ox * c1 - oy * n1 - ox, ry = ox * n1 + oy * c1 - oy;
    it.block = ((ox, oy), (it.cb.$1 - it.ca.$1 - rx, it.cb.$2 - it.ca.$2 - ry));
  }
}

_Plan _buildPlan(List<_Sub> src, List<_Sub> dst) {
  final p = src.length, q = dst.length;
  if (p == 0 || q == 0) throw StateError('morphicons: icon has no subpaths');
  final a = [for (final s in src) s.pts];
  final b = [for (final s in dst) s.pts];
  final pairs = <(int, int)>[];
  if (p == q) {
    final perm = _bestPermutation(_costMatrix(a, b));
    for (var i = 0; i < p; i++) {
      pairs.add((i, perm[i]));
    }
  } else if (p < q) {
    final f = _bestSurjection(_costMatrix(b, a));
    for (var j = 0; j < q; j++) {
      pairs.add((f[j], j));
    }
  } else {
    final f = _bestSurjection(_costMatrix(a, b));
    for (var i = 0; i < p; i++) {
      pairs.add((i, f[i]));
    }
  }
  final n = a[0].length ~/ 2;
  final items = <_Item>[];
  for (final (si, di) in pairs) {
    final al = _alignPair(a[si], b[di], src[si].closed, dst[di].closed);
    final aC = Float64List(2 * n),
        bT = Float64List(2 * n),
        bO = Float64List(2 * n);
    final cos = math.cos(-al.sim.theta), sin = math.sin(-al.sim.theta);
    for (var i = 0; i < n; i++) {
      aC[2 * i] = al.a[2 * i] - al.ca.$1;
      aC[2 * i + 1] = al.a[2 * i + 1] - al.ca.$2;
      final bx = al.b[2 * i] - al.cb.$1, by = al.b[2 * i + 1] - al.cb.$2;
      bT[2 * i] = (bx * cos - by * sin) / al.sim.sigma;
      bT[2 * i + 1] = (bx * sin + by * cos) / al.sim.sigma;
      bO[2 * i] = al.b[2 * i];
      bO[2 * i + 1] = al.b[2 * i + 1];
    }
    items.add(
      _Item(
        a: al.a,
        aC: aC,
        bT: bT,
        bO: bO,
        ca: al.ca,
        cb: al.cb,
        theta: al.sim.theta,
        lnSigma: math.log(al.sim.sigma),
        closed: src[si].closed && dst[di].closed,
      ),
    );
  }
  if (items.length > 1) _applyGlobal(items, n);
  return _Plan(items, n);
}

void _interpPolar(_Plan plan, double t, List<Float64List> out) {
  for (var k = 0; k < plan.items.length; k++) {
    final it = plan.items[k];
    final o = out[k];
    final n = plan.n;
    final s = math.exp(it.lnSigma * t);
    final ang = it.theta * t;
    final cos = math.cos(ang) * s, sin = math.sin(ang) * s;
    double cx, cy;
    if (it.block != null) {
      final (ox, oy) = it.block!.$1;
      final (dx, dy) = it.block!.$2;
      cx = it.ca.$1 + dx * t + (ox * cos - oy * sin - ox);
      cy = it.ca.$2 + dy * t + (ox * sin + oy * cos - oy);
    } else {
      cx = it.ca.$1 + (it.cb.$1 - it.ca.$1) * t;
      cy = it.ca.$2 + (it.cb.$2 - it.ca.$2) * t;
    }
    for (var i = 0; i < n; i++) {
      final px = it.aC[2 * i] + (it.bT[2 * i] - it.aC[2 * i]) * t;
      final py = it.aC[2 * i + 1] + (it.bT[2 * i + 1] - it.aC[2 * i + 1]) * t;
      o[2 * i] = cx + px * cos - py * sin;
      o[2 * i + 1] = cy + px * sin + py * cos;
    }
  }
}

/// Test hook: (subpaths, sum x, sum y) of the plan from [a] to [b] at progress [t] (compared with the JS engine's numbers).
@visibleForTesting
(int, double, double) morphSample(MorphGlyph a, MorphGlyph b, double t) {
  final plan = _buildPlan(_resampleIcon(a), _resampleIcon(b));
  final out = [for (final _ in plan.items) Float64List(2 * plan.n)];
  _interpPolar(plan, t, out);
  var sx = 0.0, sy = 0.0;
  for (final o in out) {
    for (var i = 0; i < o.length; i += 2) {
      sx += o[i];
      sy += o[i + 1];
    }
  }
  return (out.length, sx, sy);
}

// --------------------------------------------------------------- driver

/// morphicons Spring + SPRING_PRESETS.snappy (zeta 0.73, a little overshoot).
class _Spring {
  double x = 1, v = 0, k = 420, c = 30;
  void start() {
    x = 0;
    v = v.clamp(-14.0, 14.0);
  }

  bool step(double dt) {
    final steps = math.max(1, math.min(16, (dt / (1 / 240)).ceil()));
    final s = dt / steps;
    for (var i = 0; i < steps; i++) {
      final a = k * (1 - x) - c * v;
      v += a * s;
      x += v * s;
    }
    return (1 - x).abs() < .001 && v.abs() < .02;
  }
}

/// The morph state machine of src/dom createMorph: rest on an icon, or fly towards the next one (retargeting from the
/// shape on screen when interrupted).
class MorphController {
  MorphController(this._target);
  MorphGlyph _target;
  bool _rest = true;
  _Plan? _plan;
  List<Float64List>? _out;
  final _spring = _Spring();
  bool get flying => !_rest;

  List<_Sub> _snapshot() {
    final p = _plan, o = _out;
    if (_rest || p == null || o == null) return _resampleIcon(_target);
    return [
      for (var k = 0; k < o.length; k++)
        _Sub(Float64List.fromList(o[k]), p.items[k].closed),
    ];
  }

  void morphTo(MorphGlyph icon) {
    if (identical(icon, _target) && (_rest || _plan != null)) return;
    final src = _snapshot();
    _plan = _buildPlan(src, _resampleIcon(icon));
    _out = [for (final _ in _plan!.items) Float64List(2 * _plan!.n)];
    _target = icon;
    _rest = false;
    _spring.start();
  }

  /// Advances dt seconds; returns true while a repaint is needed.
  void tick(double dt) {
    if (_rest) return;
    final settled = _spring.step(dt);
    _interpPolar(_plan!, _spring.x, _out!);
    if (settled) {
      _rest = true;
      _plan = null;
      _out = null;
      _spring
        ..x = 1
        ..v = 0;
    }
  }

  /// The shape to draw now: the real curves at rest, the sampled polylines in flight.
  Path path() {
    final path = Path();
    if (_rest || _plan == null) {
      for (final c in _iconToCubics(_target)) {
        path.moveTo(c.pts[0], c.pts[1]);
        for (var i = 2; i < c.pts.length; i += 6) {
          path.cubicTo(
            c.pts[i],
            c.pts[i + 1],
            c.pts[i + 2],
            c.pts[i + 3],
            c.pts[i + 4],
            c.pts[i + 5],
          );
        }
        if (c.closed) path.close();
      }
      return path;
    }
    for (var k = 0; k < _out!.length; k++) {
      final o = _out![k];
      path.moveTo(o[0], o[1]);
      for (var i = 1; i < o.length ~/ 2; i++) {
        path.lineTo(o[2 * i], o[2 * i + 1]);
      }
      if (_plan!.items[k].closed) path.close();
    }
    return path;
  }
}

/// `<morph-icon size stroke-width>`: lucide stroke icon on the 24 grid that flies to the new [icon] when it changes.
class MorphIcon extends StatefulWidget {
  const MorphIcon({
    super.key,
    required this.icon,
    required this.color,
    this.size = 14,
    this.strokeWidth = 1.5,
  });
  final MorphGlyph icon;
  final Color color;
  final double size;
  final double strokeWidth;

  @override
  State<MorphIcon> createState() => _MorphIconState();
}

class _MorphIconState extends State<MorphIcon>
    with SingleTickerProviderStateMixin {
  late final MorphController _morph = MorphController(widget.icon);
  late final Ticker _ticker = createTicker(_onTick);
  final _repaint = ValueNotifier<int>(0);
  Duration _last = Duration.zero;

  void _onTick(Duration elapsed) {
    final dt = ((elapsed - _last).inMicroseconds / 1e6).clamp(0.0, 0.1);
    _last = elapsed;
    _morph.tick(dt);
    _repaint.value++;
    if (!_morph.flying) _ticker.stop();
  }

  @override
  void didUpdateWidget(MorphIcon old) {
    super.didUpdateWidget(old);
    if (!identical(old.icon, widget.icon)) {
      _morph.morphTo(widget.icon);
      _last = Duration.zero;
      if (!_ticker.isActive) _ticker.start();
    }
  }

  @override
  void dispose() {
    _ticker.dispose();
    _repaint.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => CustomPaint(
    size: Size.square(widget.size),
    painter: _MorphPainter(
      _morph,
      widget.color,
      widget.size,
      widget.strokeWidth,
      _repaint,
    ),
  );
}

class _MorphPainter extends CustomPainter {
  _MorphPainter(
    this.morph,
    this.color,
    this.px,
    this.stroke,
    Listenable repaint,
  ) : super(repaint: repaint);
  final MorphController morph;
  final Color color;
  final double px, stroke;

  @override
  void paint(Canvas canvas, Size size) {
    final s = px / 24;
    canvas
      ..save()
      ..scale(s);
    canvas.drawPath(
      morph.path(),
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth =
            stroke // stroke-width is in the 24 grid and scales with the icon, as in the SVG
        ..strokeCap = StrokeCap.round
        ..strokeJoin = StrokeJoin.round
        ..color = color,
    );
    canvas.restore();
  }

  @override
  bool shouldRepaint(_MorphPainter old) =>
      old.color != color || old.px != px || old.stroke != stroke;
}
