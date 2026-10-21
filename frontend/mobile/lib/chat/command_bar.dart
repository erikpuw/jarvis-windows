import 'dart:async';

import 'package:flutter/material.dart';

import '../theme/tokens.dart';
import 'lucide_glyphs.dart';
import 'metal_send_button.dart';
import 'morph_icon.dart';

/// The command bar (index.html #command-bar-inner, style.css phone block): [upload] [attachment chip] [input] [send].
class CommandBar extends StatefulWidget {
  const CommandBar({
    super.key,
    required this.input,
    required this.focus,
    required this.onSend,
    this.onUpload,
    this.attachment,
    this.hasAttachment = false,
    this.barActive = true,
  });

  final TextEditingController input;
  final FocusNode focus;

  /// Called by the send button; the caller reads and clears [input].
  final VoidCallback onSend;

  /// The file picker behind the `+` button. The button shows only when this is set.
  final VoidCallback? onUpload;

  /// The pinned-file chip, shown between the upload button and the input.
  final Widget? attachment;

  /// A file is pinned: the bar may send with an empty input (main.ts sendCommand: `!text && !pendingFile`).
  final bool hasAttachment;

  /// False while the bar is hidden: the send button's shader and halo stop.
  final bool barActive;

  static const placeholder = 'Nhập nội dung, / hành động, @ gọi tên';

  @override
  State<CommandBar> createState() => _CommandBarState();
}

class _CommandBarState extends State<CommandBar> {
  bool _focused = false;
  bool _sent = false; // paper plane -> check for a second after a send
  Timer? _sentTimer;

  @override
  void initState() {
    super.initState();
    widget.focus.addListener(_onFocus);
  }

  void _onFocus() => setState(() => _focused = widget.focus.hasFocus);

  @override
  void dispose() {
    widget.focus.removeListener(_onFocus);
    _sentTimer?.cancel();
    super.dispose();
  }

  void _send() {
    if (widget.input.text.trim().isEmpty && !widget.hasAttachment) return;
    widget.onSend();
    _sentTimer?.cancel();
    setState(() => _sent = true);
    _sentTimer = Timer(const Duration(seconds: 1), () {
      if (mounted) setState(() => _sent = false);
    });
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(4),
      decoration: BoxDecoration(
        color: JTokens.cmdBg,
        border: Border.all(
          color: Color(
            _focused ? 0x40FFFFFF : 0x26FFFFFF,
          ), // .25 focused, .15 otherwise
        ),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          if (widget.onUpload != null)
            // 14px icon with a 40px touch target (css: padding 13px, margin -13px)
            GestureDetector(
              behavior: HitTestBehavior.opaque,
              onTap: widget.onUpload,
              child: SizedBox(
                width: 28,
                height: 34,
                child: Center(
                  // icons.ts SPECS btn-upload: Plus <-> Paperclip while a file is pinned, 14px, stroke 2.5
                  child: MorphIcon(
                    icon: widget.hasAttachment ? paperclipGlyph : plusGlyph,
                    color: const Color(0x660EA5E9),
                    size: 14,
                    strokeWidth: 2.5,
                  ),
                ),
              ),
            ),
          if (widget.onUpload != null)
            const SizedBox(
              width: 5,
            ), // 12px gap minus the 7px the touch target adds on the right
          if (widget.attachment != null) ...[
            widget.attachment!,
            const SizedBox(width: 12),
          ],
          Expanded(
            child: Padding(
              padding: const EdgeInsets.only(bottom: 4),
              child: TextField(
                controller: widget.input,
                focusNode: widget.focus,
                minLines: 1,
                maxLines: 6, // max-height 140px
                keyboardType: TextInputType.multiline,
                textInputAction: TextInputAction.newline, // phones: Enter makes a new line, the button sends
                autocorrect: false,
                cursorColor: JTokens.accent,
                style: const TextStyle(
                  fontSize: JTokens.fsInput,
                  height: 1.35,
                  color: Colors.white,
                ),
                decoration: const InputDecoration(
                  isCollapsed: true,
                  border: InputBorder.none,
                  contentPadding: EdgeInsets.symmetric(vertical: 2),
                  hintText: CommandBar.placeholder,
                  hintMaxLines: 1,
                  hintStyle: TextStyle(
                    fontSize: JTokens.fsInput,
                    height: 1.35,
                    color: Color(0x4D0EA5E9),
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
              ),
            ),
          ),
          const SizedBox(width: 12),
          MetalSendButton(sent: _sent, active: widget.barActive, onTap: _send),
        ],
      ),
    );
  }
}
