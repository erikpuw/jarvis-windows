import 'package:flutter/material.dart';

import '../theme/tokens.dart';
import 'file_attach.dart';

/// An `image_result` in the answer (main.ts renderCard): the picture, rounded, tapping it opens the lightbox.
/// [url] is already resolved against the server.
class ImageResult extends StatelessWidget {
  const ImageResult({
    super.key,
    required this.url,
    this.alt = '',
    this.downloadUrl,
  });

  final String url;

  /// The original to download (an upscaled picture); a screenshot has none, so no button (main.ts image-download).
  final String? downloadUrl;

  /// The `alt` text (the web gives the image its name; a card has no visible caption, the alt only shows when the load fails).
  final String alt;

  @override
  Widget build(BuildContext context) {
    // the row is as wide as the list (tight constraints), so the whole row is the tap target
    return GestureDetector(
      behavior: HitTestBehavior.opaque,
      onTap: () => showImageLightbox(context, url),
      child: Align(
        alignment: Alignment.centerLeft,
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 420),
          child: Stack(
            children: [
              ClipRRect(
                borderRadius: BorderRadius.circular(12),
                child: DecoratedBox(
                  decoration: BoxDecoration(
                    border: Border.all(color: const Color(0xFF262626)), // .image-result-preview
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: Image.network(
                    url,
                    fit: BoxFit.contain,
                    errorBuilder: (_, _, _) => SizedBox(
                      width: 120,
                      height: 80,
                      child: Center(
                        child: Text(
                          alt,
                          style: const TextStyle(
                            fontSize: JTokens.fsLabel,
                            color: JTokens.muted,
                          ),
                        ),
                      ),
                    ),
                  ),
                ),
              ),
              if (downloadUrl != null)
                Positioned(
                  top: 8,
                  right: 8,
                  child: GestureDetector(
                    key: const ValueKey('image-download'),
                    behavior: HitTestBehavior.opaque,
                    onTap: () => launchExternal(Uri.parse(downloadUrl!)),
                    child: Container(
                      width: 32,
                      height: 32,
                      decoration: BoxDecoration(
                        color: const Color(0xCC0A0A0A),
                        border: Border.all(color: const Color(0xFF333333)),
                        borderRadius: BorderRadius.circular(8),
                      ),
                      child: const Icon(
                        Icons.download_outlined,
                        size: 18,
                        color: Color(0xFFA3A3A3),
                      ),
                    ),
                  ),
                ),
            ],
          ),
        ),
      ),
    );
  }
}

/// The full-screen lightbox (`#image-lightbox`): pinch to zoom, a tap closes it.
Future<void> showImageLightbox(BuildContext context, String url) {
  return showGeneralDialog<void>(
    context: context,
    barrierDismissible: true,
    barrierLabel: 'Đóng',
    barrierColor: const Color(0xF2080A12), // rgba(8, 10, 18, .95)
    transitionDuration: const Duration(milliseconds: 250),
    pageBuilder: (ctx, _, _) => GestureDetector(
      behavior: HitTestBehavior.opaque,
      onTap: () => Navigator.of(ctx).pop(),
      child: InteractiveViewer(
        maxScale: 5,
        child: Center(
          // #lightbox-img: radius 16, 1px white 10%, deep shadow
          child: Container(
            margin: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(16),
              border: Border.all(color: const Color(0x1AFFFFFF)),
              boxShadow: const [
                BoxShadow(color: Color(0xE6000000), blurRadius: 60, offset: Offset(0, 25)),
              ],
            ),
            child: ClipRRect(
              borderRadius: BorderRadius.circular(15),
              child: Image.network(
                url,
                fit: BoxFit.contain,
                errorBuilder: (_, _, _) => const SizedBox.shrink(),
              ),
            ),
          ),
        ),
      ),
    ),
    transitionBuilder: (_, anim, _, child) =>
        FadeTransition(opacity: anim, child: child),
  );
}
