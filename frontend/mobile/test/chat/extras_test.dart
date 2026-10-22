import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jarvis_mobile/chat/lucide_glyphs.dart';
import 'package:jarvis_mobile/chat/chat_controller.dart';
import 'package:jarvis_mobile/chat/home_screen.dart';
import 'package:jarvis_mobile/chat/status_orb.dart';
import 'package:jarvis_mobile/chat/image_lightbox.dart';
import 'package:jarvis_mobile/chat/media_player.dart';
import 'package:jarvis_mobile/chat/message_list.dart';
import 'package:jarvis_mobile/chat/reader_card.dart';
import 'package:jarvis_mobile/net/api_client.dart';
import 'package:jarvis_mobile/net/server_config.dart';
import 'package:jarvis_mobile/theme/app_theme.dart';
import 'package:provider/provider.dart';

import 'fakes.dart';

/// Phone surface, as in home_screen_test.dart: the screen has endless animations, so tests pump() instead of settling.
Future<({FakeSocket socket, ChatController chat})> pumpHome(
  WidgetTester t, {
  HomeScreen home = const HomeScreen(),
}) async {
  t.view.physicalSize = const Size(1170, 2532);
  t.view.devicePixelRatio = 3;
  addTearDown(t.view.reset);
  final socket = FakeSocket();
  final api = FakeApi();
  final chat = ChatController(socket, api);
  addTearDown(chat.dispose);
  await t.pumpWidget(
    MultiProvider(
      providers: [
        ChangeNotifierProvider.value(value: ServerConfig()),
        Provider<ApiClient>.value(value: api),
        ChangeNotifierProvider.value(value: chat),
      ],
      child: MaterialApp(theme: buildAppTheme(), routes: {'/': (_) => home}),
    ),
  );
  await t.pump(const Duration(milliseconds: 100));
  return (socket: socket, chat: chat);
}

Future<void> packet(
  WidgetTester t,
  FakeSocket socket,
  Map<String, dynamic> m,
) async {
  socket.incoming.add(m);
  await t.pump(const Duration(milliseconds: 50));
}

bool sentAny(FakeSocket socket, bool Function(Map<String, dynamic>) test) =>
    socket.sent.any(test);

