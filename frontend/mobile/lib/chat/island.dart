import 'dart:async';
import 'dart:math' as math;
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/scheduler.dart';

import '../theme/tokens.dart';
import 'chat_models.dart';
import 'island_shape.dart';
import 'island_steps.dart';
import 'size_reporter.dart';

// notify-island.ts constants
const _idleOpen = Duration(
  seconds: 5,
); // an opened card folds after this long without a touch
const _done = Duration(milliseconds: 900); // no step active for this long = the flow is finished (the last steps arrive in a burst)
const _linger = Duration(
  milliseconds: 2500,
); // a finished flow stays in the capsule this long before it leaves
const _errorShown = Duration(
  seconds: 8,
); // an error stays in the capsule this long
const _leaveMs = Duration(
  milliseconds: 300,
); // leaving: the pill narrows to nothing in 0.3 s
const _panelMaxW = 320.0;
const _panelMinW = 200.0;
const _controlsGap =
    56.0; // clear of the control button on the right (and as much on the left)
const _pillH = 34.0;
const _pillDrop = 24.0; // open: the pill reaches this far down into the body, the goo makes the neck there
const _pad =
    32.0; // room around the shapes for the blur (SVG filter region -20% / 140%)
const _fill = Color(0xFF161A24); // .island-svg rect

enum IslandState { hidden, pill, open, leaving }

/// The state machine of notify-island.ts: the timers and the target of every shape value. It owns no widget.
class IslandMachine extends ChangeNotifier {
  IslandMachine(TickerProvider vsync) {
    shape = Tweener(vsync, const {
      'pillW': 0,
      'pillH': _pillH,
      'bodyH': 0,
      'bodyO': 0,
      'clipW': 0,
      'ct': 0, // the title settling lower and smaller while the card is open
      'po': 0, // the panel's opacity
      'ro': 0, // the whole island's opacity
    }, _changed);
  }

  late final Tweener shape;
  IslandState state = IslandState.hidden;
  List<FlowStep> steps = [];
  String errorMsg = '';
  bool flowDone = false;
  bool covered = false;
  bool entering = false;
  double openW = _panelMinW;
  double panelH = 0;
  double _pillContentW = 0;
  double _naturalW = 0;
  Timer? _doneTimer, _goAwayTimer, _errorTimer, _idleTimer, _leaveTimer;
  IslandState? _savedBeforeCover;
  bool _disposed = false;

  // what render() decides for the pill
  String label = '';
  String glyphStatus =
      'active'; // the pill glyph (setStatusIcon): active | completed | failed

  void _changed() {
    if (!_disposed) notifyListeners();
  }

  @override
  void dispose() {
    _disposed = true;
    for (final t in [
      _doneTimer,
      _goAwayTimer,
      _errorTimer,
      _idleTimer,
      _leaveTimer,
    ]) {
      t?.cancel();
    }
    shape.dispose();
    super.dispose();
  }

  bool get _viewing => state == IslandState.open; // a touch screen has no hover

  // ---- drawing ----
  void _render() {
    if (errorMsg.isNotEmpty) {
      glyphStatus = 'failed';
      label = errorMsg;
    } else if (steps.isNotEmpty) {
      final failed = steps.any((s) => s.status == 'failed');
      final isDone = flowDone && !steps.any((s) => s.status == 'active');
      glyphStatus = failed
          ? 'failed'
          : isDone
          ? 'completed'
          : 'active';
      label = failed
          ? 'Lỗi xử lý'
          : isDone
          ? 'Hoàn thành'
          : 'Đang xử lý';
    }
    _layout();
    _changed();
  }

  /// Sizes the widgets measured: the pill's content width and the panel's height.
  void measured({double? pillContentW, double? panelH}) {
    if (_disposed) return;
    if (pillContentW != null) _pillContentW = pillContentW;
    if (panelH != null) this.panelH = panelH;
    _layout();
    _changed();
  }

