import 'dart:async';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jarvis_mobile/chat/morph_icon.dart';
import 'package:jarvis_mobile/net/api_client.dart';
import 'package:jarvis_mobile/net/jarvis_socket.dart';
import 'package:jarvis_mobile/net/server_config.dart';
import 'package:jarvis_mobile/voice/audio_out.dart';
import 'package:jarvis_mobile/voice/voice_input.dart';
import 'package:record/record.dart';

class FakeSocket extends JarvisSocket {
  FakeSocket() : super(ServerConfig(), device: 'test');
  final incoming = StreamController<Map<String, dynamic>>.broadcast();
  final sent = <Map<String, dynamic>>[];
  final st = ValueNotifier(SocketState.open);
  int connects = 0;
  int reconnects = 0;
  @override
  void connect() => connects++;
  @override
  void reconnectNow() => reconnects++;
  @override
  void forceReconnect({bool resetSession = false}) => reconnects++;
  @override
  void disconnect() => st.value = SocketState.closed;
  @override
  Stream<Map<String, dynamic>> get messages => incoming.stream;
  @override
  ValueListenable<SocketState> get state => st;
  @override
  bool send(Map<String, dynamic> msg) {
    if (st.value != SocketState.open) return false;
    sent.add(msg);
    return true;
  }
}

class FakeApi extends ApiClient {
  FakeApi() : super(ServerConfig());
  Map<String, dynamic> result = {'success': true, 'attachment_id': 'att1'};
  Object? failure;
  final uploads = <String>[];
  final responses = <String, Object>{};
  @override
  Future<T> get<T>(String path) async =>
      (responses[path] ?? <String, dynamic>{}) as T;

  @override
  Future<Map<String, dynamic>> upload(
    String path,
    String filePath, {
    Map<String, String> fields = const {},
  }) async {
    uploads.add('$path|$filePath');
    if (failure != null) throw failure!;
    return result;
  }
}

class FakeAudioBackend implements AudioBackend {
  final List<Uint8List> pcmPlayed = [];
  final List<Uint8List> encodedPlayed = [];
  int stopCalls = 0;
  int reactivations = 0;
  int disposeCalls = 0;

  @override
  Future<void> reactivate() async => reactivations++;
  Completer<void>? playCompleter;
  Object? failure; // thrown by the next play

  @override
  void dispose() => disposeCalls++;

  Completer<void>? _drain;

  @override
  Future<void> feedPcm(Uint8List bytes, int sampleRate) async {
    pcmPlayed.add(bytes);
    if (failure != null) throw failure!;
    if (_drain == null || _drain!.isCompleted) _drain = Completer<void>();
  }

  @override
  Future<void> get pcmDrained => _drain?.future ?? Future<void>.value();

  @override
  Future<void> playEncoded(Uint8List bytes) async {
    encodedPlayed.add(bytes);
    if (failure != null) throw failure!;
    playCompleter = Completer<void>();
    await playCompleter!.future;
  }

  @override
  void stop() {
    stopCalls++;
    finishCurrent();
  }

  /// The encoded player ends, or the PCM sink plays out everything fed so far.
  void finishCurrent() {
    if (playCompleter != null && !playCompleter!.isCompleted) {
      playCompleter!.complete();
    }
    if (_drain != null && !_drain!.isCompleted) _drain!.complete();
  }
}

class FakeSpeechBackend implements SpeechBackend {
  bool initSuccess = true;
  List<String> mockLocales = ['vi_VN', 'en_US'];
  void Function(String words, bool isFinal)? resultCb;
  @override
  bool isListening = false;
  int stopCalls = 0;
  int listenCalls = 0;
  bool emitListening = true; // false: a start that never comes up
  void Function(String status)? statusCb;
  void Function(dynamic error)? errorCb;

  /// The recogniser ends its session ("done" after a result or its own timeout).
  void endSession() {
    isListening = false;
    statusCb?.call('done');
  }

  @override
  Future<bool> initialize({
    void Function(String status)? onStatus,
    void Function(dynamic error)? onError,
  }) async {
    statusCb = onStatus;
    errorCb = onError;
    return initSuccess;
  }

  @override
  Future<List<String>> locales() async => mockLocales;

  @override
  Future<void> listen({
    required void Function(String words, bool isFinal) onResult,
    String? localeId,
  }) async {
    isListening = true;
    listenCalls++;
    resultCb = onResult;
    if (emitListening) statusCb?.call('listening');
  }

  @override
  Future<void> stop() async {
    isListening = false;
    stopCalls++;
  }
}

class FakeRecordBackend implements RecordBackend {
  bool permitted = true;
  bool recording = false;
  String? targetPath;

  @override
  Future<bool> hasPermission() async => permitted;

  @override
  Future<void> start(RecordConfig config, {required String path}) async {
    recording = true;
    targetPath = path;
    // Create empty file at targetPath to simulate recorder
    File(path).writeAsStringSync('RIFF_FAKE_AUDIO');
  }

  @override
  Future<String?> stop() async {
    recording = false;
    return targetPath;
  }

  @override
  Future<bool> isRecording() async => recording;

  @override
  void dispose() {}
}

/// The MorphIcon showing [glyph] (matched by identity, as the morph engine does).
Finder byGlyph(MorphGlyph glyph) =>
    find.byWidgetPredicate((w) => w is MorphIcon && identical(w.icon, glyph));
