// What Bộ nhớ and Nhật ký share (styles.css "Memory Center", <=768px): the framed panel, the row of category buttons, the pager
// buttons and the confirm() box.
import 'package:flutter/material.dart';
import 'package:jarvis_mobile/chat/morph_icon.dart';
import 'package:jarvis_mobile/theme/tokens.dart';

/// `.sd-memory-cats` / `.sd-memory-list`: a framed panel.
class MemPanel extends StatelessWidget {
  const MemPanel({
    super.key,
    required this.child,
    this.padding = const EdgeInsets.all(16),
  });

  final Widget child;
  final EdgeInsets padding;

  @override
  Widget build(BuildContext context) => Container(
    padding: padding,
    decoration: BoxDecoration(
      color: JTokens.surface,
      borderRadius: BorderRadius.circular(12),
      border: Border.all(color: JTokens.border),
    ),
    child: child,
  );
}

class MemCat {
  const MemCat({
    required this.id,
    required this.label,
    required this.color,
    required this.icon,
    this.activeIcon,
  });

  final String id;
  final String label;
  final Color color;
  final MorphGlyph icon;

  /// The glyph while the tab is active (absent for the logs tabs: web gives them none).
  final MorphGlyph? activeIcon;

  MorphGlyph get active => activeIcon ?? icon;
}

/// `#memory-category-nav` / `#logs-category-nav` on a phone: one row of buttons that scrolls sideways (icon in a 24px tile, label,
/// optional count pill); the active one has its category colour as border, glow and pill.
class MemCatNav extends StatelessWidget {
  const MemCatNav({
    super.key,
    required this.cats,
    required this.active,
    required this.onSelect,
    this.counts = const {},
  });

  final List<MemCat> cats;
  final String active;
  final ValueChanged<String> onSelect;

  /// category id -> the number in its pill (absent = no pill).
  final Map<String, int> counts;

