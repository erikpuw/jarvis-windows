// The building blocks the Settings pages share, from settings/styles.css (<=768px): .sd-card, .form-group, .sd-field-note,
// .sd-input-row, .status-row / .status-dot, .sd-meter, .sd-kv, .sd-badge, .sd-empty, .settings-feedback.

import 'package:flutter/material.dart';
import 'package:jarvis_mobile/theme/tokens.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';

const _tabular = [FontFeature.tabularFigures()];

/// `.sd-menu-btn`: 36px round, with a 44px touch target.
class RoundMenuButton extends StatelessWidget {
  const RoundMenuButton({super.key, required this.onTap, required this.child});
  final VoidCallback onTap;
  final Widget child;

  @override
  Widget build(BuildContext context) => GestureDetector(
    onTap: onTap,
    behavior: HitTestBehavior.opaque,
    child: Padding(
      padding: const EdgeInsets.all(4),
      child: Container(
        width: 36,
        height: 36,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          color: JTokens.accent.withValues(alpha: 0.14),
        ),
        alignment: Alignment.center,
        child: child,
      ),
    ),
  );
}

/// `.sd-card` with its `h4` (accent icon + title) and the 14px gap under it.
class SdCard extends StatelessWidget {
  const SdCard({
    super.key,
    this.icon,
    required this.title,
    required this.children,
  });

  /// null: a title without the accent icon (the MCP list and add cards).
  final IconData? icon;
  final String title;
  final List<Widget> children;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 18),
      decoration: BoxDecoration(
        color: JTokens.surface,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: JTokens.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Padding(
            padding: const EdgeInsets.only(bottom: 14),
            child: Row(
              children: [
                if (icon != null) ...[
                  Icon(icon, size: 17, color: JTokens.accent),
                  const SizedBox(width: 8),
                ],
                Expanded(
                  child: Text(
                    title,
                    style: const TextStyle(
                      fontSize: JTokens.fsUi,
                      fontWeight: FontWeight.w600,
                      color: JTokens.text,
                    ),
                  ),
                ),
              ],
            ),
          ),
          ...children,
        ],
      ),
    );
  }
}

/// `.sd-grid` on a phone: every card spans the full width, 8px apart, 16px from the sides.
class SdGrid extends StatelessWidget {
  const SdGrid({super.key, required this.children});

  final List<Widget> children;

  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    children: [
      for (var i = 0; i < children.length; i++) ...[
        if (i > 0) const SizedBox(height: 8),
        children[i],
      ],
    ],
  );
}

/// `.sd-lead`: the explaining paragraph under a card title.
class SdLead extends StatelessWidget {
  const SdLead(this.spans, {super.key});

  final List<InlineSpan> spans;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(bottom: 14),
    child: Text.rich(
      TextSpan(children: spans),
      style: const TextStyle(
        fontSize: JTokens.fsUi,
        height: 1.6,
        color: JTokens.muted,
      ),
    ),
  );
}

/// A `<code>` in a note: the browser's default monospace.
InlineSpan sdCode(String text) => TextSpan(
  text: text,
  style: const TextStyle(fontFamily: 'monospace'),
);

/// `.form-group`: a label over its control, 6px apart, 18px under the group.
class SdFormGroup extends StatelessWidget {
  const SdFormGroup({
    super.key,
    required this.label,
    required this.children,
    this.last = false,
  });

  final String label;
  final List<Widget> children;

  /// the final group of a card keeps no extra space under it.
  final bool last;

  @override
  Widget build(BuildContext context) => Padding(
    padding: EdgeInsets.only(bottom: last ? 0 : 18),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(
          label,
          style: const TextStyle(
            fontSize: JTokens.fsSmall,
            fontWeight: FontWeight.w500,
            color: JTokens.text,
          ),
        ),
        for (final c in children) ...[const SizedBox(height: 6), c],
      ],
    ),
  );
}

/// `.sd-field-note`.
class SdNote extends StatelessWidget {
  const SdNote(this.spans, {super.key});

  SdNote.text(String text, {Key? key}) : this([TextSpan(text: text)], key: key);

  final List<InlineSpan> spans;

  @override
  Widget build(BuildContext context) => Text.rich(
    TextSpan(children: spans),
    style: const TextStyle(
      fontSize: JTokens.fsSmall,
      height: 1.5,
      color: JTokens.muted,
    ),
  );
}

/// The text input of `#settings-container input[type=text|password|search]` on a phone: 40px, 8px corners, strong border.
class SdInput extends StatelessWidget {
  const SdInput({
    super.key,
    required this.controller,
    this.hint,
    this.obscure = false,
    this.onChanged,
    this.onSubmitted,
    this.errorText,
    this.minLines = 1,
    this.maxLines = 1,
  });

  final TextEditingController controller;
  final String? hint;
  final bool obscure;

