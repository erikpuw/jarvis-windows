import 'package:flutter_test/flutter_test.dart';
import 'package:jarvis_mobile/chat/typewriter.dart';

void main() {
  test('keeps up at 60 characters a second and carries the fraction', () {
    final w = Typewriter();
    for (var i = 0; i < 6; i++) {
      w.step(0.01, 12);
    }
    expect(w.shown, 3); // 0.06 s * 60 = 3.6 -> 3 shown, 0.6 owed
    w.step(0.01, 12);
    expect(w.shown, 4);
  });

  test('a large backlog is drained in about 0.3 s', () {
    final w = Typewriter();
    // 600 behind: 600 / 0.3 = 2000 cps, so 0.1 s shows 200
    expect(w.step(0.1, 600), 200);
    // a stalled frame counts as 100 ms at most
    final x = Typewriter();
    expect(x.step(5, 600), 200);
  });

  test('never passes the target and finish shows everything', () {
    final w = Typewriter();
    expect(w.step(0.1, 3), 3);
    w.finish(50);
    expect(w.shown, 50);
  });

  test('trailing newlines wait for the next letter', () {
    expect(withoutTrailingNewlines('một\n\n'), 'một');
    expect(withoutTrailingNewlines('a\nb'), 'a\nb');
  });
}
