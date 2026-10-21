import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jarvis_mobile/net/api_client.dart';
import 'package:jarvis_mobile/net/server_config.dart';
import 'package:jarvis_mobile/settings/settings_shell.dart';
import 'package:jarvis_mobile/theme/app_theme.dart';
import 'package:jarvis_mobile/theme/tokens.dart';
import 'package:provider/provider.dart';

import '../chat/fakes.dart';

void main() {
  test(
    'every text style has letter-spacing 0 and web sizes (style.css:74)',
    () {
      final t = buildAppTheme().textTheme;
      final styles = {
        'displayLarge': t.displayLarge,
        'displayMedium': t.displayMedium,
        'displaySmall': t.displaySmall,
        'headlineLarge': t.headlineLarge,
        'headlineMedium': t.headlineMedium,
        'headlineSmall': t.headlineSmall,
        'titleLarge': t.titleLarge,
        'titleMedium': t.titleMedium,
        'titleSmall': t.titleSmall,
        'bodyLarge': t.bodyLarge,
        'bodyMedium': t.bodyMedium,
        'bodySmall': t.bodySmall,
        'labelLarge': t.labelLarge,
        'labelMedium': t.labelMedium,
        'labelSmall': t.labelSmall,
      };
      for (final e in styles.entries) {
        expect(e.value!.letterSpacing, 0, reason: e.key);
      }
      expect(t.bodyLarge!.fontSize, JTokens.fsBody);
      expect(t.bodyLarge!.height, 1.5);
      expect(t.bodyMedium!.fontSize, JTokens.fsUi);
      expect(t.bodySmall!.fontSize, JTokens.fsSmall);
      expect(t.labelSmall!.fontSize, JTokens.fsLabel);
      expect(t.titleLarge!.fontSize, JTokens.fsTitle);
      expect(t.headlineSmall!.fontSize, JTokens.fsHeading);
      expect(t.bodyLarge!.fontFamily, isNot(JTokens.fontLexend));
    },
  );

  testWidgets('Settings text uses the system font, not Lexend', (t) async {
    final cfg = ServerConfig();
    final api = FakeApi();
    await t.pumpWidget(
      MultiProvider(
        providers: [
          ChangeNotifierProvider.value(value: cfg),
          Provider<ApiClient>.value(value: api),
        ],
        child: MaterialApp(
          theme: buildAppTheme(),
          home: const SettingsShell(initialPageId: 'voice'),
        ),
      ),
    );
    await t.pump(const Duration(milliseconds: 300));
    final texts = t.widgetList<Text>(find.byType(Text)).toList();
    expect(texts, isNotEmpty);
    for (final w in texts) {
      expect(
        w.style?.fontFamily,
        isNot(JTokens.fontLexend),
        reason: '${w.data}',
      );
    }
  });

  testWidgets('Typography scaling matrix differentiates legacy 16:9 vs modern phablets', (t) async {
    TextScaler computeScaler(Size size, {double userScale = 1.0}) {
      final shortest = size.shortestSide;
      final longest = size.longestSide;
      final ratio = longest / (shortest > 0 ? shortest : 1.0);
      final isLegacy16x9 = ratio < 1.85 || longest < 780;
      final isTablet = shortest >= 600;

      final double screenFactor;
      final double maxScale;
      if (isTablet) {
        screenFactor = 1.20;
        maxScale = 1.45;
      } else if (shortest < 360) {
        screenFactor = 0.90;
        maxScale = 1.15;
      } else if (shortest >= 410 && !isLegacy16x9 && longest >= 820) {
        screenFactor = 1.12;
        maxScale = 1.38;
      } else if (isLegacy16x9) {
        screenFactor = 0.96;
        maxScale = 1.20;
      } else {
        screenFactor = 1.00;
        maxScale = 1.30;
      }

      return TextScaler.linear(userScale * screenFactor)
          .clamp(minScaleFactor: 0.85, maxScaleFactor: maxScale);
    }

    // 1. Galaxy J7 Pro (411.4 x 731.4 dp, 16:9 non-bezel-less):
    // Should NOT be treated as Ultra, must be capped at 1.20x to prevent font explosion
    final j7Pro = computeScaler(const Size(411.4, 731.4));
    expect(j7Pro.scale(16.0), closeTo(16.0 * 0.96, 0.01));
    final j7ProExtreme = computeScaler(const Size(411.4, 731.4), userScale: 1.5);
    expect(j7ProExtreme.scale(16.0), closeTo(16.0 * 1.20, 0.01)); // Capped safely!

    // 2. Galaxy S24 Ultra (412 x 915 dp, tall 20:9 bezel-less):
    // Should receive +12% optical scale
    final s24Ultra = computeScaler(const Size(412, 915));
    expect(s24Ultra.scale(16.0), closeTo(16.0 * 1.12, 0.01));

    // 3. iPhone 15 Pro (393 x 852 dp, standard bezel-less):
    // Baseline 1.00x (identical 1:1 with web)
    final iphonePro = computeScaler(const Size(393, 852));
    expect(iphonePro.scale(16.0), closeTo(16.0 * 1.00, 0.01));

    // 4. iPhone SE 1st gen (320 x 568 dp, compact):
    final seCompact = computeScaler(const Size(320, 568));
    expect(seCompact.scale(16.0), closeTo(16.0 * 0.90, 0.01));

    // 5. Tablet (768 x 1024 dp):
    final tablet = computeScaler(const Size(768, 1024));
    expect(tablet.scale(16.0), closeTo(16.0 * 1.20, 0.01));
  });

}