  @override
  Widget build(BuildContext context) => SizedBox(
    height: 42,
    child: SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      padding: const EdgeInsets.fromLTRB(2, 2, 2, 4),
      child: Row(
        children: [
          for (var i = 0; i < cats.length; i++) ...[
            if (i > 0) const SizedBox(width: 8),
            _button(cats[i]),
          ],
        ],
      ),
    ),
  );

  Widget _button(MemCat c) {
    final on = c.id == active;
    final count = counts[c.id];
    return GestureDetector(
      key: Key('cat:${c.id}'),
      behavior: HitTestBehavior.opaque,
      onTap: () => onSelect(c.id),
      child: CustomPaint(
        painter: on ? _OuterGlow(c.color) : null,
        child: Container(
          height: 36,
          padding: const EdgeInsets.symmetric(horizontal: 12),
          decoration: BoxDecoration(
            gradient: on
                ? const LinearGradient(
                    colors: [Color(0x0FFFFFFF), Color(0x05FFFFFF)],
                  )
                : null,
            borderRadius: BorderRadius.circular(8),
            border: Border.all(color: on ? c.color : Colors.transparent),
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Container(
                width: 24,
                height: 24,
                decoration: BoxDecoration(
                  color: on ? const Color(0x14FFFFFF) : const Color(0x0AFFFFFF),
                  borderRadius: BorderRadius.circular(6),
                ),
                child: Center(
                  child: MorphIcon(
                    icon: on ? c.active : c.icon,
                    size: 16,
                    strokeWidth: 2,
                    color: c.color,
                  ),
                ),
              ),
              const SizedBox(width: 10),
              Text(
                c.label,
                maxLines: 1,
                style: TextStyle(
                  fontSize: JTokens.fsUi,
                  fontWeight: FontWeight.w500,
                  color: on ? Colors.white : JTokens.muted,
                ),
              ),
              if (count != null) ...[
                const SizedBox(width: 10),
                Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 7,
                    vertical: 2,
                  ),
                  decoration: BoxDecoration(
                    color: on ? c.color : const Color(0x0FFFFFFF),
                    borderRadius: BorderRadius.circular(9999),
                    border: Border.all(
                      color: on ? Colors.transparent : const Color(0x0DFFFFFF),
                    ),
                  ),
                  child: Text(
                    '$count',
                    style: TextStyle(
                      fontSize: JTokens.fsSmall,
                      fontWeight: on ? FontWeight.w700 : FontWeight.w600,
                      color: on ? const Color(0xFF04121C) : JTokens.muted,
                      fontFeatures: const [FontFeature.tabularFigures()],
                    ),
                  ),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

/// `box-shadow: 0 0 16px -4px colour` of a 36px / 8px-corner button. CSS never paints a shadow under its own box; Flutter's
/// BoxShadow does, and through the translucent gradient it tinted the whole button.
class _OuterGlow extends CustomPainter {
  _OuterGlow(this.color);
  final Color color;

  @override
  void paint(Canvas canvas, Size size) {
    final box = RRect.fromRectAndRadius(
      Offset.zero & size,
      const Radius.circular(8),
    );
    canvas.save();
    canvas.clipPath(
      Path.combine(
        PathOperation.difference,
        Path()
          ..addRect(Rect.fromLTWH(-40, -40, size.width + 80, size.height + 80)),
        Path()..addRRect(box),
      ),
    );
    canvas.drawRRect(
      box.deflate(4),
      Paint()
        ..color = color
        ..maskFilter = const MaskFilter.blur(BlurStyle.normal, 8),
    );
    canvas.restore();
  }

  @override
  bool shouldRepaint(_OuterGlow old) => old.color != color;
}

/// A plain `.settings-btn` (36px, 8px corners, strong border) with an optional leading/trailing icon; [height] 30 is `.sd-pager .settings-btn`.
class MemButton extends StatelessWidget {
  const MemButton({
    super.key,
    required this.label,
    required this.onPressed,
    this.icon,
    this.iconAfter = false,
    this.height = 36,
    this.fontSize = JTokens.fsUi,
  });

  final String label;
  final VoidCallback? onPressed;
  final MorphGlyph? icon;
  final bool iconAfter;
  final double height;
  final double fontSize;

  @override
  Widget build(BuildContext context) {
    final glyph = icon == null
        ? null
        : MorphIcon(icon: icon!, size: 14, strokeWidth: 2, color: JTokens.text);
    return Opacity(
      opacity: onPressed == null ? 0.45 : 1,
      child: OutlinedButton(
        onPressed: onPressed,
        style: OutlinedButton.styleFrom(
          side: const BorderSide(color: JTokens.borderStrong),
          minimumSize: Size(0, height),
          padding: const EdgeInsets.symmetric(horizontal: 12),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (glyph != null && !iconAfter) ...[
              glyph,
              const SizedBox(width: 6),
            ],
            Flexible(
              child: Text(
                label,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(
                  fontSize: fontSize,
                  fontWeight: FontWeight.w500,
                  color: JTokens.text,
                ),
              ),
            ),
            if (glyph != null && iconAfter) ...[
              const SizedBox(width: 6),
              glyph,
            ],
          ],
        ),
      ),
    );
  }
}

/// The browser's `confirm(text)`: the text, Hủy / OK; true only on OK.
Future<bool> memConfirm(BuildContext context, String text) async {
  final ok = await showDialog<bool>(
    context: context,
    builder: (ctx) => AlertDialog(
      backgroundColor: JTokens.surface,
      content: SingleChildScrollView(
        child: Text(
          text,
          style: const TextStyle(color: JTokens.text, fontSize: JTokens.fsUi),
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(ctx, false),
          child: const Text('Hủy'),
        ),
        TextButton(
          key: const Key('confirm-ok'),
          onPressed: () => Navigator.pop(ctx, true),
          child: const Text('OK'),
        ),
      ],
    ),
  );
  return ok == true;
}

const memMono = TextStyle(
  fontFamily: 'monospace',
  fontFamilyFallback: ['Menlo', 'SF Mono', 'Cascadia Code', 'Consolas'],
);
