import 'dart:async';
import 'dart:math' as math;
import 'dart:typed_data';

import 'package:audio_session/audio_session.dart'
    as av
    show
        AVAudioSessionCategory,
        AVAudioSessionMode;
import 'package:audio_session/audio_session.dart'
    show
        AndroidAudioAttributes,
        AndroidAudioContentType,
        AndroidAudioUsage,
        AudioSession,
        AudioSessionConfiguration;
import 'package:audioplayers/audioplayers.dart' hide AudioEvent;
import 'package:flutter/foundation.dart';
import 'package:flutter_pcm_sound/flutter_pcm_sound.dart';
import 'package:jarvis_mobile/chat/chat_models.dart';

abstract class AudioBackend {
  /// Appends samples to the streaming sink and returns once they are queued (not played): the sink plays them right
  /// after what it already holds, like the web's AudioContext timeline.
  Future<void> feedPcm(Uint8List bytes, int sampleRate);

  /// Completes when the sink has played out everything fed so far (at once when it is idle).
  Future<void> get pcmDrained;
  Future<void> playEncoded(Uint8List bytes);
  void stop();

  /// Puts the shared audio session back to the playback set-up (a cue that ended may have deactivated it).
  Future<void> reactivate();
  void dispose();
}

/// PCM (`pcm_chunk`) streams to the speaker through flutter_pcm_sound (AudioTrack on Android, an audio unit on iOS): the samples go
/// in as they are, no file or WAV wrapper. Encoded audio (`audio_chunk...audio_chunk_end`, `audio`) still goes through audioplayers.
class DefaultAudioBackend implements AudioBackend {
  DefaultAudioBackend({
    this.onWarn,
    this.tail = const Duration(milliseconds: 120),
    @visibleForTesting this.activate,
  });

  /// Problems that do not stop the sound (the audio session refusing a setting): shown so the next test says what failed.
  final void Function(String message)? onWarn;

  /// The sink reports "drained" when the last samples are handed to the hardware, which still holds ~100 ms of them.
  final Duration tail;

  /// Test seam: stands in for the audio session set-up that runs before every PCM run.
  final Future<void> Function()? activate;

  AudioPlayer? _player;
  Completer<void>? _playCompleter;
  StreamSubscription<void>? _completeSub;

  int? _pcmRate; // the rate the sink is set up for; null = not set up
  Completer<void>? _drain; // pending while the sink holds samples
  Timer? _tailTimer;
  int _gen = 0; // bumped by stop(): a feed that was waiting on setup or the session must not play

  /// iOS: playback routes to the main loudspeaker at full multimedia volume (same as music/video).
  /// Android: music content type with media usage.
  Future<void> _configureSession() async {
    try {
      final session = await AudioSession.instance;
      await session.configure(
        AudioSessionConfiguration(
          avAudioSessionCategory: av.AVAudioSessionCategory.playback,
          avAudioSessionMode: av.AVAudioSessionMode.defaultMode,
          androidAudioAttributes: const AndroidAudioAttributes(
            contentType: AndroidAudioContentType.music,
            usage: AndroidAudioUsage.media,
          ),
        ),
      );
      await session.setActive(true);
    } catch (e) {
      onWarn?.call('Không cấu hình được phiên âm thanh: $e');
    }
  }

  Future<void> _setupPcm(int sampleRate, int gen) async {
    if (_pcmRate == sampleRate) return;
    await FlutterPcmSound.setLogLevel(LogLevel.error);
    await FlutterPcmSound.setup(
      sampleRate: sampleRate,
      channelCount: 1,
      iosAudioCategory: IosAudioCategory.playback,
    );
    if (gen != _gen) return; // stop() came in meanwhile and released the sink
    _pcmRate = sampleRate;
    FlutterPcmSound.setFeedCallback((remaining) {
      if (remaining != 0) return;
      final drain = _drain;
      if (drain == null || drain.isCompleted) return;
      _tailTimer?.cancel();
      _tailTimer = Timer(tail, () {
        if (!drain.isCompleted) drain.complete();
      });
    });
  }

