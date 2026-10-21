// The Dart ports are checked against numbers produced by the JS originals (thinking-orbs 'engine' and morphicons core, run in node
// on the same inputs): dot/line counts and coordinate sums.
import 'package:flutter_test/flutter_test.dart';
import 'package:jarvis_mobile/chat/chat_models.dart';
import 'package:jarvis_mobile/chat/morph_icon.dart';
import 'package:jarvis_mobile/chat/status_orb.dart';

void main() {
  // mode: (n dots, sum x, sum y, sum r, sum white, sum alpha, n lines, sum line alpha); frame at t = 3.7 * preset speed
  const orbs = {
    'orbits': (100, 1600.0, 1600.0, 46.853385, 64.05, 44.75, 0, 0.0),
    'wave': (62, 992.0, 1018.407494, 32.226596, 23.026151, 62.0, 0, 0.0),
    'web': (
      17,
      286.015326,
      286.367681,
      13.420355,
      5.041993,
      16.46087,
      4,
      0.40626,
    ),
    'rubik': (62, 1029.448733, 995.428299, 35.359559, 21.595381, 62.0, 0, 0.0),
    'ribbon': (
      258,
      4129.608649,
      4128.641163,
      109.584755,
      108.897867,
      173.274207,
      0,
      0.0,
    ),
  };
  // The web fixture used t = 3.7*speed for orbits/wave/web/rubik/ribbon respectively (printed as "t").
  const ts = {
    'orbits': 10.75664,
    'wave': 15.35944,
    'web': 18.53848,
    'rubik': 7.01668,
    'ribbon': 10.27712,
  };

  for (final e in orbs.entries) {
    test('orb frame "${e.key}" matches thinking-orbs', () {
      final f = orbFrame(resolvePreset(e.key), 32, ts[e.key]!);
      final v = e.value;
      double sum(double Function(OrbDot) g) =>
          f.dots.fold(0, (s, d) => s + g(d));
      expect(f.dots.length, v.$1);
      expect(sum((d) => d.x), closeTo(v.$2, 1e-3));
      expect(sum((d) => d.y), closeTo(v.$3, 1e-3));
      expect(sum((d) => d.r), closeTo(v.$4, 1e-4));
      expect(sum((d) => d.white), closeTo(v.$5, 1e-4));
      expect(sum((d) => d.a ?? 1), closeTo(v.$6, 1e-4));
      expect(f.lines.length, v.$7);
      expect(f.lines.fold<double>(0, (s, l) => s + l.a), closeTo(v.$8, 1e-4));
    });
  }

  test('JARVIS state picks the same orb and speed as status-orb.ts', () {
    expect(orbFor(JState.idle), (mode: 'orbits', speed: 0.6));
    expect(orbFor(JState.listening).mode, 'wave');
    expect(orbFor(JState.thinking).mode, 'web');
    expect(orbFor(JState.working).mode, 'rubik');
    expect(orbFor(JState.speaking).mode, 'ribbon');
  });

  test('blend pairs dots by angle and fades spares', () {
    final a = orbFrame(resolvePreset('orbits'), 32, 3);
    final b = orbFrame(resolvePreset('web'), 32, 3);
    final start = blendFrames(a, b, 0, 32);
    final end = blendFrames(a, b, 1, 32);
    // spare dots of the smaller side start/end invisible, so the visible count at the ends is the real one
    expect(start.dots.length, a.dots.length);
    expect(end.dots.length, b.dots.length);
    final mid = blendFrames(a, b, 0.5, 32);
    expect(mid.dots.length, greaterThan(0));
  });

  // morphicons: send <-> check, (subpaths, sum x, sum y) at progress t
  const sendCheck = [
    (0.0, 1910.7088167926674, 1161.3458262267516),
    (0.25, 1815.7816125945005, 1267.7593696700644),
    (0.5, 1720.8544083963336, 1374.1729131133761),
    (0.8, 1606.941763358534, 1501.8691652453501),
    (1.0, 1531.0000000000002, 1587.0000000000002),
  ];
  const checkSend = [
    (0.0, 1531.0000000000005, 1587.0000000000002),
    (0.5, 1720.8544083963334, 1374.1729131133754),
    (1.0, 1910.7088167926674, 1161.3458262267516),
  ];
  test('morph plan matches morphicons (plane -> check)', () {
    for (final (t, sx, sy) in sendCheck) {
      final (n, x, y) = morphSample(sendGlyph, checkGlyph, t);
      expect(n, 2);
      expect(x, closeTo(sx, 1e-6));
      expect(y, closeTo(sy, 1e-6));
    }
  });
  test('morph plan matches morphicons (check -> plane)', () {
    for (final (t, sx, sy) in checkSend) {
      final (n, x, y) = morphSample(checkGlyph, sendGlyph, t);
      expect(n, 2);
      expect(x, closeTo(sx, 1e-6));
      expect(y, closeTo(sy, 1e-6));
    }
  });

  test('the morph settles on the target after the snappy spring', () {
    final m = MorphController(sendGlyph)..morphTo(checkGlyph);
    expect(m.flying, isTrue);
    var frames = 0;
    while (m.flying && frames < 600) {
      m.tick(1 / 60);
      frames++;
    }
    expect(m.flying, isFalse);
    expect(frames, lessThan(60)); // settles well within a second
    final b = m.path().getBounds();
    expect((b.left, b.top, b.width, b.height), (4.0, 6.0, 16.0, 11.0));
  });
}
