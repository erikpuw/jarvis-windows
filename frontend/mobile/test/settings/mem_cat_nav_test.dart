import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jarvis_mobile/chat/lucide_glyphs.dart';
import 'package:jarvis_mobile/settings/mem_widgets.dart';
import 'package:jarvis_mobile/theme/tokens.dart';

void main() {
  testWidgets('the active tab glows outside its box only, never fills it', (
    t,
  ) async {
    final key = GlobalKey();
    await t.pumpWidget(
      MaterialApp(
        home: Scaffold(
          backgroundColor: JTokens.surface,
          body: RepaintBoundary(
            key: key,
            child: MemCatNav(
              cats: const [
                MemCat(
                  id: 'a',
                  label: 'Learnings',
                  color: Color(0xFFA855F7),
                  icon: brainGlyph,
                ),
              ],
              active: 'a',
              onSelect: (_) {},
              counts: const {'a': 3},
            ),
          ),
        ),
      ),
    );
    final box = t.getRect(find.byKey(const Key('cat:a')));
    final origin = t.getTopLeft(find.byKey(key));
    late ByteData data;
    late int w;
    await t.runAsync(() async {
      final img =
          await (key.currentContext!.findRenderObject()!
                  as RenderRepaintBoundary)
              .toImage();
      w = img.width;
      data = (await img.toByteData())!;
    });
    int px(double x, double y, int c) =>
        data.getUint8((y.round() * w + x.round()) * 4 + c);
    // Just inside the left edge, between border and icon tile: only the white gradient over the panel colour.
    final x = box.left - origin.dx + 5, y = box.center.dy - origin.dy + 8;
    expect(
      px(x, y, 2) - px(x, y, 0),
      lessThan(40),
      reason: 'purple bled inside',
    );
  });
}
