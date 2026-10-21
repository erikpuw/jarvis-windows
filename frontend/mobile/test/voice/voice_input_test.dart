import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:jarvis_mobile/net/api_client.dart';
import 'package:jarvis_mobile/net/server_config.dart';
import 'package:jarvis_mobile/voice/voice_input.dart';

import '../chat/fakes.dart';

void main() {
  group('VoiceInput', () {
    late Directory tempDir;

    setUp(() {
      tempDir = Directory.systemTemp.createTempSync('voice_input_test_');
    });

    tearDown(() {
      if (tempDir.existsSync()) {
        tempDir.deleteSync(recursive: true);
      }
    });

    test('a start cue when the user switches on, the end cue when the user switches off', () async {
      final speech = FakeSpeechBackend();
      final cues = <String>[];
      final input = VoiceInput(
        cue: (n) async => cues.add(n),
        onTranscript: (_) {},
        speechBackend: speech,
        recordBackend: FakeRecordBackend(),
        getTempDir: () async => tempDir,
      );
      await input.init();
      await input.start();
      expect(cues, ['mic_start']);
      speech.resultCb!('xin chào', false);
      expect(cues, ['mic_start']);
      speech.resultCb!('xin chào', true);
      speech
          .endSession(); // a session that ends after a result restarts silently
      await Future<void>.delayed(Duration.zero);
      expect(cues, ['mic_start']);
      await input.stop();
      await Future<void>.delayed(Duration.zero);
      expect(cues, ['mic_start', 'mic_end']);
      input.dispose();
    });

    test(
      'restarts play no cue and the start cue ends before listening starts',
      () async {
        final speech = FakeSpeechBackend();
        final gate = Completer<void>();
        final cues = <String>[];
        final input = VoiceInput(
          onTranscript: (_) {},
          speechBackend: speech,
          recordBackend: FakeRecordBackend(),
          getTempDir: () async => tempDir,
          cue: (n) {
            cues.add(n);
            return n == 'mic_start' ? gate.future : Future<void>.value();
          },
        );
        await input.init();
        final started = input.start();
        await Future<void>.delayed(Duration.zero);
        expect(cues, ['mic_start']);
        expect(speech.listenCalls, 0); // the cue is still playing
        gate.complete();
        await started;
        expect(speech.listenCalls, 1);
        // a result, the session ending, a pause and a resume: all restarts, no cue
        speech.resultCb!('a', false);
        speech.endSession();
        await Future<void>.delayed(Duration.zero);
        await input.pause();
        await input.resume();
        await Future<void>.delayed(Duration.zero);
        expect(cues, ['mic_start']);
        input.dispose();
      },
    );

    test('uses native STT when vi_VN locale is available', () async {
      final speech = FakeSpeechBackend();
      final record = FakeRecordBackend();
      final transcripts = <String>[];

      final input = VoiceInput(
        cue: (_) async {},
        onTranscript: transcripts.add,
        speechBackend: speech,
        recordBackend: record,
        getTempDir: () async => tempDir,
      );

      final ok = await input.init();
      expect(ok, isTrue);

      await input.start();
      expect(speech.isListening, isTrue);
      expect(input.listening.value, isTrue);

      // Speech recognizes text
      speech.resultCb!('Xin chào Jarvis', true);
      expect(transcripts, ['Xin chào Jarvis']);

      input.dispose();
    });

    test('keeps listening: a finished session starts the next one', () async {
      final speech = FakeSpeechBackend();
      final transcripts = <String>[];
      final input = VoiceInput(
        cue: (_) async {},
        onTranscript: transcripts.add,
        speechBackend: speech,
        recordBackend: FakeRecordBackend(),
      );
      await input.init();
      await input.start();
      for (final w in ['một', 'hai', 'ba']) {
        speech.resultCb!(w, true);
        speech.endSession();
        await Future<void>.delayed(Duration.zero);
      }
      expect(transcripts, ['một', 'hai', 'ba']);
      expect(speech.listenCalls, 4);
      expect(input.listening.value, isTrue);
      input.dispose();
    });

    test(
      'pause rests the recogniser, resume restarts, stop ends it for good',
      () async {
        final speech = FakeSpeechBackend();
        final input = VoiceInput(
          cue: (_) async {},
          onTranscript: (_) {},
          speechBackend: speech,
          recordBackend: FakeRecordBackend(),
        );
        await input.init();
        await input.start();
        await input.pause();
        expect(speech.isListening, isFalse);
        expect(input.listening.value, isFalse);
        speech.endSession(); // the report of the stopped session must not restart it
        await Future<void>.delayed(Duration.zero);
        expect(speech.listenCalls, 1);
        await input.resume();
        expect(speech.listenCalls, 2);
        await input.stop();
        speech.endSession();
        await Future<void>.delayed(Duration.zero);
        expect(speech.listenCalls, 2);
        input.dispose();
      },
    );

    test(
      'sessions that hear nothing are retried, then the mic gives up',
      () async {
        final speech = FakeSpeechBackend();
        var gaveUp = 0;
        final input = VoiceInput(
          cue: (_) async {},
          onTranscript: (_) {},
          onGiveUp: () => gaveUp++,
          speechBackend: speech,
          recordBackend: FakeRecordBackend(),
          retryMs: 1,
        );
        await input.init();
        await input.start();
        for (var i = 0; i < VoiceInput.maxEmpty + 1; i++) {
          speech.endSession();
          await Future<void>.delayed(const Duration(milliseconds: 10));
        }
        expect(gaveUp, 1);
        expect(speech.listenCalls, VoiceInput.maxEmpty + 1);
        input.dispose();
      },
    );

    test(
      'giving up plays the end cue once, a stop that was never on none',
      () async {
        final speech = FakeSpeechBackend();
        final cues = <String>[];
        final input = VoiceInput(
          cue: (n) async => cues.add(n),
          onTranscript: (_) {},
          speechBackend: speech,
          recordBackend: FakeRecordBackend(),
          retryMs: 1,
        );
        await input.init();
        await input.stop(); // never switched on
        await Future<void>.delayed(Duration.zero);
        expect(cues, isEmpty);
        await input.start();
        for (var i = 0; i < VoiceInput.maxEmpty + 1; i++) {
          speech.endSession();
          await Future<void>.delayed(const Duration(milliseconds: 10));
        }
        expect(cues, ['mic_start', 'mic_end']);
        input.dispose();
      },
    );

    test(
      'a duplicate done after a restart keeps the new session watched',
      () async {
        final speech = FakeSpeechBackend();
        final input = VoiceInput(
          cue: (_) async {},
          onTranscript: (_) {},
          speechBackend: speech,
          recordBackend: FakeRecordBackend(),
          retryMs: 20,
        );
        await input.init();
        await input.start(); // session A, listening
        speech.resultCb!('a', true);
        speech.emitListening = false; // session B never comes up
        speech.endSession(); // notListening: B starts
        expect(speech.listenCalls, 2);
        speech.endSession(); // done: the duplicate, must not clear B's watchdog
        await Future<void>.delayed(const Duration(milliseconds: 700));
        expect(
          speech.listenCalls,
          greaterThanOrEqualTo(3),
        ); // watchdog retried B
        input.dispose();
      },
    );

    test(
      'a start that never reports listening is retried, then given up',
      () async {
        final speech = FakeSpeechBackend()..emitListening = false;
        var gaveUp = 0;
        final input = VoiceInput(
          cue: (_) async {},
          onTranscript: (_) {},
          onGiveUp: () => gaveUp++,
          speechBackend: speech,
          recordBackend: FakeRecordBackend(),
          retryMs: 1,
        );
        await input.init();
        await input.start();
        for (var i = 0; i < VoiceInput.maxEmpty + 1; i++) {
          speech.endSession(); // the session ends without ever listening
          await Future<void>.delayed(const Duration(milliseconds: 15));
        }
        expect(gaveUp, 1);
        expect(speech.listenCalls, VoiceInput.maxEmpty + 1);
        input.dispose();
      },
    );

    test('falls back to Whisper upload when vi_VN locale missing', () async {
      final speech = FakeSpeechBackend()..mockLocales = ['en_US'];
      final record = FakeRecordBackend();
      final transcripts = <String>[];

      final mockClient = MockClient((req) async {
        if (req.url.path == '/api/stt') {
          return http.Response(
            jsonEncode({'success': true, 'text': 'Bật đèn phòng khách'}),
            200,
            headers: {'content-type': 'application/json'},
          );
        }
        return http.Response('Not Found', 404);
      });

      final apiClient = ApiClient(ServerConfig(), client: mockClient);

      final input = VoiceInput(
        cue: (_) async {},
        onTranscript: transcripts.add,
        apiClient: apiClient,
        speechBackend: speech,
        recordBackend: record,
        getTempDir: () async => tempDir,
      );

      await input.init();
      await input.start();

      expect(record.recording, isTrue);
      expect(input.listening.value, isTrue);

      await input.stop();

      expect(record.recording, isFalse);
      expect(transcripts, ['Bật đèn phòng khách']);
      expect(input.listening.value, isFalse);

      input.dispose();
    });

    test('a denied permission gives up: message, end cue, onGiveUp', () async {
      for (final native in [true, false]) {
        final speech = FakeSpeechBackend();
        final record = FakeRecordBackend()..permitted = false;
        if (!native) speech.mockLocales = ['en_US'];
        final cues = <String>[];
        final errors = <String>[];
        var gaveUp = 0;
        final input = VoiceInput(
          cue: (n) async => cues.add(n),
          onTranscript: (_) {},
          onError: errors.add,
          onGiveUp: () => gaveUp++,
          speechBackend: speech,
          recordBackend: record,
          getTempDir: () async => tempDir,
        );
        await input.init();
        await input.start();
        if (native) speech.errorCb!('error_permission');
        await Future<void>.delayed(Duration.zero);
        expect(gaveUp, 1, reason: native ? 'native' : 'whisper');
        expect(errors.single, contains('Microphone access denied'));
        expect(cues, ['mic_start', 'mic_end']);
        input.dispose();
      }
    });
  });
}