  @override
  Future<void> get pcmDrained => _drain?.future ?? Future<void>.value();

  @override
  Future<void> feedPcm(Uint8List bytes, int sampleRate) async {
    final gen = _gen;
    // ponytail: another rate mid-stream waits for the sink to play out, then sets it up again (backend speaks one rate)
    if (_pcmRate != null && _pcmRate != sampleRate) {
      await pcmDrained;
      if (gen != _gen) return;
    }
    await _setupPcm(sampleRate, gen);
    if (gen != _gen) return;
    final drain = _drain;
    if (drain == null || drain.isCompleted) {
      // each run: audioplayers (the cues) deactivates the shared session when its own sound ends
      await (activate ?? _configureSession)();
      if (gen != _gen) return;
      _drain = Completer<void>();
    }
    _tailTimer?.cancel(); // more samples: the sink is not done
    // the plugin sends the whole backing buffer: hand it exactly the samples
    final samples = Uint8List.fromList(
      bytes.sublist(0, bytes.length - bytes.length % 2),
    );
    await FlutterPcmSound.feed(
      PcmArrayInt16(bytes: ByteData.sublistView(samples)),
    );
  }

  AudioPlayer _encodedPlayer() {
    final existing = _player;
    if (existing != null) return existing;
    final player = _player = AudioPlayer();
    unawaited(
      AudioPlayer.global
          .setAudioContext(
            AudioContext(
              iOS: AudioContextIOS(
                category: AVAudioSessionCategory.playAndRecord,
                options: const {
                  AVAudioSessionOptions.defaultToSpeaker,
                  AVAudioSessionOptions.allowBluetooth,
                },
              ),
              android: const AudioContextAndroid(
                contentType: AndroidContentType.speech,
                usageType: AndroidUsageType.media,
                audioFocus: AndroidAudioFocus.gain,
              ),
            ),
          )
          .catchError(
            (Object e) => onWarn?.call('Không đặt được ngữ cảnh âm thanh: $e'),
          ),
    );
    return player;
  }

  @override
  Future<void> playEncoded(Uint8List bytes) async {
    final player = _encodedPlayer();
    stop();
    final completer = _playCompleter = Completer<void>();
    _completeSub = player.onPlayerComplete.listen((_) {
      if (!completer.isCompleted) completer.complete();
    });
    try {
      await player.play(BytesSource(bytes));
      await completer.future;
    } catch (_) {
      if (!completer.isCompleted) completer.complete();
      rethrow;
    }
  }

  @override
  Future<void> reactivate() => (activate ?? _configureSession)();

  @override
  void stop() {
    _gen++;
    _completeSub?.cancel();
    _completeSub = null;
    if (_playCompleter != null && !_playCompleter!.isCompleted) {
      _playCompleter!.complete();
    }
    _player?.stop();
    _tailTimer?.cancel();
    if (_drain != null && !_drain!.isCompleted) _drain!.complete();
    if (_pcmRate != null) {
      // frees what is still queued in the sink; the next run sets it up again
      _pcmRate = null;
      unawaited(
        FlutterPcmSound.release().catchError((Object e) {
          onWarn?.call('Không dừng được bộ phát PCM: $e');
          return null;
        }),
      );
    }
  }

  @override
  void dispose() {
    stop();
    _player?.dispose();
  }
}

/// Make-up gain + soft-knee saturation limiter on the 16-bit PCM stream.
/// Boosts speech by [gain] (3.24 = +80%) while smoothly saturating peaks under [ceiling] (-1 dBFS)
/// without envelope-canceling or pumping quiet syllables.
class Loudness {
  static const double gain = 3.24; // +80% total boost from baseline 1.8 (1.8 * 1.80, ≈ +10.2 dB)
  static const int ceiling = 29204; // −1 dBFS
  static const int threshold = 18000;
  static const int headroom = ceiling - threshold; // 11204
  static const double releaseS = 0.08;

  Loudness({this.sampleRate = 24000});
  int sampleRate;
  

  void reset() {}

