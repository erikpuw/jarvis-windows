import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';

import '../theme/tokens.dart';
import 'chat_models.dart';

// style.css #welcome: Lexend only, three weights, left edge = the text in the command input, transparent.
const _ink1 = Color(0xF2D6F0FF);
const _ink2 = Color(0xB8D6F0FF);
const _ink3 = Color(0x85D6F0FF);
const _slotInk = Color(0xFF7FD8FF);
const _rotate = Duration(milliseconds: 2200);

TextStyle _lexend(double size, double weight, Color color) => TextStyle(
  fontFamily: JTokens.fontLexend,
  fontSize: size,
  color: color,
  fontVariations: [FontVariation('wght', weight)],
);

const _icons = <String, IconData>{
  'clear': LucideIcons.sun,
  'cloudy': LucideIcons.cloud,
  'rain': LucideIcons.cloudRain,
  'storm': LucideIcons.cloudLightning,
  'snow': LucideIcons.snowflake,
  'fog': LucideIcons.cloudFog,
  'haze': LucideIcons.haze,
};

/// The new-session greeting (welcome.ts): the server's time-slot greeting, weather, a question, and the tools rotating in a clipped slot.
class WelcomeView extends StatefulWidget {
  const WelcomeView({super.key, required this.data});
  final WelcomeData? data;

  @override
  State<WelcomeView> createState() => _WelcomeViewState();
}

