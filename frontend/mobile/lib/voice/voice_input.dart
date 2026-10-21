import 'dart:async';
import 'dart:io';

import 'package:audioplayers/audioplayers.dart';
import 'package:flutter/foundation.dart';
import 'package:jarvis_mobile/net/api_client.dart';
import 'package:path_provider/path_provider.dart';
import 'package:record/record.dart';
import 'package:speech_to_text/speech_to_text.dart';

abstract class SpeechBackend {
  Future<bool> initialize({
    void Function(String status)? onStatus,
    void Function(dynamic error)? onError,
  });
  Future<List<String>> locales();
  Future<void> listen({
    required void Function(String words, bool isFinal) onResult,
    String? localeId,
  });
  Future<void> stop();
  bool get isListening;
}

abstract class RecordBackend {
  Future<bool> hasPermission();
  Future<void> start(RecordConfig config, {required String path});
  Future<String?> stop();
  Future<bool> isRecording();
  void dispose();
}

class DefaultSpeechBackend implements SpeechBackend {
  final SpeechToText _stt = SpeechToText();

  @override
  Future<bool> initialize({
    void Function(String status)? onStatus,
    void Function(dynamic error)? onError,
  }) {
    return _stt.initialize(
      onStatus: onStatus,
      onError: (e) => onError?.call(e.errorMsg),
    );
  }

  @override
  Future<List<String>> locales() async {
    final list = await _stt.locales();
    return list.map((l) => l.localeId).toList();
  }

  @override
  Future<void> listen({
    required void Function(String words, bool isFinal) onResult,
    String? localeId,
  }) {
    return _stt.listen(
      listenOptions: SpeechListenOptions(localeId: localeId),
      onResult: (res) => onResult(res.recognizedWords, res.finalResult),
    );
  }

  @override
  Future<void> stop() => _stt.stop();

  @override
  bool get isListening => _stt.isListening;
}

class DefaultRecordBackend implements RecordBackend {
  final AudioRecorder _recorder = AudioRecorder();

  @override
  Future<bool> hasPermission() => _recorder.hasPermission();

  @override
  Future<void> start(RecordConfig config, {required String path}) {
    return _recorder.start(config, path: path);
  }

  @override
  Future<String?> stop() => _recorder.stop();

  @override
  Future<bool> isRecording() => _recorder.isRecording();

  @override
  void dispose() => _recorder.dispose();
}

/// The short "ting" Safari's recogniser plays when it starts and when it stops; the native recogniser is silent.
Future<void> playMicCue(String name) async {
  AudioPlayer? player;
  try {
    player = AudioPlayer();
    await player.setReleaseMode(ReleaseMode.release);
    await player.play(AssetSource('sounds/$name.wav'), volume: 0.35);
    await player.onPlayerComplete.first.timeout(const Duration(seconds: 1));
  } catch (e) {
    debugPrint('[voice_input] cue $name: $e');
  } finally {
    await player?.dispose();
  }
}

/// Mic input, mirroring voice.ts createVoiceInput. Flow: start() -> speech heard -> pause() while JARVIS thinks and talks ->
/// resume() as soon as it is done -> and so on; stop() when the user switches the mic off. A session ends after each result (or
/// by the OS timing it out) and is started again at once; a start that never comes up, or a session that heard nothing, is retried
/// after [retryMs]; after [maxEmpty] such failures in a row the mic is stopped for good and [onGiveUp] fires.
class VoiceInput {
  VoiceInput({
    required this.onTranscript,
    this.onError,
    this.onGiveUp,
    this.apiClient,
    this.cue = playMicCue,
    SpeechBackend? speechBackend,
    RecordBackend? recordBackend,
    Future<Directory> Function()? getTempDir,
    this.retryMs = 3000,
    this.firstStartMs = 15000,
  }) : _speech = speechBackend ?? DefaultSpeechBackend(),
       _record = recordBackend ?? DefaultRecordBackend(),
       _getTempDir = getTempDir ?? getTemporaryDirectory;

