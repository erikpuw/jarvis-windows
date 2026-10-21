// The busy label at several sheen positions, real font, dpr 3, the app theme's 1.5 line height around it: no glyph pixel may
// be desaturated grey (neither a vertical wash nor a grey layer) outside the narrow white band.
import 'dart:io';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jarvis_mobile/chat/chat_models.dart';
import 'package:jarvis_mobile/chat/status_label.dart';

int lo(int a, int b, int c) => [a, b, c].reduce((p, q) => p < q ? p : q);

void main() {
  testWidgets('busy glyphs are state colour or white, never grey', (t) async {
    final font = FontLoader('Lexend')
      ..addFont(
        Future.value(
          ByteData.view(
            File('assets/fonts/Lexend.ttf').readAsBytesSync().buffer,
          ),
        ),
      );
    await font.load();
    t.view.devicePixelRatio = 3;
    addTearDown(t.view.resetDevicePixelRatio);
    for (final ms in [0, 400, 800, 1100, 1500, 1900]) {
      await t.pumpWidget(
        MaterialApp(
          home: Scaffold(
            backgroundColor: Colors.black,
            body: RepaintBoundary(
              key: const Key('s'),
              child: Align(
                alignment: Alignment.topLeft,
                child: DefaultTextStyle.merge(
                  style: const TextStyle(fontFamily: 'Lexend', height: 1.5),
                  child: const StatusRow(
                    state: JState.thinking,
                    text: 'Đang nghĩ…',
                  ),
                ),
              ),
            ),
          ),
        ),
      );
      await t.pump(Duration(milliseconds: ms));
      await t.runAsync(() async {
        final b = t.renderObject<RenderRepaintBoundary>(
          find.byKey(const Key('s')),
        );
        final img = await b.toImage(pixelRatio: 3);
        final out = Platform.environment['OUT'];
        if (out != null) {
          final png = await img.toByteData(format: ui.ImageByteFormat.png);
          File('$out/status-$ms.png')
              .writeAsBytesSync(png!.buffer.asUint8List());
        }
        final raw = (await img.toByteData())!;
        var grey = 0, solid = 0;
        double top = 0, bottom = 0;
        var nt = 0, nb = 0;
        // the label starts 40 css px in (28 orb box + gaps); the orb is left of it
        for (var y = 0; y < img.height; y++) {
          for (var x = 40 * 3; x < img.width; x++) {
            final i = (y * img.width + x) * 4;
            final a = raw.getUint8(i + 3);
            if (a < 230) continue; // glyph edges
            solid++;
            final r = raw.getUint8(i),
                g = raw.getUint8(i + 1),
                bl = raw.getUint8(i + 2);
            // every pixel sits on the line #6ec4ff -> white (the band's skirt): blue stays full, green follows red
            final k = (r - 0x6e) / (255 - 0x6e);
            final onLine =
                bl >= 235 && (g - (0xc4 + k * (255 - 0xc4))).abs() < 20;
            final nearWhite = lo(r, g, bl) >= 170;
            if (!onLine) grey++;
            if (!nearWhite) {
              if (y < img.height / 4) {
                top += r;
                nt++;
              } else {
                bottom += r;
                nb++;
              }
            }
          }
        }
        expect(solid, greaterThan(500), reason: 'glyphs drawn at $ms ms');
        expect(grey, lessThan(solid * 0.01), reason: 'grey pixels at $ms ms');
        if (nt > 50 && nb > 50) {
          expect(
            (top / nt - bottom / nb).abs(),
            lessThan(25),
            reason: 'vertical wash at $ms ms',
          );
        }
      });
    }
  });
}
