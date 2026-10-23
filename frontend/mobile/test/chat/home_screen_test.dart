import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jarvis_mobile/auth/auth_controller.dart';
import 'package:jarvis_mobile/auth/auth_user.dart';
import 'package:jarvis_mobile/chat/lucide_glyphs.dart';
import 'package:jarvis_mobile/chat/chat_controller.dart';
import 'package:jarvis_mobile/chat/chat_models.dart';
import 'package:jarvis_mobile/chat/command_bar.dart';
import 'package:jarvis_mobile/chat/home_screen.dart';
import 'package:jarvis_mobile/chat/sessions_controller.dart';
import 'package:jarvis_mobile/chat/markdown_view.dart';
import 'package:jarvis_mobile/chat/metal_send_button.dart';
import 'package:jarvis_mobile/chat/status_label.dart';
import 'package:jarvis_mobile/chat/status_orb.dart';
import 'package:jarvis_mobile/chat/stream_loader.dart';
import 'package:jarvis_mobile/chat/welcome_view.dart';
import 'package:jarvis_mobile/main.dart';
import 'package:jarvis_mobile/net/api_client.dart';
import 'package:jarvis_mobile/net/server_config.dart';
import 'package:jarvis_mobile/theme/app_theme.dart';
import 'package:jarvis_mobile/voice/audio_out.dart';
import 'package:jarvis_mobile/voice/voice_input.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';
import 'package:provider/provider.dart';

import 'fakes.dart';

class Harness {
  Harness(this.socket, this.chat, this.api);
  final FakeSocket socket;
  final ChatController chat;
  final FakeApi api;

  Future<void> packet(WidgetTester t, Map<String, dynamic> m) async {
    socket.incoming.add(m);
    await t.pump(const Duration(milliseconds: 50));
  }
}

/// Phone surface (390x844 logical, dpr 3). The screen has endless animations (orb, loader), so tests use pump(), not pumpAndSettle().
Future<Harness> pumpHome(
  WidgetTester t, {
  String? initialFile,
  VoiceInput? voiceInput,
}) async {
  t.view.physicalSize = const Size(1170, 2532);
  t.view.devicePixelRatio = 3;
  addTearDown(t.view.reset);
  final cfg = ServerConfig();
  final socket = FakeSocket();
  final api = FakeApi();
  final chat = ChatController(socket, api);
  final sessions = SessionsController(socket, api, chat);
  addTearDown(sessions.dispose);
  addTearDown(chat.dispose);
  await t.pumpWidget(
    MultiProvider(
      providers: [
        ChangeNotifierProvider.value(value: cfg),
        Provider<ApiClient>.value(value: api),
        ChangeNotifierProvider.value(value: chat),
        ChangeNotifierProvider.value(value: sessions),
      ],
      child: MaterialApp(
        theme: buildAppTheme(),
        routes: {
          '/': (_) =>
              HomeScreen(initialFile: initialFile, voiceInput: voiceInput),
          '/settings': (_) => const Scaffold(body: Text('settings page')),
        },
      ),
    ),
  );
  await t.pump(const Duration(milliseconds: 100));
  return Harness(socket, chat, api);
}

Finder _userBubbleFrame() => find.byWidgetPredicate((w) {
  if (w is! DecoratedBox) return false;
  final d = w.decoration;
  return d is BoxDecoration &&
      d.borderRadius is BorderRadius &&
      (d.borderRadius! as BorderRadius).topLeft.x == 18;
});

String get _table12 {
  final head = '| ${List.generate(12, (i) => 'Cột $i').join(' | ')} |';
  final sep = '|${List.filled(12, ' --- ').join('|')}|';
  final row =
      '| ${List.generate(12, (i) => 'giá trị dài số $i').join(' | ')} |';
  return '$head\n$sep\n$row\n$row';
}