  static double _tanh(double x) {
    if (x > 15.0) return 1.0;
    if (x < -15.0) return -1.0;
    final e = math.exp(2 * x);
    return (e - 1) / (e + 1);
  }

  Uint8List apply(Uint8List bytes) {
    final n = bytes.length ~/ 2;
    final src = ByteData.sublistView(bytes);
    final out = Uint8List(n * 2);
    final dst = ByteData.sublistView(out);
    for (var i = 0; i < n; i++) {
      final x = src.getInt16(i * 2, Endian.little) * gain;
      final a = x.abs();
      double y;
      if (a <= threshold) {
        y = x;
      } else {
        final sign = x > 0 ? 1.0 : -1.0;
        final excess = (a - threshold).toDouble();
        y = sign * (threshold + headroom * _tanh(excess / headroom));
      }
      dst.setInt16(i * 2, y.round(), Endian.little);
    }
    return out;
  }
}

class AudioOut {
  AudioOut({
    AudioBackend? backend,
    this.bufferMs = 450,
    this.margin = const Duration(seconds: 3),
    this.onError,
  }) : _injected = backend;

  final AudioBackend? _injected;
  late final AudioBackend backend =
      _injected ?? DefaultAudioBackend(onWarn: _report);
  final int bufferMs;

  /// Every playback failure goes here (the chat shows it in the island), once per streak: a device that cannot play would
  /// otherwise repeat it for every sentence.
  final void Function(String message)? onError;
  bool _reported = false;

  void _report(Object e) {
    debugPrint('[audio_out] $e');
    if (_reported) return;
    _reported = true;
    onError?.call(e is String ? e : 'Không phát được giọng nói: $e');
  }

  /// Added to the expected length of a run: native playback that fails silently never completes, and the chat would stay
  /// in "speaking" for good. Past it the run is stopped and the queue goes on.
  final Duration margin;

  final ValueNotifier<bool> _playing = ValueNotifier(false);
  ValueListenable<bool> get playing => _playing;

  final List<PcmChunk> _pcmQueue = []; // handed over, not yet fed to the sink
  final List<Uint8List> _encodedChunks = [];
  int _generation = 0;

  /// Feeds run one after another, in arrival order (setting up the sink is async).
  Future<void> _pcmChain = Future<void>.value();
  bool _pcmRun =
      false; // the sink holds fed samples that have not played out yet
  bool _watching = false;
  bool _fedOk = false; // this run fed the sink at least once
  int _fedCount = 0;
  final Stopwatch _clock = Stopwatch()..start();
  final Loudness _loudness = Loudness();
  Duration _sinkEnd =
      Duration.zero; // _clock time at which the fed samples run out

  int get queueLength => _pcmQueue.length;

  void handle(AudioEvent e) {
    switch (e) {
      case PcmChunk():
        _handlePcm(e);
      case EncodedChunk():
        _encodedChunks.add(e.bytes);
      case EncodedEnd():
        _playAssembledEncoded();
      case EncodedWhole():
        _playWholeEncoded(e.bytes);
      case StopAudio():
        stop();
    }
  }

  /// Web `enqueuePcm`: every chunk is queued on the sink as it arrives, so sentences play back to back with no seam. A run
  /// that starts on an idle sink waits [bufferMs] first; a sentence gap inside a run is fed as silence.
  void _handlePcm(PcmChunk chunk) {
    final gen = _generation;
    _pcmQueue.add(chunk);
    _playing.value = true;
    _pcmChain = _pcmChain.then((_) => _feedNext(gen));
  }

