import 'dart:async';
import 'dart:typed_data';

import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jarvis_mobile/chat/chat_models.dart';
import 'package:jarvis_mobile/voice/audio_out.dart';

import '../chat/fakes.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  group('streaming PCM sink', () {
    const channel = MethodChannel('flutter_pcm_sound/methods');
    final calls = <MethodCall>[];
    final messenger =
        TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;

    setUp(() {
      calls.clear();
      messenger.setMockMethodCallHandler(channel, (c) async {
        calls.add(c);
        return true;
      });
      messenger.setMockMethodCallHandler(
        const MethodChannel('com.ryanheise.audio_session'),
        (c) async => null,
      );
    });
    tearDown(() {
      messenger.setMockMethodCallHandler(channel, null);
      messenger.setMockMethodCallHandler(
        const MethodChannel('com.ryanheise.audio_session'),
        null,
      );
    });

    Future<void> drained() => messenger.handlePlatformMessage(
      channel.name,
      const StandardMethodCodec().encodeMethodCall(
        const MethodCall('OnFeedSamples', {'remaining_frames': 0}),
      ),
      null,
    );

    test(
      'sets up once per rate, feeds every chunk as it comes, drains once',
      () async {
        final b = DefaultAudioBackend(tail: Duration.zero);
        await b.feedPcm(Uint8List(4800), 24000);
        expect(calls.map((c) => c.method), ['setLogLevel', 'setup', 'feed']);
        expect(calls[1].arguments['sample_rate'], 24000);
        expect(calls[1].arguments['num_channels'], 1);
        expect(calls[1].arguments['ios_audio_category'], 'playback');
        expect((calls[2].arguments['buffer'] as Uint8List).length, 4800);
        var done = false;
        unawaited(b.pcmDrained.then((_) => done = true));
        await b.feedPcm(Uint8List(2), 24000); // queued behind the first
        expect(calls.where((c) => c.method == 'setup').length, 1);
        expect(calls.where((c) => c.method == 'feed').length, 2);
        await Future<void>.delayed(const Duration(milliseconds: 20));
        expect(done, isFalse); // still playing
        await drained();
        await Future<void>.delayed(const Duration(milliseconds: 20));
        expect(done, isTrue);

        await b.feedPcm(Uint8List(2), 48000); // idle sink: set up at once
        expect(calls.where((c) => c.method == 'setup').length, 2);
        b.stop();
        await b.pcmDrained; // stop frees a waiter
        await Future<void>.delayed(Duration.zero);
        expect(calls.last.method, 'release');
      },
    );

    test('another rate waits until the sink has played out', () async {
      final b = DefaultAudioBackend(tail: Duration.zero);
      await b.feedPcm(Uint8List(4), 24000);
      var fed = false;
      unawaited(b.feedPcm(Uint8List(4), 48000).then((_) => fed = true));
      await Future<void>.delayed(const Duration(milliseconds: 20));
      expect(fed, isFalse);
      expect(calls.where((c) => c.method == 'setup').length, 1);
      await drained();
      await Future<void>.delayed(const Duration(milliseconds: 20));
      expect(fed, isTrue);
      expect(calls.where((c) => c.method == 'setup').length, 2);
      b.stop();
    });

    test(
      'a stop that lands while the sink is being set up feeds nothing',
      () async {
        final setupGate = Completer<void>();
        messenger.setMockMethodCallHandler(channel, (c) async {
          calls.add(c);
          if (c.method == 'setup') await setupGate.future;
          return true;
        });
        final b = DefaultAudioBackend(tail: Duration.zero);
        final run = b.feedPcm(Uint8List(4800), 24000);
        await Future<void>.delayed(const Duration(milliseconds: 20));
        b.stop(); // barge-in
        setupGate.complete();
        await run;
        expect(calls.where((c) => c.method == 'feed'), isEmpty);
        // the next utterance sets up again and plays
        await b.feedPcm(Uint8List(4), 24000);
        expect(calls.where((c) => c.method == 'setup').length, 2);
        expect(calls.where((c) => c.method == 'feed').length, 1);
        b.stop();
      },
    );

    test('each run (not each chunk) re-activates the audio session', () async {
      var activations = 0;
      final b = DefaultAudioBackend(
        tail: Duration.zero,
        activate: () async => activations++,
      );
      await b.feedPcm(Uint8List(4), 24000);
      await b.feedPcm(Uint8List(4), 24000);
      expect(activations, 1);
      await drained();
      await Future<void>.delayed(const Duration(milliseconds: 20));
      await b.feedPcm(Uint8List(4), 24000);
      expect(activations, 2);
      b.stop();
    });

    test('a native failure reaches the caller', () async {
      messenger.setMockMethodCallHandler(channel, (c) async {
        if (c.method == 'setup') {
          throw PlatformException(code: 'AudioTrackError');
        }
        return true;
      });
      final b = DefaultAudioBackend(tail: Duration.zero);
      await expectLater(
        b.feedPcm(Uint8List(2), 24000),
        throwsA(isA<PlatformException>()),
      );
    });
  });

  group('Loudness', () {
    Uint8List pcm(List<int> s) => Uint8List.view(Int16List.fromList(s).buffer);
    List<int> samples(Uint8List b) => Int16List.view(
      b.buffer,
      b.offsetInBytes,
      b.lengthInBytes ~/ 2,
    ).toList();

    test('quiet speech is made louder by the make-up gain', () {
      final out = samples(Loudness().apply(pcm([0, 4000, -4000, 2000])));
      expect(out, [0, 12960, -12960, 6480]);
    });

    test('loud peaks never pass the ceiling (no clipping)', () {
      final l = Loudness();
      final out = samples(l.apply(pcm([30000, -32768, 32767, 20000])));
      for (final s in out) {
        expect(s.abs(), lessThanOrEqualTo(Loudness.ceiling));
      }
    });

    test('the limiter lets go again after a peak', () {
      final l = Loudness();
      l.apply(pcm([32767])); // a peak
      final quiet = samples(l.apply(pcm(List.filled(24000, 4000))));
      expect(quiet.last, 12960); // one second later: full gain again
    });

    test('AudioOut feeds the processed samples', () async {
      final b = FakeAudioBackend();
      final out = AudioOut(backend: b, bufferMs: 0);
      addTearDown(out.dispose);
      out.handle(PcmChunk(pcm([4000]), sampleRate: 24000));
      await Future<void>.delayed(Duration.zero);
      expect(samples(b.pcmPlayed.single), [12960]);
    });
  });

  group('AudioOut', () {
    test('a failing run is reported once until a run succeeds', () async {
      final errors = <String>[];
      final b = FakeAudioBackend()..failure = StateError('boom');
      final out = AudioOut(backend: b, bufferMs: 0, onError: errors.add);
      addTearDown(out.dispose);
      out.handle(PcmChunk(Uint8List.fromList([1, 2]), sampleRate: 24000));
      await Future<void>.delayed(const Duration(milliseconds: 20));
      out.handle(
        PcmChunk(Uint8List.fromList([3, 4]), sampleRate: 24000, gapMs: 1),
      );
      await Future<void>.delayed(const Duration(milliseconds: 20));
      expect(errors, hasLength(1));
      expect(errors.single, contains('boom'));
      b.failure = null;
      out.handle(
        PcmChunk(Uint8List.fromList([5, 6]), sampleRate: 24000, gapMs: 1),
      );
      await Future<void>.delayed(const Duration(milliseconds: 20));
      b.finishCurrent();
      await Future<void>.delayed(const Duration(milliseconds: 20));
      b.failure = StateError('again');
      out.handle(PcmChunk(Uint8List.fromList([7, 8]), sampleRate: 24000));
      await Future<void>.delayed(const Duration(milliseconds: 20));
      expect(errors, hasLength(2));
    });

    test('an encoded failure and a timeout are reported too', () async {
      final errors = <String>[];
      final b = FakeAudioBackend()..failure = StateError('no codec');
      final out = AudioOut(
        backend: b,
        bufferMs: 0,
        margin: const Duration(milliseconds: 10),
        onError: errors.add,
      );
      addTearDown(out.dispose);
      out.handle(EncodedWhole(Uint8List.fromList([1, 2, 3])));
      await Future<void>.delayed(const Duration(milliseconds: 20));
      expect(errors.single, contains('no codec'));
      final b2 = FakeAudioBackend();
      final out2 = AudioOut(
        backend: b2,
        bufferMs: 0,
        margin: const Duration(milliseconds: 10),
        onError: errors.add,
      );
      addTearDown(out2.dispose);
      out2.handle(EncodedWhole(Uint8List.fromList([1, 2, 3])));
      await Future<void>.delayed(const Duration(milliseconds: 60));
      expect(errors.last, contains('không phát xong'));
    });

    late FakeAudioBackend backend;
    late AudioOut audioOut;

    setUp(() {
      backend = FakeAudioBackend();
      audioOut = AudioOut(backend: backend, bufferMs: 0);
    });

    tearDown(() {
      audioOut.dispose();
    });

    test('dispose releases the backend player', () {
      final b = FakeAudioBackend();
      AudioOut(backend: b, bufferMs: 0).dispose();
      expect(b.disposeCalls, 1);
    });

    test('a cue that ends during speech re-activates the session once, an idle one not', () async {
      audioOut.reactivate(); // idle
      await Future<void>.delayed(Duration.zero);
      expect(backend.reactivations, 0);
      audioOut.handle(PcmChunk(Uint8List.fromList([1, 2]), sampleRate: 24000));
      await Future<void>.delayed(Duration.zero);
      expect(audioOut.playing.value, isTrue);
      audioOut.reactivate();
      await Future<void>.delayed(Duration.zero);
      expect(backend.reactivations, 1);
    });

    test('stop clears pcm queue', () async {
      audioOut.handle(PcmChunk(Uint8List.fromList([1, 2]), sampleRate: 24000));
      audioOut.handle(PcmChunk(Uint8List.fromList([3, 4]), sampleRate: 24000));
      audioOut.handle(PcmChunk(Uint8List.fromList([5, 6]), sampleRate: 24000));
      await Future<void>.delayed(Duration.zero);
      expect(audioOut.playing.value, isTrue);

      audioOut.stop();

      expect(audioOut.playing.value, isFalse);
      expect(backend.stopCalls, greaterThanOrEqualTo(1));
      expect(audioOut.queueLength, 0);
    });

    test('StopAudio event clears queue and stops playing', () async {
      audioOut.handle(PcmChunk(Uint8List.fromList([1, 2]), sampleRate: 24000));
      await Future<void>.delayed(Duration.zero);
      expect(audioOut.playing.value, isTrue);

      audioOut.handle(const StopAudio());
      expect(audioOut.playing.value, isFalse);
      expect(audioOut.queueLength, 0);
    });

    test('encoded chunks assemble on EncodedEnd and play', () async {
      audioOut.handle(EncodedChunk(Uint8List.fromList([1, 2])));
      audioOut.handle(EncodedChunk(Uint8List.fromList([3, 4])));
      expect(backend.encodedPlayed.isEmpty, isTrue);

      audioOut.handle(const EncodedEnd());
      await Future<void>.delayed(Duration.zero);

      expect(backend.encodedPlayed.length, 1);
      expect(backend.encodedPlayed.first, Uint8List.fromList([1, 2, 3, 4]));
      expect(audioOut.playing.value, isTrue);
    });

    test('EncodedWhole plays immediately', () async {
      audioOut.handle(EncodedWhole(Uint8List.fromList([9, 8, 7])));
      await Future<void>.delayed(Duration.zero);

      expect(backend.encodedPlayed.length, 1);
      expect(backend.encodedPlayed.first, Uint8List.fromList([9, 8, 7]));
      expect(audioOut.playing.value, isTrue);
    });

    test('every chunk goes to the sink as it arrives, not after the one before has played (web: gapless timeline)', () async {
      audioOut.handle(PcmChunk(Uint8List.fromList([1, 2]), sampleRate: 24000));
      await Future<void>.delayed(Duration.zero);
      audioOut.handle(PcmChunk(Uint8List.fromList([3, 4]), sampleRate: 24000));
      audioOut.handle(PcmChunk(Uint8List.fromList([5, 6]), sampleRate: 24000));
      await Future<void>.delayed(Duration.zero);
      expect(backend.pcmPlayed.map((b) => b.length), [2, 2, 2]);
      expect(audioOut.playing.value, isTrue);
      backend.finishCurrent(); // the sink plays out
      await Future<void>.delayed(const Duration(milliseconds: 20));
      expect(audioOut.playing.value, isFalse);
    });

    test('a sentence gap is silence fed in the same run', () async {
      audioOut.handle(PcmChunk(Uint8List.fromList([1, 2]), sampleRate: 24000));
      audioOut.handle(
        PcmChunk(Uint8List.fromList([5, 6]), sampleRate: 24000, gapMs: 10),
      );
      await Future<void>.delayed(const Duration(milliseconds: 20));
      expect(backend.pcmPlayed.length, 2);
      final second = backend.pcmPlayed.last;
      expect(second.length, 480 + 2); // 10 ms at 24 kHz, 16-bit
      expect(second.sublist(0, 480).every((b) => b == 0), isTrue);
    });

    test('only the first chunk of a run waits for the start buffer', () async {
      final out = AudioOut(backend: backend, bufferMs: 40);
      addTearDown(out.dispose);
      out.handle(PcmChunk(Uint8List.fromList([1, 2]), sampleRate: 24000));
      out.handle(PcmChunk(Uint8List.fromList([3, 4]), sampleRate: 24000));
      await Future<void>.delayed(const Duration(milliseconds: 10));
      expect(backend.pcmPlayed, isEmpty);
      expect(out.playing.value, isTrue);
      await Future<void>.delayed(const Duration(milliseconds: 60));
      expect(backend.pcmPlayed.length, 2);
    });

    test(
      'a long answer that keeps streaming is not cut by the stuck-sink guard',
      () async {
        final errors = <String>[];
        final out = AudioOut(
          backend: backend,
          bufferMs: 0,
          margin: const Duration(milliseconds: 40),
          onError: errors.add,
        );
        addTearDown(out.dispose);
        // 10 ms chunks every 30 ms for ~240 ms: far past the first chunk + margin, sink never empty
        for (var i = 0; i < 8; i++) {
          out.handle(PcmChunk(Uint8List(480), sampleRate: 24000));
          await Future<void>.delayed(const Duration(milliseconds: 30));
        }
        expect(errors, isEmpty);
        expect(backend.stopCalls, 0);
        expect(out.playing.value, isTrue);
        backend.finishCurrent();
        await Future<void>.delayed(const Duration(milliseconds: 20));
        expect(out.playing.value, isFalse);
      },
    );

    test(
      'a sink that never plays out is stopped: not stuck in speaking',
      () async {
        final errors = <String>[];
        final out = AudioOut(
          backend: backend,
          bufferMs: 0,
          margin: const Duration(milliseconds: 20),
          onError: errors.add,
        );
        addTearDown(out.dispose);
        out.handle(PcmChunk(Uint8List.fromList([1, 2]), sampleRate: 24000));
        await Future<void>.delayed(Duration.zero);
        expect(out.playing.value, isTrue);
        await Future<void>.delayed(const Duration(milliseconds: 80));
        expect(out.playing.value, isFalse);
        expect(errors.single, contains('không phát xong'));
        out.handle(PcmChunk(Uint8List.fromList([3, 4]), sampleRate: 24000));
        await Future<void>.delayed(Duration.zero);
        expect(backend.pcmPlayed.length, 2); // the next sentence still plays
      },
    );
  });
}