  void _layout() {
    if (state == IslandState.pill || state == IslandState.open) {
      _naturalW = _pillContentW;
    }
    final narrow = state == IslandState.leaving || entering;
    final pillW = narrow ? 0.0 : _naturalW;
    final open = state == IslandState.open;
    final leaving = state == IslandState.leaving;
    final ms = open ? 600 : 220;
    final Curve ease = open ? spring : easeOut;
    shape
      ..to('bodyH', open ? panelH : 0, ms, ease)
      ..to('bodyO', open ? 1 : 0, ms, ease)
      ..to('pillH', open ? _pillH + _pillDrop : _pillH, ms, ease)
      ..to('pillW', pillW, 300, leaving ? easeOut : pop)
      ..to('clipW', pillW, leaving ? 250 : 300, leaving ? easeOut : pop)
      ..to('ct', open ? 1 : 0, open ? 600 : 250, open ? spring : easeOut)
      ..to(
        'po',
        open ? 1 : 0,
        open ? 360 : 120,
        Curves.ease,
        delayMs: open ? 180 : 0,
      )
      ..to(
        'ro',
        state == IslandState.hidden || leaving ? 0 : 1,
        leaving ? 200 : 250,
        Curves.ease,
        delayMs: leaving ? 50 : 0,
      );
  }

  void _setState(IslandState next) {
    state = next;
    _layout();
    _changed();
  }

  // ---- showing and leaving ----
  void _show() {
    _leaveTimer?.cancel();
    _goAwayTimer?.cancel();
    if (state == IslandState.hidden) {
      entering =
          true; // starts as a narrow sliver with its content wiped out...
      _setState(IslandState.pill);
      final b = SchedulerBinding.instance;
      b.addPostFrameCallback((_) {
        b.addPostFrameCallback((_) {
          if (_disposed) return;
          entering = false; // ...and grows to its text
          _layout();
          _changed();
        });
        b.scheduleFrame();
      });
    } else if (state == IslandState.leaving) {
      _setState(IslandState.pill);
    }
  }

  void _leave() {
    if (covered ||
        state == IslandState.hidden ||
        state == IslandState.leaving) {
      return;
    }
    _idleTimer?.cancel();
    _goAwayTimer?.cancel();
    _setState(IslandState.leaving);
    _leaveTimer?.cancel();
    _leaveTimer = Timer(_leaveMs, () => _setState(IslandState.hidden));
  }

  /// The capsule leaves when there is nothing more to say: a finished flow, no error showing.
  void _maybeGoAway([Duration delay = _linger]) {
    _goAwayTimer?.cancel();
    if (covered ||
        errorMsg.isNotEmpty ||
        !flowDone ||
        state != IslandState.pill) {
      return;
    }
    _goAwayTimer = Timer(delay, () {
      if (state == IslandState.open) {
        _maybeGoAway(const Duration(milliseconds: 600)); // someone is looking
        return;
      }
      _leave();
    });
  }

  // ---- the card: opened by a tap, folded after 5 s without a touch ----
  void _openCard() {
    _leaveTimer?.cancel();
    _goAwayTimer?.cancel();
    _setState(IslandState.open);
    armIdle();
  }

  void foldCard() {
    _idleTimer?.cancel();
    if (state == IslandState.open) _setState(IslandState.pill);
    _maybeGoAway();
  }

  void armIdle() {
    _idleTimer?.cancel();
    if (state != IslandState.open) return;
    _idleTimer = Timer(_idleOpen, foldCard);
  }

  void toggle() => state == IslandState.open ? foldCard() : _openCard();

  /// A touch outside the island folds an open card.
  void tapOutside() {
    if (state == IslandState.open) foldCard();
  }

  // ---- the three kinds of event ----
  void resetFlow() {
    _doneTimer?.cancel();
    _goAwayTimer?.cancel();
    steps = [];
    flowDone = false;
    if (errorMsg.isEmpty && state == IslandState.pill) _leave();
    _changed();
  }

