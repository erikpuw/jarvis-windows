import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jarvis_mobile/theme/app_theme.dart';
import 'package:jarvis_mobile/theme/tokens.dart';

void main() {
  test('tokens match web CSS', () {
    expect(JTokens.bg, const Color(0xFF050508));
    expect(JTokens.accent, const Color(0xFF0EA5E9));
    expect(JTokens.chatText, const Color(0xFFE5E7EB));
    expect(JTokens.fsBody, 15);
    expect(JTokens.bubbleRadius, 18);
    // settings/styles.css --sd-*: neutral zinc, no slate
    expect(JTokens.page, const Color(0xFF000000));
    expect(JTokens.surface, const Color(0xFF121214));
    expect(JTokens.surface2, const Color(0xFF18181B));
    expect(JTokens.border, const Color(0x14FFFFFF));
    expect(JTokens.borderStrong, const Color(0x29FFFFFF));
    expect(JTokens.text, const Color(0xFFF4F4F5));
    expect(JTokens.muted, const Color(0xFFA1A1AA));
  });
  test('theme uses the black page background', () {
    expect(buildAppTheme().scaffoldBackgroundColor, JTokens.page);
  });
}
