@Tags(['screens'])
library;

// Review artifacts, not goldens (skipped by default, see dart_test.yaml; run: flutter test test/screens --run-skipped): renders the home screen like a phone (390x844 @3x) and writes
// mobile/build/screens/home_welcome.png, home_chat_loader.png, home_chat_streaming.png, home_chat.png …. There is no emulator on this machine (ruling R11).
// Fonts: Lexend comes from the app bundle; the Material fonts (Roboto) are read from the Flutter SDK when found,
// otherwise the test draws with flutter_test's fallback font. Roboto also stands in for the monospace stack.

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jarvis_mobile/chat/chat_controller.dart';
import 'package:jarvis_mobile/chat/home_screen.dart';
import 'package:jarvis_mobile/chat/lucide_glyphs.dart';
import 'package:jarvis_mobile/chat/metal_send_button.dart';
import 'package:jarvis_mobile/net/api_client.dart';
import 'package:jarvis_mobile/net/server_config.dart';
import 'package:jarvis_mobile/theme/app_theme.dart';
import 'package:provider/provider.dart';

import '../chat/fakes.dart';
import 'screen_support.dart';

void main() {
  testWidgets('home screen screenshots', (t) async {
    final haveFonts = await t.runAsync(loadScreenFonts) ?? false;
    debugPrint(
      haveFonts
          ? 'screenshot fonts: Lexend (bundle) + Roboto (SDK)'
          : 'screenshot fonts: flutter_test fallback (SDK fonts not found)',
    );
    t.view.physicalSize = const Size(1170, 2532);
    t.view.devicePixelRatio = 3;
    addTearDown(t.view.reset);

    final socket = FakeSocket();
    final chat = ChatController(socket, FakeApi());
    addTearDown(chat.dispose);
    final key = GlobalKey();
    await t.pumpWidget(
      RepaintBoundary(
        key: key,
        child: MultiProvider(
          providers: [
            ChangeNotifierProvider(create: (_) => ServerConfig()),
            Provider<ApiClient>.value(value: FakeApi()),
            ChangeNotifierProvider.value(value: chat),
          ],
          child: MaterialApp(
            debugShowCheckedModeBanner: false,
            theme: buildAppTheme(),
            home: const HomeScreen(),
          ),
        ),
      ),
    );

    await t.runAsync(
      () => Future<void>.delayed(const Duration(milliseconds: 300)),
    ); // the ring shader loads
    socket.incoming.add({
      'type': 'welcome',
      'greeting': 'Chào buổi tối',
      'tools': ['thời tiết', 'giá vàng', 'lịch chiếu phim'],
      'weather': {
        'desc': 'trời quang',
        'temp': 29.4,
        'kind': 'clear',
        'place': 'Hà Nội',
      },
    });
    await advance(t, 100);
    await advance(t, 1500);
    await shot(t, key, 'home_welcome');

    await t.enterText(
      find.byType(TextField),
      'So sánh các mẫu điện thoại giúp tôi',
    );
    await t.tap(find.byType(MetalSendButton));
    await advance(t, 120);
    await shot(t, key, 'home_send_morph'); // the plane flying into the check
    await advance(t, 500);
    await shot(t, key, 'home_chat_sent'); // check shown
    socket.incoming.add({'type': 'status', 'state': 'thinking'});
    socket.incoming.add({'type': 'stream_start'});
    await advance(t, 700);
    await shot(
      t,
      key,
      'home_chat_loader',
    ); // goo loader at the left, before the first letter
    socket.incoming.add({'type': 'text_chunk', 'text': _answer});
    await advance(t, 260);
    await shot(
      t,
      key,
      'home_chat_loader_collapsing',
    ); // balls shrinking, first letters typed
    await advance(t, 700);
    await shot(t, key, 'home_chat_streaming'); // mid-typewriter
    socket.incoming.add({'type': 'stream_end'});
    socket.incoming.add({'type': 'status', 'state': 'idle'});
    await advance(t, 100);
    await advance(t, 1500);
    await shot(t, key, 'home_chat'); // finished, idle, plane back
    expect(t.takeException(), isNull);
  });

  testWidgets('controls and island screenshots', (t) async {
    await t.runAsync(loadScreenFonts);
    t.view.physicalSize = const Size(1170, 2532);
    t.view.devicePixelRatio = 3;
    addTearDown(t.view.reset);

    final socket = FakeSocket();
    final chat = ChatController(socket, FakeApi());
    addTearDown(chat.dispose);
    final key = GlobalKey();
    await t.pumpWidget(
      RepaintBoundary(
        key: key,
        child: MultiProvider(
          providers: [
            ChangeNotifierProvider(create: (_) => ServerConfig()),
            Provider<ApiClient>.value(value: FakeApi()),
            ChangeNotifierProvider.value(value: chat),
          ],
          child: MaterialApp(
            debugShowCheckedModeBanner: false,
            theme: buildAppTheme(),
            home: const HomeScreen(),
          ),
        ),
      ),
    );
    await t.runAsync(
      () => Future<void>.delayed(const Duration(milliseconds: 300)),
    );
    await advance(t, 500);
    await t.tap(byGlyph(menuGlyph));
    await advance(t, 150);
    await shot(t, key, 'controls_morphing'); // menu -> x in flight
    await advance(t, 700);
    await shot(t, key, 'controls_open');

    await t.tap(byGlyph(xGlyph).first); // fold again
    await advance(t, 500);
    for (final (id, status, label) in [
      ('1', 'completed', 'Định tuyến → general'),
      ('2', 'failed', 'Tra cứu → giá vàng'),
      ('3', 'active', 'Trả lời...'),
    ]) {
      socket.incoming.add({
        'type': 'flow_step',
        'step': {'id': id, 'label': label, 'status': status},
      });
      await advance(t, 50);
    }
    await advance(t, 700);
    await t.tap(find.text('Lỗi xử lý'));
    await advance(t, 900);
    await shot(t, key, 'island_open'); // active + done + failed rows
    expect(t.takeException(), isNull);
    await t.pumpWidget(const SizedBox());
    await advance(t, 6000);
  });
}

const _answer = '''## Tóm tắt nhanh

Đây là so sánh ngắn các mẫu, **giá** là giá niêm yết (`VND`):

- Pin tốt nhất: *Galaxy S25 Ultra*
- Camera: iPhone 17 Pro
- Rẻ nhất: Redmi Note 15

| Mẫu | Màn hình | Chip | RAM | Pin | Giá |
| --- | --- | --- | --- | --- | --- |
| iPhone 17 Pro | 6,3 inch OLED | A19 Pro | 12 GB | 3.700 mAh | 34.990.000 |
| Galaxy S25 Ultra | 6,9 inch AMOLED | Snapdragon 8 Elite | 12 GB | 5.000 mAh | 33.990.000 |

```dart
void main() {
  final models = ['iPhone', 'Galaxy', 'Redmi'];
  print(models.map((m) => m.toUpperCase()).join(', '));
}
```
''';
