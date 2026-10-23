import 'dart:async';
import 'dart:collection';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../net/api_client.dart';
import '../net/jarvis_socket.dart';
import 'chat_models.dart';

class _Queued {
  _Queued(this.text, this.filePath, this.bubble);
  final String text;
  final String? filePath;
  final UserMsg bubble;
}

/// Chat-screen state built from WS packets. Mirrors frontend/src/main.ts (socket handler,
/// transition(), pendingQueriesQueue, uploadAndSend, cancel paths) without the mic and playback.
class ChatController extends ChangeNotifier {
  ChatController(this._socket, this._api, {this.ttsEnabled = true}) {
    _sub = _socket.messages.listen(_onMessage);
    _socket.state.addListener(_onSocketState);
  }

  static const _ttsKey = 'jarvis_tts_disabled'; // the web's localStorage key

  /// The stored TTS switch, read before runApp (main.ts: localStorage jarvis_tts_disabled).
  static Future<bool> loadTtsEnabled() async {
    try {
      return !((await SharedPreferences.getInstance()).getBool(_ttsKey) ??
          false);
    } catch (_) {
      return true;
    }
  }

  /// ws.ts onopen: the server forgets the switch with the socket, so a muted app tells it again every time.
  void _onSocketState() {
    if (_socket.state.value == SocketState.open && !ttsEnabled) {
      _socket.send({'type': 'toggle_tts', 'enabled': false});
    }
  }

  static const _disconnected =
      '⚠️ Mất kết nối tới máy chủ — tin nhắn chưa gửi được, đang thử kết nối lại.';
  static const _cardPrefix = '[INTERACTIVE_CARD_JSON]:';
  static const _labels = {
    JState.idle: 'Sẵn sàng',
    JState.listening: 'Đang nghe…',
    JState.thinking: 'Đang nghĩ…',
    JState.working: 'Đang làm việc…',
    JState.speaking: 'Đang đọc…',
  };

  final JarvisSocket _socket;
  final ApiClient _api;
  late final StreamSubscription<Map<String, dynamic>> _sub;
  final _audio = StreamController<AudioEvent>.broadcast();
  final _items = <ChatItem>[];
  final _queue = <_Queued>[];

  JState _state = JState.idle;
  String _statusText = _labels[JState.idle]!;
  bool _welcomeActive = true;
  WelcomeData? _welcome;
  FlowSteps _flow = const FlowSteps();
  String? _error;
  int _errorSeq = 0; // bumped on every error, so the same text twice still reaches the island
  AskCard? _ask;
  MediaOpen? _media;
  ReaderCard? _reader;
  bool _disposed = false;

  bool _busy = false;
  bool _playing = false; // sound is coming out (main.ts isSpeaking || audioPlayer.isPlaying())
  bool _micOn = false; // main.ts !isMuted
  bool _ttsOpen = false;
  bool _speechPreparing = false;
  bool _wasStreamed = false;
  bool _hasChunks = false;
  int? _active; // index of the streaming AssistantMsg
  JState _lastWorkState = JState.thinking;
  String? _lastWorkMessage;

  bool ttsEnabled;
  int _cardSeq = 0; // card ids: a clock tick is too coarse on Windows, two cards in one tick overwrote each other

  List<ChatItem> get items => UnmodifiableListView(_items);
  JState get state => _state;
  String get statusText => _statusText;
  bool get welcomeVisible => _welcomeActive;
  WelcomeData? get welcome => _welcome;
  FlowSteps get flow => _flow;
  String? get error => _error;
  int get errorSeq => _errorSeq;
  AskCard? get ask => _ask;
  MediaOpen? get media => _media;
  ReaderCard? get reader => _reader;
  Stream<AudioEvent> get audio => _audio.stream;

  /// main.ts turnRunning: include speech preparation and local playback.
  bool get turnRunning =>
      _busy ||
      _ttsOpen ||
      _speechPreparing ||
      _playing ||
      _state == JState.thinking ||
      _state == JState.working ||
      _state == JState.speaking;

  void clearChat({bool keepWelcome = true}) {
    _items.clear();
    _queue.clear();
    _active = null;
    if (!keepWelcome) _welcomeActive = false;
    _notify();
  }

