import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:webview_flutter/webview_flutter.dart';
import 'package:webview_flutter_android/webview_flutter_android.dart';
import 'package:webview_flutter_wkwebview/webview_flutter_wkwebview.dart';

import '../theme/tokens.dart';
import 'chat_models.dart';

/// The media player (main.ts openMediaPlayer): the only place a WebView is used. It plays `embedUrl` in an autoplaying iframe
/// (see [embedPage]), the way the web does. [onClose] is the controller's closeMedia, which tells the server media_state false.
class MediaPlayer extends StatelessWidget {
  const MediaPlayer({
    super.key,
    required this.media,
    required this.onClose,
    @visibleForTesting this.webBuilder,
  });

  final MediaOpen media;
  final VoidCallback onClose;

  /// Test seam: tests have no WebView plugin, so they build a stand-in for the page.
  final Widget Function(String url)? webBuilder;

  /// The page the iframe sits in. YouTube refuses an embed that arrives without a Referer ("Error 153"), which is what a
  /// bare embed URL loaded as the WebView's own page is; inside a page with this origin it gets one, as in the web app.
  static const pageOrigin = 'https://com.jarvis.mobile';

  /// main.ts media_open: the same iframe the web builds, with `playsinline=1` so iOS keeps the video in the page.
  static String embedPage(String embed) {
    final sep = embed.contains('?') ? '&' : '?';
    final src = const HtmlEscape(HtmlEscapeMode.attribute)
        .convert('$embed${sep}autoplay=1&playsinline=1');
    return '<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<style>html,body{margin:0;height:100%;background:#000}iframe{border:0;width:100%;height:100%}</style>'
        '</head><body><iframe src="$src" allow="autoplay; encrypted-media; picture-in-picture" allowfullscreen>'
        '</iframe></body></html>';
  }

  @override
  Widget build(BuildContext context) {
    final url = media.embedUrl;
    final title = media.title.isNotEmpty ? media.title : media.query;
    // .media-player: #121214, 1px white 8%, radius 16, deep shadow; the parent gives it the 16:9 box
    return DecoratedBox(
      decoration: BoxDecoration(
        color: JTokens.surface,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: JTokens.border),
        boxShadow: const [
          BoxShadow(
            color: Color(0xD9000000),
            blurRadius: 48,
            spreadRadius: -12,
            offset: Offset(0, 24),
          ),
        ],
      ),
      child: ClipRRect(
        borderRadius: BorderRadius.circular(15),
        child: Stack(
          children: [
            Positioned.fill(child: webBuilder?.call(url) ?? _WebPage(url: url)),
            // main.ts openMediaPlayer: the title over the video, top 10 left 12, cyan 50%
            Positioned(
              top: 10,
              left: 12,
              right: 56,
              child: IgnorePointer(
                child: Text(
                  (title.isEmpty ? 'NOW PLAYING' : title).toUpperCase(),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                    fontSize: JTokens.fsLabel,
                    letterSpacing: 2,
                    color: Color(0x8000D4FF),
                  ),
                ),
              ),
            ),
            // .media-player-close: top 8 right 10, #18181b, 1px white 12%, #a1a1aa, radius 8, 32px tall
            Positioned(
              top: 8,
              right: 10,
              child: GestureDetector(
                key: const ValueKey('media-close'),
                onTap: onClose,
                child: Container(
                  constraints: const BoxConstraints(
                    minHeight: 32,
                    minWidth: 32,
                  ),
                  padding: const EdgeInsets.symmetric(
                    horizontal: 10,
                    vertical: 4,
                  ),
                  alignment: Alignment.center,
                  decoration: BoxDecoration(
                    color: JTokens.surface2,
                    border: Border.all(color: const Color(0x1FFFFFFF)),
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: const Text(
                    '✕',
                    style: TextStyle(
                      fontSize: JTokens.fsUi,
                      color: JTokens.muted,
                    ),
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _WebPage extends StatefulWidget {
  const _WebPage({required this.url});
  final String url;

  @override
  State<_WebPage> createState() => _WebPageState();
}

class _WebPageState extends State<_WebPage> {
  // Autoplay needs inline playback on iOS and no user-gesture requirement on Android, else the video stays paused or jumps full-screen.
  late final WebViewController _web = _build();

  WebViewController _build() {
    final params = WebViewPlatform.instance is WebKitWebViewPlatform
        ? WebKitWebViewControllerCreationParams(
            allowsInlineMediaPlayback: true,
            mediaTypesRequiringUserAction: const {},
          )
        : const PlatformWebViewControllerCreationParams();
    final c = WebViewController.fromPlatformCreationParams(params)
      ..setJavaScriptMode(JavaScriptMode.unrestricted)
      ..setBackgroundColor(Colors.black)
      ..loadHtmlString(
        MediaPlayer.embedPage(widget.url),
        baseUrl: MediaPlayer.pageOrigin,
      );
    final p = c.platform;
    if (p is AndroidWebViewController) {
      p.setMediaPlaybackRequiresUserGesture(false);
    }
    return c;
  }

  @override
  Widget build(BuildContext context) => WebViewWidget(controller: _web);
}
