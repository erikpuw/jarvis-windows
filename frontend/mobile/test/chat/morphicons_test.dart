// morphicons on the buttons the web morphs (icons.ts SPECS): the glyph follows the state on the same mounted MorphIcon.
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jarvis_mobile/chat/command_bar.dart';
import 'package:jarvis_mobile/chat/controls_capsule.dart';
import 'package:jarvis_mobile/chat/lucide_glyphs.dart';
import 'package:jarvis_mobile/chat/morph_icon.dart';

import 'fakes.dart';

Widget _controls({bool tts = false, bool mic = false, bool bar = false}) =>
    MaterialApp(
      home: Stack(
        children: [
          ControlsCapsule(
            ttsMuted: tts,
            micMuted: mic,
            barVisible: bar,
            onTts: () {},
            onToggleBar: () {},
            onSettings: () {},
          ),
        ],
      ),
    );

Widget _bar({bool attached = false}) => MaterialApp(
  home: Scaffold(
    body: CommandBar(
      input: TextEditingController(),
      focus: FocusNode(),
      onSend: () {},
      onUpload: () {},
      hasAttachment: attached,
    ),
  ),
);

void main() {
  testWidgets('controls: tts, mic and bar buttons morph in place', (t) async {
    await t.pumpWidget(_controls());
    await t.tap(byGlyph(menuGlyph)); // open the menu
    await t.pump(const Duration(milliseconds: 400));
    final tts = t.state(byGlyph(volume2Glyph));
    final mic = t.state(byGlyph(micGlyph));
    final bar = t.state(byGlyph(squareTerminalGlyph));
    await t.pumpWidget(_controls(tts: true, mic: true, bar: true));
    await t.pump(const Duration(milliseconds: 50));
    expect(identical(t.state(byGlyph(volumeXGlyph)), tts), isTrue);
    expect(identical(t.state(byGlyph(micOffGlyph)), mic), isTrue);
    expect(identical(t.state(byGlyph(chevronDownGlyph)), bar), isTrue);
    await t.pump(const Duration(seconds: 1));
  });

  testWidgets('controls: main button morphs menu <-> x', (t) async {
    await t.pumpWidget(_controls());
    final main = t.state(byGlyph(menuGlyph));
    await t.tap(byGlyph(menuGlyph));
    await t.pump(const Duration(milliseconds: 50));
    expect(identical(t.state(byGlyph(xGlyph)), main), isTrue);
    await t.pump(const Duration(seconds: 5)); // the menu folds after 4 s
  });

  testWidgets('upload button morphs plus <-> paperclip, 14px / stroke 2.5', (
    t,
  ) async {
    await t.pumpWidget(_bar());
    final plus = t.state(byGlyph(plusGlyph));
    final w = t.widget<MorphIcon>(byGlyph(plusGlyph));
    expect((w.size, w.strokeWidth), (14.0, 2.5));
    await t.pumpWidget(_bar(attached: true));
    await t.pump(const Duration(milliseconds: 50));
    expect(identical(t.state(byGlyph(paperclipGlyph)), plus), isTrue);
    await t.pump(const Duration(seconds: 1));
  });
}