  void showHistory(List<Map<String, dynamic>> rows) {
    clearChat();
    for (final row in rows) {
      final content = row['content'];
      if (content is! String) continue;
      if (row['role'] == 'user') {
        _addItem(UserMsg(content));
      } else if (row['role'] == 'assistant') {
        if (content.startsWith(_cardPrefix)) {
          try {
            final card = jsonDecode(
              content.substring(_cardPrefix.length).trim(),
            );
            if (card is Map<String, dynamic> && AskCard.isAskCard(card)) {
              continue;
            }
          } catch (_) {
            // Malformed cards are rendered by the normal assistant path.
          }
        }
        _addAssistant(content);
      }
    }
    if (_items.isNotEmpty) _welcomeActive = false;
    _notify();
  }

  /// main.ts socket.onSession: old socket flags end; local audio keeps playing.
  void onNewSocket() {
    _busy = false;
    _ttsOpen = _speechPreparing = false;
    _closeBubble();
    _transition(JState.idle);
    _notify();
  }

  // ---- state machine (main.ts transition / updateStatus) ----

  void _transition(JState want, [String? message]) {
    final msg = (message == null || message.isEmpty) ? null : message;
    // idle with the mic on and no sound out is "listening" (main.ts transition)
    final next = want == JState.idle && _micOn && !_playing
        ? JState.listening
        : want;
    if (next == _state && msg == null) return;
    _state = next;
    _updateStatus(next, msg);
  }

  /// The mic button (main.ts btnMute click): switching it on turns an idle bar into "listening", off the reverse.
  void setListening(bool on) {
    _micOn = on;
    if (on && _state == JState.idle) _transition(JState.idle);
    if (!on && _state == JState.listening) {
      _state = JState.idle;
      _updateStatus(JState.idle);
    }
    _notify();
  }

  /// The recognizer may run only in "listening" (main.ts transition: every other state pauses it).
  bool get wantsMic => _state == JState.listening;

  /// Sound started or stopped (main.ts audioPlayer.onStarted / onFinished).
  void setPlaying(bool playing) {
    if (playing == _playing) return;
    _playing = playing;
    _speechPreparing = false;
    if (playing) {
      if (_state != JState.speaking) {
        _transition(JState.speaking);
      } else {
        _updateStatus(JState.speaking);
      }
    } else if (_queue.isNotEmpty) {
      _drain();
    } else if (!ttsEnabled) {
      _busy = false;
      _transition(JState.idle);
    } else {
      _afterSpeech();
    }
    _notify();
  }

  void _updateStatus(JState s, [String? message]) {
    if (s == JState.thinking || s == JState.working) {
      _lastWorkState = s;
      _lastWorkMessage = message;
    }
    _statusText = message ?? _labels[s]!;
  }

  /// The speech went quiet (main.ts afterSpeech).
  void _afterSpeech() {
    if (_busy) {
      _transition(_lastWorkState, _lastWorkMessage);
    } else if (!_ttsOpen) {
      _transition(JState.idle);
    }
  }

  /// Sends the next queued message (main.ts audioPlayer.onFinished queue branch).
  void _drain() {
    if (_queue.isEmpty) return;
    final q = _queue.removeAt(0);
    final i = _items.indexOf(q.bubble);
    if (i >= 0) {
      _items[i] = UserMsg(
        q.bubble.text,
        attachmentName: q.bubble.attachmentName,
      );
    }
    if (q.filePath != null) {
      unawaited(_upload(q.text, q.filePath!).whenComplete(_notify));
    } else if (_deliver(q.text)) {
      _transition(JState.thinking);
    }
  }

  bool get _busyNow =>
      _playing ||
      _busy ||
      _state == JState.thinking ||
      _state == JState.working;

  // ---- sending ----

  bool _deliver(String text, {String? attachmentId}) {
    final ok = _socket.send({
      'type': 'transcript',
      'text': text,
      'attachmentId': ?attachmentId,
      'isFinal': true,
    });
    if (!ok) {
      _setError(_disconnected);
      _transition(JState.idle);
    }
    return ok;
  }

  Future<void> sendText(String text, {String? filePath}) async {
    if (text.isEmpty && filePath == null) return;
    _error = null;
    final name = filePath?.split(RegExp(r'[\\/]')).last;
    // main.ts addChatMessage: the exact same user message twice in a row is not drawn twice (it is still sent).
    final last = _items.isEmpty ? null : _items.last;
    final dup =
        last is UserMsg && last.text == text && last.attachmentName == name;
    final msg = UserMsg(text, attachmentName: name);
    if (_busyNow) {
      final pending = UserMsg(text, attachmentName: name, pending: true);
      if (dup) {
        _items[_items.length - 1] = pending;
      } else {
        _addItem(pending);
      }
      _queue.add(_Queued(text, filePath, pending));
    } else if (filePath != null) {
      if (!dup) _addItem(msg);
      _notify();
      await _upload(text, filePath);
    } else if (_deliver(text)) {
      if (!dup) _addItem(msg);
      if (_state == JState.idle || _state == JState.listening) {
        _transition(JState.thinking);
      }
    }
    _notify();
  }

