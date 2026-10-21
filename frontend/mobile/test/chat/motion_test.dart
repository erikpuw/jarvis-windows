import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jarvis_mobile/chat/chat_models.dart';
import 'package:jarvis_mobile/chat/status_label.dart';
import 'package:jarvis_mobile/chat/welcome_view.dart';

Widget _row(JState s, String text, {Listenable? activity}) => MaterialApp(
  home: Scaffold(
    body: StatusRow(state: s, text: text, activity: activity),
  ),
);

double _dy(WidgetTester t, Finder f) =>
    t.widget<Transform>(f).transform.getTranslation().y;

void main() {
  testWidgets(
    'status text slides between two busy states (old ghost leaves, new rises)',
    (t) async {
      await t.pumpWidget(_row(JState.thinking, 'Đang suy nghĩ…'));
      await t.pumpWidget(_row(JState.working, 'Đang xử lý…'));
      await t.pump(const Duration(milliseconds: 100));
      expect(find.byKey(const Key('status-ghost')), findsOneWidget);
      expect(find.byKey(const Key('status-label')), findsOneWidget);
      // ghost: ease-in, 200 ms; new: starts after 90 ms delay, 12 px away
      expect(
        _dy(t, find.byKey(const Key('status-label'))).abs(),
        inInclusiveRange(6, 12),
      );
      await t.pump(const Duration(milliseconds: 800));
      expect(find.byKey(const Key('status-ghost')), findsNothing);
      expect(_dy(t, find.byKey(const Key('status-label'))), 0);
    },
  );

  testWidgets('idle label rolls left after 10 s and back on touch', (t) async {
    final wake = ValueNotifier(0);
    await t.pumpWidget(_row(JState.idle, 'Sẵn sàng', activity: wake));
    await t.pump(const Duration(seconds: 10));
    await t.pump(const Duration(milliseconds: 200));
    final mid = _dx(t);
    expect(mid, lessThan(0)); // sliding out to the left
    await t.pump(const Duration(milliseconds: 400));
    expect(t.getSize(find.byKey(const Key('status-quiet'))).width, 0);
    wake.value++;
    await t.pump();
    await t.pump(const Duration(milliseconds: 700));
    expect(_dx(t), 0);
    expect(
      t.getSize(find.byKey(const Key('status-quiet'))).width,
      greaterThan(20),
    );
  });

  testWidgets(
    'welcome word slides: old leaves, new enters, slot follows the word',
    (t) async {
      await t.pumpWidget(
        const MaterialApp(
          home: Scaffold(
            body: WelcomeView(
              data: WelcomeData(greeting: 'x', tools: ['aa', 'bbbbbbbb']),
            ),
          ),
        ),
      );
      await t.pump(const Duration(milliseconds: 100));
      final w0 = t.getSize(find.byKey(const Key('welcome-slot'))).width;
      await t.pump(const Duration(milliseconds: 2200));
      await t.pump(const Duration(milliseconds: 150));
      expect(find.byKey(const Key('welcome-slot-old')), findsOneWidget);
      expect(find.byKey(const Key('welcome-slot-new')), findsOneWidget);
      await t.pump(const Duration(milliseconds: 600));
      expect(find.byKey(const Key('welcome-slot-old')), findsNothing);
      final w1 = t.getSize(find.byKey(const Key('welcome-slot'))).width;
      expect(w1, isNot(w0));
      await t.pumpWidget(const SizedBox());
    },
  );

  testWidgets(
    'welcome slot is as wide as the word under a large system font size',
    (t) async {
      await t.pumpWidget(
        const MediaQuery(
          data: MediaQueryData(textScaler: TextScaler.linear(1.3)),
          child: MaterialApp(
            home: Scaffold(
              body: WelcomeView(
                data: WelcomeData(greeting: 'x', tools: ['giá thuốc men']),
              ),
            ),
          ),
        ),
      );
      await t.pump(const Duration(milliseconds: 600));
      final slot = t.getSize(find.byKey(const Key('welcome-slot'))).width;
      final word = t.getSize(find.text('giá thuốc men')).width;
      expect(slot, greaterThanOrEqualTo(word));
      await t.pumpWidget(const SizedBox());
    },
  );

  for (final name in [
    'bách khoa toàn thư',
    'đơn vị hành chính',
    'tra cứu pháp luật',
  ]) {
    // The test font (Ahem) draws every glyph as a full em square, so these names are wider than a real Lexend
    // run: at 1.0 the "Thử hỏi về" line cannot hold them and the slot must wrap whole, never shrink.
    testWidgets('long tool name "$name" is never clipped on a 390 px phone', (
      t,
    ) async {
      t.view.physicalSize = const Size(390, 844);
      t.view.devicePixelRatio = 1;
      addTearDown(t.view.reset);
      await t.pumpWidget(
        MediaQuery(
          data: const MediaQueryData(size: Size(390, 844)),
          child: MaterialApp(
            home: Scaffold(
              body: WelcomeView(
                data: WelcomeData(greeting: 'x', tools: [name]),
              ),
            ),
          ),
        ),
      );
      await t.pump(const Duration(milliseconds: 600));
      expect(t.takeException(), isNull);
      final slot = t.getSize(find.byKey(const Key('welcome-slot'))).width;
      final word = t.getSize(find.text(name)).width;
      expect(slot, greaterThanOrEqualTo(word));
      await t.pumpWidget(const SizedBox());
    });
  }
}

double _dx(WidgetTester t) => t
    .widget<Transform>(find.byKey(const Key('status-quiet')))
    .transform
    .getTranslation()
    .x;