  void flowStep(FlowStep step) {
    final i = steps.indexWhere((s) => s.id == step.id);
    steps = [...steps];
    if (i >= 0) {
      steps[i] = step;
    } else {
      steps.add(step);
    }
    flowDone = false;
    _doneTimer?.cancel();
    _goAwayTimer?.cancel();
    _render();
    if (errorMsg.isEmpty) _show();
    if (!steps.any((s) => s.status == 'active')) {
      _doneTimer = Timer(_done, () {
        flowDone = true;
        _render();
        _maybeGoAway();
      });
    }
  }

  void error(String message) {
    errorMsg = message;
    _errorTimer?.cancel();
    _goAwayTimer?.cancel();
    _render();
    _show();
    void settle() {
      if (_viewing) {
        _errorTimer = Timer(const Duration(milliseconds: 800), settle);
        return;
      }
      errorMsg = '';
      _render();
      if (steps.isNotEmpty) {
        _maybeGoAway(const Duration(milliseconds: 400));
      } else {
        _leave();
      }
    }

    _errorTimer = Timer(_errorShown, settle);
  }

  // ---- covered by Settings (syncCovered) ----
  void setCovered(bool value) {
    if (value == covered) return;
    covered = value;
    if (value) {
      // pause the self-hiding timers and remember where we were
      _goAwayTimer?.cancel();
      _leaveTimer?.cancel();
      _idleTimer?.cancel();
      if (state != IslandState.hidden) _savedBeforeCover = state;
    } else {
      final saved = _savedBeforeCover;
      _savedBeforeCover = null;
      if (saved != null) {
        // a card that was open comes back folded; a capsule that was leaving has nothing left to show
        _setState(
          saved == IslandState.open
              ? IslandState.pill
              : saved == IslandState.leaving
              ? IslandState.hidden
              : saved,
        );
        _maybeGoAway();
      }
    }
    _changed();
  }
}

/// The notification island (notify-island.ts): a capsule at the top centre with the flow tracker and system errors. Two rounded
/// rects, the pill and the card body, are painted under a blur + alpha threshold (the SVG goo filter) so they melt into one
/// shape; the values move along Sileo's spring (island_shape.dart). A tap opens the card.
class Island extends StatefulWidget {
  const Island({super.key, required this.steps, this.error, this.errorSeq = 0});

  final List<FlowStep> steps;
  final String? error;

  /// Changes with every error, so the same text twice still shows the pill again.
  final int errorSeq;

  @override
  State<Island> createState() => _IslandState();
}

class _IslandState extends State<Island> with SingleTickerProviderStateMixin {
  late final IslandMachine _m = IslandMachine(this);

  @override
  void initState() {
    super.initState();
    _feed(widget.steps);
    final e = widget.error;
    if (e != null) _m.error(e);
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    // Settings (or any opaque route) covering the screen turns the tickers off: that is "covered"
    _m.setCovered(!TickerMode.valuesOf(context).enabled);
  }

  @override
  void didUpdateWidget(Island old) {
    super.didUpdateWidget(old);
    if (!identical(widget.steps, old.steps)) _feed(widget.steps);
    final e = widget.error;
    if (e != null && widget.errorSeq != old.errorSeq) _m.error(e);
  }

  /// The controller hands over the whole list; the island takes it as the packets it was built for. Compared with the rows the
  /// island itself holds: a new turn's reset can reach it in the same rebuild as that turn's first steps, and the old rows
  /// (their checks) would then stay beside the running step.
  void _feed(List<FlowStep> after) {
    final held = _m.steps;
    if (held.any((h) => !after.any((a) => a.id == h.id))) _m.resetFlow();
    for (final s in after) {
      final i = _m.steps.indexWhere((h) => h.id == s.id);
      if (i < 0 ||
          _m.steps[i].label != s.label ||
          _m.steps[i].status != s.status) {
        _m.flowStep(s);
      }
    }
  }

