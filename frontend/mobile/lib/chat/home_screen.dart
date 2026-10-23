import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../net/api_client.dart';
import '../net/server_config.dart';
import '../theme/tokens.dart';
import '../settings/sd_widgets.dart' show RoundMenuButton;
import '../voice/voice_input.dart';
import 'ask_panel.dart';
import 'chat_controller.dart';
import 'chat_models.dart';
import 'command_bar.dart';
import 'command_suggest.dart';
import 'controls_capsule.dart';
import 'file_attach.dart';
import 'image_lightbox.dart';
import 'island.dart';
import 'media_player.dart';
import 'message_list.dart';
import 'reader_card.dart';
import 'status_label.dart';
import 'sessions_controller.dart';
import 'sessions_drawer.dart';
import 'lucide_glyphs.dart';
import 'morph_icon.dart';
import 'welcome_view.dart';

/// The main chat screen (route `/`): the web page on a phone, without the orb and the webcam.
/// Layers, bottom to top: welcome, chat column (messages, ask panel, status row, command bar), media (only over the chat),
/// controls, house button, island (80), reader (85), sessions drawer (95). Settings (100) is its own route.
class HomeScreen extends StatefulWidget {
  const HomeScreen({
    super.key,
    @visibleForTesting this.initialFile,
    @visibleForTesting this.launch = launchExternal,
    @visibleForTesting this.pickFile = pickUploadFile,
    @visibleForTesting this.voiceInput,
    @visibleForTesting this.mediaBuilder,
    this.onCueEnd,
  });

  /// A mic cue finished playing: AudioOut re-activates the audio session if speech is playing.
  final VoidCallback? onCueEnd;

  /// Test seam: a file already pinned to the next message (the `+` button sets it in the app).
  final String? initialFile;

  /// Test seams: opening a URL in the browser, and the file picker.
  final Future<bool> Function(Uri url) launch;
  final Future<String?> Function() pickFile;
  final VoiceInput? voiceInput;

  /// Test seam: tests cannot host the real WebView player.
  final Widget Function(MediaOpen media)? mediaBuilder;

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  final _input = TextEditingController();
  final _focus = FocusNode();
  late final SuggestController _suggest = SuggestController(
    context.read<ApiClient>(),
    _input,
  );
  final _activity = ValueNotifier<int>(0);
  Timer? _blurTimer;
  late String? _file =
      widget.initialFile; // the file pinned to the next message
  bool _barVisible = true; // main.ts toggleCommandBar(true) at start-up
  bool _sessionsOpen = false;
  final _columnKey = GlobalKey();
  final _chatKey = GlobalKey();
  double _askLift = 0; // padding the chat needs while the question box is up
  static const _askBottom =
      62.0; // 54 = the bar and its 10px, then the box rests 8px over it

  VoiceInput? _voiceInput;
  bool _voiceReady = false;
  bool _micOn = false; // main.ts !isMuted: the mic button (starts muted)
  ChatController? _chat;

  @override
  void initState() {
    super.initState();
    _focus.addListener(_onFocus);
    _voiceInput = widget.voiceInput;
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    _chat ??= context.read<ChatController>()..addListener(_syncMic);
  }

  /// The recogniser runs only while the chat is "listening"; every other state pauses it, and it resumes unless the
  /// keyboard is up (main.ts transition()).
  void _syncMic() {
    final v = _voiceInput;
    if (v == null || !_micOn) return;
    if (_chat!.wantsMic) {
      if (!_focus.hasFocus) v.resume();
    } else {
      v.pause();
    }
  }

  Future<void> _toggleMic() async {
    final chat = context.read<ChatController>();
    if (_micOn) {
      setState(() => _micOn = false);
      chat.setListening(false);
      await _voiceInput?.stop();
      return;
    }
    setState(() => _micOn = true);
    chat.setListening(true);
    final v = _voiceInput ??= VoiceInput(
      cue: (name) async {
        await playMicCue(name);
        widget.onCueEnd?.call();
      },
      onTranscript: chat.sendTranscript,
      onError: chat.reportError,
      onGiveUp: _micGaveUp,
      apiClient: context.read<ApiClient>(),
    );
    if (!_voiceReady) {
      _voiceReady = true;
      await v.init();
    }
    if (!mounted || !_micOn) return;
    await v.start();
    _syncMic();
  }

