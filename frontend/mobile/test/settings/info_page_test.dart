// Thông tin (pages.ts infoPage + index.ts loadReadme): the version bar, the README through the markdown view, its error lines.
import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:jarvis_mobile/settings/pages/info_page.dart';
import 'package:jarvis_mobile/chat/markdown_view.dart';

import 'catalog_fixtures.dart';
import 'fixtures.dart';

Future<List<http.Request>> _pump(
  WidgetTester t, {
  Map<String, http.Response Function(http.Request)> extra = const {},
}) async {
  final calls = <http.Request>[];
  await pumpPage(
    t,
    const InfoPage(),
    routed({
      'GET /api/system/readme': (_) => jsonOk(readmeJson()),
      ...extra,
    }, calls: calls),
  );
  await t.pump(const Duration(milliseconds: 50));
  return calls;
}

void main() {
  testWidgets(
    'README layout divs are hidden while their markdown content remains',
    (t) async {
      await _pump(
        t,
        extra: {
          'GET /api/system/readme': (_) => jsonOk({
            'success': true,
            'content': '# JARVIS\n\n<div align="center">\n\n**Trợ lý AI**\n\n</div>\n\n## Giới thiệu'
                .replaceAll('\n', '\r\n'),
          }),
        },
      );
      expect(find.textContaining('<div', findRichText: true), findsNothing);
      expect(find.textContaining('</div>', findRichText: true), findsNothing);
      expect(
        find.textContaining('Trợ lý AI', findRichText: true),
        findsOneWidget,
      );
      expect(find.text('Giới thiệu'), findsOneWidget);
    },
  );

  testWidgets('README div examples in code are preserved', (t) async {
    const examples =
        '```html\n<div align="center">\nexample\n</div>\n```\n\n~~~html\n<div>\nexample\n</div>\n~~~\n\n`<div align="center">`\n\n    <div>\n    example\n    </div>';
    await _pump(
      t,
      extra: {
        'GET /api/system/readme': (_) => jsonOk({
          'success': true,
          'content': '<div align="center">\n\n$examples\n\n</div>',
        }),
      },
    );
    final markdown = t.widget<MarkdownView>(find.byType(MarkdownView)).text;
    expect(markdown.trim(), examples);
  });

  testWidgets('external README badges keep their URL without a server prefix', (
    t,
  ) async {
    const url = 'https://img.shields.io/badge/Python-3.11-blue';
    await _pump(
      t,
      extra: {
        'GET /api/system/readme': (_) =>
            jsonOk({'success': true, 'content': '# JARVIS\n\n![Python]($url)'}),
      },
    );
    expect(t.takeException(), isNull);
    final image = t.widget<Image>(find.byType(Image));
    expect((image.image as NetworkImage).url, url);
  });

  testWidgets('version bar, README rendered as markdown', (t) async {
    final calls = await _pump(t);
    expect(calls.where((c) => c.url.path == '/api/system/readme').length, 1);
    for (final s in [
      'Thông tin',
      'Phiên bản:',
      'v1.0.0',
      'Nền tảng:',
      'Windows · Desktop Native',
      'Nguồn dữ liệu:',
      'README.md',
      'Tải lại tài liệu',
      'Chat',
      'Giọng nói',
    ]) {
      expect(find.text(s), findsWidgets, reason: s);
    }
    expect(find.textContaining('Trợ lý', findRichText: true), findsOneWidget);
    expect(find.text('Đang nạp nội dung tài liệu README.md…'), findsNothing);
  });

  testWidgets('loading line before the answer', (t) async {
    final gate = Completer<void>();
    await pumpPage(
      t,
      const InfoPage(),
      MockClient((_) async {
        await gate.future;
        return jsonOk(readmeJson());
      }),
    );
    expect(find.text('Đang nạp nội dung tài liệu README.md…'), findsOneWidget);
    gate.complete();
    await t.pump(const Duration(milliseconds: 50));
    expect(find.text('Đang nạp nội dung tài liệu README.md…'), findsNothing);
  });

  testWidgets('Tải lại tài liệu fetches again', (t) async {
    final calls = await _pump(t);
    await t.tap(find.text('Tải lại tài liệu'));
    await t.pump(const Duration(milliseconds: 50));
    expect(calls.where((c) => c.url.path == '/api/system/readme').length, 2);
  });

  testWidgets("success:false shows web's error text", (t) async {
    await _pump(
      t,
      extra: {
        'GET /api/system/readme': (_) => jsonOk({
          'success': false,
          'error': 'README.md not found',
          'content': '',
        }),
      },
    );
    expect(
      find.text('Không tải được tài liệu README.md: README.md not found'),
      findsOneWidget,
    );
  });

  testWidgets('an HTTP failure shows Lỗi nạp tài liệu README.md', (t) async {
    await _pump(
      t,
      extra: {
        'GET /api/system/readme': (_) => jsonOk({'detail': 'down'}, 500),
      },
    );
    expect(find.text('Lỗi nạp tài liệu README.md: down'), findsOneWidget);
  });
}
