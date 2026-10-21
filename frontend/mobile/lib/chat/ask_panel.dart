import 'package:flutter/material.dart';

import '../theme/tokens.dart';
import 'chat_models.dart';
import 'size_reporter.dart';

/// Where the question boxes live: one box at a time. A new card, or none, makes the shown one leave (`close()` in ask-panel.ts)
/// while the new one rises. [onHeight] reports the live box's height (0 when none) so the chat can make room.
class AskLayer extends StatefulWidget {
  const AskLayer({
    super.key,
    required this.card,
    required this.onAnswer,
    required this.onHeight,
  });

  final AskCard? card;
  final void Function(Map<String, dynamic> msg) onAnswer;
  final ValueChanged<double> onHeight;

  @override
  State<AskLayer> createState() => _AskLayerState();
}

class _AskLayerState extends State<AskLayer> {
  final _shown = <({AskCard card, bool leaving})>[];

  @override
  void initState() {
    super.initState();
    final card = widget.card;
    if (card != null) _shown.add((card: card, leaving: false));
  }

  @override
  void didUpdateWidget(AskLayer old) {
    super.didUpdateWidget(old);
    final card = widget.card;
    if (identical(card, old.card)) return;
    for (var i = 0; i < _shown.length; i++) {
      if (!_shown[i].leaving) _shown[i] = (card: _shown[i].card, leaving: true);
    }
    if (card != null) {
      _shown.add((card: card, leaving: false));
    } else {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) widget.onHeight(0);
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Stack(
      alignment: Alignment.bottomCenter,
      children: [
        for (final e in _shown)
          AskPanel(
            key: ObjectKey(e.card),
            card: e.card,
            leaving: e.leaving,
            onAnswer: widget.onAnswer,
            onSize: (s) {
              if (!e.leaving) widget.onHeight(s.height);
            },
            onGone: () {
              if (mounted) {
                setState(() => _shown.removeWhere((x) => x.card == e.card));
              }
            },
          ),
      ],
    );
  }
}

/// The question box above the command bar (ask-panel.ts + ask-panel.css): approve, select or input.
/// An answer goes back as `interactive_response` through [onAnswer]; the controller then drops the card.
/// It rises in 260 ms (`ask-in`) and, once [leaving], sinks away in 160 ms (`ask-out`) and calls [onGone].
class AskPanel extends StatefulWidget {
  const AskPanel({
    super.key,
    required this.card,
    required this.onAnswer,
    this.leaving = false,
    this.onSize,
    this.onGone,
  });

  final AskCard card;
  final void Function(Map<String, dynamic> msg) onAnswer;
  final bool leaving;
  final ValueChanged<Size>? onSize;
  final VoidCallback? onGone;

  @override
  State<AskPanel> createState() => _AskPanelState();
}

const _ink = Color(0xFFA3A3A3); // .ask-panel colour
const _panelFill = Color(0xFF0A0A0A);