  /// The mic stopped for good (heard nothing six times, or no permission): its button goes off too.
  void _micGaveUp() {
    if (!mounted) return;
    context.read<ChatController>().setListening(
      false,
    ); // VoiceInput already reported why
    setState(() => _micOn = false);
  }

  void _onFocus() {
    if (_focus.hasFocus) {
      _suggest.prefetch();
      _voiceInput
          ?.pause(); // main.ts focus: the keyboard is up, the recogniser rests
    } else {
      _syncMic(); // main.ts blur: resume when the mic is on and nothing is busy
      // the web hides it 200ms after blur so a tap on the panel still lands
      _blurTimer = Timer(const Duration(milliseconds: 200), () {
        if (!_focus.hasFocus) _suggest.hide();
      });
    }
  }

  @override
  void dispose() {
    _chat?.removeListener(_syncMic);
    _voiceInput?.dispose();
    _blurTimer?.cancel();
    _focus.removeListener(_onFocus);
    _suggest.dispose();
    _input.dispose();
    _focus.dispose();
    _activity.dispose();
    super.dispose();
  }

  String _resolve(String url) => url.startsWith('/')
      ? context.read<ServerConfig>().http(url).toString()
      : url;

  /// The `+` button: the picked file is pinned until the next message (`#file-upload`).
  Future<void> _pickFile() async {
    String? path;
    try {
      path = await widget.pickFile();
    } catch (_) {
      if (mounted) {
        context.read<ChatController>().reportError(
          'Không mở được bộ chọn tệp.',
        );
      }
      return;
    }
    if (path == null || !mounted) return;
    setState(() => _file = path);
    _focus.requestFocus();
  }

  /// A link in an answer opens the browser, like `target="_blank"` (markdown.ts).
  void _onLink(String url) {
    final uri = Uri.tryParse(url);
    if (uri != null && uri.hasScheme) widget.launch(uri);
  }

  /// The small button after a link opens the reader card (`.reader-trigger-btn`).
  void _onReader(String url, String title) =>
      context.read<ChatController>().openReader(url, title: title);

  /// Makes room for the question box: the chat's end is padded so its last message stays above the box
  /// (ask-panel.ts liftChat). The box rests 8px over the bar; the chat's bottom edge is `_chatKey`.
  void _liftChat(double panelH) {
    final stack = _columnKey.currentContext?.findRenderObject();
    final chat = _chatKey.currentContext?.findRenderObject();
    if (stack is! RenderBox || chat is! RenderBox || !mounted) return;
    final stackBottom = stack.localToGlobal(Offset(0, stack.size.height)).dy;
    final chatBottom = chat.localToGlobal(Offset(0, chat.size.height)).dy;
    final boxTop = stackBottom - _askBottom - panelH;
    final lift = panelH == 0 ? 0.0 : math.max(0.0, chatBottom - boxTop + 8);
    if (lift != _askLift) setState(() => _askLift = lift);
  }

  /// The cards the message list does not draw itself: a picture or a file from `output_file` / `image_result`.
  Widget? _extra(BuildContext context, ChatItem item) => switch (item) {
    ImageMsg(:final url?, :final caption) when url.isNotEmpty => ImageResult(
      url: _resolve(url),
      alt: caption,
      downloadUrl: item.downloadUrl == null
          ? null
          : _resolve(item.downloadUrl!),
    ),
    FileMsg() => FileCard(
      file: item,
      downloadUrl: _resolve(
        item.downloadUrl.isEmpty ? item.url : item.downloadUrl,
      ),
    ),
    _ => null,
  };

