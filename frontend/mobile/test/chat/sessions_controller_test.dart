import 'dart:async';

import 'package:flutter_test/flutter_test.dart';
import 'package:jarvis_mobile/chat/chat_controller.dart';
import 'package:jarvis_mobile/chat/chat_models.dart';
import 'package:jarvis_mobile/chat/sessions_controller.dart';
import 'package:jarvis_mobile/net/jarvis_socket.dart';

import 'fakes.dart';

const listPath = '/api/sessions/mine?limit=50';
Map<String, dynamic> history(String text) => {
  'success': true,
  'messages': [
    {'role': 'user', 'content': text},
  ],
};
Future<void> flush() => Future<void>.delayed(Duration.zero);

void main() {
  late FakeSocket socket;
  late FakeApi api;
  late ChatController chat;
  late SessionsController sessions;
  setUp(() {
    socket = FakeSocket();
    api = FakeApi();
    chat = ChatController(socket, api);
    sessions = SessionsController(socket, api, chat);
    api.responses[listPath] = {'success': true, 'sessions': []};
    api.responses['/api/sessions/mine/web-a'] = history('A');
    api.responses['/api/sessions/mine/web-b'] = history('B');
  });
  tearDown(() {
    sessions.dispose();
    chat.dispose();
    socket.dispose();
  });
  Future<void> event(String id, {bool resumed = false}) async {
    socket.confirmed = id;
    socket.sessionCtl.add(SessionEvent(id, resumed: resumed));
    await flush();
  }

  test('sessionGroup uses local calendar days', () {
    final now = DateTime(2026, 10, 23, 9);
    int sec(DateTime d) => d.millisecondsSinceEpoch ~/ 1000;
    expect(sessionGroup(sec(DateTime(2026, 10, 23, 0, 10)), now), 'Hôm nay');
    expect(sessionGroup(sec(DateTime(2026, 10, 22, 23, 59)), now), 'Hôm qua');
    expect(sessionGroup(sec(DateTime(2026, 10, 20)), now), 'Cũ hơn');
  });
  test('pick switches the socket and draws that session', () async {
    api.responses['/api/sessions/mine/web-a'] = {
      'success': true,
      'messages': [
        {'role': 'user', 'content': 'A'},
        {'role': 'assistant', 'content': 'answer'},
      ],
    };
    await sessions.pick('web-a');
    expect(socket.switched, ['web-a']);
    expect(chat.items.length, 2);
    expect(sessions.activeId, 'web-a');
  });
  test('a pick while a turn runs does nothing', () async {
    socket.incoming.add({'type': 'status', 'state': 'thinking'});
    await flush();
    expect(sessions.locked, isTrue);
    await sessions.pick('web-a');
    sessions.startNew();
    expect(socket.switched, isEmpty);
    expect(sessions.activeId, isNull);
  });
  test(
    'the packet of the switch itself does not draw the history twice',
    () async {
      await sessions.pick('web-a');
      await event('web-a', resumed: true);
      expect(api.gets.where((p) => p == '/api/sessions/mine/web-a').length, 1);
    },
  );
  test('a reconnect redraws after clearing the old turn, but not during local playback', () async {
    await event('web-a');
    await event('web-a', resumed: true);
    expect(api.gets.where((p) => p == '/api/sessions/mine/web-a').length, 1);
    socket.incoming.add({'type': 'status', 'state': 'thinking'});
    await flush();
    await event('web-a', resumed: true);
    expect(api.gets.where((p) => p == '/api/sessions/mine/web-a').length, 2);
    chat.setPlaying(true);
    await event('web-a', resumed: true);
    expect(api.gets.where((p) => p == '/api/sessions/mine/web-a').length, 2);
    expect(chat.turnRunning, isTrue);
  });
  test('a slow history of an earlier pick is dropped', () async {
    final slow = Completer<Map<String, dynamic>>();
    api.responses['/api/sessions/mine/web-a'] = slow.future;
    final a = sessions.pick('web-a');
    await sessions.pick('web-b');
    slow.complete(history('A'));
    await a;
    expect((chat.items.single as UserMsg).text, 'B');
  });
  test('a different id from the server clears the chat', () async {
    await event('web-a');
    chat.showHistory([
      {'role': 'user', 'content': 'old'},
    ]);
    await event('web-z');
    expect(chat.items, isEmpty);
    expect(sessions.activeId, 'web-z');
  });
  test('the first reply of a session refreshes the list once', () async {
    socket.confirmed = 'web-a';
    socket.incoming.add({'type': 'stream_end'});
    socket.incoming.add({'type': 'stream_end'});
    await flush();
    expect(api.gets.where((p) => p == listPath).length, 1);
  });
  test('startNew resets the chat and asks for no session', () async {
    chat.showHistory([
      {'role': 'user', 'content': 'old'},
    ]);
    sessions.startNew();
    await flush();
    expect(socket.switched, [null]);
    expect(chat.welcomeVisible, isTrue);
    expect(sessions.activeId, isNull);
  });
  test(
    'refresh drops stale responses and clear invalidates in-flight requests',
    () async {
      final old = Completer<Map<String, dynamic>>();
      api.responses[listPath] = old.future;
      final first = sessions.refresh();
      api.responses[listPath] = {
        'sessions': [
          {'session_id': 'web-b', 'title': 'B', 'last_msg': 1},
        ],
      };
      await sessions.refresh();
      old.complete({
        'sessions': [
          {'session_id': 'web-a', 'title': 'A', 'last_msg': 1},
        ],
      });
      await first;
      expect(sessions.items.single.id, 'web-b');
      final pending = Completer<Map<String, dynamic>>();
      api.responses[listPath] = pending.future;
      final request = sessions.refresh();
      sessions.clear();
      pending.complete({
        'sessions': [
          {'session_id': 'web-a', 'title': 'A', 'last_msg': 1},
        ],
      });
      await request;
      expect(sessions.items, isEmpty);
    },
  );
}
