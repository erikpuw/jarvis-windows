// Streaming one answer while the others stay put: finished messages are not rebuilt per chunk, and a drag mid-stream works.
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jarvis_mobile/chat/chat_models.dart';
import 'package:jarvis_mobile/chat/markdown_view.dart';
import 'package:jarvis_mobile/chat/message_list.dart';

String _id(String u) => u;

String _para(int i) =>
    'Đoạn $i: ${List.filled(18, 'chữ tiếng Việt dài').join(' ')}\n\n';

void main() {
  testWidgets('200 chunks + a drag: finished messages build 0 times per chunk', (
    t,
  ) async {
    final items = ValueNotifier<List<ChatItem>>([
      for (var i = 0; i < 6; i++) ...[
        UserMsg('câu hỏi $i'),
        AssistantMsg(_para(i) + _para(i + 1)),
      ],
      const AssistantMsg('', streaming: true),
    ]);
    await t.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: ValueListenableBuilder<List<ChatItem>>(
            valueListenable: items,
            builder: (_, v, _) => MessageList(items: v, resolveUrl: _id),
          ),
        ),
      ),
    );
    var text = '';
    await t.pump();
    markdownViewBuilds = 0;
    final sw = Stopwatch()..start();
    for (var i = 0; i < 200; i++) {
      text += 'từ$i ';
      items.value = [
        ...items.value.sublist(0, items.value.length - 1),
        AssistantMsg(text, streaming: true),
      ];
      await t.pump(const Duration(milliseconds: 16));
      if (i == 100) {
        await t.drag(find.byType(ListView), const Offset(0, 120));
        await t.pump();
      }
    }
    sw.stop();
    // only the streaming answer is walked, once per chunk; the finished ones never (before the fix: 628)
    // ignore: avoid_print
    print(
      'BENCH markdownViewBuilds=$markdownViewBuilds pumpMs=${sw.elapsedMilliseconds}',
    );
    expect(markdownViewBuilds, lessThanOrEqualTo(210));
  });

  testWidgets(
    'an edited finished row shows its new content while another streams',
    (t) async {
      final items = ValueNotifier<List<ChatItem>>([
        const UserMsg('chờ gửi', pending: true),
        const AssistantMsg('bản cũ'),
        const AssistantMsg('', streaming: true),
      ]);
      await t.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: ValueListenableBuilder<List<ChatItem>>(
              valueListenable: items,
              builder: (_, v, _) => MessageList(items: v, resolveUrl: _id),
            ),
          ),
        ),
      );
      items.value = [
        const UserMsg('chờ gửi'),
        const AssistantMsg('bản mới'),
        const AssistantMsg('chữ ', streaming: true),
      ];
      await t.pump(const Duration(milliseconds: 100));
      expect(find.byType(CircularProgressIndicator), findsNothing);
      expect(find.textContaining('bản mới'), findsOneWidget);
      expect(find.textContaining('bản cũ'), findsNothing);
      // the list shrinks: stale cached rows past its end are dropped, not shown
      items.value = [const UserMsg('chờ gửi')];
      await t.pump(const Duration(milliseconds: 100));
      expect(find.textContaining('bản mới'), findsNothing);
    },
  );
}
