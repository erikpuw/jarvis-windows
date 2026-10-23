import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jarvis_mobile/chat/chat_controller.dart';
import 'package:jarvis_mobile/chat/home_screen.dart';
import 'package:jarvis_mobile/chat/lucide_glyphs.dart';
import 'package:jarvis_mobile/chat/morph_icon.dart';
import 'package:jarvis_mobile/chat/reader_card.dart';
import 'package:jarvis_mobile/chat/sessions_controller.dart';
import 'package:jarvis_mobile/net/api_client.dart';
import 'package:jarvis_mobile/net/server_config.dart';
import 'package:jarvis_mobile/theme/app_theme.dart';
import 'package:provider/provider.dart';

import 'fakes.dart';
import '../screens/screen_support.dart' show loadScreenFonts;

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  setUpAll(() async {
    expect(await loadScreenFonts(), isTrue);
  });
  late FakeSocket socket;
  late FakeApi api;
  late ChatController chat;
  late SessionsController sessions;
  Future<void> home(WidgetTester t) async {
    t.view.physicalSize = const Size(1170, 2532);
    t.view.devicePixelRatio = 3;
    addTearDown(t.view.reset);
    socket = FakeSocket();
    api = FakeApi();
    chat = ChatController(socket, api);
    sessions = SessionsController(socket, api, chat);
    addTearDown(() {
      sessions.dispose();
      chat.dispose();
      socket.dispose();
    });
    final now = DateTime.now();
    final today =
        DateTime(now.year, now.month, now.day, 12).millisecondsSinceEpoch ~/
        1000;
    final yesterday =
        DateTime(now.year, now.month, now.day - 1, 12).millisecondsSinceEpoch ~/
        1000;
    api.responses['/api/sessions/mine?limit=50'] = {
      'sessions': [
        {'session_id': 'web-a', 'title': 'Alpha', 'last_msg': today},
        {'session_id': 'web-b', 'title': 'Beta', 'last_msg': today},
        {'session_id': 'web-c', 'title': 'Gamma', 'last_msg': yesterday},
      ],
    };
    api.responses['/api/sessions/mine/web-a'] = {'messages': []};
    await t.pumpWidget(
      MultiProvider(
        providers: [
          ChangeNotifierProvider.value(value: ServerConfig()),
          Provider<ApiClient>.value(value: api),
          ChangeNotifierProvider.value(value: chat),
          ChangeNotifierProvider.value(value: sessions),
        ],
        child: MaterialApp(
          theme: buildAppTheme(),
          // tests have no WebView plugin: an open video is a plain box of the player's size
          home: HomeScreen(
            mediaBuilder: (_) => const ColoredBox(color: Colors.red),
          ),
          routes: {
            '/settings/menu': (_) => const Scaffold(body: Text('menu route')),
          },
        ),
      ),
    );
    await t.pump(const Duration(milliseconds: 100));
  }

  Future<void> open(WidgetTester t) async {
    await t.tap(find.byKey(const Key('home-sessions-btn')));
    await t.pump();
    await t.pump(const Duration(milliseconds: 300));
  }

  testWidgets(
    'the drawer lies over an open video (style.css --z-sessions 95 > --z-media 70)',
    (t) async {
      await home(t);
      socket.incoming.add({
        'type': 'media_open',
        'query': 'phim',
        'embed_url': 'https://www.youtube.com/embed/abc',
        'title': 'Phim',
      });
      await t.pump(const Duration(milliseconds: 50));
      expect(chat.media, isNotNull);
      await open(t);
      // the first rows sit where the 16:9 card is (top 56): the tap must reach the row, not the video
      await t.tap(find.byKey(const Key('session-web-a')));
      await t.pump();
      expect(socket.switched, ['web-a']);
    },
  );

  testWidgets(
    'the controls lie over an open video: the video sits only over the chat (user 2026-10-23)',
    (t) async {
      await home(t);
      socket.incoming.add({
        'type': 'media_open',
        'query': 'phim',
        'embed_url': 'https://www.youtube.com/embed/abc',
        'title': 'Phim',
      });
      await t.pump(const Duration(milliseconds: 50));
      Finder glyph(MorphGlyph g) =>
          find.byWidgetPredicate((w) => w is MorphIcon && w.icon == g);
      await t.tap(glyph(menuGlyph));
      await t.pump(const Duration(milliseconds: 400));
      // the open capsule hangs down over the 16:9 card (top 56): its TTS button must still take the tap
      await t.tap(glyph(volume2Glyph));
      await t.pump(const Duration(milliseconds: 50));
      expect(socket.sent.last, {'type': 'toggle_tts', 'enabled': false});
    },
  );

  testWidgets(
    'the reader card lies over an open video (style.css z-reader 85 > z-media 70)',
    (t) async {
      await home(t);
      socket.incoming.add({
        'type': 'media_open',
        'query': 'phim',
        'embed_url': 'https://www.youtube.com/embed/abc',
        'title': 'Phim',
      });
      await t.pump(const Duration(milliseconds: 50));
      chat.openReader('https://example.com/bai-viet', title: 'Bài viết');
      await t.pump(const Duration(milliseconds: 400));
      final video = find.byWidgetPredicate(
        (w) => w is ColoredBox && w.color == Colors.red,
      );
      final reader = find.byType(ReaderPanel);
      final overlap = t.getRect(video).intersect(t.getRect(reader));
      expect(
        overlap.isEmpty,
        isFalse,
        reason: 'the reader card covers part of the video',
      );
      final hit = t.hitTestOnBinding(overlap.center).path.map((e) => e.target);
      expect(hit, contains(t.renderObject(reader)));
      expect(hit, isNot(contains(t.renderObject(video))));
    },
  );

  testWidgets(
    'the house opens the drawer with the sessions grouped and the open one lit',
    (t) async {
      await home(t);
      await sessions.pick('web-a');
      await open(t);
      expect(find.text('Hôm nay'), findsOneWidget);
      expect(find.text('Hôm qua'), findsOneWidget);
      for (final id in ['web-a', 'web-b', 'web-c']) {
        expect(find.byKey(Key('session-$id')), findsOneWidget);
      }
      final row = find.byKey(const Key('session-web-a'));
      final container = t.widget<Container>(
        find.descendant(of: row, matching: find.byType(Container)).first,
      );
      expect(
        (container.decoration as BoxDecoration).color,
        const Color(0xFF111827),
      );
    },
  );
  testWidgets('picking a session closes the drawer and switches', (t) async {
    await home(t);
    await open(t);
    await t.tap(find.byKey(const Key('session-web-a')));
    await t.pump();
    await t.pump(const Duration(milliseconds: 300));
    expect(find.byKey(const Key('sessions-drawer')), findsNothing);
    expect(socket.switched, ['web-a']);
  });
  testWidgets(
    'while a turn runs a row tap does nothing and the row keeps its look',
    (t) async {
      await home(t);
      await open(t);
      socket.incoming.add({'type': 'status', 'state': 'thinking'});
      await t.pump();
      await t.tap(find.byKey(const Key('session-web-a')));
      await t.pump();
      await t.tap(find.byKey(const Key('sessions-new')));
      await t.pump();
      expect(find.byKey(const Key('sessions-drawer')), findsOneWidget);
      expect(socket.switched, isEmpty);
      expect(
        t.widget<Text>(find.text('Alpha')).style!.color,
        const Color(0xFF94A3B8),
      );
    },
  );
  testWidgets('Bảng điều khiển opens the Dashboard with its menu', (t) async {
    await home(t);
    await open(t);
    await t.tap(find.byKey(const Key('sessions-dash')));
    await t.pump();
    await t.pump(const Duration(milliseconds: 400));
    expect(find.text('menu route'), findsOneWidget);
  });
  testWidgets('the scrim closes the drawer', (t) async {
    await home(t);
    await open(t);
    await t.tapAt(const Offset(300, 300));
    await t.pump();
    await t.pump(const Duration(milliseconds: 300));
    expect(find.byKey(const Key('sessions-drawer')), findsNothing);
  });
}
