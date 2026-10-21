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
  });
  test('theme uses token background', () {
    expect(buildAppTheme().scaffoldBackgroundColor, JTokens.bg);
  });
}