  @override
  void dispose() {
    _m.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final screen = MediaQuery.sizeOf(context);
    _m.openW = math.max(
      _panelMinW,
      math.min(screen.width - 2 * _controlsGap, _panelMaxW),
    );
    return AnimatedBuilder(
      animation: _m,
      builder: (context, _) {
        if (_m.state == IslandState.hidden || _m.covered) {
          return const SizedBox.shrink();
        }
        return _body(screen);
      },
    );
  }

  Widget _body(Size screen) {
    final m = _m;
    final cur = m.shape.cur;
    final openW = m.openW;
    final totalH = _pillH + m.panelH + _pillDrop;
    final open = m.state == IslandState.open;
    final fading = m.state == IslandState.leaving || m.entering;
    final settled =
        m.state == IslandState.pill && !m.shape.animating && cur['bodyH']! == 0;
    return RepaintBoundary(
      child: IgnorePointer(
        ignoring: m.state == IslandState.leaving,
        child: Listener(
          behavior: HitTestBehavior.translucent,
          onPointerDown: (_) => m.armIdle(),
          onPointerMove: (_) => m.armIdle(),
          onPointerSignal: (_) => m.armIdle(),
          child: NotificationListener<ScrollNotification>(
            onNotification: (_) {
              m.armIdle();
              return false;
            },
            child: Opacity(
              opacity: cur['ro']!.clamp(0.0, 1.0),
              child: SizedBox(
                width: openW,
                height: totalH,
                child: Stack(
                  clipBehavior: Clip.none,
                  children: [
                    Positioned(
                      left: -_pad,
                      top: -_pad,
                      width: openW + 2 * _pad,
                      height: totalH + 2 * _pad,
                      child: IgnorePointer(
                        child: settled
                            // a resting pill needs no melting: a plain fill, no blur layers re-rastered on every orb frame
                            ? CustomPaint(
                                painter: _ShapePainter(
                                  openW: openW,
                                  pillW: cur['pillW']!,
                                  pillH: cur['pillH']!,
                                  bodyH: 0,
                                  bodyO: 0,
                                  alpha: 0.9,
                                ),
                              )
                            : Opacity(
                                opacity: 0.9,
                                child: ColorFiltered(
                                  // alpha * 20 - 10: the threshold of the feColorMatrix (the offset is in 0..255)
                                  colorFilter: const ColorFilter.matrix(
                                    <double>[
                                      1, 0, 0, 0, 0, //
                                      0, 1, 0, 0, 0, //
                                      0, 0, 1, 0, 0, //
                                      0, 0, 0, 20, -2550,
                                    ],
                                  ),
                                  child: ImageFiltered(
                                    imageFilter: ui.ImageFilter.blur(
                                      sigmaX: 8,
                                      sigmaY: 8,
                                      tileMode: TileMode.decal,
                                    ),
                                    child: CustomPaint(
                                      painter: _ShapePainter(
                                        openW: openW,
                                        pillW: cur['pillW']!,
                                        pillH: cur['pillH']!,
                                        bodyH: cur['bodyH']!,
                                        bodyO: cur['bodyO']!,
                                      ),
                                    ),
                                  ),
                                ),
                              ),
                      ),
                    ),
                    Positioned(
                      top: 0,
                      left: 0,
                      right: 0,
                      height: _pillH,
                      child: Center(
                        child: TapRegion(
                          groupId: this,
                          onTapOutside: (_) => m.tapOutside(),
                          child: GestureDetector(
                            behavior: HitTestBehavior.opaque,
                            onTap: m.toggle,
                            child: SizedBox(
                              width: math.max(0, cur['clipW']!),
                              height: _pillH,
                              child: ClipRect(
                                child: OverflowBox(
                                  minWidth: 0,
                                  maxWidth: double.infinity,
                                  child: AnimatedOpacity(
                                    duration: Duration(
                                      milliseconds:
                                          m.state == IslandState.leaving
                                          ? 180
                                          : 300,
                                    ),
                                    opacity: fading ? 0 : 1,
                                    child: Transform.translate(
                                      offset: Offset(0, 3 * cur['ct']!),
                                      child: Transform.scale(
                                        scale: 1 - 0.1 * cur['ct']!,
                                        child: SizeReporter(
                                          onSize: (s) =>
                                              m.measured(pillContentW: s.width),
                                          child: _pillContent(screen.width),
                                        ),
                                      ),
                                    ),
                                  ),
                                ),
                              ),
                            ),
                          ),
                        ),
                      ),
                    ),
                    Positioned(
                      top: _pillH,
                      left: 0,
                      right: 0,
                      child: IgnorePointer(
                        ignoring: !open,
                        child: Opacity(
                          opacity: cur['po']!.clamp(0.0, 1.0),
                          child: TapRegion(
                            groupId: this,
                            onTapOutside: (_) => m.tapOutside(),
                            child: SizeReporter(
                              onSize: (s) => m.measured(panelH: s.height),
                              child: _panel(screen.height),
                            ),
                          ),
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }

  /// `.island-pill-content`: the status icon and the current step (or the error).
  Widget _pillContent(double screenW) {
    final m = _m;
    return ConstrainedBox(
      constraints: BoxConstraints(maxWidth: screenW - 112),
      child: SizedBox(
        height: _pillH,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              StatusGlyph(status: m.glyphStatus),
              const SizedBox(width: 6),
              Flexible(
                child: Text(
                  m.label,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                    fontSize: JTokens.fsUi,
                    color: Colors.white,
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  /// `.island-panel`: the steps (when there are some) and the full error.
  Widget _panel(double screenH) {
    final m = _m;
    return Padding(
      padding: const EdgeInsets.only(top: 6),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (m.steps.isNotEmpty)
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 4, 16, 4),
              child: IslandSteps(
                steps: m.steps,
                maxHeight: math.min(screenH * 0.46, 320),
              ),
            ),
          if (m.errorMsg.isNotEmpty)
            Padding(
              padding: const EdgeInsets.fromLTRB(14, 0, 14, 12),
              child: ConstrainedBox(
                constraints: BoxConstraints(
                  maxHeight: math.min(screenH * 0.4, 240),
                ),
                child: SingleChildScrollView(
                  child: Text(
                    m.errorMsg,
                    style: const TextStyle(
                      fontSize: JTokens.fsUi,
                      color: Color(0xFFFECACA),
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

/// The two rects (notify-island.ts: `.island-pill-rect` and `.island-body-rect`), painted sharp; the blur above melts them.
class _ShapePainter extends CustomPainter {
  _ShapePainter({
    required this.openW,
    required this.pillW,
    required this.pillH,
    required this.bodyH,
    required this.bodyO,
    this.alpha = 1,
  });

  final double openW, pillW, pillH, bodyH, bodyO;
  final double alpha;

  @override
  void paint(Canvas canvas, Size size) {
    canvas.translate(_pad, _pad);
    if (bodyH > 0 && bodyO > 0) {
      canvas.drawRRect(
        RRect.fromRectXY(
          Rect.fromLTWH(0, _pillH, openW, bodyH),
          math.min(16, openW / 2),
          math.min(16, bodyH / 2),
        ),
        Paint()..color = _fill.withValues(alpha: bodyO.clamp(0.0, 1.0)),
      );
    }
    if (pillW > 0) {
      canvas.drawRRect(
        RRect.fromRectXY(
          Rect.fromLTWH((openW - pillW) / 2, 0, pillW, pillH),
          math.min(17, pillW / 2),
          math.min(17, pillH / 2),
        ),
        Paint()..color = _fill.withValues(alpha: alpha),
      );
    }
  }

  @override
  bool shouldRepaint(_ShapePainter old) =>
      openW != old.openW ||
      pillW != old.pillW ||
      pillH != old.pillH ||
      bodyH != old.bodyH ||
      bodyO != old.bodyO ||
      alpha != old.alpha;
}
