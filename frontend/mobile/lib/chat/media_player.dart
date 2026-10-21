import 'package:flutter/material.dart';
import 'package:webview_flutter/webview_flutter.dart';
import 'package:webview_flutter_android/webview_flutter_android.dart';
import 'package:webview_flutter_wkwebview/webview_flutter_wkwebview.dart';

import '../theme/tokens.dart';
import 'chat_models.dart';

/// The media player (main.ts openMediaPlayer): the only place a WebView is used. It plays `embedUrl` with `autoplay=1`
/// appended, the way the web iframe does. [onClose] is the controller's closeMedia, which tells the server media_state false.
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

  static String autoplayUrl(String embed) {
    final sep = embed.contains('?') ? '&' : '?';
    return '$embed${sep}autoplay=1';
  }

  @override
  Widget build(BuildContext context) {
    final pad = MediaQuery.paddingOf(context);
    final url = autoplayUrl(media.embedUrl);
    final title = media.title.isNotEmpty ? media.title : media.query;
    return ColoredBox(
      color: Colors.black,
      child: Stack(
        children: [
          Positioned.fill(
            top: pad.top,
            child: webBuilder?.call(url) ?? _WebPage(url: url),
          ),
          Positioned(
            top: 10 + pad.top,
            left: 12,
            right: 56,
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
          Positioned(
            top: 4 + pad.top,
            right: 4,
            child: IconButton(
              key: const ValueKey('media-close'),
              onPressed: onClose,
              icon: const Icon(Icons.close, color: Colors.white),
            ),
          ),
        ],
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
      ..loadRequest(Uri.parse(widget.url));
    final p = c.platform;
    if (p is AndroidWebViewController) {
      p.setMediaPlaybackRequiresUserGesture(false);
    }
    return c;
  }

  @override
  Widget build(BuildContext context) => WebViewWidget(controller: _web);
}
