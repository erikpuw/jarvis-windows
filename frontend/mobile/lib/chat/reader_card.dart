import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:url_launcher/url_launcher.dart';

import '../net/api_client.dart';
import '../theme/tokens.dart';
import 'chat_models.dart';

/// The reader card's open and close (`#reader-backdrop` / `#reader-card` in style.css): both fade in 0.2 s, the card also
/// slides 8px up; closing runs it backwards, then the layer is gone. [card] null = closed.
class ReaderLayer extends StatefulWidget {
  const ReaderLayer({super.key, required this.card, required this.onClose});

  final ReaderCard? card;
  final VoidCallback onClose;

  @override
  State<ReaderLayer> createState() => _ReaderLayerState();
}

class _ReaderLayerState extends State<ReaderLayer>
    with SingleTickerProviderStateMixin {
  late final _c = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 200),
  );
  ReaderCard? _last; // what the card shows while it fades out

  @override
  void initState() {
    super.initState();
    _last = widget.card;
    if (_last != null) _c.forward();
  }

  @override
  void didUpdateWidget(ReaderLayer old) {
    super.didUpdateWidget(old);
    final card = widget.card;
    if (card != null) {
      _last = card;
      _c.forward();
    } else {
      _c.reverse();
    }
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: _c,
      builder: (context, _) {
        final last = _last;
        if (last == null || (_c.isDismissed && widget.card == null)) {
          return const SizedBox.shrink();
        }
        final v = Curves.ease.transform(_c.value);
        return IgnorePointer(
          ignoring: widget.card == null,
          child: Stack(
            children: [
              Positioned.fill(
                child: ColoredBox(
                  color: Colors.black.withValues(alpha: 0.5 * v),
                ),
              ),
              Positioned.fill(
                child: Opacity(
                  opacity: v,
                  child: Transform.translate(
                    offset: Offset(0, 8 * (1 - v)),
                    child: ReaderPanel(
                      key: ValueKey(last.url),
                      card: last,
                      onClose: widget.onClose,
                    ),
                  ),
                ),
              ),
            ],
          ),
        );
      },
    );
  }
}

/// The reader card (reader-card.ts): the clean text of an article over the chat, from `/api/reader`.
/// Closes on the X, a tap outside it, or the system back gesture (the route is the whole screen).
class ReaderPanel extends StatefulWidget {
  const ReaderPanel({super.key, required this.card, required this.onClose});

  final ReaderCard card;
  final VoidCallback onClose;

  @override
  State<ReaderPanel> createState() => _ReaderPanelState();
}

class _ReaderPanelState extends State<ReaderPanel> {
  late final Future<Map<String, dynamic>> _article = context
      .read<ApiClient>()
      .get<Map<String, dynamic>>(
        '/api/reader?url=${Uri.encodeComponent(widget.card.url)}',
      );

  void _openOriginal() => launchUrl(
    Uri.parse(widget.card.url),
    mode: LaunchMode.externalApplication,
  );

  @override
  Widget build(BuildContext context) {
    final pad = MediaQuery.paddingOf(context);
    final width = MediaQuery.sizeOf(context).width;
    return Stack(
      children: [
        // the backdrop: a tap outside the card closes it
        Positioned.fill(
          child: GestureDetector(
            behavior: HitTestBehavior.opaque,
            onTap: widget.onClose,
          ),
        ),
        Positioned(
          top: 52 + pad.top,
          bottom: 74 + pad.bottom,
          left: 0,
          right: 0,
          child: Center(
            child: Container(
              width: width - 28 > 720 ? 720 : width - 28,
              decoration: BoxDecoration(
                color: const Color(0xF20A0C10),
                border: Border.all(color: const Color(0x1FFFFFFF)),
                borderRadius: BorderRadius.circular(14),
                boxShadow: const [
                  BoxShadow(
                    color: Color(0xBF000000),
                    blurRadius: 48,
                    offset: Offset(0, 16),
                  ),
                ],
              ),
              child: Column(
                children: [
                  _header(),
                  Expanded(child: _body()),
                  _footer(),
                ],
              ),
            ),
          ),
        ),
      ],
    );
  }