  Future<void> _feedNext(int gen) async {
    if (gen != _generation || _pcmQueue.isEmpty) return;
    final continuing = _pcmRun;
    if (!continuing) {
      _pcmRun = true;
      _fedOk = false;
      if (bufferMs > 0) {
        await Future<void>.delayed(Duration(milliseconds: bufferMs));
        if (gen != _generation) return;
      }
    }
    final chunk = _pcmQueue.removeAt(0);
    var bytes = (_loudness..sampleRate = chunk.sampleRate).apply(chunk.bytes);
    if (continuing && chunk.gapMs > 0) {
      final silence = chunk.sampleRate * chunk.gapMs ~/ 1000 * 2;
      bytes =
          (BytesBuilder(copy: false)
                ..add(Uint8List(silence))
                ..add(bytes))
              .takeBytes();
    }
    try {
      await backend.feedPcm(bytes, chunk.sampleRate);
      if (gen != _generation) return;
      _fedOk = true;
      _fedCount++;
      final now = _clock.elapsed;
      _sinkEnd =
          (_sinkEnd > now ? _sinkEnd : now) +
          Duration(
            microseconds: bytes.length * 1000000 ~/ (chunk.sampleRate * 2),
          );
    } catch (err) {
      _report(err);
    }
    if (gen == _generation) unawaited(_watchDrain(gen));
  }

  /// Ends the run when the sink has played out and nothing more was handed over; a sink that never reports it (native
  /// playback failing silently) is stopped past the expected end + [margin], so the chat does not stay in "speaking".
  /// The deadline follows [_sinkEnd]: every chunk fed meanwhile moves it (a long answer streams for many seconds).
  Future<void> _watchDrain(int gen) async {
    if (_watching) return;
    _watching = true;
    while (true) {
      final before = _fedCount;
      final left = _sinkEnd + margin - _clock.elapsed;
      final drained = await backend.pcmDrained
          .then((_) => true)
          .timeout(
            left.isNegative ? Duration.zero : left,
            onTimeout: () => false,
          );
      if (gen != _generation) return; // stop() reset the flags
      if (!drained && _fedCount != before) continue; // fed since: new deadline
      if (!drained) {
        backend.stop();
        _report('Âm thanh không phát xong nên đã bỏ qua (thiết bị im lặng?).');
      }
      await _pcmChain; // chunks already handed over are fed first
      if (gen != _generation) return;
      // more was fed: wait for it
      if (drained && _fedCount != before) continue;
      if (drained && _fedOk) _reported = false;
      _watching = false;
      _pcmRun = false;
      if (_pcmQueue.isEmpty) _playing.value = false;
      return;
    }
  }

  Future<void> _playAssembledEncoded() async {
    if (_encodedChunks.isEmpty) return;
    final builder = BytesBuilder(copy: false);
    for (final c in _encodedChunks) {
      builder.add(c);
    }
    _encodedChunks.clear();
    final allBytes = builder.takeBytes();
    await _playWholeEncoded(allBytes);
  }

  void _resetPcm() {
    _generation++;
    _pcmQueue.clear();
    _pcmRun = false;
    _watching = false;
    _sinkEnd = Duration.zero;
    _loudness.reset();
  }

  Future<void> _playWholeEncoded(Uint8List bytes) async {
    _resetPcm();
    _playing.value = true;

    final currentGen = _generation;
    try {
      // length unknown: bytes at the slowest usual rate (32 kbit/s)
      await _guard(
        backend.playEncoded(bytes),
        Duration(milliseconds: bytes.length * 8 ~/ 32),
      );
    } catch (err) {
      _report(err);
    } finally {
      if (_generation == currentGen) {
        _playing.value = false;
      }
    }
  }

  Future<void> _guard(Future<void> play, Duration expected) async {
    var timedOut = false;
    await play.timeout(
      expected + margin,
      onTimeout: () {
        timedOut = true;
        backend.stop();
      },
    );
    if (timedOut) {
      _report('Âm thanh không phát xong nên đã bỏ qua (thiết bị im lặng?).');
    } else {
      _reported = false;
    }
  }

  /// A mic cue ended: if speech is playing, its session is set up again (the cue's player may have deactivated it).
  void reactivate() {
    if (_playing.value) unawaited(backend.reactivate().catchError(_report));
  }

  void stop() {
    _resetPcm();
    _encodedChunks.clear();
    _playing.value = false;
    backend.stop();
  }

  void dispose() {
    stop();
    backend.dispose();
    _playing.dispose();
  }
}