  void _send() {
    final text = _input.text.trim();
    final file = _file;
    // main.ts sendCommand: `!text && !pendingFile`
    if (text.isEmpty && file == null) return;
    _input.clear();
    _suggest.hide();
    _focus.unfocus(); // main.ts dismissKeyboardOnMobile
    setState(() => _file = null);
    context.read<ChatController>().sendText(text, filePath: file);
  }

  void _toggleBar() {
    setState(() => _barVisible = !_barVisible);
    if (!_barVisible) _focus.unfocus();
  }

  @override
  Widget build(BuildContext context) {
    final chat = context.watch<ChatController>();
    final size = MediaQuery.sizeOf(context);
    final pad = MediaQuery.paddingOf(context);
    final narrow = size.width <= 380; // @media (max-width: 380px)
    final width = narrow ? size.width - 16 : math.min(800.0, size.width - 28);
    // #command-container { bottom: var(--container-bottom) } - the web adds no safe-area inset, so the bar sits 18px (16 when narrow) off the very bottom
    final bottom = narrow ? 16.0 : 18.0;
    // style.css phone .media-player: top 56px, width calc(100% - 24px), 16:9. main.ts initChatAutoCeiling: the chat stops 10px
    // under it (otherwise under the island).
    final media = chat.media;
    final mediaTop = 56 + pad.top;
    final mediaWidth = size.width - 24;
    final mediaHeight = mediaWidth * 9 / 16;
    final chatTop = media == null ? 44 + pad.top : mediaTop + mediaHeight + 10;
    return Scaffold(
      backgroundColor: Colors.black,
      body: Listener(
        onPointerDown: (_) => _activity.value++,
        // the browser blurs the input on a tap elsewhere; buttons, links and scrollers win the gesture first
        child: GestureDetector(
          behavior: HitTestBehavior.translucent,
          onTap: _focus.unfocus,
          child: Stack(
            children: [
              Positioned.fill(
                child: Stack(
                  children: [
                    Positioned.fill(
                      child: AnimatedSwitcher(
                        duration: const Duration(milliseconds: 400),
                        child: chat.welcomeVisible
                            ? IgnorePointer(
                                child: WelcomeView(data: chat.welcome),
                              )
                            : const SizedBox.shrink(),
                      ),
                    ),
                    // #jarvis-label: bottom 2px, centred, under the chat column (z-label 20 < z-chat 30)
                    const Positioned(
                      left: 0,
                      right: 0,
                      bottom: 2,
                      child: IgnorePointer(
                        child: Text(
                          'JARVIS',
                          textAlign: TextAlign.center,
                          style: TextStyle(
                            color: Color(0x337BD3FC),
                            fontSize: JTokens.fsSmall,
                            letterSpacing: 4,
                            fontWeight: FontWeight.w400,
                            height: 1.17, // line-height: normal (~15.2px at 13px, the box web puts at 2-17px)
                          ),
                        ),
                      ),
                    ),
                    Positioned.fill(
                      child: Align(
                        alignment: Alignment.bottomCenter,
                        child: Padding(
                          padding: EdgeInsets.only(
                            bottom: bottom,
                            top: chatTop,
                          ),
                          child: SizedBox(width: width, child: _column(chat)),
                        ),
                      ),
                    ),
                  ],
                ),
              ),
              // the video lies only over the chat: the controls, the house, the island, the reader and the sessions drawer
              // stay above it (user 2026-10-23; the web's #controls is z 50 < media 70, the app keeps them usable)
              if (media != null)
                Positioned(
                  top: mediaTop,
                  left: 12,
                  width: mediaWidth,
                  height: mediaHeight,
                  child:
                      widget.mediaBuilder?.call(media) ??
                      MediaPlayer(
                        key: ValueKey(media.embedUrl),
                        media: media,
                        onClose: chat.closeMedia,
                      ),
                ),
              ControlsCapsule(
                ttsMuted: !chat.ttsEnabled,
                micMuted: !_micOn,
                barVisible: _barVisible,
                onMic: _toggleMic,
                onTts: () => chat.setTts(!chat.ttsEnabled),
                onToggleBar: _toggleBar,
                onSettings: () => Navigator.pushNamed(context, '/settings'),
              ),
              Positioned(
                left: 12 + pad.left,
                top: pad.top + 12,
                child: RoundMenuButton(
                  key: const Key('home-sessions-btn'),
                  onTap: () {
                    setState(() => _sessionsOpen = !_sessionsOpen);
                    if (_sessionsOpen) {
                      context.read<SessionsController>().refresh();
                    }
                  },
                  child: MorphIcon(
                    icon: houseGlyph,
                    color: JTokens.accent.withValues(alpha: 0.7),
                    size: 18,
                    strokeWidth: 1.75,
                  ),
                ),
              ),
              // island 80, reader 85, sessions 95 (style.css); the video sits under all of them
              Positioned(
                top: 8 + pad.top,
                left: 0,
                right: 0,
                child: Center(
                  child: Island(
                    steps: chat.flow.steps,
                    error: chat.error,
                    errorSeq: chat.errorSeq,
                  ),
                ),
              ),
              Positioned.fill(
                child: ReaderLayer(
                  card: chat.reader,
                  onClose: chat.closeReader,
                ),
              ),
              Positioned.fill(
                child: SessionsDrawer(
                  open: _sessionsOpen,
                  onClose: () => setState(() => _sessionsOpen = false),
                  onDashboard: () =>
                      Navigator.pushNamed(context, '/settings/menu'),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _column(ChatController chat) {
    // hidden: only the status row stays; chat and bar fade out sliding 10px down
    // `#command-container > :not(#status-row)`: opacity + translateY(10px), 0.25s ease. Only a layer opacity and a translate move
    // per frame (the child is cached in its own layer), never layout.
    Widget fading(Widget child) => IgnorePointer(
      ignoring: !_barVisible,
      child: TweenAnimationBuilder<double>(
        duration: const Duration(milliseconds: 250),
        curve: Curves.ease,
        tween: Tween(end: _barVisible ? 1.0 : 0.0),
        child: RepaintBoundary(child: child),
        builder: (_, v, child) => Opacity(
          opacity: v,
          child: Transform.translate(
            offset: Offset(0, 10 * (1 - v)),
            child: child,
          ),
        ),
      ),
    );
    return Stack(
      key: _columnKey,
      alignment: Alignment.bottomCenter,
      children: [
        Column(
          children: [
            Expanded(
              child: fading(
                MessageList(
                  key: _chatKey,
                  items: chat.items,
                  resolveUrl: _resolve,
                  onLinkTap: _onLink,
                  onReaderTap: _onReader,
                  bottomInset: chat.ask == null ? 0 : _askLift,
                  buildExtra: _extra,
                ),
              ),
            ),
            const SizedBox(height: 10),
            StatusRow(
              state: chat.state,
              text: chat.statusText,
              centered: !_barVisible,
              activity: _activity,
            ),
            const SizedBox(height: 10),
            fading(
              CommandBar(
                input: _input,
                focus: _focus,
                onSend: _send,
                onUpload: () => _pickFile(),
                attachment: _file == null
                    ? null
                    : PinnedFile(
                        name: _file!.split(RegExp(r'[\\/]')).last,
                        onRemove: () => setState(() => _file = null),
                      ),
                hasAttachment: _file != null,
                barActive: _barVisible && chat.media == null,
              ),
            ),
          ],
        ),
        // bottom: 54px = the bar (44) and 10px, as in `#command-suggest { bottom: 54px }`
        Positioned(
          left: 0,
          right: 0,
          bottom: 54,
          child: CommandSuggest(controller: _suggest),
        ),
        // the question box rises 8px above the bar (`.ask-panel { bottom: calc(100% + 8px) }`)
        Positioned(
          left: 0,
          right: 0,
          bottom: _askBottom,
          child: fading(
            AskLayer(
              card: chat.ask,
              onAnswer: chat.answerAsk,
              onHeight: _liftChat,
            ),
          ),
        ),
      ],
    );
  }
}