  /// A `<textarea rows="n">`: [minLines] rows, growing to [maxLines].
  final int minLines;
  final int? maxLines;
  final ValueChanged<String>? onChanged;
  final ValueChanged<String>? onSubmitted;
  final String? errorText;

  @override
  Widget build(BuildContext context) {
    OutlineInputBorder border(Color c) => OutlineInputBorder(
      borderRadius: BorderRadius.circular(8),
      borderSide: BorderSide(color: c),
    );
    return TextField(
      controller: controller,
      obscureText: obscure,
      minLines: minLines,
      maxLines: obscure ? 1 : maxLines,
      autocorrect: false,
      enableSuggestions: !obscure,
      onChanged: onChanged,
      onSubmitted: onSubmitted,
      style: const TextStyle(color: JTokens.text, fontSize: JTokens.fsUi),
      decoration: InputDecoration(
        hintText: hint,
        hintStyle: const TextStyle(color: JTokens.textMuted),
        errorText: errorText,
        errorStyle: const TextStyle(
          color: JTokens.err,
          fontSize: JTokens.fsSmall,
        ),
        isDense: true,
        filled: true,
        fillColor: JTokens.surface2,
        contentPadding: const EdgeInsets.symmetric(
          horizontal: 12,
          vertical: 12,
        ),
        constraints: const BoxConstraints(minHeight: 40),
        border: border(JTokens.borderStrong),
        enabledBorder: border(JTokens.borderStrong),
        focusedBorder: border(JTokens.accent),
        errorBorder: border(JTokens.err),
        focusedErrorBorder: border(JTokens.err),
      ),
    );
  }
}

/// `.sd-search-box`: magnifier and a borderless field in a 38px box (agents / hooks / ... / mcp toolbars).
class SdSearchBox extends StatelessWidget {
  const SdSearchBox({
    super.key,
    required this.controller,
    required this.hint,
    required this.onChanged,
  });

  final TextEditingController controller;
  final String hint;
  final ValueChanged<String> onChanged;

  @override
  Widget build(BuildContext context) => Container(
    height: 38,
    padding: const EdgeInsets.symmetric(horizontal: 12),
    decoration: BoxDecoration(
      color: JTokens.surface2,
      borderRadius: BorderRadius.circular(8),
      border: Border.all(color: JTokens.borderStrong),
    ),
    child: Row(
      children: [
        const Icon(LucideIcons.search, size: 16, color: JTokens.muted),
        const SizedBox(width: 8),
        Expanded(
          child: TextField(
            controller: controller,
            onChanged: onChanged,
            autocorrect: false,
            style: const TextStyle(color: JTokens.text, fontSize: JTokens.fsUi),
            decoration: InputDecoration(
              hintText: hint,
              hintStyle: const TextStyle(color: JTokens.textMuted),
              isDense: true,
              border: InputBorder.none,
              enabledBorder: InputBorder.none,
              focusedBorder: InputBorder.none,
              filled: false,
              contentPadding: EdgeInsets.zero,
            ),
          ),
        ),
      ],
    ),
  );
}

/// `.sd-input-row`: the field takes the width, the button (and its feedback) sit in the row; the feedback goes under it on a phone.
class SdInputRow extends StatelessWidget {
  const SdInputRow({super.key, required this.input, required this.button});

  final Widget input;
  final Widget button;

  @override
  Widget build(BuildContext context) => Row(
    children: [
      Expanded(child: input),
      const SizedBox(width: 8),
      button,
    ],
  );
}

/// `.settings-feedback`: the text after an action, green when it worked, red when it did not.
class SdFeedback extends StatelessWidget {
  const SdFeedback(this.value, {super.key});

  final (String, bool)? value;

  @override
  Widget build(BuildContext context) {
    final v = value;
    if (v == null || v.$1.isEmpty) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.only(top: 8),
      child: Text(
        v.$1,
        style: TextStyle(
          fontSize: JTokens.fsSmall,
          color: v.$2 ? JTokens.ok : JTokens.err,
        ),
      ),
    );
  }
}

/// `.sd-empty` (also the loading and the error line of a list).
class SdEmpty extends StatelessWidget {
  const SdEmpty(this.text, {super.key, this.error = false, this.pad = true});

  final String text;
  final bool error;
  final bool pad;

  @override
  Widget build(BuildContext context) => Padding(
    padding: EdgeInsets.symmetric(vertical: pad ? 12 : 0),
    child: Text(
      text,
      style: TextStyle(
        fontSize: JTokens.fsUi,
        color: error ? JTokens.err : JTokens.muted,
      ),
    ),
  );
}

enum DotState { unknown, ok, err, off }

/// `.status-dot`: 8px; green and red glow, anything else the dull grey.
class StatusDot extends StatelessWidget {
  const StatusDot(this.state, {super.key});

  final DotState state;

