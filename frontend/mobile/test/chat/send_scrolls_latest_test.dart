import 'dart:collection';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jarvis_mobile/chat/chat_models.dart';
import 'package:jarvis_mobile/chat/message_list.dart';

String _id(String u) => u;

void main() {
  // ChatController.items is an UnmodifiableListView over one growing list: the "old" and "new" lists the widget
  // sees are the same object, so a send must still bring the newest message back into view (main.ts
  // scrollToBottomIfNeeded(true)), even while the user is reading far up the history.
  testWidgets('sending while scrolled up jumps back to the newest message', (t) async {
    final backing = <ChatItem>[
      for (var i = 0; i < 40; i++) ...[UserMsg('hỏi $i'), AssistantMsg('trả lời $i ' * 8)],
    ];
    final items = ValueNotifier<List<ChatItem>>(UnmodifiableListView(backing));
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
    final list = find.byType(Scrollable).first;
    await t.drag(list, const Offset(0, 3000)); // read old history (reversed list: drag down = older)
    await t.pumpAndSettle();
    final pos = t.state<ScrollableState>(list).position;
    expect(pos.pixels, greaterThan(500));

    backing.add(const UserMsg('tin mới'));
    items.value = UnmodifiableListView(backing); // same backing list, new view, as ChatController does
    await t.pump();
    await t.pump();
    expect(pos.pixels, 0);
    expect(find.text('tin mới'), findsOneWidget);
  });
}
