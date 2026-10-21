import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jarvis_mobile/chat/chat_models.dart';
import 'package:jarvis_mobile/chat/status_label.dart';

const _key = Key('shot');

Widget _app(JState s, [String text = 'MMMMMMMMMMMMMMMM']) => MaterialApp(
  home: Scaffold(
    backgroundColor: Colors.black,
    body: RepaintBoundary(
      key: _key,
      child: Align(
        alignment: Alignment.topLeft,
        child: StatusRow(state: s, text: text),
      ),
    ),
  ),
);

/// Pixels of the label (x from [x0]) as (r,g,b,a) rows of the middle scan line.
Future<List<List<int>>?> _scan(WidgetTester t) => t.runAsync(() async {
  final b = t.renderObject<RenderRepaintBoundary>(find.byKey(_key));
  final img = await b.toImage();
  final data = (await img.toByteData(format: ui.ImageByteFormat.rawRgba))!;
  const y = 9; // inside the glyph squares
  return [
    for (var x = 40; x < img.width; x++) // the label, past the orb
      [for (var c = 0; c < 4; c++) data.getUint8((y * img.width + x) * 4 + c)],
  ];
});

void main() {
  testWidgets(
    'busy text is the full state colour, not dimmed by the idle alpha',
    (t) async {
      await t.pumpWidget(_app(JState.thinking));
      await t.pump(const Duration(milliseconds: 700)); // slide done
      final px = (await _scan(t))!;
      // rightmost lit pixel of the text, away from the sheen at the start of the cycle
      final lit = px
          .where((p) => p[3] == 255 && p[0] + p[1] + p[2] > 60)
          .toList();
      expect(lit, isNotEmpty);
      final last = lit.last;
      // #6ec4ff on black: full alpha means the exact colour
      expect(last.sublist(0, 3), [0x6e, 0xc4, 0xff]);
    },
  );

  testWidgets('sheen travels ease-in-out like the css keyframes', (t) async {
    await t.pumpWidget(_app(JState.thinking));
    await t.pump();
    // 550 ms into the 2.2 s loop: linear = 25 % (peak well inside the text), ease-in-out = 13 % (peak left of it)
    await t.pump(const Duration(milliseconds: 550));
    final px = (await _scan(t))!;
    var best = 0, bestX = 0;
    for (var x = 0; x < px.length; x++) {
      if (px[x][3] > 0 && px[x][0] > best) {
        best = px[x][0];
        bestX = x;
      }
    }
    final first = px.indexWhere((p) => p[3] > 0 && p[0] + p[1] + p[2] > 60);
    expect(bestX - first, lessThan(6));
  });

  testWidgets(
    'label starts after a 28 px orb box + 6 px gap (css #status-orb)',
    (t) async {
      await t.pumpWidget(_app(JState.idle));
      await t.pump();
      final left = t.getTopLeft(find.byKey(const Key('status-label'))).dx;
      expect(left, 6 + 28 + 6);
    },
  );

  testWidgets('the slide ghost is not cut to the new, shorter label', (
    t,
  ) async {
    await t.pumpWidget(_app(JState.idle, 'MMMMMMMMMMMMMMMM'));
    await t.pumpWidget(_app(JState.idle, 'MM'));
    await t.pump(
      const Duration(milliseconds: 40),
    ); // ghost still near full, label still waiting
    final ghost = t.getRect(find.byKey(const Key('status-ghost')));
    final live = t.getRect(find.byKey(const Key('status-label')));
    expect(ghost.width, greaterThan(live.width * 4));
    final px = (await _scan(t))!;
    // x counts from 40: pixels well past the 26 px of the new text are painted by the ghost
    expect(px.skip(60).any((p) => p[3] > 100), isTrue);
  });

  testWidgets('busy -> idle ink fades in over 500 ms (transition: all .5s)', (
    t,
  ) async {
    await t.pumpWidget(_app(JState.thinking, 'MMMM'));
    await t.pump(const Duration(milliseconds: 700));
    await t.pumpWidget(_app(JState.idle, 'MMMM'));
    await t.pump();
    Future<int> alpha() async => (await _scan(t))![10][3];
    final start = await alpha();
    await t.pump(const Duration(milliseconds: 40));
    final mid = await alpha();
    await t.pump(const Duration(milliseconds: 600));
    final end = await alpha();
    expect(start, lessThan(20));
    expect(mid, inExclusiveRange(start + 10, end - 10));
    expect(end, closeTo(0xBF, 4)); // rgba(185,212,248,.75)
  });

  testWidgets('the sheen peak is near white (rgba 255 .95)', (t) async {
    await t.pumpWidget(_app(JState.thinking));
    await t.pump(
      const Duration(milliseconds: 1100),
    ); // half the loop: the peak is mid-text
    final px = (await _scan(t))!;
    final peak = px
        .where((p) => p[3] > 0)
        .map((p) => p[0])
        .reduce((a, b) => a > b ? a : b);
    expect(peak, greaterThanOrEqualTo(0xEE));
  });
}
