import 'package:flutter_test/flutter_test.dart';
import 'package:jarvis_mobile/chat/command_suggest.dart';
import 'package:jarvis_mobile/chat/markdown_view.dart';

void main() {
  test('a table gets blank lines around it', () {
    const md = 'Giá:\n| a | b |\n| --- | --- |\n| 1 | 2 |\n**TP.HCM**';
    expect(
      normalizeMarkdownTables(md),
      'Giá:\n\n| a | b |\n| --- | --- |\n| 1 | 2 |\n\n**TP.HCM**',
    );
  });

  test('a table inside a code fence is left alone', () {
    const md = '```\n| a | b |\n| --- | --- |\n```';
    expect(normalizeMarkdownTables(md), md);
  });

  test('a streaming tail table is cut off and counted', () {
    final t = streamingTableTail(
      'Xin chào\n\n| a | b | c |\n| --- | --- | --- |\n| 1',
    );
    expect(t!.head, 'Xin chào\n');
    expect(t.cols, 3);
    expect(
      streamingTableTail('| a | b |\n| --- | --- |\n| 1 | 2 |\n\nHết'),
      isNull,
    );
    expect(streamingTableTail('chỉ có chữ'), isNull);
  });

  test('active token is the word before the caret', () {
    final t = activeToken('mở /che app', 7);
    expect((t.token, t.start, t.end), ('/che', 3, 7));
    expect(activeToken('', 0).token, '');
  });
}