  static const maxEmpty = 5;

  final void Function(String transcript) onTranscript;
  final void Function(String message)? onError;
  final VoidCallback? onGiveUp;
  final ApiClient? apiClient;

  /// Plays `mic_start` when the user switches the mic on (awaited before listening starts) and `mic_end` when the user switches it off or it gives up (restarts after a result, a timeout or a pause stay silent).
  final Future<void> Function(String name) cue;
  final int retryMs;
  final int firstStartMs; // the very first start may be waiting for the "allow the microphone" dialog
  final SpeechBackend _speech;
  final RecordBackend _record;
  final Future<Directory> Function() _getTempDir;

  final ValueNotifier<bool> _listening = ValueNotifier(false);
  ValueListenable<bool> get listening => _listening;

  bool _hasViLocale = false;
  bool _useWhisper = false;
  String? _recordingPath;

  bool _shouldListen = false;
  bool _paused = false;
  bool _starting = false; // begin() was called and the recogniser has not said "listening" yet
  bool _everStarted = false;
  bool _heard = false; // this session produced a result
  bool _dupEnd = false; // the next end report is the second one of a session already handled
  int _empty = 0; // failures in a row
  Timer? _retry;
  Timer? _watch;

  Future<bool> init() async {
    try {
      final available = await _speech.initialize(
        onStatus: (status) {
          if (status == 'listening') {
            _onSessionStart();
          } else if (status == 'notListening' || status == 'done') {
            _onSessionEnd();
          }
        },
        onError: (e) {
          debugPrint('[voice_input] stt error: $e');
          if (e == 'error_permission') {
            _giveUp(_denied);
          }
        },
      );

      if (available) {
        final locales = await _speech.locales();
        _hasViLocale = locales.any(
          (l) => l.toLowerCase().replaceAll('-', '_').startsWith('vi'),
        );
      }
      _useWhisper = !available || !_hasViLocale;
      return true;
    } catch (e) {
      debugPrint('[voice_input] stt init failed, falling back to whisper: $e');
      _useWhisper = true;
      return true;
    }
  }

  Future<void> start() async {
    _shouldListen = true;
    _paused = false;
    _empty = 0;
    // the user's switch only: restarts after a result, a timeout or a pause stay silent, and the cue is over before the
    // recogniser (or the recorder) opens, so the mic does not hear it
    await cue('mic_start');
    if (!_shouldListen) return;
    await _begin();
  }

  Future<void> stop() async {
    final wasOn = _shouldListen;
    _shouldListen = false;
    _paused = false;
    _empty = 0;
    await _halt();
    // Safari's stop sound, after the recogniser is closed
    if (wasOn) {
      unawaited(cue('mic_end'));
    }
  }

  /// JARVIS is thinking or talking: the recogniser rests (the user's switch stays on).
  Future<void> pause() async {
    if (_paused) return;
    _paused = true;
    await _halt();
  }

  Future<void> resume() async {
    if (!_paused) return;
    _paused = false;
    if (_shouldListen) await _begin();
  }

  static const _denied =
      'Microphone access denied. Please allow microphone access.';

  /// The mic stops for good (heard nothing, or no permission): [message] is shown, the end cue plays and [onGiveUp] turns the
  /// mic button off.
  void _giveUp([
    String message =
        'Mic không nghe được gì nên đã tắt. Bấm nút mic để bật lại.',
  ]) {
    _shouldListen = false;
    _retry?.cancel();
    _watch?.cancel();
    onError?.call(message);
    unawaited(cue('mic_end'));
    onGiveUp?.call();
  }

