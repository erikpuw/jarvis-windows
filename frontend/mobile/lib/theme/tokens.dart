import 'package:flutter/material.dart';

/// Design tokens mirrored from the web frontend CSS.
class JTokens {
  JTokens._();

  /// Solid panels over the black page (table frame, command bar): style.css keeps #050508 there.
  static const bg = Color(0xFF050508);

  /// Page background of the main screen, login and Settings (body / --sd-bg: #000).
  static const page = Color(0xFF000000);

  // Neutral zinc palette (web 7b34d4b: settings/styles.css --sd-*, no slate/cyan glow).
  static const surface = Color(0xFF121214);
  static const surface2 = Color(0xFF18181B);
  static const surface3 = Color(0xFF27272A); // active tab / pressed control (.suggest-tab.active, #controls button.active)
  static const border = Color(0x14FFFFFF);
  static const borderStrong = Color(0x29FFFFFF);
  static const text = Color(0xFFF4F4F5);
  static const chatText = Color(0xFFE5E7EB);
  static const muted = Color(0xFFA1A1AA);
  static const textMuted = Color(0xFF71717A); // placeholders, inactive tabs (#71717a)
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
  /// Chat bubble font size (web phone: 15px; the app reads one step larger, then scales per screen in main.dart).
  static const double bubbleFont = 16;

  /// Table and code font size.
  static const double tableFont = 13.5;

  static const double bubbleRadius = 18;
  static const double chatGap = 10;
  static const double navRail = 60;

  static const easeOut = Cubic(0.16, 1, 0.3, 1);
  static const fontLexend = 'Lexend';
}
