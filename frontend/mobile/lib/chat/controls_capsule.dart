import 'dart:async';

import 'package:flutter/material.dart';

import '../theme/tokens.dart';
import 'lucide_glyphs.dart';
import 'morph_icon.dart';

/// Top-right control menu (controls-menu.ts + style.css `#controls`): one round main button; opened, the buttons drop into one
/// column inside a vertical capsule under it (44px slots, 6px padding). It folds back by itself after 4s without a touch.
/// Web buttons not here: webcam and orb (the app has neither).
class ControlsCapsule extends StatefulWidget {
  const ControlsCapsule({
    super.key,
    required this.ttsMuted,
    required this.micMuted,
    required this.barVisible,
    this.onMic,
    required this.onTts,
    required this.onToggleBar,
  });

  /// TTS replies are switched off (the volume button turns red).
  final bool ttsMuted;

  /// The mic is off (btn-mute `muted`).
  final bool micMuted;

  /// The command bar is shown (btn-cmd-bar `active`).
  final bool barVisible;

  /// Task 7 wires the voice input; until then the mic button does nothing.
  final VoidCallback? onMic;
  final VoidCallback onTts;
  final VoidCallback onToggleBar;

  static const idle = Duration(seconds: 4);

  @override
  State<ControlsCapsule> createState() => _ControlsCapsuleState();
}

class _ControlsCapsuleState extends State<ControlsCapsule> {
  static const _slot = 44.0;
  static const _spring = Cubic(0.34, 1.4, 0.64, 1);
  static const _anim = Duration(milliseconds: 300);

  bool _open = false;
  Timer? _timer;

  void _set(bool open) {
    _timer?.cancel();
    setState(() => _open = open);
    if (open) _timer = Timer(ControlsCapsule.idle, () => _set(false));
  }

  /// Any touch on a button of the open menu counts as activity: wait another [ControlsCapsule.idle].
  void _touched() {
    if (_open) _set(true);
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  /// [active]: `#controls button.active` (bar shown, mic on) sits on a #27272a disc with a 25% white ring.
  Widget _button(Widget icon, VoidCallback? onTap, {bool active = false}) =>
      GestureDetector(
        behavior: HitTestBehavior.opaque,
        onTap: () {
          onTap?.call();
          _touched();
        },
        child: SizedBox(
          width: _slot,
          height: _slot,
          child: Center(
            child: AnimatedContainer(
              duration: const Duration(milliseconds: 200),
              width: 34, // what the 44px capsule leaves inside its 5px padding
              height: 34,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                color: active ? JTokens.surface3 : Colors.transparent,
                border: Border.all(
                  color: active ? const Color(0x40FFFFFF) : Colors.transparent,
                ),
              ),
              child: Center(child: icon),
            ),
          ),
        ),
      );

  /// icons.ts SPECS: the 18px glyph (stroke 1.5) morphs between its off and on lucide icon when the state flips.
  Widget _morph(MorphGlyph glyph, Color color) =>
      MorphIcon(icon: glyph, color: color, size: 18);

  @override
  Widget build(BuildContext context) {
    final pad = MediaQuery.paddingOf(context);
    const red = Color(0x99EF4444); // rgba(239,68,68,.6)
    const active = Colors.white; // #controls button.active
    const sky = Color(0x800EA5E9); // rgba(14,165,233,.5)
    final buttons = [
      _button(
        _morph(
          widget.barVisible ? chevronDownGlyph : squareTerminalGlyph,
          widget.barVisible ? active : sky,
        ),
        widget.onToggleBar,
        active: widget.barVisible,
      ),
      _button(
        _morph(
          widget.ttsMuted ? volumeXGlyph : volume2Glyph,
          widget.ttsMuted ? red : sky,
        ),
        widget.onTts,
      ),
      _button(
        _morph(
          widget.micMuted ? micOffGlyph : micGlyph,
          widget.micMuted ? red : active,
        ),
        widget.onMic,
        active: !widget.micMuted,
      ),
    ];
    final capsuleHeight = 6 + buttons.length * _slot + 6;
    return Positioned(
      // --controls-inset: 12px on phones, plus the safe area
      top: 12 + pad.top,
      // the box is the capsule's 44px, centred on the 36px button (4px wider each side); open, it grows down to hold the capsule so
      // that its buttons take touches (a child outside its parent's bounds does not)
      right: 8 + pad.right,
      width: 44,
      height: _open ? 42 + capsuleHeight : 36,
      child: Stack(
        children: [
          // the capsule: 44 wide, centred on the main button, 6px under it
          Positioned(
            top: 42,
            left: 0,
            right: 0,
            height: capsuleHeight,
            child: IgnorePointer(
              ignoring: !_open,
              child: AnimatedOpacity(
                duration: const Duration(milliseconds: 200),
                opacity: _open ? 1 : 0,
                child: AnimatedScale(
                  duration: _anim,
                  curve: _spring,
                  alignment: Alignment.topCenter,
                  scale: _open ? 1 : 0.2,
                  child: Container(
                    padding: const EdgeInsets.all(
                      5,
                    ), // 6px incl. the 1px border
                    decoration: BoxDecoration(
                      color: const Color(0xE6000000),
                      border: Border.all(color: const Color(0x330EA5E9)),
                      borderRadius: BorderRadius.circular(22),
                    ),
                    child: Column(children: buttons),
                  ),
                ),
              ),
            ),
          ),
          Positioned(
            top: 0,
            right: 4,
            width: 36,
            height: 36,
            child: GestureDetector(
              onTap: () => _set(!_open),
              child: Container(
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  color: const Color(0x240EA5E9),
                  border: Border.all(color: const Color(0x330EA5E9)),
                ),
                child: Center(
                  child: _morph(
                    _open ? xGlyph : menuGlyph,
                    const Color(0xB30EA5E9),
                  ),
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}
