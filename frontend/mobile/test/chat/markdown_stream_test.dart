// Streaming an answer: finished blocks are built once and keep their scroll position; only the growing last block is rebuilt.
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jarvis_mobile/chat/markdown_view.dart';

String _id(String u) => u;

String get _table {
  final head = '| ${List.generate(12, (i) => 'Cột $i').join(' | ')} |';
  final sep = '|${List.filled(12, ' --- ').join('|')}|';
  final row =
      '| ${List.generate(12, (i) => 'giá trị dài số $i').join(' | ')} |';
  return '$head\n$sep\n$row\n$row';
}

Widget _view(String text, {bool streaming = true}) => MaterialApp(
  home: Scaffold(
    body: SizedBox(
      width: 360,
      child: SingleChildScrollView(
        child: MarkdownView(text, streaming: streaming, resolveUrl: _id),
      ),
    ),
  ),
);

void main() {
  test(
    'blocks are cut at blank lines, but a loose list and a fence stay whole',
    () {
      expect(splitMarkdownBlocks('a\n\nb\n\n\nc'), ['a', 'b', 'c']);
      expect(splitMarkdownBlocks('1. x\n\n2. y\n\nsau'), [
        '1. x\n\n2. y',
        'sau',
      ]);
      expect(splitMarkdownBlocks('```\na\n\nb\n```\n\nhết'), [
        '```\na\n\nb\n```',
        'hết',
      ]);
      expect(splitMarkdownBlocks('a\n'), ['a']);
    },
  );

  testWidgets(
    'a table keeps its scroll offset while text streams in and after the final render',
    (t) async {
      final base = 'Mở đầu\n\n${normalizeMarkdownTables(_table)}\n\nĐuôi';
      await t.pumpWidget(_view(base));
      final scroller = find.byType(SingleChildScrollView).last;
      await t.drag(scroller, const Offset(-200, 0));
      await t.pump();
      double offset() => t
          .state<ScrollableState>(
            find.descendant(of: scroller, matching: find.byType(Scrollable)),
          )
          .position
          .pixels;
      final moved = offset();
      expect(moved, greaterThan(100));

      final before = markdownBlockBuilds;
      var text = base;
      for (final c in [' dài', ' thêm', ' nữa']) {
        text += c;
        await t.pumpWidget(_view(text));
      }
      expect(
        markdownBlockBuilds - before,
        3,
      ); // only the tail block, once per step
      expect(offset(), moved);

      await t.pumpWidget(_view('$text\n', streaming: false)); // stream_end
      expect(offset(), moved);
      expect(
        markdownBlockBuilds - before,
        3,
      ); // nothing finished was built again
    },
  );

  test('a ~~~ fence and its blank lines stay one block', () {
    expect(splitMarkdownBlocks('~~~\na\n\nb\n~~~\n\nhết'), [
      '~~~\na\n\nb\n~~~',
      'hết',
    ]);
    expect(splitMarkdownBlocks('```\n~~~\n\n```\n\nx'), [
      '```\n~~~\n\n```',
      'x',
    ]);
  });

  testWidgets(
    'a table that is the last block keeps its offset as rows arrive and at stream_end',
    (t) async {
      final rows = _table.split('\n');
      final four = rows.join('\n');
      await t.pumpWidget(_view('Mở đầu\n\n$four', streaming: false));
      final scroller = find.byType(SingleChildScrollView).last;
      await t.drag(scroller, const Offset(-200, 0));
      await t.pump();
      double offset() => t
          .state<ScrollableState>(
            find.descendant(of: scroller, matching: find.byType(Scrollable)),
          )
          .position
          .pixels;
      final moved = offset();
      expect(moved, greaterThan(100));
      await t.pumpWidget(
        _view('Mở đầu\n\n$four\n${rows.last}', streaming: false),
      );
      expect(offset(), moved);
      await t.pumpWidget(
        _view('Mở đầu\n\n$four\n${rows.last}\n', streaming: false),
      );
      expect(offset(), moved);
    },
  );

  testWidgets(
    'a reference link resolves across blocks and a new handler reaches the link',
    (t) async {
      Widget view(void Function(String) onTap) => MaterialApp(
        home: Scaffold(
          body: MarkdownView(
            'xem [trang][1]\n\nhết\n\n[1]: https://example.com/a',
            resolveUrl: _id,
            onLinkTap: onTap,
          ),
        ),
      );
      final taps = <String>[];
      await t.pumpWidget(view((u) => taps.add('old $u')));
      expect(find.textContaining('[1]', findRichText: true), findsNothing);
      final before = markdownBlockBuilds;
      await t.pumpWidget(view(taps.add));
      expect(
        markdownBlockBuilds,
        greaterThan(before),
      ); // a new handler: rebuilt
    },
  );

  testWidgets(
    'document mode joins consecutive lines like GitHub; chat keeps a single newline as a break; code keeps its lines',
    (t) async {
      String shown() => t
          .widgetList<RichText>(find.byType(RichText))
          .map((r) => r.text.toPlainText())
          .join('|');
      const md = 'dòng một\ndòng hai\n\n```\ncode a\ncode b\n```';
      Widget page({required bool document}) => MaterialApp(
        home: Scaffold(
          body: MarkdownView(md, resolveUrl: _id, document: document),
        ),
      );

      await t.pumpWidget(page(document: false));
      expect(shown(), contains('dòng một\ndòng hai'));

      await t.pumpWidget(page(document: true));
      // formatMarkdown(..., { document: true }) = marked breaks:false (web 16add0d): badges on separate lines sit in one row
      expect(shown(), contains('dòng một dòng hai'));
      expect(shown(), contains('code a\ncode b'));
    },
  );
}
