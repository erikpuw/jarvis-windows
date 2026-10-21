import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/scheduler.dart';

import '../theme/tokens.dart';
import 'chat_models.dart';
import 'markdown_view.dart';
import 'stream_loader.dart';
import 'typewriter.dart';

/// #chat-history: newest at the bottom, 6px between messages, 6px padding. A reversed list keeps the newest one in place as text
/// streams in. A message the user sends jumps back to the bottom.
class MessageList extends StatefulWidget {
  const MessageList({
    super.key,
    required this.items,
    required this.resolveUrl,
    this.onLinkTap,
    this.onReaderTap,
    this.bottomInset = 0,
    this.buildExtra,
  });

  final List<ChatItem> items;
  final String Function(String url) resolveUrl;
  final void Function(String url)? onLinkTap;

  /// The small button after an http(s) link (`.reader-trigger-btn`): opens the reader card.
  final void Function(String url, String title)? onReaderTap;

  /// Extra room under the last message (the height of the question box over it).
  final double bottomInset;

  /// Draws the cards this list does not (ImageMsg, FileMsg).
  final Widget? Function(BuildContext context, ChatItem item)? buildExtra;

  @override
  State<MessageList> createState() => _MessageListState();
}

class _MessageListState extends State<MessageList> {
  final _scroll = ScrollController();
  // A finished message is the same object on every chunk of the one streaming below it: its row widget is handed back as is,
  // so Flutter skips it (no markdown walk, no layout of its own) instead of rebuilding every visible message per chunk.
  final _rows =
      <int, ({ChatItem item, Object? a, Object? b, Object? c, Widget row})>{};
  bool _covered = false; // messages sit under the top edge: the black fade shows (.has-chat-fade)
  // How many items the list had last build. `old.items` can't be used: ChatController.items is a view over
  // one growing list, so the old and new widget see the same length and a send never scrolled.
  int _seen = 0;

  @override
  void initState() {
    super.initState();
    _seen = widget.items.length;
  }

  @override
  void didUpdateWidget(MessageList old) {
    super.didUpdateWidget(old);
    final items = widget.items;
    final grew = items.length > _seen;
    _seen = items.length;
    // main.ts scrollToBottomIfNeeded(true): a send, or a new answer starting (stream_start), brings the
    // newest message back into view even while the user reads far up the history.
    final last = items.isEmpty ? null : items.last;
    if (grew && (last is UserMsg || (last is AssistantMsg && last.streaming))) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (_scroll.hasClients) _scroll.jumpTo(0);
      });
    }
  }

  @override
  void dispose() {
    _scroll.dispose();
    super.dispose();
  }

  void _onMetrics(ScrollMetrics m) {
    final covered = m.maxScrollExtent > 0;
    if (covered != _covered) setState(() => _covered = covered);
  }

  @override
  Widget build(BuildContext context) {
    final items = widget.items;
    _rows.removeWhere((n, _) => n >= items.length);
    return Stack(
      children: [
        NotificationListener<ScrollMetricsNotification>(
          onNotification: (n) {
            // layout is in progress here; defer the rebuild
            WidgetsBinding.instance.addPostFrameCallback((_) {
              if (mounted) _onMetrics(n.metrics);
            });
            return false;
          },
          // the question box hangs over the bottom: the padding glides to its height (ask-panel.ts padChat); a reversed list
          // keeps the newest message at its end meanwhile
          child: TweenAnimationBuilder<double>(
            tween: Tween(end: widget.bottomInset),
            duration: const Duration(milliseconds: 260),
            curve: const Cubic(0.2, 0.9, 0.3, 1),
            builder: (context, inset, _) {
              final w = MediaQuery.sizeOf(context).width;
              final hPad = w >= 410 ? 12.0 : 8.0;
              return ListView.separated(
                controller: _scroll,
                reverse: true,
                padding: EdgeInsets.fromLTRB(hPad, 6, hPad, 6 + inset),
                itemCount: items.length,
                separatorBuilder: (_, _) => SizedBox(height: w >= 410 ? 8 : 6),
                itemBuilder: (context, i) {
                  final n =
                      items.length -
                      1 -
                      i; // position from the oldest: stable while a message grows
                  return _cachedRow(context, n, items[n]);
                },
              );
            },
          ),
        ),
        // a 32px black fade over the top edge once messages scroll under it
        Positioned(
          top: 0,
          left: 0,
          right: 0,
          height: 32,
          child: IgnorePointer(
            child: AnimatedOpacity(
              duration: const Duration(milliseconds: 200),
              opacity: _covered ? 1 : 0,
              child: const DecoratedBox(
                decoration: BoxDecoration(
                  gradient: LinearGradient(
                    begin: Alignment.topCenter,
                    end: Alignment.bottomCenter,
                    stops: [0, 0.5, 1],
                    colors: [
                      Color(0xF2000000),
                      Color(0x73000000),
                      Color(0x00000000),
                    ],
                  ),
                ),
              ),
            ),
          ),
        ),
      ],
    );
  }

  Widget _cachedRow(BuildContext context, int n, ChatItem item) {
    final settled =
        item is UserMsg || (item is AssistantMsg && !item.streaming);
    final hit = _rows[n];
    if (settled &&
        hit != null &&
        identical(hit.item, item) &&
        hit.a == widget.onLinkTap &&
        hit.b == widget.onReaderTap &&
        hit.c == widget.resolveUrl) {
      return hit.row;
    }
    final row = KeyedSubtree(
      key: ValueKey(n),
      child: _row(context, item),
    ); // ListView adds the RepaintBoundary
    if (settled) {
      _rows[n] = (
        item: item,
        a: widget.onLinkTap,
        b: widget.onReaderTap,
        c: widget.resolveUrl,
        row: row,
      );
    } else {
      _rows.remove(n);
    }
    return row;
  }

  Widget _row(BuildContext context, ChatItem item) => switch (item) {
    UserMsg() => _UserBubble(item),
    AssistantMsg() => _Answer(
      item,
      resolveUrl: widget.resolveUrl,
      onLinkTap: widget.onLinkTap,
      onReaderTap: widget.onReaderTap,
    ),
    _ => widget.buildExtra?.call(context, item) ?? const SizedBox.shrink(),
  };
}