  /// A spoken transcript (main.ts voice handler, queued while busy).
  void sendTranscript(String text) {
    // speaking over JARVIS interrupts it, unless the recogniser only heard its own voice (main.ts voice handler)
    final heard = text.trim().toLowerCase();
    final said =
        _items.whereType<AssistantMsg>().lastOrNull?.text.toLowerCase() ?? '';
    final echo =
        said.length > 5 && (said.contains(heard) || heard.contains(said));
    if (_playing && !echo) cancel();
    unawaited(sendText(text));
  }

  Future<void> _upload(String text, String filePath) async {
    final name = filePath.split(RegExp(r'[\\/]')).last;
    if (_state == JState.idle || _state == JState.listening) {
      _transition(JState.thinking, 'Đang tải $name…');
      _notify();
    }
    try {
      final data = await _api.upload('/api/upload', filePath);
      if (data['success'] == true) {
        _deliver(text, attachmentId: data['attachment_id']?.toString());
      } else {
        _uploadFailed('Upload failed: ${data['error']}');
      }
    } on ApiException catch (e) {
      _uploadFailed('Upload failed: ${e.message}');
    } catch (_) {
      _uploadFailed('Upload failed due to a network error.');
    }
  }

  void _setError(String msg) {
    _error = msg;
    _errorSeq++;
  }

  /// An error from the screen rather than the socket (the file picker): the island shows it like any other.
  void reportError(String msg) {
    _setError(msg);
    _notify();
  }

  void _uploadFailed(String msg) {
    _setError(msg);
    if (_state == JState.thinking) _transition(JState.idle);
  }

  /// Our own cancel (main.ts barge-in path): a cancelled turn gets neither stream_end nor idle.
  void cancel() {
    _socket.send({'type': 'cancel'});
    _audio.add(const StopAudio());
    _busy = _playing = false;
    _ttsOpen = _speechPreparing = false;
    _hasChunks = false;
    _closeBubble(dropEmpty: true);
    _transition(JState.idle);
    _notify();
  }

  void answerAsk(Map<String, dynamic> m) {
    _socket.send(m);
    _ask = null;
    _notify();
  }

  void setTts(bool on) {
    ttsEnabled = on;
    unawaited(_saveTts(on));
    _socket.send({'type': 'toggle_tts', 'enabled': on});
    if (!on) {
      _busy = _playing = false;
      _hasChunks = false;
      _audio.add(const StopAudio());
      _transition(JState.idle);
    }
    _notify();
  }

  Future<void> _saveTts(bool on) async {
    try {
      await (await SharedPreferences.getInstance()).setBool(_ttsKey, !on);
    } catch (_) {
      // a failed write only loses the setting across restarts
    }
  }

  void mediaState(bool active) =>
      _socket.send({'type': 'media_state', 'active': active});

  /// The media player was closed (main.ts closeMediaPlayer).
  void closeMedia() {
    _media = null;
    mediaState(false);
    _transition(JState.idle);
    _notify();
  }

  /// reader-card.ts opens from a tap on a link, not from a packet.
  void openReader(String url, {String title = ''}) {
    _reader = ReaderCard(url: url, title: title);
    _notify();
  }

  void closeReader() {
    _reader = null;
    _notify();
  }

  // ---- bubbles ----

  void _addItem(ChatItem it, {bool beforeActive = false}) {
    _welcomeActive = false;
    final a = _active;
    if (beforeActive && a != null) {
      _items.insert(a, it);
      _active = a + 1;
    } else {
      _items.add(it);
    }
  }

  void _closeBubble({bool dropEmpty = false}) {
    final a = _active;
    if (a == null) return;
    final m = _items[a] as AssistantMsg;
    _active = null;
    if (dropEmpty && m.text.isEmpty) {
      _items.removeAt(a);
    } else {
      _items[a] = AssistantMsg(m.text);
    }
  }

  /// server.py's error fallback sends one audio/text packet and no stream_end (main.ts dropEmptyAssistantBubble).
  void _dropEmptyBubble() {
    final a = _active;
    if (a != null && (_items[a] as AssistantMsg).text.isEmpty) {
      _closeBubble(dropEmpty: true);
    }
  }