void main() {
  Map<String, dynamic> step(
    String id,
    String status, [
    String label = 'Bước',
  ]) => {
    'type': 'flow_step',
    'step': {'id': id, 'label': label, 'status': status},
  };

  testWidgets('flow_step shows in island, folds and leaves', (t) async {
    final h = await pumpHome(t);
    await packet(t, h.socket, step('1', 'active', 'Định tuyến → general'));
    await run(
      t,
      const Duration(milliseconds: 500),
    ); // the capsule grows to its text
    expect(find.text('Đang xử lý'), findsOneWidget);
    await t.tap(find.text('Đang xử lý'));
    await run(
      t,
      const Duration(milliseconds: 800),
    ); // the card drops on the spring
    expect(find.textContaining('Định tuyến'), findsOneWidget);
    await packet(t, h.socket, step('1', 'completed', 'Định tuyến → general'));
    await run(t, const Duration(seconds: 1)); // DONE_MS passed
    expect(find.text('Hoàn thành'), findsOneWidget);
    await run(
      t,
      const Duration(seconds: 6),
    ); // folds after 5 s without a touch...
    await run(
      t,
      const Duration(seconds: 3),
    ); // ...lingers 2.5 s, narrows away in 0.3 s
    expect(find.text('Hoàn thành'), findsNothing);
    expect(find.textContaining('Định tuyến'), findsNothing);
  });

  testWidgets('Hoàn thành waits for the end of a burst of steps', (t) async {
    final h = await pumpHome(t);
    await packet(t, h.socket, step('1', 'active'));
    await packet(t, h.socket, step('1', 'completed'));
    await run(t, const Duration(milliseconds: 400));
    await packet(
      t,
      h.socket,
      step('2', 'active'),
    ); // inside DONE_MS: the flow goes on
    await run(
      t,
      const Duration(milliseconds: 600),
    ); // 1 s after the first completion
    expect(find.text('Hoàn thành'), findsNothing);
    expect(find.text('Đang xử lý'), findsOneWidget);
    await packet(t, h.socket, step('2', 'completed'));
    await run(t, const Duration(milliseconds: 500));
    expect(find.text('Hoàn thành'), findsNothing); // still inside DONE_MS
    await run(t, const Duration(milliseconds: 500));
    expect(find.text('Hoàn thành'), findsOneWidget);
  });

  testWidgets('a covered island keeps its timers still until it is back', (
    t,
  ) async {
    final h = await pumpHome(t);
    await packet(t, h.socket, step('1', 'completed'));
    await run(t, const Duration(seconds: 1));
    expect(find.text('Hoàn thành'), findsOneWidget);
    final nav = t.state<NavigatorState>(find.byType(Navigator));
    nav.push(MaterialPageRoute<void>(builder: (_) => const Scaffold()));
    await run(
      t,
      const Duration(milliseconds: 600),
    ); // Settings opens over the chat
    await run(
      t,
      const Duration(seconds: 10),
    ); // far past the linger: nothing runs under it
    nav.pop();
    await run(t, const Duration(milliseconds: 600));
    expect(find.text('Hoàn thành'), findsOneWidget);
    await run(t, const Duration(seconds: 3));
    expect(find.text('Hoàn thành'), findsNothing);
  });

  testWidgets('the same error twice in a row shows the island both times', (
    t,
  ) async {
    final h = await pumpHome(t);
    h.chat.reportError('Mic hỏng');
    await run(t, const Duration(milliseconds: 600));
    expect(find.text('Mic hỏng'), findsWidgets);
    await run(t, const Duration(seconds: 10));
    expect(find.text('Mic hỏng'), findsNothing);
    h.chat.reportError('Mic hỏng');
    await run(t, const Duration(milliseconds: 600));
    expect(find.text('Mic hỏng'), findsWidgets);
  });

  testWidgets('a failing file picker shows its error in the island', (t) async {
    await pumpHome(
      t,
      home: HomeScreen(pickFile: () async => throw Exception('no picker')),
    );
    await t.tap(byGlyph(plusGlyph));
    await run(t, const Duration(milliseconds: 600));
    expect(find.text('Không mở được bộ chọn tệp.'), findsWidgets);
  });

  testWidgets(
    'a link opens the browser, the trigger beside it opens the reader',
    (t) async {
      final launched = <Uri>[];
      final h = await pumpHome(
        t,
        home: HomeScreen(
          launch: (u) async {
            launched.add(u);
            return true;
          },
        ),
      );
      await packet(t, h.socket, {
        'type': 'text',
        'text': 'xem [bài báo](https://example.com/a) nhé',
      });
      await run(t, const Duration(milliseconds: 500));
      await t.tapOnText(find.textRange.ofSubstring('bài báo'));
      expect(launched, [Uri.parse('https://example.com/a')]);
      expect(h.chat.reader, isNull);
      await t.tap(find.byKey(const ValueKey('reader-trigger')));
      await run(t, const Duration(milliseconds: 300));
      expect(launched, hasLength(1));
      expect(h.chat.reader?.url, 'https://example.com/a');
      expect(h.chat.reader?.title, 'bài báo');
      h.chat.closeReader();
      await run(t, const Duration(milliseconds: 300));
      expect(
        find.byType(ReaderPanel),
        findsNothing,
      ); // the card has faded out and is gone
    },
  );

  testWidgets(
    'the chat is padded while the question box is up, then restored',
    (t) async {
      final h = await pumpHome(t);
      double bottom() {
        final list = t.widget<ListView>(
          find.descendant(
            of: find.byType(MessageList),
            matching: find.byType(ListView),
          ),
        );
        return (list.padding! as EdgeInsets).bottom;
      }

      expect(bottom(), 6);
      await packet(t, h.socket, {
        'type': 'interactive',
        'card': {'id': 'c1', 'type': 'approve', 'title': 'Cho phép?'},
      });
      await run(
        t,
        const Duration(milliseconds: 500),
      ); // the box rose, the padding glided
      expect(bottom(), greaterThan(6));
      await t.tap(find.text('Đồng ý'));
      await run(t, const Duration(milliseconds: 500));
      expect(bottom(), 6);
      expect(find.text('Cho phép?'), findsNothing); // the box has left
    },
  );

  testWidgets('a multiple select sends every picked value on submit', (
    t,
  ) async {
    final h = await pumpHome(t);
    await packet(t, h.socket, {
      'type': 'interactive',
      'card': {
        'id': 'c2',
        'type': 'select',
        'multiple': true,
        'options': [
          {'value': 'a', 'label': 'Mot'},
          {'value': 'b', 'label': 'Hai', 'selected': true},
          {'value': 'c', 'label': 'Ba'},
        ],
      },
    });
    await run(t, const Duration(milliseconds: 500));
    await t.tap(find.text('Mot'));
    await run(t, const Duration(milliseconds: 50));
    expect(
      sentAny(h.socket, (m) => m['type'] == 'interactive_response'),
      isFalse, // toggling answers nothing
    );
    await t.tap(find.text('Xác nhận'));
    await run(t, const Duration(milliseconds: 50));
    final sent = h.socket.sent.singleWhere(
      (m) => m['type'] == 'interactive_response',
    );
    expect(sent, {
      'type': 'interactive_response',
      'cardId': 'c2',
      'action': 'submit',
      'value': ['b', 'a'],
    });
  });

  testWidgets('ask panel sends interactive_response', (t) async {
    final h = await pumpHome(t);
    await packet(t, h.socket, {
      'type': 'interactive',
      'card': {
        'id': 'c1',
        'type': 'approve',
        'title': 'Cho phép?',
        'approveLabel': 'Đồng ý',
        'rejectLabel': 'Từ chối',
      },
    });
    await t.tap(find.text('Đồng ý'));
    await t.pump(const Duration(milliseconds: 50));
    expect(
      sentAny(
        h.socket,
        (m) =>
            m['type'] == 'interactive_response' &&
            m['cardId'] == 'c1' &&
            m['action'] == 'approve',
      ),
      isTrue,
    );
    expect(h.chat.ask, isNull);
  });

  testWidgets('an open media player stops the animations under it', (t) async {
    final h = await pumpHome(
      t,
      home: HomeScreen(mediaBuilder: (_) => const SizedBox()),
    );
    bool orbTicking() {
      final e = t.element(find.byType(StatusOrb));
      return TickerMode.valuesOf(e).enabled;
    }

    expect(orbTicking(), isTrue);
    await packet(t, h.socket, {
      'type': 'media_open',
      'query': 'phim',
      'embed_url': 'https://www.youtube.com/embed/abc',
      'title': 'Phim',
    });
    await run(t, const Duration(milliseconds: 100));
    expect(h.chat.media, isNotNull);
    expect(orbTicking(), isFalse);
    h.chat.closeMedia();
    await run(t, const Duration(milliseconds: 100));
    expect(orbTicking(), isTrue);
  });

  testWidgets('closing media sends media_state false', (t) async {
    // The player alone: HomeScreen would build the real WebView, which tests cannot host.
    final socket = FakeSocket();
    final chat = ChatController(socket, FakeApi());
    addTearDown(chat.dispose);
    await packet(t, socket, {
      'type': 'media_open',
      'query': 'phim',
      'embed_url': 'https://www.youtube.com/embed/abc',
      'title': 'Phim',
    });
    expect(
      sentAny(socket, (m) => m['type'] == 'media_state' && m['active'] == true),
      isTrue,
    );
    await t.pumpWidget(
      MaterialApp(
        theme: buildAppTheme(),
        home: MediaPlayer(
          media: chat.media!,
          onClose: chat.closeMedia,
          webBuilder: (_) => const SizedBox(),
        ),
      ),
    );
    await t.tap(find.byKey(const ValueKey('media-close')));
    await t.pump(const Duration(milliseconds: 50));
    expect(
      sentAny(
        socket,
        (m) => m['type'] == 'media_state' && m['active'] == false,
      ),
      isTrue,
    );
    expect(chat.media, isNull);
  });

  test('media player embeds YouTube in an iframe page like the web, not as the top page', () {
    // a bare embed URL as the WebView's own page sends no Referer: YouTube answers "Error 153"
    final html = MediaPlayer.embedPage('https://www.youtube.com/embed/abc');
    expect(html, contains('<iframe'));
    expect(
      html,
      contains('src="https://www.youtube.com/embed/abc?autoplay=1&amp;playsinline=1"'),
    );
    expect(html, contains('allow="autoplay; encrypted-media; picture-in-picture"'));
    expect(MediaPlayer.pageOrigin, startsWith('https://'));
  });

  testWidgets('output_file image opens lightbox on tap', (t) async {
    final h = await pumpHome(t);
    await packet(t, h.socket, {
      'type': 'output_file',
      'kind': 'image',
      'name': 'anh.png',
      'url': '/api/outputs/a.png',
      'download_url': '/api/outputs/a.png?download=1',
    });
    await t.pump(
      const Duration(milliseconds: 500),
    ); // the welcome fades out (400 ms) before the card is laid out
    await t.tap(find.byType(ImageResult));
    await t.pump(const Duration(milliseconds: 400));
    expect(find.byType(InteractiveViewer), findsOneWidget);
    await t.tap(find.byType(InteractiveViewer));
    await t.pump(const Duration(milliseconds: 400));
    expect(find.byType(InteractiveViewer), findsNothing);
  });
}

/// Pumps [d] in 50 ms frames: the island and the glides need several frames, as on a device (one big pump is one frame).
Future<void> run(WidgetTester t, Duration d) async {
  for (var left = d.inMilliseconds; left > 0; left -= 50) {
    await t.pump(Duration(milliseconds: left < 50 ? left : 50));
  }
}
