// icons.ts decorateActionButton / runAction: idle -> spinner -> check / x -> idle on one mounted morph icon.
import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jarvis_mobile/chat/lucide_glyphs.dart';
import 'package:jarvis_mobile/chat/morph_icon.dart';
import 'package:jarvis_mobile/settings/action_button.dart';

import '../chat/fakes.dart';

Widget _app(ActionButton b) => MaterialApp(
  home: Scaffold(body: Center(child: b)),
);

void main() {
  testWidgets('idle -> spinner -> check -> idle on the same icon', (t) async {
    final done = Completer<bool?>();
    var calls = 0;
    await t.pumpWidget(
      _app(
        ActionButton(
          kind: ActionKind.save,
          label: 'Lưu',
          task: () {
            calls++;
            return done.future;
          },
        ),
      ),
    );
    final icon = t.state(byGlyph(saveGlyph));
    final w = t.widget<MorphIcon>(byGlyph(saveGlyph));
    expect((w.size, w.strokeWidth), (15.0, 2.0));
    await t.tap(find.text('Lưu'));
    await t.pump();
    expect(identical(t.state(byGlyph(loaderCircleGlyph)), icon), isTrue);
    await t.tap(find.text('Lưu')); // busy: pointer-events none + early return
    expect(calls, 1);
    done.complete(null);
    await t.pump();
    await t.pump(const Duration(milliseconds: 50));
    expect(identical(t.state(byGlyph(checkGlyph)), icon), isTrue);
    await t.pump(const Duration(milliseconds: 1250)); // ACTION_FEEDBACK_MS
    await t.pump(const Duration(milliseconds: 50));
    expect(identical(t.state(byGlyph(saveGlyph)), icon), isTrue);
    await t.pump(const Duration(seconds: 1));
  });

  testWidgets('a throwing task shows the x and the message, then restores', (
    t,
  ) async {
    final feedback = <(String, bool)>[];
    await t.pumpWidget(
      _app(
        ActionButton(
          kind: ActionKind.test,
          label: 'Thử',
          task: () async => throw Exception('hỏng'),
          onFeedback: (text, ok) => feedback.add((text, ok)),
        ),
      ),
    );
    final icon = t.state(byGlyph(plugZapGlyph));
    await t.tap(find.text('Thử'));
    await t.pump();
    await t.pump(const Duration(milliseconds: 50));
    expect(identical(t.state(byGlyph(xGlyph)), icon), isTrue);
    expect(feedback, [('Exception: hỏng', false)]);
    await t.pump(const Duration(milliseconds: 1300));
    await t.pump(const Duration(milliseconds: 50));
    expect(identical(t.state(byGlyph(plugZapGlyph)), icon), isTrue);
    await t.pump(const Duration(seconds: 1));
  });

  testWidgets('false means cancelled: back to idle with no feedback', (
    t,
  ) async {
    final feedback = <(String, bool)>[];
    await t.pumpWidget(
      _app(
        ActionButton(
          kind: ActionKind.delete,
          label: 'Xoá',
          task: () async => false,
          onFeedback: (text, ok) => feedback.add((text, ok)),
        ),
      ),
    );
    await t.tap(find.text('Xoá'));
    await t.pump();
    await t.pump(const Duration(milliseconds: 100));
    expect(byGlyph(trashGlyph), findsOneWidget);
    expect(feedback, isEmpty);
    await t.pump(const Duration(seconds: 1));
  });

  testWidgets('success reports okText', (t) async {
    final feedback = <(String, bool)>[];
    await t.pumpWidget(
      _app(
        ActionButton(
          kind: ActionKind.save,
          label: 'Lưu',
          okText: 'Đã lưu giọng đọc!',
          task: () async => null,
          onFeedback: (text, ok) => feedback.add((text, ok)),
        ),
      ),
    );
    await t.tap(find.text('Lưu'));
    await t.pump();
    await t.pump(const Duration(milliseconds: 50));
    expect(feedback, [('Đã lưu giọng đọc!', true)]);
    await t.pump(const Duration(seconds: 2));
  });
}