  @override
  Widget build(BuildContext context) {
    final (color, glow) = switch (state) {
      DotState.ok => (JTokens.ok, const Color(0x804ADE80)),
      DotState.err => (JTokens.err, const Color(0x73F87171)),
      _ => (const Color(0xFF475569), null),
    };
    return Container(
      width: 8,
      height: 8,
      decoration: BoxDecoration(
        shape: BoxShape.circle,
        color: color,
        boxShadow: glow == null
            ? null
            : [BoxShadow(color: glow, blurRadius: 6)],
      ),
    );
  }
}

/// `.status-row`: dot, name, and the state text pushed to the right; a hairline under it unless [last].
class StatusRow extends StatelessWidget {
  const StatusRow({
    super.key,
    required this.name,
    required this.text,
    this.state = DotState.unknown,
    this.last = false,
    this.dense = false,
  });

  final String name;
  final String text;
  final DotState state;
  final bool last;

  /// `.sd-ov-services .status-row`: 8px instead of 10px above and below.
  final bool dense;

  @override
  Widget build(BuildContext context) {
    final v = dense ? 8.0 : 10.0;
    return Container(
      padding: EdgeInsets.symmetric(vertical: v),
      decoration: BoxDecoration(
        border: last
            ? null
            : const Border(bottom: BorderSide(color: JTokens.border)),
      ),
      child: Row(
        children: [
          StatusDot(state),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              name,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(
                fontSize: JTokens.fsUi,
                color: JTokens.text,
              ),
            ),
          ),
          const SizedBox(width: 12),
          Text(
            text,
            maxLines: 1,
            style: const TextStyle(
              fontSize: JTokens.fsSmall,
              color: JTokens.muted,
              fontFeatures: _tabular,
            ),
          ),
        ],
      ),
    );
  }
}

/// `.sd-meter`: a 4px track with the accent fill at [percent] (0-100).
class Meter extends StatelessWidget {
  const Meter(this.percent, {super.key});

  final num percent;

  @override
  Widget build(BuildContext context) {
    final f = (percent.clamp(0, 100)) / 100;
    return ClipRRect(
      borderRadius: BorderRadius.circular(2),
      child: Container(
        height: 4,
        alignment: Alignment.centerLeft,
        color: const Color(0x2494A3B8),
        child: FractionallySizedBox(
          widthFactor: f.toDouble(),
          child: Container(color: JTokens.accent),
        ),
      ),
    );
  }
}

/// `.sd-meter-row`: "label ... value" over a meter, 14px under it.
class MeterRow extends StatelessWidget {
  const MeterRow({
    super.key,
    required this.icon,
    required this.label,
    required this.value,
    required this.percent,
  });

  final IconData icon;
  final String label;
  final String value;
  final num percent;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(bottom: 14),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Row(
          children: [
            Icon(icon, size: 14, color: JTokens.accent),
            const SizedBox(width: 6),
            Expanded(
              child: Text(
                label,
                style: const TextStyle(
                  fontSize: JTokens.fsUi,
                  color: JTokens.text,
                ),
              ),
            ),
            const SizedBox(width: 12),
            Text(
              value,
              style: const TextStyle(
                fontSize: JTokens.fsUi,
                color: JTokens.muted,
                fontFeatures: _tabular,
              ),
            ),
          ],
        ),
        const SizedBox(height: 6),
        Meter(percent),
      ],
    ),
  );
}

/// `.sd-kv`: a label column as wide as its longest label, the value filling the rest, right-aligned and wrapping.
class SdKv extends StatelessWidget {
  const SdKv(this.rows, {super.key});

  final List<(String, String)> rows;

  @override
  Widget build(BuildContext context) => Table(
    columnWidths: const {0: IntrinsicColumnWidth(), 1: FlexColumnWidth()},
    children: [
      for (final (label, value) in rows)
        TableRow(
          children: [
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 5),
              child: Text(
                label,
                softWrap: false,
                style: const TextStyle(
                  fontSize: JTokens.fsUi,
                  color: JTokens.muted,
                ),
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 5, 0, 5),
              child: Text(
                value,
                textAlign: TextAlign.right,
                style: const TextStyle(
                  fontSize: JTokens.fsUi,
                  color: JTokens.text,
                  fontFeatures: _tabular,
                ),
              ),
            ),
          ],
        ),
    ],
  );
}

/// `.sd-badge`.
class SdBadge extends StatelessWidget {
  const SdBadge(this.text, {super.key});

  final String text;

  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 4),
    decoration: BoxDecoration(
      color: JTokens.surface2,
      borderRadius: BorderRadius.circular(6),
      border: Border.all(color: JTokens.border),
    ),
    child: Text(
      text,
      style: const TextStyle(
        fontSize: JTokens.fsSmall,
        color: JTokens.text,
        fontFeatures: _tabular,
      ),
    ),
  );
}