  void _addAssistant(String text) {
    if (_items.isNotEmpty) {
      final last = _items.last;
      if (last is AssistantMsg && last.text == text) return;
    }
    if (text.startsWith(_cardPrefix)) {
      try {
        final card = jsonDecode(text.substring(_cardPrefix.length).trim());
        if (card is Map<String, dynamic>) return _card(card);
      } catch (e) {
        debugPrint('[chat] parse interactive card failed: $e');
      }
    }
    _addItem(AssistantMsg(text));
  }

  void _card(Map<String, dynamic>? c) {
    final id = c?['id'];
    if (c == null || id == null || id == '') return;
    if (AskCard.isAskCard(c)) {
      _ask = AskCard(c);
      return;
    }
    final name = (c['name'] as String?) ?? '';
    final ChatItem it;
    if (c['type'] == 'image_result') {
      final url = (c['url'] as String?) ?? '';
      if (url.isEmpty) return;
      it = ImageMsg(
        id: '$id',
        url: url,
        caption: name.isEmpty ? 'ảnh' : name,
        downloadUrl: c['downloadUrl'] as String?,
      );
    } else if (c['type'] == 'file') {
      it = FileMsg(
        id: '$id',
        name: name.isEmpty ? 'tệp' : name,
        url: (c['url'] as String?) ?? '',
        kind: (c['kind'] as String?) ?? 'document',
        ext: (c['ext'] as String?) ?? '',
        label: (c['label'] as String?) ?? '',
        caption: (c['caption'] as String?) ?? '',
        downloadUrl: (c['downloadUrl'] as String?) ?? '',
        size: c['size'] is num ? (c['size'] as num).toInt() : null,
      );
    } else {
      return;
    }
    final i = _items.indexWhere(
      (e) =>
          (e is ImageMsg && e.id == '$id') || (e is FileMsg && e.id == '$id'),
    );
    if (i >= 0) {
      _items[i] = it;
    } else {
      _addItem(it, beforeActive: true);
    }
  }

  // ---- packets (main.ts socket.onMessage) ----

  void _onMessage(Map<String, dynamic> m) {
    if (_disposed) return;
    final type = m['type'];
    if (type == 'audio' || type == 'text') _dropEmptyBubble();
    switch (type) {
      case 'audio':
        _onAudio(m);
      case 'stream_start':
        _closeBubble();
        _wasStreamed = false;
        _flow = const FlowSteps();
        _items.add(const AssistantMsg('', streaming: true));
        _welcomeActive = false;
        _active = _items.length - 1;
      case 'text_chunk':
        final chunk = m['text'];
        final a = _active;
        if (chunk is String && chunk.isNotEmpty && a != null) {
          _items[a] = AssistantMsg(
            (_items[a] as AssistantMsg).text + chunk,
            streaming: true,
          );
        }
      case 'audio_chunk':
        final bytes = _bytes(m['data']);
        if (bytes == null || !ttsEnabled) return;
        _hasChunks = true;
        _audio.add(EncodedChunk(bytes));
      case 'pcm_chunk':
        final bytes = _bytes(m['data']);
        if (bytes == null || !ttsEnabled) return;
        _audio.add(
          PcmChunk(
            bytes,
            sampleRate: (m['sample_rate'] as num?)?.toInt() ?? 48000,
            gapMs: (m['gap_ms'] as num?)?.toInt() ?? 0,
          ),
        );
      case 'audio_chunk_end':
        if (ttsEnabled && _hasChunks) _audio.add(const EncodedEnd());
        _hasChunks = false;
      case 'stream_end':
        _wasStreamed = true;
        _closeBubble();
      case 'status':
        _onStatus(m);
      case 'text':
        final t = m['text'] as String? ?? '';
        if (!_wasStreamed || t.startsWith('💡')) _addAssistant(t);
      case 'media_open':
        final embed = m['embed_url'] as String? ?? '';
        if (embed.isNotEmpty) {
          _media = MediaOpen(
            query: m['query'] as String? ?? '',
            embedUrl: embed,
            title: m['title'] as String? ?? '',
          );
          mediaState(true);
          _hasChunks = false;
          _audio.add(const StopAudio());
        }
      case 'screenshot_processed':
        var url = m['url'] as String? ?? '';
        if (url.isNotEmpty) {
          if (!url.contains('?')) {
            url = '$url?t=${DateTime.now().millisecondsSinceEpoch}';
          }
          final id = 'screenshot_${_cardSeq++}';
          _card({
            'id': id,
            'type': 'image_result',
            'name': 'Ảnh chụp màn hình',
            'url': url,
          });
        }
      case 'output_file':
        _onOutputFile(m);
      case 'interactive':
        final card = m['card'];
        _card(card is Map<String, dynamic> ? card : null);
      case 'flow_step':
        final s = m['step'];
        if (s is Map && s['id'] != null && s['id'] != 0 && s['id'] != '') {
          _flow = _flow.upsert(
            FlowStep(
              id: '${s['id']}',
              label: '${s['label'] ?? ''}',
              status: '${s['status'] ?? ''}',
            ),
          );
        }
      case 'welcome':
        _onWelcome(m);
      case 'memory_updated':
        debugPrint('[chat] memory updated');
    }
    _notify();
  }