void main() {
  testWidgets('a tap on the empty screen or the chat closes the keyboard', (
    t,
  ) async {
    await pumpHome(t);
    final field = find.byType(TextField);
    await t.tap(field);
    await t.pump();
    expect(t.widget<TextField>(field).focusNode!.hasFocus, isTrue);
    await t.tapAt(const Offset(195, 300)); // empty area above the bar
    await t.pump();
    expect(t.widget<TextField>(field).focusNode!.hasFocus, isFalse);
    // tapping the field itself keeps it
    await t.tap(field);
    await t.pump();
    expect(t.widget<TextField>(field).focusNode!.hasFocus, isTrue);
  });

  testWidgets('assistant answer has no bubble, user has bubble', (t) async {
    final h = await pumpHome(t);
    await t.enterText(find.byType(TextField), 'xin chào');
    await t.tap(find.byType(MetalSendButton));
    await t.pump(const Duration(milliseconds: 50));
    await h.packet(t, {'type': 'text', 'text': 'câu trả lời'});

    final user = find.text('xin chào');
    expect(user, findsOneWidget);
    expect(
      find.ancestor(of: user, matching: _userBubbleFrame()),
      findsOneWidget,
    );
    final answer = find.textContaining('câu trả lời', findRichText: true);
    expect(answer, findsOneWidget);
    expect(
      find.ancestor(of: answer, matching: _userBubbleFrame()),
      findsNothing,
    );
    // the answer's text uses the chat colour
    final rich = t.widget<RichText>(answer);
    expect(rich.text.style?.color, const Color(0xFFE5E7EB));
  });

  testWidgets('wide table scrolls inside frame', (t) async {
    final h = await pumpHome(t);
    await h.packet(t, {'type': 'text', 'text': _table12});
    expect(t.takeException(), isNull);
    final scroller = find.byWidgetPredicate(
      (w) => w is SingleChildScrollView && w.scrollDirection == Axis.horizontal,
    );
    expect(scroller, findsOneWidget);
    // the table is wider than the screen, so the frame scrolls
    final table = t.getSize(find.byType(Table));
    expect(table.width, greaterThan(390));
    expect(t.getSize(scroller).width, lessThanOrEqualTo(390));
  });

  testWidgets('code block is highlighted, scrolls and has a copy button', (
    t,
  ) async {
    final h = await pumpHome(t);
    await h.packet(t, {
      'type': 'text',
      'text': '```dart\nvoid main() { print("a very long line of code that must scroll sideways"); }\n```',
    });
    expect(t.takeException(), isNull);
    expect(find.text('Sao chép'), findsOneWidget);
    expect(find.text('dart'), findsOneWidget);
    expect(
      find.byWidgetPredicate(
        (w) =>
            w is SingleChildScrollView && w.scrollDirection == Axis.horizontal,
      ),
      findsOneWidget,
    );
  });

  testWidgets('welcome hides after first message', (t) async {
    final h = await pumpHome(t);
    expect(find.byType(WelcomeView), findsOneWidget);
    await h.packet(t, {
      'type': 'welcome',
      'greeting': 'Chào buổi tối',
      'tools': ['a', 'b'],
    });
    expect(find.text('Chào buổi tối'), findsOneWidget);

    await t.enterText(find.byType(TextField), 'hi');
    await t.tap(find.byType(MetalSendButton));
    await t.pump(const Duration(milliseconds: 100));
    await t.pump(const Duration(milliseconds: 500));
    expect(find.byType(WelcomeView), findsNothing);
  });

  testWidgets('send button sends transcript', (t) async {
    final h = await pumpHome(t);
    await t.enterText(find.byType(TextField), '  gửi cái này  ');
    await t.tap(find.byType(MetalSendButton));
    await t.pump(const Duration(milliseconds: 50));
    expect(h.socket.sent.single, {
      'type': 'transcript',
      'text': 'gửi cái này',
      'isFinal': true,
    });
    expect(
      t.widget<TextField>(find.byType(TextField)).controller!.text,
      isEmpty,
    );
  });

  testWidgets('empty input does not send', (t) async {
    final h = await pumpHome(t);
    await t.tap(find.byType(MetalSendButton));
    await t.pump(const Duration(milliseconds: 50));
    expect(h.socket.sent, isEmpty);
  });

  String shownText(WidgetTester t) =>
      t.widget<MarkdownView>(find.byType(MarkdownView)).text;

  testWidgets('the loader sits at the left, not centred', (t) async {
    final h = await pumpHome(t);
    await h.packet(t, {'type': 'stream_start'});
    final at = t.getCenter(find.byType(StreamLoader));
    expect(at.dx, lessThan(60)); // 390 wide: a centred loader would be near 195
  });

  testWidgets('first chunk: the loader collapses, then letters are typed', (
    t,
  ) async {
    final h = await pumpHome(t);
    await h.packet(t, {'type': 'stream_start'});
    expect(find.byType(StreamLoader), findsOneWidget);
    await h.packet(t, {'type': 'text_chunk', 'text': 'x' * 120});
    // streamHoldUntil: 200 ms with no letter, the balls shrink meanwhile
    await t.pump(const Duration(milliseconds: 100));
    expect(find.byType(StreamLoader), findsOneWidget);
    expect(shownText(t), isEmpty);
    await t.pump(const Duration(milliseconds: 400));
    expect(find.byType(StreamLoader), findsNothing); // gone after 340 ms
    final partial = shownText(t).length;
    expect(partial, inInclusiveRange(1, 119)); // typed, never the whole chunk
    for (var i = 0; i < 40; i++) {
      await t.pump(const Duration(milliseconds: 50));
    }
    expect(shownText(t).length, 120);
  });

  testWidgets(
    'a second chunk after a catch-up types on the next frames, no new hold',
    (t) async {
      final h = await pumpHome(t);
      await h.packet(t, {'type': 'stream_start'});
      await h.packet(t, {'type': 'text_chunk', 'text': 'abc'});
      for (var i = 0; i < 30; i++) {
        await t.pump(const Duration(milliseconds: 50));
      }
      expect(shownText(t), 'abc'); // caught up, the loop has stopped
      await h.packet(t, {'type': 'text_chunk', 'text': 'x' * 60});
      for (var i = 0; i < 4; i++) {
        await t.pump(
          const Duration(milliseconds: 16),
        ); // 64 ms, far under the 200 ms first hold
      }
      expect(shownText(t).length, greaterThan(3));
    },
  );

  // main.ts typeStep runs on every requestAnimationFrame: the text grows each frame, not in 30 fps chunks.
  testWidgets('typing reveals text on every frame like the web', (t) async {
    final h = await pumpHome(t);
    await h.packet(t, {'type': 'stream_start'});
    await h.packet(t, {'type': 'text_chunk', 'text': 'x' * 3000});
    for (var i = 0; i < 20; i++) {
      await t.pump(const Duration(milliseconds: 16)); // past the hold
    }
    var changes = 0;
    var last = shownText(t).length;
    for (var i = 0; i < 62; i++) {
      // one second at 60 fps
      await t.pump(const Duration(milliseconds: 16));
      final n = shownText(t).length;
      if (n != last) changes++;
      last = n;
    }
    expect(changes, greaterThanOrEqualTo(58)); // ~every one of the 62 frames
  });

  testWidgets('stream_end renders everything at once', (t) async {
    final h = await pumpHome(t);
    await h.packet(t, {'type': 'stream_start'});
    await h.packet(t, {'type': 'text_chunk', 'text': 'y' * 300});
    await t.pump(const Duration(milliseconds: 300));
    expect(shownText(t).length, lessThan(300));
    await h.packet(t, {'type': 'stream_end'});
    expect(shownText(t).length, 300);
  });

  testWidgets(
    'the bar sits 18px from the very bottom, the JARVIS label under it',
    (t) async {
      // an iPhone home indicator: the web page adds no safe-area inset to #command-container, so neither does the app
      t.view.padding = const FakeViewPadding(top: 141, bottom: 102);
      t.view.viewPadding = const FakeViewPadding(top: 141, bottom: 102);
      addTearDown(t.view.resetPadding);
      await pumpHome(t);
      final bar = t.getBottomLeft(find.byType(CommandBar)).dy;
      expect(bar, 844 - 18);
      final label = find.text('JARVIS');
      expect(label, findsOneWidget);
      final box = t.getRect(label);
      expect(bar, closeTo(826, 0.5));
      expect(box.center.dx, closeTo(195, 0.5)); // left: 50%, centred
      expect(box.bottom, closeTo(842, 0.5)); // bottom: 2px
      expect(
        box.top,
        closeTo(842 - 15.2, 0.5),
      ); // line-height normal: the box web puts at 2-17px
      expect(box.top - bar, inInclusiveRange(0, 1.5)); // 1px under the bar
      final style = t.widget<Text>(label).style!;
      expect(style.fontSize, 13);
      expect(style.letterSpacing, 4);
      expect(style.fontWeight, FontWeight.w400);
      expect(style.color, const Color(0x337BD3FC)); // rgba(123,211,252,.2)
    },
  );

  testWidgets('status row follows the state', (t) async {
    final h = await pumpHome(t);
    expect(find.text('Sẵn sàng'), findsOneWidget);
    await h.packet(t, {'type': 'status', 'state': 'thinking'});
    await t.pump(const Duration(milliseconds: 500));
    // the busy label is painted glyph by glyph with the sheen gradient (SheenText), not a Text widget
    expect(
      find.byWidgetPredicate((w) => w is SheenText && w.text == 'Đang nghĩ…'),
      findsOneWidget,
    );
  });

  testWidgets('controls capsule opens, toggles TTS and opens settings', (
    t,
  ) async {
    final h = await pumpHome(t);
    await t.tap(byGlyph(menuGlyph));
    await t.pump(const Duration(milliseconds: 400));
    expect(byGlyph(xGlyph), findsOneWidget);

    await t.tap(byGlyph(volume2Glyph));
    await t.pump(const Duration(milliseconds: 50));
    expect(h.socket.sent.last, {'type': 'toggle_tts', 'enabled': false});
    expect(byGlyph(volumeXGlyph), findsOneWidget);

    await t.tap(find.byIcon(LucideIcons.settings));
    await t.pump(
      const Duration(milliseconds: 100),
    ); // the route is built on this frame
    await t.pump(const Duration(milliseconds: 400));
    expect(find.text('settings page'), findsOneWidget);
  });

  testWidgets('hide button fades the chat and bar away', (t) async {
    await pumpHome(t);
    await t.tap(byGlyph(menuGlyph));
    await t.pump(const Duration(milliseconds: 400));
    await t.tap(byGlyph(chevronDownGlyph));
    await t.pump();
    await t.pump(const Duration(milliseconds: 400));
    final fades = find
        .ancestor(of: find.byType(TextField), matching: find.byType(Opacity))
        .evaluate()
        .map((e) => (e.widget as Opacity).opacity);
    expect(fades, contains(0.0));
  });

  testWidgets('typing / opens the suggestions and a pick fills the input', (
    t,
  ) async {
    final h = await pumpHome(t);
    h.api.responses['/api/command-bar/skills'] = {
      'success': true,
      'commands': [
        {'name': 'check_system', 'description': 'Kiểm tra máy'},
      ],
    };
    h.api.responses['/api/command-bar/context'] = {
      'success': true,
      'mentions': <Object>[],
      'files': <Object>[],
    };
    await t.tap(find.byType(TextField));
    await t.pump(const Duration(milliseconds: 50));
    await t.enterText(find.byType(TextField), '/chec');
    await t.pump(const Duration(milliseconds: 50));
    expect(find.text('/check_system'), findsOneWidget);
    await t.tap(find.text('/check_system'));
    await t.pump(const Duration(milliseconds: 50));
    expect(
      t.widget<TextField>(find.byType(TextField)).controller!.text,
      '/check_system ',
    );
    expect(find.text('/check_system'), findsNothing);
  });

  testWidgets('a pinned file is sent with an empty input', (t) async {
    final h = await pumpHome(t, initialFile: '/tmp/a.png');
    await t.tap(find.byType(MetalSendButton));
    await t.pump(const Duration(milliseconds: 50));
    expect(h.api.uploads, ['/api/upload|/tmp/a.png']);
    expect(h.socket.sent.single, {
      'type': 'transcript',
      'text': '',
      'attachmentId': 'att1',
      'isFinal': true,
    });
  });

  testWidgets(
    'hiding the bar stops the send button loops, the orb keeps going',
    (t) async {
      await pumpHome(t);
      expect(
        t.widget<MetalSendButton>(find.byType(MetalSendButton)).active,
        isTrue,
      );
      await t.tap(byGlyph(menuGlyph));
      await t.pump(const Duration(milliseconds: 400));
      await t.tap(byGlyph(chevronDownGlyph));
      await t.pump(const Duration(milliseconds: 400));
      expect(
        t.widget<MetalSendButton>(find.byType(MetalSendButton)).active,
        isFalse,
      );
      expect(find.byType(StatusOrb), findsOneWidget);
    },
  );

  testWidgets('JarvisApp connects the socket once and reconnects on resume', (
    t,
  ) async {
    t.view.physicalSize = const Size(1170, 2532);
    t.view.devicePixelRatio = 3;
    addTearDown(t.view.reset);
    final socket = FakeSocket();
    await t.pumpWidget(JarvisApp(cfg: ServerConfig(), socket: socket));
    await t.pump(const Duration(milliseconds: 100));
    expect(socket.connects, 1);
    expect(socket.reconnects, 0);
    t.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
    t.binding.handleAppLifecycleStateChanged(AppLifecycleState.hidden);
    t.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
    expect(socket.reconnects, 0); // going away does not reconnect
    t.binding.handleAppLifecycleStateChanged(AppLifecycleState.hidden);
    t.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
    t.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    expect(socket.reconnects, 1);
    expect(socket.connects, 1);
    expect(find.byType(HomeScreen), findsOneWidget);
    await t.pumpWidget(
      const SizedBox(),
    ); // dispose the app: its timers and tickers go
  });

  testWidgets(
    'JarvisApp keeps the chat and session when auth notifies without a new user',
    (t) async {
      t.view.physicalSize = const Size(1170, 2532);
      t.view.devicePixelRatio = 3;
      addTearDown(t.view.reset);
      final cfg = ServerConfig();
      final socket = FakeSocket();
      final auth = AuthController(ApiClient(cfg))..setAuthenticatedForTesting();
      await t.pumpWidget(JarvisApp(cfg: cfg, socket: socket, auth: auth));
      await t.pump(const Duration(milliseconds: 100));
      expect(socket.reconnects, 0);
      // saving the profile refreshes the same user (refreshUser) and login notifies twice: neither is a new identity
      auth.setAuthenticatedForTesting();
      auth.setAuthenticatedForTesting();
      await t.pump(const Duration(milliseconds: 50));
      expect(socket.reconnects, 0);
      // another user signs in: fresh chat and session
      auth.setAuthenticatedForTesting(
        AuthUser(id: 'u2', username: 'b', role: 'member'),
        'token2',
      );
      await t.pump(const Duration(milliseconds: 50));
      expect(socket.reconnects, 1);
      await t.pumpWidget(const SizedBox());
    },
  );

  testWidgets(
    'JarvisApp plays the audio the chat emits and shows it speaking',
    (t) async {
      t.view.physicalSize = const Size(1170, 2532);
      t.view.devicePixelRatio = 3;
      addTearDown(t.view.reset);
      final socket = FakeSocket();
      final backend = FakeAudioBackend();
      final out = AudioOut(backend: backend, bufferMs: 0);
      await t.pumpWidget(
        JarvisApp(cfg: ServerConfig(), socket: socket, audioOut: out),
      );
      await t.pump(const Duration(milliseconds: 100));
      final chat = t.element(find.byType(HomeScreen)).read<ChatController>();
      socket.incoming.add({
        'type': 'pcm_chunk',
        'data': base64Encode([1, 2, 3, 4]),
        'sample_rate': 24000,
      });
      await t.pump(const Duration(milliseconds: 50));
      expect(backend.pcmPlayed.length, 1);
      expect(chat.state, JState.speaking);
      backend.finishCurrent();
      await t.pump(const Duration(milliseconds: 50));
      expect(chat.state, JState.idle);
      await t.pumpWidget(const SizedBox());
    },
  );

  testWidgets(
    'the mic button listens until switched off, pausing while JARVIS works',
    (t) async {
      final speech = FakeSpeechBackend();
      final input = VoiceInput(
        cue: (_) async {},
        onTranscript: (_) {},
        speechBackend: speech,
        recordBackend: FakeRecordBackend(),
      );
      final h = await pumpHome(t, voiceInput: input);
      expect(h.chat.state, JState.idle);
      await t.tap(byGlyph(menuGlyph));
      await t.pump(const Duration(milliseconds: 400));
      await t.tap(byGlyph(micOffGlyph));
      await t.pump(const Duration(milliseconds: 50));
      expect(h.chat.state, JState.listening);
      expect(speech.listenCalls, 1);
      await h.packet(t, {'type': 'status', 'state': 'thinking'});
      expect(speech.isListening, isFalse); // paused while it thinks
      await h.packet(t, {'type': 'status', 'state': 'idle'});
      expect(h.chat.state, JState.listening);
      expect(speech.listenCalls, 2); // resumed
      await t.tap(byGlyph(micGlyph));
      await t.pump(const Duration(milliseconds: 50));
      expect(h.chat.state, JState.idle);
      expect(speech.isListening, isFalse);
      await t.pumpWidget(const SizedBox());
    },
  );
}
