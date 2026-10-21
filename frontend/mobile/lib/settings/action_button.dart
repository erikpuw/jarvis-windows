import 'dart:async';

import 'package:flutter/material.dart';

import '../chat/lucide_glyphs.dart';
import '../chat/morph_icon.dart';
import '../theme/tokens.dart';

/// icons.ts ACTION_ICON: the idle icon of an action button.
enum ActionKind {
  save(saveGlyph),
  test(plugZapGlyph),
  upload(uploadGlyph),
  delete(trashGlyph),
  refresh(refreshCwGlyph);

  const ActionKind(this.glyph);
  final MorphGlyph glyph;
}

const _feedbackMs = Duration(milliseconds: 1200); // ACTION_FEEDBACK_MS

/// A settings button that runs [task] behind one morphing icon (icons.ts decorateActionButton + runAction): idle icon -> spinner
/// -> check / x -> idle icon. [task] returning `false` means cancelled (back to idle silently); throwing means failure. The result
/// text goes to [onFeedback] (okText, or the error message); with no [onFeedback] a failure is shown in a SnackBar, never
/// silently. The button ignores taps while busy.
class ActionButton extends StatefulWidget {
  const ActionButton({
    super.key,
    required this.kind,
    required this.label,
    required this.task,
    this.okText = 'Đã lưu',
    this.onFeedback,
    this.primary = false,
    this.danger = false,
    this.destructive = false,
    this.compact = false,
    this.enabled = true,
    this.height,
    this.minWidth = 0,
    this.onDone,
  });

  final ActionKind kind;
  final String label;
  final Future<bool?> Function() task;
  final String okText;
  final void Function(String text, bool ok)? onFeedback;

  /// `.settings-btn.primary`: accent fill, dark text.
  final bool primary;

  /// `.settings-btn.danger-restart` (the Restart button in the page head): red tint, 11px text, 40px high.
  final bool danger;

  /// `.settings-btn.danger`: red outline and text (Xóa, Xoá đã chọn).
  final bool destructive;

  /// The small toolbar button (`.sd-btn-bulk-delete`, `.sd-btn-reembed-all`): 30px, 13px text, 6px corners and gap.
  final bool compact;

  /// Overrides the height (a phone's `.settings-btn` is 40px; `.sd-mem-detail-actions .primary` 38px).
  final double? height;
  final double minWidth;

  /// `:disabled`: 45% opacity, no taps.
  final bool enabled;

  /// runAction's caller continuing after the call: runs once the feedback (check / x) has gone; `ok` is false for a failure and for a
  /// cancelled task.
  final Future<void> Function(bool ok)? onDone;

  @override
  State<ActionButton> createState() => _ActionButtonState();
}

enum _Phase { idle, busy, ok, error }

class _ActionButtonState extends State<ActionButton>
    with SingleTickerProviderStateMixin {
  // spin-flow 1s linear infinite while busy
  late final AnimationController _spin = AnimationController(
    vsync: this,
    duration: const Duration(seconds: 1),
  );
  _Phase _phase = _Phase.idle;

  @override
  void dispose() {
    _spin.dispose();
    super.dispose();
  }

  Future<void> _run() async {
    if (_phase != _Phase.idle) return;
    setState(() => _phase = _Phase.busy);
    _spin.repeat();
    var ok = true;
    var cancelled = false;
    var message = '';
    try {
      cancelled = (await widget.task()) == false;
    } catch (e) {
      ok = false;
      message = e is Exception ? e.toString() : '$e';
    }
    if (!mounted) return;
    _spin
      ..stop()
      ..value = 0;
    if (cancelled) {
      setState(() => _phase = _Phase.idle);
      await widget.onDone?.call(false);
      return;
    }
    setState(() => _phase = ok ? _Phase.ok : _Phase.error);
    final text = ok ? widget.okText : message;
    if (widget.onFeedback != null) {
      widget.onFeedback!(text, ok);
    } else if (!ok) {
      ScaffoldMessenger.maybeOf(context)
          ?.showSnackBar(SnackBar(content: Text(text)));
    }
    await Future<void>.delayed(_feedbackMs);
    if (mounted) setState(() => _phase = _Phase.idle);
    await widget.onDone?.call(ok);
  }

  @override
  Widget build(BuildContext context) {
    final idle = widget.primary
        ? const Color(0xFF04121C)
        : widget.danger
        ? const Color(0xFFFCA5A5)
        : widget.destructive
        ? JTokens.err
        : JTokens.text;
    final glyph = switch (_phase) {
      _Phase.idle => widget.kind.glyph,
      _Phase.busy => loaderCircleGlyph,
      _Phase.ok => checkGlyph,
      _Phase.error => xGlyph,
    };
    final color = switch (_phase) {
      _Phase.ok => widget.primary ? const Color(0xFF04121C) : JTokens.ok,
      _Phase.error => JTokens.err,
      _ => idle,
    };
    final icon = RotationTransition(
      turns: _spin,
      child: MorphIcon(icon: glyph, color: color, size: 15, strokeWidth: 2),
    );
    final label = Text(
      widget.label,
      maxLines: 1,
      overflow: TextOverflow.ellipsis,
      style: TextStyle(
        fontSize: widget.danger
            ? JTokens.fsLabel
            : widget.compact
            ? JTokens.fsSmall
            : JTokens.fsUi,
        fontWeight: widget.primary ? FontWeight.w600 : FontWeight.w500,
        color: idle,
      ),
    );
    final shape = RoundedRectangleBorder(
      borderRadius: BorderRadius.circular(widget.compact ? 6 : 8),
    );
    // busy keeps the button looking enabled (pointer-events none, not :disabled): _run just returns
    final child = Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        icon,
        SizedBox(width: widget.compact ? 6 : 8),
        Flexible(child: label),
      ],
    );
    final size = Size(
      widget.minWidth,
      widget.height ?? (widget.danger ? 40 : (widget.compact ? 30 : 36)),
    );
    // .sd-btn-bulk-delete:not(:disabled): a stronger red tint and glow
    final lit = widget.destructive && widget.compact && widget.enabled;
    final button = widget.primary
        ? ElevatedButton(
            onPressed: widget.enabled ? _run : null,
            style: ElevatedButton.styleFrom(
              backgroundColor: JTokens.accent,
              minimumSize: size,
              shape: shape,
              elevation: 0,
            ),
            child: child,
          )
        : OutlinedButton(
            onPressed: widget.enabled ? _run : null,
            style: OutlinedButton.styleFrom(
              side: BorderSide(
                color: lit
                    ? const Color(0x80F87171)
                    : widget.destructive
                    ? const Color(0x66F87171)
                    : widget.danger
                    ? const Color(0x66F87171)
                    : JTokens.borderStrong,
              ),
              backgroundColor: lit
                  ? const Color(0x26F87171)
                  : widget.danger
                  ? const Color(0x14EF4444)
                  : null,
              padding: widget.danger || widget.compact
                  ? const EdgeInsets.symmetric(horizontal: 10)
                  : null,
              minimumSize: size,
              shape: shape,
            ),
            child: child,
          );
    return Opacity(opacity: widget.enabled ? 1 : 0.45, child: button);
  }
}
