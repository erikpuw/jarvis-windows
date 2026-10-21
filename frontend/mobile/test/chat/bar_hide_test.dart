import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jarvis_mobile/chat/chat_models.dart';
import 'package:jarvis_mobile/chat/status_label.dart';

Widget host(bool centered) => MaterialApp(
  home: Scaffold(
    body: Align(
      alignment: Alignment.topLeft,
      child: SizedBox(
        width: 400,
        child: StatusRow(
          state: JState.idle,
          text: 'Sẵn sàng',
          centered: centered,
        ),
      ),
    ),
  ),
);

void main() {
  testWidgets('status row cross-fades between left and centre, never slides', (
    t,
  ) async {
    await t.pumpWidget(host(false));
    final left = t.getCenter(find.byType(Row).first).dx;
    await t.pumpWidget(host(true));
    final xs = <double>{};
    for (var i = 0; i < 25; i++) {
      await t.pump(const Duration(milliseconds: 10));
      xs.add(t.getCenter(find.byType(Row).first).dx);
    }
    final centre = t.getCenter(find.byType(Row).first).dx;
    expect(centre, greaterThan(left + 50));
    expect(
      xs.every((x) => (x - left).abs() < 0.01 || (x - centre).abs() < 0.01),
      isTrue,
      reason: '$xs',
    );
  });

  testWidgets('the row is invisible half way, visible at both ends', (t) async {
    await t.pumpWidget(host(false));
    await t.pumpWidget(host(true));
    double op() => t
        .widgetList<Opacity>(
          find.descendant(
            of: find.byType(StatusRow),
            matching: find.byType(Opacity),
          ),
        )
        .map((o) => o.opacity)
        .reduce((a, b) => a < b ? a : b);
    await t.pump(const Duration(milliseconds: 125));
    expect(op(), lessThan(0.05));
    await t.pump(const Duration(milliseconds: 130));
    expect(op(), 1);
  });
}
