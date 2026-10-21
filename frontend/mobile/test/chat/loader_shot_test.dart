// Blur sigma is 2.2, the user's on-device choice (2026-10-19), deliberately thinner than the web's 2.8 (the numbers below are
// the web's css with stdDeviation 2.2 rendered the same way). The stream loader against the web's: lit area (css px^2, green > 40 on black) of frontend/src/stream-loader.css
// rendered in headless Edge at the same animation times (blur 2.2, "18 -7", 0.77 scale, 4x device pixels).

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jarvis_mobile/chat/stream_loader.dart';

Future<double> _litArea(WidgetTester t, int ms) async {
  await t.pumpWidget(
    MaterialApp(
      home: Scaffold(
        backgroundColor: Colors.black,
        body: RepaintBoundary(
          key: const Key('s'),
          child: Container(
            color: Colors.black,
            width: 120,
            height: 80,
            alignment: Alignment.center,
            child: const StreamLoader(),
          ),
        ),
      ),
    ),
  );
  await t.pump(Duration(milliseconds: ms));
  return (await t.runAsync(() async {
    final b = t.renderObject<RenderRepaintBoundary>(find.byKey(const Key('s')));
    final img = await b.toImage(pixelRatio: 4);
    final raw = (await img.toByteData())!;
    var lit = 0;
    for (var i = 0; i < img.width * img.height; i++) {
      if (raw.getUint8(i * 4 + 1) > 40) lit++;
    }
    return lit / 16;
  }))!;
}

void main() {
  for (final (ms, web) in [(0, 429.8), (2442, 389.0), (5280, 371.5)]) {
    testWidgets('loader area at $ms ms matches the web ($web)', (t) async {
      expect(await _litArea(t, ms), closeTo(web, web * 0.02));
    });
  }
}