class _AskPanelState extends State<AskPanel> with TickerProviderStateMixin {
  // ask-in 0.26s cubic-bezier(0.2, 0.9, 0.3, 1.15), ask-out 0.16s ease-in
  late final _in = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 260),
  )..forward();
  late final _out = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 160),
  );
  static const _rise = Cubic(0.2, 0.9, 0.3, 1.15);
  bool _answered = false; // answer() in ask-panel.ts: only the first tap counts
  final _input = TextEditingController();
  late final Set<Object?> _picked = {
    for (final o in _options)
      if (o['selected'] == true) o['value'],
  };

  Map<String, dynamic> get _raw => widget.card.raw;

  List<Map<String, dynamic>> get _options => [
    for (final o in (_raw['options'] as List?) ?? const [])
      if (o is Map) Map<String, dynamic>.from(o),
  ];

  @override
  void initState() {
    super.initState();
    final v = _raw['value'];
    if (v is String) _input.text = v;
  }

  @override
  void didUpdateWidget(AskPanel old) {
    super.didUpdateWidget(old);
    if (widget.leaving && !old.leaving) {
      _out.forward().whenComplete(() => widget.onGone?.call());
    }
  }

  @override
  void dispose() {
    _in.dispose();
    _out.dispose();
    _input.dispose();
    super.dispose();
  }

  void _answer(String action, [Object? value]) {
    if (_answered || widget.leaving) return;
    _answered = true;
    widget.onAnswer({
      'type': 'interactive_response',
      'cardId': widget.card.id,
      'action': action,
      'value': ?value,
    });
  }

  @override
  Widget build(BuildContext context) {
    final card = widget.card;
    final title = _raw['title'] as String?;
    final description = _raw['description'] as String?;
    final actions = <Widget>[];
    final body = <Widget>[];

    if (title != null && title.isNotEmpty) {
      body.add(
        Text(
          title,
          style: const TextStyle(
            fontSize: JTokens.fsLabel,
            fontWeight: FontWeight.w600,
            letterSpacing: 0.44,
            color: Color(0xFF737373),
          ),
        ),
      );
    }
    if (description != null && description.isNotEmpty) {
      body.add(
        Text(
          description,
          style: const TextStyle(
            color: Color(0xFFE5E5E5),
            fontSize: JTokens.fsSmall,
            height: 1.5,
          ),
        ),
      );
    }

    switch (card.type) {
      case 'approve':
        actions.addAll([
          _AskButton(
            label: (_raw['rejectLabel'] as String?) ?? 'Từ chối',
            onTap: () => _answer('reject'),
          ),
          _AskButton(
            label: (_raw['approveLabel'] as String?) ?? 'Đồng ý',
            primary: true,
            onTap: () => _answer('approve'),
          ),
        ]);
      case 'select':
        body.add(_optionList());
        if (_raw['multiple'] == true) {
          actions.add(
            _AskButton(
              label: (_raw['submitLabel'] as String?) ?? 'Xác nhận',
              primary: true,
              onTap: () => _answer('submit', _picked.toList()),
            ),
          );
        }
      default: // input
        body.add(
          TextField(
            controller: _input,
            maxLines: 3,
            style: const TextStyle(color: Color(0xFFE5E5E5), fontSize: 13),
            decoration: InputDecoration(
              isDense: true,
              filled: true,
              fillColor: const Color(0xFF050505),
              hintText: (_raw['placeholder'] as String?) ?? 'Nhập nội dung...',
              hintStyle: const TextStyle(color: Color(0xFF525252)),
              contentPadding: const EdgeInsets.all(10),
              border: OutlineInputBorder(
                borderRadius: BorderRadius.circular(8),
                borderSide: const BorderSide(color: Color(0xFF333333)),
              ),
              focusedBorder: OutlineInputBorder(
                borderRadius: BorderRadius.circular(8),
                borderSide: const BorderSide(color: Color(0xFF525252)),
              ),
            ),
          ),
        );
        actions.addAll([
          _AskButton(
            label: (_raw['cancelLabel'] as String?) ?? 'Hủy',
            onTap: () => _answer('cancel'),
          ),
          _AskButton(
            label: (_raw['submitLabel'] as String?) ?? 'Gửi',
            primary: true,
            onTap: () => _answer('submit', _input.text),
          ),
        ]);
    }

    return Align(
      alignment: Alignment.bottomCenter,
      child: AnimatedBuilder(
        animation: Listenable.merge([_in, _out]),
        builder: (context, child) {
          final v = _rise.transform(_in.value);
          final o = Curves.easeIn.transform(_out.value);
          return IgnorePointer(
            ignoring: widget.leaving,
            child: Opacity(
              opacity: (v.clamp(0.0, 1.0) * (1 - o)).clamp(0.0, 1.0),
              child: Transform.translate(
                offset: Offset(0, 14 * (1 - v) + 10 * o),
                child: Transform.scale(scale: 0.97 + 0.03 * v, child: child),
              ),
            ),
          );
        },
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 400),
          child: SizeReporter(
            onSize: (s) => widget.onSize?.call(s),
            child: Container(
              width: double.infinity,
              padding: const EdgeInsets.fromLTRB(16, 14, 16, 14),
              decoration: BoxDecoration(
                color: _panelFill,
                border: Border.all(color: const Color(0xFF262626)),
                borderRadius: BorderRadius.circular(16),
                boxShadow: const [
                  BoxShadow(
                    color: Color(0x8C000000),
                    blurRadius: 32,
                    offset: Offset(0, 12),
                  ),
                ],
              ),
              child: DefaultTextStyle.merge(
                style: const TextStyle(color: _ink, fontSize: JTokens.fsSmall),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    for (var i = 0; i < body.length; i++) ...[
                      if (i > 0) const SizedBox(height: 10),
                      body[i],
                    ],
                    if (actions.isNotEmpty) ...[
                      const SizedBox(height: 10),
                      Row(
                        mainAxisAlignment: MainAxisAlignment.end,
                        children: [
                          for (var i = 0; i < actions.length; i++) ...[
                            if (i > 0) const SizedBox(width: 8),
                            actions[i],
                          ],
                        ],
                      ),
                    ],
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }

  /// `.ask-options`: one choice answers at once; several toggle, then the confirm button sends them.
  Widget _optionList() {
    final multiple = _raw['multiple'] == true;
    return ConstrainedBox(
      constraints: BoxConstraints(
        maxHeight: MediaQuery.sizeOf(context).height * 0.4,
      ),
      child: SingleChildScrollView(
        child: Column(
          children: [
            for (final o in _options)
              Padding(
                padding: const EdgeInsets.only(bottom: 4),
                child: _OptionRow(
                  label: '${o['label'] ?? o['value']}',
                  selected: _picked.contains(o['value']),
                  onTap: () {
                    if (!multiple) {
                      _answer('submit', [o['value']]);
                      return;
                    }
                    setState(() {
                      if (!_picked.remove(o['value'])) _picked.add(o['value']);
                    });
                  },
                ),
              ),
          ],
        ),
      ),
    );
  }
}

class _OptionRow extends StatelessWidget {
  const _OptionRow({
    required this.label,
    required this.selected,
    required this.onTap,
  });
  final String label;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        width: double.infinity,
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
        decoration: BoxDecoration(
          color: selected ? const Color(0x0FFFFFFF) : Colors.transparent,
          border: Border.all(
            color: selected ? const Color(0xFF404040) : const Color(0xFF262626),
          ),
          borderRadius: BorderRadius.circular(8),
        ),
        child: Text(
          label,
          style: const TextStyle(color: Color(0xFFE5E5E5), fontSize: 13),
        ),
      ),
    );
  }
}

class _AskButton extends StatelessWidget {
  const _AskButton({
    required this.label,
    required this.onTap,
    this.primary = false,
  });
  final String label;
  final VoidCallback onTap;
  final bool primary;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 5),
        decoration: BoxDecoration(
          border: Border.all(
            color: primary ? const Color(0xFF525252) : const Color(0xFF333333),
          ),
          borderRadius: BorderRadius.circular(8),
        ),
        child: Text(
          label,
          style: TextStyle(
            fontSize: 13,
            fontWeight: FontWeight.w500,
            color: primary ? const Color(0xFFFAFAFA) : _ink,
          ),
        ),
      ),
    );
  }
}
