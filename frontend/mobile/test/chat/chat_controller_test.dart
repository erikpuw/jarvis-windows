import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:jarvis_mobile/chat/chat_controller.dart';
import 'package:jarvis_mobile/chat/chat_models.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:jarvis_mobile/net/jarvis_socket.dart' show SocketState;

import 'fakes.dart';

void main() {
  late FakeSocket s;
  late FakeApi api;
  late ChatController c;
  late List<AudioEvent> audio;

  Future<void> pump(Map<String, dynamic> m) async {
    s.incoming.add(m);
    await Future<void>.delayed(Duration.zero);
  }

  setUp(() {
    s = FakeSocket();
    api = FakeApi();
    c = ChatController(s, api);
    audio = [];
    c.audio.listen(audio.add);
  });

  test('stream chunks build one answer', () async {
    await pump({'type': 'stream_start'});
    await pump({'type': 'text_chunk', 'text': 'Xin '});
    await pump({'type': 'text_chunk', 'text': 'chào'});
    expect((c.items.single as AssistantMsg).streaming, isTrue);
    await pump({'type': 'stream_end'});
    final m = c.items.single as AssistantMsg;
    expect(m.text, 'Xin chào');
    expect(m.streaming, isFalse);
  });

  test('cancel resets to idle without stream_end', () async {
    await pump({'type': 'status', 'state': 'thinking'});
    await pump({'type': 'stream_start'});
    await pump({'type': 'text_chunk', 'text': 'a'});
    c.cancel();
    await Future<void>.delayed(Duration.zero);
    expect(c.state, JState.idle);
    expect(s.sent.last, {'type': 'cancel'});
    expect(audio.whereType<StopAudio>(), isNotEmpty);
    expect((c.items.single as AssistantMsg).streaming, isFalse);
  });

  test('cancel drops an empty streaming bubble', () async {
    await pump({'type': 'stream_start'});
    c.cancel();
    expect(c.items, isEmpty);
  });

  test('send while disconnected shows error', () async {
    s.st.value = SocketState.closed;
    await c.sendText('hi');
    expect(c.error, isNotNull);
    expect(c.items.whereType<UserMsg>(), isEmpty);
    expect(c.state, JState.idle);
  });

  test('send while open goes thinking', () async {
    await c.sendText('hi');
    expect(s.sent.single, {
      'type': 'transcript',
      'text': 'hi',
      'isFinal': true,
    });
    expect(c.state, JState.thinking);
    expect((c.items.single as UserMsg).text, 'hi');
  });

  test('status packet drives status text', () async {
    expect(c.statusText, 'Sẵn sàng');
    await pump({'type': 'status', 'state': 'thinking'});
    expect(c.statusText, 'Đang nghĩ…');
    await pump({
      'type': 'status',
      'state': 'working',
      'message': 'Công cụ: Tra giá',
    });
    expect(c.state, JState.working);
    expect(c.statusText, 'Công cụ: Tra giá');
    await pump({'type': 'status', 'state': 'speaking', 'source': 'tts'});
    expect(c.statusText, 'Đang đọc…');
    await pump({'type': 'status', 'state': 'idle'});
    expect(c.state, JState.speaking); // LLM idle never covers the reading label
    await pump({'type': 'status', 'state': 'idle', 'source': 'tts'});
    expect(c.state, JState.idle);
  });

  test('work status during preparing speech is shown after it', () async {
    await pump({'type': 'status', 'state': 'speaking', 'source': 'tts'});
    await pump({'type': 'status', 'state': 'working', 'message': 'x'});
    expect(c.state, JState.speaking);
    await pump({'type': 'status', 'state': 'idle', 'source': 'tts'});
    expect(c.state, JState.working);
    expect(c.statusText, 'x');
  });

  test('welcome hides after first message', () async {
    expect(c.welcomeVisible, isTrue);
    await pump({
      'type': 'welcome',
      'greeting': 'Chào',
      'tools': ['a'],
      'weather': {'desc': 'nắng', 'temp': 30, 'kind': 'clear', 'place': 'HN'},
    });
    expect(c.welcome!.greeting, 'Chào');
    expect(c.welcome!.weather!.temp, 30);
    expect(c.welcomeVisible, isTrue);
    await c.sendText('hi');
    expect(c.welcomeVisible, isFalse);
  });

  test('tts off drops audio packets', () async {
    c.setTts(false);
    expect(s.sent.last, {'type': 'toggle_tts', 'enabled': false});
    await pump({
      'type': 'pcm_chunk',
      'data': base64Encode([1, 2]),
    });
    await pump({
      'type': 'audio_chunk',
      'data': base64Encode([1, 2]),
    });
    await pump({'type': 'audio_chunk_end'});
    await pump({
      'type': 'audio',
      'data': base64Encode([1]),
    });
    expect(audio.whereType<PcmChunk>(), isEmpty);
    expect(audio.whereType<EncodedChunk>(), isEmpty);
    expect(audio.whereType<EncodedEnd>(), isEmpty);
    expect(audio.whereType<EncodedWhole>(), isEmpty);
    c.setTts(true);
    await pump({
      'type': 'pcm_chunk',
      'data': base64Encode([1, 2]),
      'sample_rate': 24000,
      'gap_ms': 5,
    });
    final p = audio.whereType<PcmChunk>().single;
    expect(
      [p.bytes.toList(), p.sampleRate, p.gapMs],
      [
        [1, 2],
        24000,
        5,
      ],
    );
  });

  test('encoded audio packets map to events', () async {
    await pump({
      'type': 'audio_chunk',
      'data': base64Encode([3]),
    });
    await pump({'type': 'audio_chunk_end'});
    await pump({
      'type': 'audio',
      'data': base64Encode([4]),
    });
    expect(audio.map((e) => e.runtimeType), [
      EncodedChunk,
      EncodedEnd,
      EncodedWhole,
    ]);
  });

  test('upload then transcript with attachmentId', () async {
    await c.sendText('look', filePath: '/tmp/a.png');
    expect(api.uploads.single, '/api/upload|/tmp/a.png');
    expect(s.sent.single, {
      'type': 'transcript',
      'text': 'look',
      'attachmentId': 'att1',
      'isFinal': true,
    });
    expect((c.items.single as UserMsg).attachmentName, 'a.png');
  });

  test('upload failure sets error and returns to idle', () async {
    api.result = {'success': false, 'error': 'too big'};
    await c.sendText('look', filePath: '/tmp/a.png');
    expect(c.error, 'Upload failed: too big');
    expect(c.state, JState.idle);
    expect(s.sent, isEmpty);
  });

  test('send while busy is queued and sent when the turn ends', () async {
    await c.sendText('one');
    await pump({'type': 'status', 'state': 'thinking'});
    await c.sendText('two');
    expect(s.sent.length, 1);
    expect((c.items.last as UserMsg).pending, isTrue);
    await pump({'type': 'status', 'state': 'idle'});
    expect(s.sent.last, {'type': 'transcript', 'text': 'two', 'isFinal': true});
    expect((c.items.last as UserMsg).pending, isFalse);
    expect(c.state, JState.thinking);
  });

  test(
    'identical user message twice in a row adds one bubble but sends both',
    () async {
      await c.sendText('hi');
      await pump({'type': 'status', 'state': 'idle'});
      await c.sendText('hi');
      expect(c.items.whereType<UserMsg>().length, 1);
      expect(s.sent.length, 2);
    },
  );

  test('identical user message after an answer is a new bubble', () async {
    await c.sendText('hi');
    await pump({'type': 'text', 'text': 'chào'});
    await pump({'type': 'status', 'state': 'idle'});
    await c.sendText('hi');
    expect(c.items.whereType<UserMsg>().length, 2);
  });

  test('output files arriving in one tick keep their own cards', () async {
    for (var i = 0; i < 20; i++) {
      s.incoming.add({
        'type': 'output_file',
        'kind': 'image',
        'url': '/api/outputs/$i',
        'name': '$i.png',
      });
    }
    await Future<void>.delayed(Duration.zero);
    expect(c.items.length, 20);
  });

  test('image and file packets become items', () async {
    await pump({
      'type': 'output_file',
      'kind': 'image',
      'url': '/api/outputs/t1',
      'name': 'x.png',
      'download_url': '/api/outputs/t1?download=1',
    });
    await pump({
      'type': 'output_file',
      'kind': 'document',
      'url': '/api/outputs/t2',
      'name': 'r.docx',
      'ext': 'docx',
      'label': 'Word',
      'size': 2048,
      'download_url': '/api/outputs/t2?download=1',
    });
    final i = c.items[0] as ImageMsg;
    expect(
      [i.url, i.caption, i.downloadUrl],
      ['/api/outputs/t1', 'x.png', '/api/outputs/t1?download=1'],
    );
    final f = c.items[1] as FileMsg;
    expect(
      [f.name, f.url, f.kind, f.size],
      ['r.docx', '/api/outputs/t2', 'document', 2048],
    );
    await pump({'type': 'screenshot_processed', 'url': '/api/shot.png'});
    expect((c.items[2] as ImageMsg).url, startsWith('/api/shot.png?t='));
  });

  test(
    'empty assistant bubble is dropped when a text packet arrives',
    () async {
      await pump({'type': 'stream_start'});
      await pump({'type': 'text', 'text': 'lỗi'});
      expect(c.items.length, 1);
      expect((c.items.single as AssistantMsg).text, 'lỗi');
    },
  );

  test('flow steps, ask, media', () async {
    await pump({
      'type': 'flow_step',
      'step': {'id': 1, 'label': 'a', 'status': 'active'},
    });
    await pump({
      'type': 'flow_step',
      'step': {'id': 2, 'label': 'b', 'status': 'active'},
    });
    await pump({
      'type': 'flow_step',
      'step': {'id': 1, 'label': 'a', 'status': 'done'},
    });
    expect(c.flow.steps.map((e) => e.status), ['done', 'active']);
    await pump({'type': 'stream_start'});
    expect(c.flow.steps, isEmpty);

    await pump({
      'type': 'interactive',
      'card': {'id': 'q', 'type': 'approve'},
    });
    expect(c.ask!.id, 'q');
    expect(c.items.whereType<ImageMsg>(), isEmpty);
    c.answerAsk({
      'type': 'interactive_response',
      'cardId': 'q',
      'action': 'approve',
    });
    expect(c.ask, isNull);
    expect(s.sent.last['cardId'], 'q');

    await pump({
      'type': 'media_open',
      'query': 'q',
      'embed_url': 'https://e/x',
      'title': 'T',
    });
    expect(c.media!.embedUrl, 'https://e/x');
    expect(s.sent.last, {'type': 'media_state', 'active': true});
    c.mediaState(false);
    expect(s.sent.last, {'type': 'media_state', 'active': false});
  });

  group('playback (setPlaying)', () {
    test('sound out moves the status to speaking, its end to idle', () async {
      await pump({'type': 'status', 'state': 'speaking', 'source': 'tts'});
      c.setPlaying(true);
      expect(c.state, JState.speaking);
      await pump({'type': 'status', 'state': 'idle', 'source': 'tts'});
      expect(c.state, JState.speaking, reason: 'tts idle while playing');
      c.setPlaying(false);
      expect(c.state, JState.idle);
    });

    test('a pause between sentences keeps the reading label', () async {
      await pump({'type': 'status', 'state': 'speaking', 'source': 'tts'});
      c.setPlaying(true);
      c.setPlaying(false);
      expect(c.state, JState.speaking, reason: 'tts has not said idle yet');
      await pump({'type': 'status', 'state': 'idle', 'source': 'tts'});
      expect(c.state, JState.idle);
    });

    test('playback end sends the queued voice turn', () async {
      c.setPlaying(true);
      await c.sendText('câu hai');
      expect(s.sent.where((m) => m['type'] == 'transcript'), isEmpty);
      c.setPlaying(false);
      expect(s.sent.last['text'], 'câu hai');
      expect(c.state, JState.thinking);
    });
  });

  group('mic (setListening)', () {
    test('mic on turns idle into listening, off turns it back', () {
      c.setListening(true);
      expect(c.state, JState.listening);
      expect(c.statusText, 'Đang nghe…');
      expect(c.wantsMic, isTrue);
      c.setListening(false);
      expect(c.state, JState.idle);
      expect(c.statusText, 'Sẵn sàng');
      expect(c.wantsMic, isFalse);
    });

    test('with the mic on, every return to idle is listening again', () async {
      c.setListening(true);
      await pump({'type': 'status', 'state': 'thinking'});
      expect(c.wantsMic, isFalse); // the recogniser rests while JARVIS works
      await pump({'type': 'status', 'state': 'idle'});
      expect(c.state, JState.listening);
      c.setPlaying(true);
      expect(c.state, JState.speaking);
      c.setPlaying(false);
      expect(c.state, JState.listening);
    });

    test('a voice turn sends and moves to thinking', () async {
      c.setListening(true);
      c.sendTranscript('bật đèn');
      await Future<void>.delayed(Duration.zero);
      expect(s.sent.last['text'], 'bật đèn');
      expect(c.state, JState.thinking);
    });

    test('speaking over the sound cancels it and sends the new turn', () async {
      c.setListening(true);
      c.setPlaying(true);
      c.sendTranscript('dừng lại, bật đèn');
      await Future<void>.delayed(Duration.zero);
      expect(
        s.sent.map((m) => m['type']),
        containsAllInOrder(['cancel', 'transcript']),
      );
      expect(audio.whereType<StopAudio>(), isNotEmpty);
      expect(c.state, JState.thinking);
    });
  });

  test('tts off is sent again every time the socket opens', () async {
    c.setTts(false);
    s.sent.clear();
    s.st.value = SocketState.closed;
    s.st.value = SocketState.open;
    expect(s.sent, [
      {'type': 'toggle_tts', 'enabled': false},
    ]);
    c.setTts(true);
    s.sent.clear();
    s.st.value = SocketState.closed;
    s.st.value = SocketState.open;
    expect(s.sent, isEmpty);
  });

  test('tts off survives a restart: it is stored and read back', () async {
    SharedPreferences.setMockInitialValues({});
    c.setTts(false);
    await Future<void>.delayed(Duration.zero);
    expect(await ChatController.loadTtsEnabled(), isFalse);
    c.setTts(true);
    await Future<void>.delayed(Duration.zero);
    expect(await ChatController.loadTtsEnabled(), isTrue);
  });

  test('every error bumps errorSeq, even the same text twice', () {
    final before = c.errorSeq;
    c.reportError('x');
    c.reportError('x');
    expect(c.errorSeq, before + 2);
  });
}