  Widget _header() => Container(
    padding: const EdgeInsets.fromLTRB(16, 12, 8, 12),
    decoration: const BoxDecoration(
      border: Border(bottom: BorderSide(color: Color(0x14FFFFFF))),
    ),
    child: Row(
      children: [
        Expanded(
          child: FutureBuilder<Map<String, dynamic>>(
            future: _article,
            builder: (context, snap) {
              final data = snap.data ?? const {};
              final source = (data['source'] as String?) ?? '';
              final title = snap.hasError
                  ? (widget.card.title.isEmpty
                        ? 'Không thể tải bài viết'
                        : widget.card.title)
                  : (data['title'] as String?) ??
                        (widget.card.title.isEmpty
                            ? 'Đang tải bài viết...'
                            : widget.card.title);
              return Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisSize: MainAxisSize.min,
                children: [
                  if (source.isNotEmpty)
                    Text(
                      '📰 $source',
                      style: const TextStyle(
                        fontSize: JTokens.fsLabel,
                        color: JTokens.muted,
                      ),
                    ),
                  Text(
                    title,
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                      fontSize: JTokens.fsBody,
                      fontWeight: FontWeight.w600,
                      color: Colors.white,
                    ),
                  ),
                ],
              );
            },
          ),
        ),
        IconButton(
          onPressed: widget.onClose,
          icon: const Icon(Icons.close, size: 18, color: JTokens.muted),
        ),
      ],
    ),
  );

  Widget _body() => FutureBuilder<Map<String, dynamic>>(
    future: _article,
    builder: (context, snap) {
      if (snap.hasError) {
        return Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                'Không thể trích xuất nội dung tự động từ trang này (có thể do trang yêu cầu JavaScript hoặc bảo vệ chống bot).',
                style: TextStyle(
                  fontSize: JTokens.fsSmall,
                  color: JTokens.muted,
                ),
              ),
              const SizedBox(height: 10),
              GestureDetector(
                onTap: _openOriginal,
                child: const Text(
                  'Bấm vào đây để mở trực tiếp bài viết gốc ↗',
                  style: TextStyle(
                    fontSize: JTokens.fsSmall,
                    color: JTokens.accent,
                  ),
                ),
              ),
            ],
          ),
        );
      }
      if (!snap.hasData) return const _Skeleton();
      final paragraphs = ((snap.data!['content'] as String?) ?? '')
          .split(RegExp(r'\n\s*\n|\n'))
          .map((p) => p.trim())
          .where((p) => p.isNotEmpty)
          .toList();
      return SingleChildScrollView(
        padding: const EdgeInsets.fromLTRB(16, 14, 16, 14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (paragraphs.isEmpty)
              const Text(
                'Không có nội dung văn bản bóc tách được từ trang này.',
                style: TextStyle(
                  fontSize: JTokens.fsSmall,
                  color: JTokens.muted,
                ),
              )
            else
              for (final p in paragraphs)
                Padding(
                  padding: const EdgeInsets.only(bottom: 12),
                  child: Text(
                    p,
                    style: const TextStyle(
                      fontSize: JTokens.fsBody,
                      height: 1.6,
                      color: Color(0xFFE5E7EB),
                    ),
                  ),
                ),
          ],
        ),
      );
    },
  );

  Widget _footer() => Container(
    padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
    decoration: const BoxDecoration(
      border: Border(top: BorderSide(color: Color(0x14FFFFFF))),
    ),
    child: Row(
      children: [
        const Expanded(
          child: Text(
            'Chạm bên ngoài để đóng',
            style: TextStyle(fontSize: JTokens.fsLabel, color: JTokens.muted),
          ),
        ),
        GestureDetector(
          onTap: _openOriginal,
          child: const Text(
            'Mở bài gốc ↗',
            style: TextStyle(fontSize: JTokens.fsSmall, color: JTokens.accent),
          ),
        ),
      ],
    ),
  );
}

/// reader-card.ts `.reader-loading`: five grey lines of the widths 80, 60, 90, 70, 50 %.
class _Skeleton extends StatelessWidget {
  const _Skeleton();

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.all(16),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        for (final w in [0.8, 0.6, 0.9, 0.7, 0.5])
          Padding(
            padding: const EdgeInsets.only(bottom: 12),
            child: FractionallySizedBox(
              widthFactor: w,
              child: Container(
                height: 12,
                decoration: BoxDecoration(
                  color: const Color(0x14FFFFFF),
                  borderRadius: BorderRadius.circular(6),
                ),
              ),
            ),
          ),
      ],
    ),
  );
}
