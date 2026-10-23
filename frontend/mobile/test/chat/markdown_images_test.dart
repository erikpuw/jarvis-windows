import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter_svg/flutter_svg.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jarvis_mobile/chat/markdown_view.dart';

void main() {
  setUp(() => svg.cache.clear());

  testWidgets('Shields badges use compact PNGs and preserve query parameters', (
    t,
  ) async {
    const source =
        'https://img.shields.io/badge/Python-3.11%2B-blue.SVG?style=flat';
    const png =
        'https://img.shields.io/badge/Python-3.11%2B-blue.png?style=flat';
    final recorder = ui.PictureRecorder();
    Canvas(
      recorder,
    ).drawRect(const Rect.fromLTWH(0, 0, 92, 20), Paint()..color = Colors.blue);
    final picture = recorder.endRecording();
    final image = await t.runAsync(() => picture.toImage(92, 20));
    picture.dispose();
    PaintingBinding.instance.imageCache.putIfAbsent(
      const NetworkImage(png),
      () =>
          OneFrameImageStreamCompleter(Future.value(ImageInfo(image: image!))),
    );
    addTearDown(PaintingBinding.instance.imageCache.clear);
    await t.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SizedBox(
            width: 390,
            child: MarkdownView(
              '[![Python]($source)](https://python.org) ![Python]($source)',
              document: true,
              resolveUrl: (u) => u,
            ),
          ),
        ),
      ),
    );
    await t.pumpAndSettle();
    final badges = find.byType(Image);
    expect(badges, findsNWidgets(2));
    expect(find.byType(SvgPicture), findsNothing);
    expect((t.widget<Image>(badges.first).image as NetworkImage).url, png);
    expect(t.getSize(badges.first), const Size(92, 20));
    expect(t.getTopLeft(badges.first).dy, t.getTopLeft(badges.last).dy);
    expect(t.takeException(), isNull);
  });

  testWidgets('document SVG badges keep their intrinsic size and share a row', (
    t,
  ) async {
    const a = 'https://example.com/Python.svg';
    const b = 'https://example.com/Tests.SVG?style=flat';
    await t.runAsync(() async {
      for (final url in [a, b]) {
        await svg.cache.putIfAbsent(
          SvgNetworkLoader(url).cacheKey(null),
          () => const SvgStringLoader(
            '<svg xmlns="http://www.w3.org/2000/svg" width="120" height="20" viewBox="0 0 120 20"><rect width="120" height="20" fill="#007ec6"/></svg>',
          ).loadBytes(null),
        );
      }
    });
    await t.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SizedBox(
            width: 390,
            child: MarkdownView(
              '![Python]($a)\n![Tests]($b)',
              document: true,
              resolveUrl: (u) => u,
            ),
          ),
        ),
      ),
    );
    await t.pumpAndSettle();
    final badges = find.byType(SvgPicture);
    expect(badges, findsNWidgets(2));
    expect(t.getSize(badges.first), const Size(120, 20));
    expect(t.getTopLeft(badges.first).dy, t.getTopLeft(badges.last).dy);
    expect(find.text('Python'), findsNothing);
    expect(find.text('Tests'), findsNothing);
    expect(t.takeException(), isNull);
  });

  testWidgets('raster markdown images still use Image.network', (t) async {
    await t.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: MarkdownView(
            '![Photo](https://example.com/photo.png)',
            resolveUrl: (u) => u,
          ),
        ),
      ),
    );
    expect(find.byType(SvgPicture), findsNothing);
    expect(
      (t.widget<Image>(find.byType(Image)).image as NetworkImage).url,
      'https://example.com/photo.png',
    );
  });
}
