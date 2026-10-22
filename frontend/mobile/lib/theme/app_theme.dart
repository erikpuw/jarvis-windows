import 'package:flutter/material.dart';

import 'tokens.dart';

/// Material 3's default TextTheme adds its own tracking (0.1-0.5) and sizes; the web page has none of that: the system font
/// (style.css:74), letter-spacing normal, the sizes of the `--fs-*` tokens, line-height 1.5 in reading text.
TextTheme _webTextTheme(TextTheme base) {
  TextStyle s(TextStyle? b, double size, FontWeight w, {double? height}) =>
      TextStyle(
        fontFamily: b?.fontFamily,
        fontFamilyFallback: b?.fontFamilyFallback,
        fontSize: size,
        fontWeight: w,
        letterSpacing: 0,
        height: height,
      );
  return TextTheme(
    displayLarge: s(base.displayLarge, JTokens.fsHeading, FontWeight.w600),
    displayMedium: s(base.displayMedium, JTokens.fsHeading, FontWeight.w600),
    displaySmall: s(base.displaySmall, JTokens.fsHeading, FontWeight.w600),
    headlineLarge: s(base.headlineLarge, JTokens.fsHeading, FontWeight.w600),
    headlineMedium: s(base.headlineMedium, JTokens.fsHeading, FontWeight.w600),
    headlineSmall: s(base.headlineSmall, JTokens.fsHeading, FontWeight.w600),
    titleLarge: s(base.titleLarge, JTokens.fsTitle, FontWeight.w600),
    titleMedium: s(base.titleMedium, JTokens.fsBody, FontWeight.w500),
    titleSmall: s(base.titleSmall, JTokens.fsUi, FontWeight.w500),
    bodyLarge: s(base.bodyLarge, JTokens.fsBody, FontWeight.w400, height: 1.5),
    bodyMedium: s(base.bodyMedium, JTokens.fsUi, FontWeight.w400, height: 1.5),
    bodySmall: s(base.bodySmall, JTokens.fsSmall, FontWeight.w400, height: 1.5),
    labelLarge: s(base.labelLarge, JTokens.fsUi, FontWeight.w500),
    labelMedium: s(base.labelMedium, JTokens.fsSmall, FontWeight.w500),
    labelSmall: s(base.labelSmall, JTokens.fsLabel, FontWeight.w500),
  );
}

ThemeData buildAppTheme() {
  final base = ThemeData(
    brightness: Brightness.dark,
    useMaterial3: true,
    scaffoldBackgroundColor: JTokens.page,
    colorScheme: const ColorScheme.dark(
      primary: JTokens.accent,
      secondary: JTokens.cyan,
      surface: JTokens.surface,
      error: JTokens.err,
      onSurface: JTokens.text,
    ),
    dividerColor: JTokens.border,
  );
  return base.copyWith(
    textTheme: _webTextTheme(base.textTheme)
        .apply(bodyColor: JTokens.text, displayColor: JTokens.text),
  );
}