  Future<void> _begin() async {
    if (_starting || _listening.value || !_shouldListen || _paused) return;
    _retry?.cancel();
    if (_useWhisper) return _beginWhisper();
    _heard = false;
    _starting = true;
    _watch?.cancel();
    _watch = Timer(
      Duration(milliseconds: _everStarted ? retryMs : firstStartMs),
      () {
        if (!_starting || !_shouldListen || _paused) return;
        _starting = false;
        if (++_empty > maxEmpty) return _giveUp();
        _dupEnd = false;
        unawaited(_speech.stop());
        _retry = Timer(
          const Duration(milliseconds: 500),
          () => unawaited(_begin()),
        );
      },
    );
    try {
      await _speech.listen(
        localeId: 'vi_VN',
        onResult: (words, isFinal) {
          _heard = true;
          _empty = 0;
          if (isFinal && words.trim().isNotEmpty) {
            onTranscript(words.trim());
          }
        },
      );
    } catch (e) {
      debugPrint('[voice_input] native stt failed, fallback to whisper: $e');
      _starting = false;
      _watch?.cancel();
      _useWhisper = true;
      await _begin();
    }
  }

  void _onSessionStart() {
    _starting = false;
    _dupEnd = false;
    _everStarted = true;
    _watch?.cancel();
    _listening.value = true;
  }

  /// speech_to_text reports `notListening` and then `done` for one session: the second one is [_dupEnd] and must not touch
  /// the session that was started in between.
  void _onSessionEnd() {
    if (_starting) {
      if (_dupEnd) {
        _dupEnd = false;
        return;
      }
      // ended before it ever said "listening": a failed start, counted like voice.ts onend
      _starting = false;
      _watch?.cancel();
      if (_shouldListen && !_paused) _failed();
      return;
    }
    if (!_listening.value) return; // stale: the session was stopped already
    _watch?.cancel();
    _listening.value = false;
    _dupEnd = true;
    if (!_shouldListen || _paused) return;
    if (_heard) {
      _empty = 0;
      unawaited(_begin());
    } else {
      _failed();
    }
  }

  void _failed() {
    if (++_empty > maxEmpty) return _giveUp();
    _retry = Timer(Duration(milliseconds: retryMs), () => unawaited(_begin()));
  }

  /// Stops whatever is running (pause and stop both land here).
  Future<void> _halt() async {
    _retry?.cancel();
    _watch?.cancel();
    _starting = false;
    _dupEnd = false;
    if (!_useWhisper) {
      final was = _listening.value;
      _listening.value = false;
      _heard = false;
      if (was || _speech.isListening) await _speech.stop();
      return;
    }
    await _finishWhisper();
  }

  // Whisper fallback: record to a temp file, send it to /api/stt when the recording ends.
  Future<void> _beginWhisper() async {
    final hasPerm = await _record.hasPermission();
    if (!hasPerm) {
      debugPrint('[voice_input] Record permission denied');
      _giveUp(_denied);
      return;
    }
    final tempDir = await _getTempDir();
    _recordingPath = '${tempDir.path}/speech.wav';
    _listening.value = true;
    await _record.start(
      const RecordConfig(
        encoder: AudioEncoder.wav,
        sampleRate: 16000,
        numChannels: 1,
      ),
      path: _recordingPath!,
    );
  }

  Future<void> _finishWhisper() async {
    if (!_listening.value) return;
    _listening.value = false;
    final path = await _record.stop();
    final wavPath = path ?? _recordingPath;
    if (wavPath != null && apiClient != null) {
      final file = File(wavPath);
      if (file.existsSync()) {
        try {
          final res = await apiClient!.upload('/api/stt', wavPath);
          final success = res['success'] == true;
          final text = res['text'] as String?;
          if (success && text != null && text.trim().isNotEmpty) {
            onTranscript(text.trim());
          }
        } catch (e) {
          debugPrint('[voice_input] whisper upload failed: $e');
        } finally {
          try {
            file.deleteSync();
          } catch (_) {}
        }
      }
    }
  }

  void dispose() {
    _shouldListen = false;
    _retry?.cancel();
    _watch?.cancel();
    unawaited(_halt());
    _listening.dispose();
    _record.dispose();
  }
}
