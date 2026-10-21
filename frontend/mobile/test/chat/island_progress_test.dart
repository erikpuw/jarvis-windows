// The island's progress display vs notify-island.ts: the pill glyph is one mounted morph icon (setStatusIcon), the step rows
// are the timeline (dot + connector), and the pill label follows the steps.
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jarvis_mobile/chat/chat_models.dart';
import 'package:jarvis_mobile/chat/island.dart';
import 'package:jarvis_mobile/chat/island_steps.dart';
import 'package:jarvis_mobile/chat/lucide_glyphs.dart';
import 'package:jarvis_mobile/chat/morph_icon.dart';

import '../chat/fakes.dart';

FlowStep _s(String id, String status, [String label = 'Bước']) =>
    FlowStep(id: id, label: label, status: status);

Future<void> _run(WidgetTester t, int ms) async {
  for (var left = ms; left > 0; left -= 50) {
    await t.pump(Duration(milliseconds: left < 50 ? left : 50));
  }
}

Widget _app(List<FlowStep> steps) => MaterialApp(
  home: Scaffold(
    body: Align(
      alignment: Alignment.topCenter,
      child: Island(steps: steps),
    ),
  ),
);

Future<void> _open(WidgetTester t, String pillText) async {
  await t.tap(find.text(pillText));
  await _run(t, 800);
}

void main() {
  testWidgets(
    'a new turn replaces the old rows even when the reset and its first steps arrive together',
    (t) async {
      // the real backend sequence of a spoken answer (engine/turn/loop.py): Nhận, Chọn công cụ, Trả lời, Hoàn thành
      await t.pumpWidget(
        _app([
          _s('1', 'completed', 'Nhận: bật nhạc'),
          _s('2', 'completed', 'Chọn công cụ → không cần'),
          _s('3', 'completed', 'Trả lời'),
          _s('4', 'completed', 'Hoàn thành'),
        ]),
      );
      await _run(t, 500);
      // stream_start of the next turn and its first flow packets reach the screen in one rebuild
      await t.pumpWidget(
        _app([
          _s('1', 'completed', 'Nhận: kể chuyện'),
          _s('2', 'active', 'Chọn công cụ'),
        ]),
      );
      await _run(t, 500);
      await _open(t, 'Đang xử lý');
      expect(find.textContaining('Trả lời'), findsNothing);
      expect(
        find.text('Hoàn thành'),
        findsNothing,
      ); // neither a row nor the pill
      expect(
        find.byWidgetPredicate((w) => w is StepDot && w.status == 'completed'),
        findsOneWidget,
      );
      await _run(t, 9000);
    },
  );

  testWidgets('a step going active -> completed morphs the same pill glyph', (
    t,
  ) async {
    await t.pumpWidget(_app([_s('1', 'active')]));
    await _run(t, 500);
    expect(find.text('Đang xử lý'), findsOneWidget);
    final glyph = t.state(byGlyph(loaderCircleGlyph));
    await t.pumpWidget(_app([_s('1', 'completed')]));
    await _run(t, 1000); // DONE_MS: the flow is finished
    expect(find.text('Hoàn thành'), findsOneWidget);
    expect(identical(t.state(byGlyph(checkGlyph)), glyph), isTrue);
    await _run(t, 9000);
  });

  testWidgets('a failed step shows the x in the pill and in its row', (
    t,
  ) async {
    await t.pumpWidget(_app([_s('1', 'completed'), _s('2', 'failed')]));
    await _run(t, 500);
    expect(find.text('Lỗi xử lý'), findsOneWidget);
    expect(byGlyph(xGlyph), findsOneWidget);
    await _open(t, 'Lỗi xử lý');
    expect(
      find.byWidgetPredicate((w) => w is StepDot && w.status == 'failed'),
      findsOneWidget,
    );
    expect(
      find.byWidgetPredicate((w) => w is StepDot && w.status == 'completed'),
      findsOneWidget,
    );
    await _run(t, 9000);
  });

  testWidgets('the pill label follows the active step', (t) async {
    await t.pumpWidget(_app([_s('1', 'completed'), _s('2', 'active')]));
    await _run(t, 500);
    expect(find.text('Đang xử lý'), findsOneWidget);
    await t.pumpWidget(_app([_s('1', 'completed'), _s('2', 'completed')]));
    await _run(t, 500);
    expect(find.text('Đang xử lý'), findsOneWidget); // still inside DONE_MS
    await _run(t, 600);
    expect(find.text('Hoàn thành'), findsOneWidget);
    await _run(t, 9000);
  });

  testWidgets(
    'rows: timeline connectors between the steps, none after the last',
    (t) async {
      await t.pumpWidget(
        _app([
          _s('1', 'completed', 'Định tuyến → general'),
          _s('2', 'active', 'Trả lời...'),
        ]),
      );
      await _run(t, 500);
      await _open(t, 'Đang xử lý');
      expect(find.byKey(const ValueKey('island-connector')), findsOneWidget);
      // the name and its detail are one paragraph (shared baseline), not two Texts
      final para = find.byWidgetPredicate(
        (w) =>
            w is RichText &&
            w.text.toPlainText().contains('Định tuyến') &&
            w.text.toPlainText().contains('· general'),
      );
      expect(para, findsOneWidget);
      expect(find.text('Định tuyến'), findsNothing);
      expect(find.textContaining('Trả lời'), findsOneWidget);
      await _run(t, 9000);
    },
  );

  testWidgets('a row keeps its dot while its status changes', (t) async {
    await t.pumpWidget(_app([_s('1', 'active')]));
    await _run(t, 500);
    await _open(t, 'Đang xử lý');
    final dot = t.state(find.byType(StepDot));
    await t.pumpWidget(_app([_s('1', 'completed')]));
    await _run(t, 100);
    expect(identical(t.state(find.byType(StepDot)), dot), isTrue);
    expect(t.widget<StepDot>(find.byType(StepDot)).status, 'completed');
    await _run(t, 9000);
  });

  testWidgets(
    'only a completed / failed dot pops: active and pending are at scale 1',
    (t) async {
      await t.pumpWidget(_app([_s('1', 'active'), _s('2', 'pending')]));
      await _run(t, 500);
      await _open(t, 'Đang xử lý');
      for (final dot in find.byType(StepDot).evaluate()) {
        final scale = find.descendant(
          of: find.byWidget(dot.widget),
          matching: find.byType(ScaleTransition),
        );
        expect(t.widget<ScaleTransition>(scale.first).scale.value, 1.0);
      }
      await t.pumpWidget(_app([_s('1', 'completed'), _s('2', 'pending')]));
      await t.pump(const Duration(milliseconds: 100));
      final first = find.descendant(
        of: find.byType(StepDot).first,
        matching: find.byType(ScaleTransition),
      );
      expect(
        t.widget<ScaleTransition>(first.first).scale.value,
        isNot(1.0),
      ); // popping
      await _run(t, 9000);
    },
  );
}