  Uint8List? _bytes(Object? b64) {
    if (b64 is! String || b64.isEmpty) return null;
    try {
      return base64Decode(b64);
    } catch (_) {
      return null;
    }
  }

  void _onAudio(Map<String, dynamic> m) {
    if (!ttsEnabled) return;
    final bytes = _bytes(m['data']);
    if (bytes != null) {
      _audio.add(EncodedWhole(bytes));
    } else {
      debugPrint('[chat] audio packet without data, returning to idle');
      _transition(JState.idle);
    }
    final text = m['text'];
    if (text is String && text.isNotEmpty && !_wasStreamed) _addAssistant(text);
  }

  void _onStatus(Map<String, dynamic> m) {
    final s = m['state'];
    final message = m['message'] as String?;
    final tts = m['source'] == 'tts';
    if (tts && !ttsEnabled) return;
    if (s == 'thinking' || s == 'working') {
      final st = s == 'thinking' ? JState.thinking : JState.working;
      _busy = true;
      if (_speechPreparing || _playing) {
        // shown when the speech ends
        _lastWorkState = st;
        _lastWorkMessage = message;
        return;
      }
      if (_state != st) {
        _transition(st, message);
      } else {
        _updateStatus(st, message);
      }
    } else if (s == 'idle') {
      if (tts) {
        _ttsOpen = _speechPreparing = false;
        if (!_playing) _afterSpeech(); // main.ts:1464 - sound still out: its own end settles the label
      } else {
        _busy = false;
        if (_state != JState.speaking) _transition(JState.idle);
      }
      if (_state == JState.idle || _state == JState.listening) _drain();
    } else if (s == 'speaking') {
      if (tts) {
        _ttsOpen = true;
        _speechPreparing = !_playing;
      }
      if (_state != JState.speaking) {
        _transition(JState.speaking, message);
      } else {
        _updateStatus(JState.speaking, message);
      }
    }
  }

  void _onOutputFile(Map<String, dynamic> m) {
    final id = 'output_${_cardSeq++}';
    if (m['kind'] == 'image') {
      final url = m['url'] as String? ?? '';
      _card({
        'id': id,
        'type': 'image_result',
        'name': m['name'],
        'url': url,
        'downloadUrl': (m['download_url'] as String?) ?? url,
      });
    } else {
      _card({
        'id': id,
        'type': 'file',
        'kind': 'document',
        'name': m['name'],
        'ext': m['ext'],
        'label': m['label'],
        'caption': m['caption'],
        'url': m['url'],
        'downloadUrl': m['download_url'],
        'size': m['size'],
      });
    }
  }

  void _onWelcome(Map<String, dynamic> m) {
    if (!_welcomeActive) return; // gone for good after the first message
    final w = m['weather'];
    final old = _welcome;
    final tools = m['tools'];
    _welcome = WelcomeData(
      greeting: (m['greeting'] as String?)?.isNotEmpty == true
          ? m['greeting'] as String
          : old?.greeting,
      tools: (old?.tools.isNotEmpty ?? false)
          ? old!.tools
          : (tools is List ? tools.map((e) => '$e').toList() : const []),
      weather: w is Map
          ? WelcomeWeather(
              desc: '${w['desc'] ?? ''}',
              temp: (w['temp'] as num?)?.toDouble(),
              kind: w['kind'] as String?,
              place: '${w['place'] ?? ''}',
            )
          : old?.weather,
    );
  }

  void _notify() {
    if (!_disposed) notifyListeners();
  }

  /// Resets all chat items, active stream, errors, and welcome state (e.g. on user switch/login).
  void reset() {
    _items.clear();
    _queue.clear();
    _active = null;
    _welcomeActive = true;
    _welcome = null;
    _flow = const FlowSteps();
    _error = null;
    _ask = null;
    _media = null;
    _reader = null;
    _state = JState.idle;
    _statusText = _labels[JState.idle]!;
    notifyListeners();
  }

  @override
  void dispose() {
    _disposed = true;
    _socket.state.removeListener(_onSocketState);
    _sub.cancel();
    _audio.close();
    super.dispose();
  }
}