class _WelcomeViewState extends State<WelcomeView>
    with SingleTickerProviderStateMixin {
  // welcome-rise: 0.9s, the question 0.16s later, the "try" line 0.24s later
  late final AnimationController _rise = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 1140),
  )..forward();

  @override
  void dispose() {
    _rise.dispose();
    super.dispose();
  }

  Widget _stage(double from, double to, Widget child) {
    final a = CurvedAnimation(
      parent: _rise,
      curve: Interval(from, to, curve: const Cubic(0.22, 1, 0.36, 1)),
    );
    return FadeTransition(
      opacity: a,
      child: SlideTransition(
        position: Tween(
          begin: const Offset(0, 8 / 40),
          end: Offset.zero,
        ).animate(a),
        child: child,
      ),
    );
  }

  Widget _weather(WelcomeWeather? w) {
    final style = _lexend(13, 300, _ink3).copyWith(
      letterSpacing: 13 * 0.02,
      fontFeatures: const [FontFeature.tabularFigures()],
    );
    final parts = w == null
        ? <String>[]
        : [
            if (w.temp != null) '${w.temp!.round()}°C',
            if (w.desc.isNotEmpty)
              w.desc[0].toUpperCase() + w.desc.substring(1),
            if (w.place.isNotEmpty) w.place,
          ];
    return AnimatedOpacity(
      duration: const Duration(milliseconds: 400),
      opacity: w == null ? 0 : 1,
      child: Padding(
        padding: const EdgeInsets.only(top: 12),
        child: ConstrainedBox(
          constraints: const BoxConstraints(minHeight: 18),
          child: w == null
              ? null
              : Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Icon(
                      _icons[w.kind] ?? LucideIcons.cloud,
                      size: 16,
                      color: _ink3,
                    ),
                    for (var n = 0; n < parts.length; n++) ...[
                      const SizedBox(width: 8),
                      if (n > 0) ...[
                        Opacity(opacity: 0.6, child: Text('·', style: style)),
                        const SizedBox(width: 8),
                      ],
                      Text(parts[n], style: style),
                    ],
                  ],
                ),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final size = MediaQuery.sizeOf(context);
    final w = size.width;
    // padding: 0 24px calc(136px + 12vh) calc((100vw - min(800px, 100vw - 28px)) / 2 + 31px); content centred in what is left
    final left = (w - math.min(800, w - 28)) / 2 + 31;
    final hello = (w * 0.105).clamp(40.0, 56.0);
    return Padding(
      padding: EdgeInsets.fromLTRB(left, 0, 24, 136 + size.height * 0.12),
      child: Align(
        alignment: Alignment.centerLeft,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _stage(
              0,
              0.79,
              Transform.translate(
                offset: Offset(-0.05 * hello, 0),
                child: Text(
                  widget.data?.greeting ?? '',
                  style: _lexend(
                    hello,
                    200,
                    _ink1,
                  ).copyWith(height: 1.05, letterSpacing: -0.025 * hello),
                ),
              ),
            ),
            _weather(widget.data?.weather),
            _stage(
              0.14,
              0.93,
              Padding(
                padding: const EdgeInsets.only(top: 24),
                child: Text(
                  'Tôi có thể giúp gì cho ngài hôm nay?',
                  style: _lexend(17, 300, _ink2).copyWith(height: 1.4),
                ),
              ),
            ),
            _stage(
              0.21,
              1,
              Padding(
                padding: const EdgeInsets.only(top: 12),
                // Wrap, not Row: a long tool name ("bách khoa toàn thư") at a large font size moves whole to the
                // next line instead of being squeezed and clipped.
                child: Wrap(
                  crossAxisAlignment: WrapCrossAlignment.center,
                  children: [
                    Text(
                      'Thử hỏi về ',
                      style: _lexend(17, 300, _ink3).copyWith(height: 1.5),
                    ),
                    _WordSlot(words: widget.data?.tools ?? const []),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// The tools rotating in a clipped slot (welcome.ts show()): every ROTATE_MS the next word slides in, up or down at random,
/// and the old one leaves the other way over 450 ms; the slot's width follows the word.
class _WordSlot extends StatefulWidget {
  const _WordSlot({required this.words});
  final List<String> words;

  @override
  State<_WordSlot> createState() => _WordSlotState();
}

class _WordSlotState extends State<_WordSlot>
    with SingleTickerProviderStateMixin {
  static const _ease = Cubic(0.22, 1, 0.36, 1);
  static const _h = 25.5; // 1.5em at 17px
  late final AnimationController _c = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 450),
    value: 1,
  );
  final _rng = math.Random();
  Timer? _timer;
  List<String> _words = const [];
  int _i = 0;
  String? _cur, _old;
  bool _down = true;
  double _wFrom = 0, _wTo = 0;
  final _style = _lexend(17, 400, _slotInk).copyWith(height: 1.5);

  // The slot is measured with the same style and system font scale the Text renders with, or a large
  // Android font size clips the word's end ("giá thuốc men" -> "giá thuốc me").
  TextStyle _shown = const TextStyle();
  TextScaler _scaler = TextScaler.noScaling;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final shown = DefaultTextStyle.of(context).style.merge(_style);
    final scaler = MediaQuery.textScalerOf(context);
    final changed = shown != _shown || scaler != _scaler;
    _shown = shown;
    _scaler = scaler;
    if (changed && _cur != null) _wFrom = _wTo = _measure(_cur!);
    _sync();
  }

  @override
  void didUpdateWidget(_WordSlot old) {
    super.didUpdateWidget(old);
    _sync();
  }

  /// Shuffled once, when the first list arrives; later updates keep it (welcome.ts: only while no words yet).
  void _sync() {
    if (_words.isNotEmpty || widget.words.isEmpty) return;
    _words = [...widget.words]..shuffle(_rng);
    _show(_words[0]);
    if (_words.length > 1) {
      _timer = Timer.periodic(_rotate, (_) {
        if (mounted) _show(_words[++_i % _words.length]);
      });
    }
  }

  double _measure(String w) =>
      (TextPainter(
        text: TextSpan(text: w, style: _shown),
        textScaler: _scaler,
        textDirection: TextDirection.ltr,
        maxLines: 1,
      )..layout()).width.ceilToDouble() +
      1;

  void _show(String word) {
    setState(() {
      _down = _rng.nextBool();
      _old = _cur;
      _cur = word;
      _wFrom = _old == null ? _measure(word) : _width();
      _wTo = _measure(word);
    });
    _c.forward(from: 0);
  }

  double _width() => _wFrom + (_wTo - _wFrom) * _ease.transform(_c.value);

  @override
  void dispose() {
    _timer?.cancel();
    _c.dispose();
    super.dispose();
  }

  Widget _word(Key key, String w, double dy, double opacity) => Positioned(
    left: 0,
    top: 0,
    child: Opacity(
      opacity: opacity,
      child: Transform.translate(
        key: key,
        offset: Offset(0, dy * _h),
        child: Text(w, style: _style, maxLines: 1, softWrap: false),
      ),
    ),
  );

  @override
  Widget build(BuildContext context) {
    if (_cur == null) return const SizedBox(height: _h);
    return AnimatedBuilder(
      animation: _c,
      builder: (context, _) {
        final e = _ease.transform(_c.value);
        final o = Curves.ease.transform(_c.value);
        final settled = _c.value >= 1;
        return SizedBox(
          key: const Key('welcome-slot'),
          height: _h,
          width: _wFrom + (_wTo - _wFrom) * e,
          child: ClipRect(
            child: Stack(
              clipBehavior: Clip.none,
              children: [
                // down: the new word falls in from above and the old one leaves downwards; otherwise the other way
                if (!settled && _old != null)
                  _word(
                    const Key('welcome-slot-old'),
                    _old!,
                    (_down ? 1 : -1) * e,
                    1 - o,
                  ),
                _word(
                  const Key('welcome-slot-new'),
                  _cur!,
                  (_down ? -1 : 1) * (1 - e),
                  _old == null ? 1 : o,
                ),
              ],
            ),
          ),
        );
      },
    );
  }
}
