import 'package:flutter/material.dart';

/// Design tokens mirrored from the web frontend CSS.
class JTokens {
  JTokens._();

  static const bg = Color(0xFF050508);
  static const surface = Color(0xFF0D1117);
  static const surface2 = Color(0xFF0A0E14);
  static const border = Color(0x1F94A3B8);
  static const borderStrong = Color(0x4094A3B8);
  static const text = Color(0xFFE2E8F0);
  static const chatText = Color(0xFFE5E7EB);
  static const muted = Color(0xFF94A3B8);
  static const textMuted = Color(0x4DFFFFFF);
  static const accent = Color(0xFF0EA5E9);
  static const accentSoft = Color(0x1F0EA5E9);
  static const cyan = Color(0xFF00D4FF);
  static const ok = Color(0xFF4ADE80);
  static const err = Color(0xFFF87171);
  static const cmdBg = Color(0x6608080C);

  static const double fsLabel = 11;
  static const double fsSmall = 13;
  static const double fsUi = 14;
  static const double fsBody = 15;
  static const double fsInput = 16;
  static const double fsTitle = 18;
  static const double fsHeading = 20;
  /// Chat bubble font size: 14.5px on Android and 15.0px on iOS for balanced optical scale with the command bar.
  static double get bubbleFont => 16.0;

  /// Table and code font size: 12.5px on Android, 13.5px on iOS.
  static double get tableFont => 13.5;

  static const double bubbleRadius = 18;
  static const double chatGap = 10;
  static const double navRail = 60;

  static const easeOut = Cubic(0.16, 1, 0.3, 1);
  static const fontLexend = 'Lexend';
}