/// `.chat-bubble.user`: the only message with a bubble (radius 18, 4 at the bottom right).
class _UserBubble extends StatelessWidget {
  const _UserBubble(this.msg);
  final UserMsg msg;

  @override
  Widget build(BuildContext context) {
    final text = msg.attachmentName == null
        ? msg.text
        : '📎 [${msg.attachmentName}] ${msg.text}';
    return Align(
      alignment: Alignment.centerRight,
      child: ConstrainedBox(
        constraints: BoxConstraints(
          maxWidth: MediaQuery.sizeOf(context).width * 0.92,
        ),
        child: Opacity(
          opacity: msg.pending ? 0.8 : 1,
          child: DecoratedBox(
            decoration: const BoxDecoration(
              color: Color(0xB3000000),
              border: Border.fromBorderSide(
                BorderSide(color: Color(0x26FFFFFF)),
              ),
              borderRadius: BorderRadius.only(
                topLeft: Radius.circular(JTokens.bubbleRadius),
                topRight: Radius.circular(JTokens.bubbleRadius),
                bottomLeft: Radius.circular(JTokens.bubbleRadius),
                bottomRight: Radius.circular(4),
              ),
            ),
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  if (msg.pending) ...[
                    const SizedBox(
                      width: 10,
                      height: 10,
                      child: CircularProgressIndicator(
                        strokeWidth: 2,
                        color: JTokens.accent,
                        backgroundColor: Color(0x330EA5E9),
                      ),
                    ),
                    const SizedBox(width: 8),
                  ],
                  Flexible(
                    child: Text(
                      text,
                      style: TextStyle(
                        fontSize: JTokens.bubbleFont,
                        height: 1.5,
                        color: const Color(0xF2FFFFFF),
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

/// `.chat-bubble.assistant`: no bubble, the full width, `--chat-text`. While it streams, the text is typed out
/// (main.ts typeStep) and the loader shows until the first letter, then collapses.
class _Answer extends StatefulWidget {
  const _Answer(
    this.msg, {
    required this.resolveUrl,
    this.onLinkTap,
    this.onReaderTap,
  });
  final AssistantMsg msg;
  final String Function(String url) resolveUrl;
  final void Function(String url)? onLinkTap;

  /// The small button after an http(s) link (`.reader-trigger-btn`): opens the reader card.
  final void Function(String url, String title)? onReaderTap;

  @override
  State<_Answer> createState() => _AnswerState();
}

class _AnswerState extends State<_Answer> with SingleTickerProviderStateMixin {
  static const _card = '[INTERACTIVE_CARD_JSON]:';
  static const _collapseMs =
      340; // a little longer than the 300 ms shrink (COLLAPSE_MS)

  final _type = Typewriter();
  late final Ticker _ticker = createTicker(_tick);
  Duration _prev = Duration.zero;
  bool _holdPending = false; // first text of the turn: 200 ms without a letter (streamHoldUntil), once
  Duration? _holdFrom;
  double _dt = 0; // time owed since the last rebuild: typing is rebuilt at about 30 fps, not on every frame
  Timer? _collapseTimer;
  bool _loader = false; // the loader is on screen (spinning, then collapsing)
  bool _collapsing = false;

  AssistantMsg get _msg => widget.msg;
  bool get _live => _msg.streaming;

  @override
  void initState() {
    super.initState();
    _loader = _live && _msg.text.isEmpty;
    if (!_live) _type.finish(_msg.text.length);
    _wake();
  }

  @override
  void didUpdateWidget(_Answer old) {
    super.didUpdateWidget(old);
    if (!_live) {
      // stream_end / cancel: the final render shows everything at once
      _ticker.stop();
      _type.finish(_msg.text.length);
      if (_loader) _endLoader();
      return;
    }
    if (_loader && !_collapsing && _msg.text.isNotEmpty) {
      // the first text: the balls shrink and the first letter waits for them (streamHoldUntil)
      _collapsing = true;
      _holdPending = true;
      _collapseTimer = Timer(const Duration(milliseconds: _collapseMs), () {
        if (mounted) setState(() => _loader = _collapsing = false);
      });
    }
    _wake();
  }

  void _endLoader() {
    _collapseTimer?.cancel();
    _loader = _collapsing = false;
  }

  /// Each text_chunk wakes the loop; it stops by itself once every letter is shown (main.ts wakeStreamTypewriter).
  void _wake() {
    if (_ticker.isActive || !_live || _msg.text.startsWith(_card)) return;
    if (_type.shown >= _msg.text.length) return;
    _prev = Duration.zero;
    _dt = 0;
    _ticker.start();
  }

  void _tick(Duration now) {
    _dt += (now - _prev).inMicroseconds / 1e6;
    _prev = now;
    if (_holdPending) {
      _holdFrom ??= now;
      if (now - _holdFrom! < const Duration(milliseconds: Typewriter.holdMs)) {
        _dt = 0;
        return;
      }
      _holdPending = false;
    }
    // Every frame, like main.ts typeStep on requestAnimationFrame: finished blocks keep their widgets, so only
    // the growing last block is parsed again.
    final dt = _dt;
    _dt = 0;
    final before = _type.shown;
    final shown = _type.step(dt, _msg.text.length);
    if (shown != before) setState(() {});
    if (shown >= _msg.text.length) _ticker.stop();
  }

  @override
  void dispose() {
    _collapseTimer?.cancel();
    _ticker.dispose();
    super.dispose();
  }

  /// The text shown so far, never cut inside a surrogate pair.
  String get _visible {
    final t = _msg.text;
    if (!_live) return t;
    if (t.startsWith(_card)) return ''; // an interactive card is not typed out
    var n = _type.shown.clamp(0, t.length);
    if (n > 0 && n < t.length && (t.codeUnitAt(n - 1) & 0xFC00) == 0xD800) n++;
    return withoutTrailingNewlines(t.substring(0, n));
  }

  @override
  Widget build(BuildContext context) {
    final waiting = _live && _msg.text.isEmpty;
    final Widget body = waiting
        ? SizedBox(height: streamLoaderBox.height, width: streamLoaderBox.width)
        : ConstrainedBox(
            constraints: BoxConstraints(minHeight: streamLoaderBox.height),
            child: Padding(
              padding: const EdgeInsets.symmetric(vertical: 6),
              child: DefaultTextStyle.merge(
                style: TextStyle(
                  fontSize: JTokens.bubbleFont,
                  height: 1.5,
                  color: JTokens.chatText,
                ),
                child: SizedBox(
                  width: double.infinity,
                  child: RepaintBoundary(
                    child: MarkdownView(
                      _visible,
                      streaming: _live,
                      resolveUrl: widget.resolveUrl,
                      onLinkTap: widget.onLinkTap,
                      onReaderTap: widget.onReaderTap,
                    ),
                  ),
                ),
              ),
            ),
          );
    final Widget stack = Stack(
      clipBehavior: Clip.none,
      children: [
        body,
        if (_loader || waiting)
          Positioned(
            left:
                (_collapsing ? streamLoaderCollapseAt : streamLoaderSpinAt).dx,
            top: (_collapsing ? streamLoaderCollapseAt : streamLoaderSpinAt).dy,
            child: IgnorePointer(child: StreamLoader(collapsing: _collapsing)),
          ),
      ],
    );
    // the loader is a small block on the left; the text spans the column (one tree for both, so the loader keeps spinning)
    return Align(alignment: Alignment.centerLeft, child: stack);
  }
}
