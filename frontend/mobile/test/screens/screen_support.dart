// Shared by the screenshot tests (flutter test test/screens --run-skipped): fonts that look like a phone's, 60 fps pumping, PNG output.
import 'dart:io';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

Directory? materialFonts() {
  var dir = File(Platform.resolvedExecutable).parent;
  for (var i = 0; i < 8; i++) {
    final d = Directory('${dir.path}/bin/cache/artifacts/material_fonts');
    if (d.existsSync()) return d;
    dir = dir.parent;
  }
  final root = Platform.environment['FLUTTER_ROOT'];
  if (root != null) {
    final d = Directory('$root/bin/cache/artifacts/material_fonts');
    if (d.existsSync()) return d;
  }
  return null;
}

File? lucideFont() {
  final cfg = File('.dart_tool/package_config.json').readAsStringSync();
  final m = RegExp(r'"name": "lucide_icons_flutter",\s*"rootUri": "([^"]+)"')
      .firstMatch(cfg);
  if (m == null) return null;
  final root = Uri.parse(m.group(1)!);
  final dir = Directory.fromUri(Directory('.dart_tool').uri.resolveUri(root));
  final f = Directory('${dir.path}/assets').existsSync()
      ? Directory('${dir.path}/assets')
            .listSync()
            .whereType<File>()
            .where((f) => f.path.endsWith('.ttf'))
            .toList()
      : <File>[];
  return f.isEmpty
      ? null
      : (f.firstWhere(
          (x) => x.path.toLowerCase().contains('lucide.ttf'),
          orElse: () => f.first,
        ));
}

Future<bool> loadScreenFonts() async {
  final dir = materialFonts();
  if (dir == null) return false;
  Future<void> load(String family, List<(String, FontWeight)> files) async {
    final loader = FontLoader(family);
    for (final (name, _) in files) {
      final bytes = File('${dir.path}/$name').readAsBytesSync();
      loader.addFont(Future.value(ByteData.sublistView(bytes)));
    }
    await loader.load();
  }

  const roboto = [
    ('roboto-regular.ttf', FontWeight.w400),
    ('roboto-medium.ttf', FontWeight.w500),
    ('roboto-bold.ttf', FontWeight.w700),
  ];
  await load('Roboto', roboto);
  final lexend = FontLoader('Lexend')
    ..addFont(
      Future.value(
        ByteData.sublistView(File('assets/fonts/Lexend.ttf').readAsBytesSync()),
      ),
    );
  await lexend.load();
  final icons = FontLoader('MaterialIcons')
    ..addFont(
      Future.value(
        ByteData.sublistView(
          File('${dir.path}/materialicons-regular.otf').readAsBytesSync(),
        ),
      ),
    );
  await icons.load();
  final lucide = lucideFont();
  if (lucide != null) {
    final l = FontLoader('packages/lucide_icons_flutter/Lucide')
      ..addFont(Future.value(ByteData.sublistView(lucide.readAsBytesSync())));
    await l.load();
  }
  for (final mono in ['Menlo', 'monospace']) {
    await load(mono, roboto);
  }
  return true;
}

/// 60 fps frames: the spring and orb tick once per frame (one big pump() is one 100 ms step at most).
Future<void> advance(WidgetTester t, int ms) async {
  for (var i = 0; i < ms ~/ 16; i++) {
    await t.pump(const Duration(milliseconds: 16));
  }
}

Future<void> shot(WidgetTester t, GlobalKey key, String name) async {
  final boundary =
      key.currentContext!.findRenderObject()! as RenderRepaintBoundary;
  await t.runAsync(() async {
    final image = await boundary.toImage(pixelRatio: 3);
    final data = await image.toByteData(format: ui.ImageByteFormat.png);
    final out = File('build/screens/$name.png')..createSync(recursive: true);
    out.writeAsBytesSync(data!.buffer.asUint8List());
  });
}
