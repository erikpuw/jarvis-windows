import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import 'lucide_glyphs.dart';
import 'morph_icon.dart';
import 'sessions_controller.dart';

class SessionsDrawer extends StatelessWidget {
  const SessionsDrawer({
    super.key,
    required this.open,
    required this.onClose,
    required this.onDashboard,
  });
  final bool open;
  final VoidCallback onClose;
  final VoidCallback onDashboard;

  @override
  Widget build(BuildContext context) =>
      _SlidingSessions(open: open, onClose: onClose, onDashboard: onDashboard);
}

class _SlidingSessions extends StatefulWidget {
  const _SlidingSessions({
    required this.open,
    required this.onClose,
    required this.onDashboard,
  });
  final bool open;
  final VoidCallback onClose;
  final VoidCallback onDashboard;
  @override
  State<_SlidingSessions> createState() => _SlidingSessionsState();
}

class _SlidingSessionsState extends State<_SlidingSessions>
    with SingleTickerProviderStateMixin {
  late final _slide = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 200),
    value: widget.open ? 1 : 0,
  );
  late final _ease = CurvedAnimation(parent: _slide, curve: Curves.ease);
  @override
  void didUpdateWidget(covariant _SlidingSessions oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.open != oldWidget.open) {
      widget.open ? _slide.forward() : _slide.reverse();
    }
  }

  @override
  void dispose() {
    _ease.dispose();
    _slide.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final sessions = context.watch<SessionsController>();
    final mq = MediaQuery.of(context);
    final left = 12 + mq.padding.left;
    final top = mq.padding.top + 54;
    final bottom = mq.size.width <= 380 ? 16.0 : 18.0;
    final now = DateTime.now();
    String? previousGroup;
    final rows = <Widget>[];
    for (final session in sessions.items) {
      final group = sessionGroup(session.lastMsg, now);
      if (group != previousGroup) {
        rows.add(
          Padding(
            padding: const EdgeInsets.fromLTRB(4, 10, 4, 2),
            child: Text(
              group,
              style: const TextStyle(fontSize: 11, color: Color(0xFF64748B)),
            ),
          ),
        );
        previousGroup = group;
      }
      final active = session.id == sessions.activeId;
      rows.add(
        Padding(
          padding: const EdgeInsets.only(bottom: 2),
          child: GestureDetector(
            key: Key('session-${session.id}'),
            behavior: HitTestBehavior.opaque,
            onTap: () {
              if (sessions.locked) return;
              widget.onClose();
              sessions.pick(session.id);
            },
            child: Container(
              padding: const EdgeInsets.symmetric(vertical: 7, horizontal: 9),
              decoration: BoxDecoration(
                color: active ? const Color(0xFF111827) : null,
                borderRadius: BorderRadius.circular(8),
              ),
              child: Text(
                session.title,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(
                  fontSize: 13,
                  color: active
                      ? const Color(0xFFE5E7EB)
                      : const Color(0xFF94A3B8),
                ),
              ),
            ),
          ),
        ),
      );
    }
    return AnimatedBuilder(
      animation: _ease,
      builder: (context, _) {
        if (_slide.value == 0 && !widget.open) return const SizedBox.shrink();
        final t = _ease.value;
        return Stack(
          children: [
            Positioned(
              left: 0,
              right: 0,
              top: top,
              bottom: bottom,
              child: GestureDetector(
                key: const Key('sessions-scrim'),
                behavior: HitTestBehavior.opaque,
                onTap: widget.onClose,
                child: ColoredBox(color: Color.fromRGBO(0, 0, 0, 0.55 * t)),
              ),
            ),
            Positioned(
              left: left,
              top: top,
              bottom: bottom,
              child: Transform.translate(
                offset: Offset(-(200 + 24 + left) * (1 - t), 0),
                child: Container(
                  key: const Key('sessions-drawer'),
                  width: 200,
                  padding: const EdgeInsets.symmetric(
                    vertical: 12,
                    horizontal: 8,
                  ),
                  decoration: BoxDecoration(
                    color: const Color(0xFF121214),
                    border: Border.all(color: const Color(0x14FFFFFF)),
                    borderRadius: BorderRadius.circular(12),
                    boxShadow: const [
                      BoxShadow(
                        color: Color(0x80000000),
                        blurRadius: 24,
                        offset: Offset(4, 0),
                      ),
                    ],
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      GestureDetector(
                        key: const Key('sessions-new'),
                        behavior: HitTestBehavior.opaque,
                        onTap: () {
                          if (sessions.locked) return;
                          widget.onClose();
                          sessions.startNew();
                        },
                        child: Container(
                          height: 38,
                          padding: const EdgeInsets.symmetric(horizontal: 10),
                          decoration: BoxDecoration(
                            border: Border.all(color: const Color(0xFF1F2937)),
                            borderRadius: BorderRadius.circular(9),
                          ),
                          child: const Row(
                            children: [
                              MorphIcon(
                                icon: plusGlyph,
                                size: 16,
                                color: Color(0xFFE5E7EB),
                              ),
                              SizedBox(width: 8),
                              Text(
                                'Phiên mới',
                                style: TextStyle(
                                  fontSize: 13,
                                  color: Color(0xFFE5E7EB),
                                ),
                              ),
                            ],
                          ),
                        ),
                      ),
                      const SizedBox(height: 8),
                      Expanded(
                        child: SingleChildScrollView(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.stretch,
                            children: rows,
                          ),
                        ),
                      ),
                      GestureDetector(
                        key: const Key('sessions-dash'),
                        behavior: HitTestBehavior.opaque,
                        onTap: () {
                          widget.onClose();
                          widget.onDashboard();
                        },
                        child: Container(
                          padding: const EdgeInsets.fromLTRB(9, 9, 9, 0),
                          decoration: const BoxDecoration(
                            border: Border(
                              top: BorderSide(color: Color(0xFF1F2937)),
                            ),
                          ),
                          child: const Row(
                            children: [
                              MorphIcon(
                                icon: settingsGlyph,
                                size: 16,
                                color: Color(0xFFE5E7EB),
                              ),
                              SizedBox(width: 8),
                              Text(
                                'Bảng điều khiển',
                                style: TextStyle(
                                  fontSize: 13,
                                  color: Color(0xFFE5E7EB),
                                ),
                              ),
                            ],
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ],
        );
      },
    );
  }
}
