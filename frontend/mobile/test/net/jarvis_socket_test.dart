import 'dart:async';
import 'dart:convert';

import 'package:fake_async/fake_async.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:jarvis_mobile/net/jarvis_socket.dart';
import 'package:jarvis_mobile/net/server_config.dart';
import 'package:stream_channel/stream_channel.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

class FakeSink implements WebSocketSink {
  FakeSink(this.sent, this.onClose);
  final List<String> sent;
  final void Function() onClose;
  @override
  void add(dynamic data) => sent.add(data as String);
  @override
  void addError(Object error, [StackTrace? st]) {}
  @override
  Future addStream(Stream stream) async {}
  @override
  Future close([int? closeCode, String? closeReason]) async => onClose();
  @override
  Future get done => Future.value();
}

class FakeChannel extends StreamChannelMixin implements WebSocketChannel {
  final incoming = StreamController<dynamic>();
  final sent = <String>[];
  late final FakeSink _sink = FakeSink(sent, () => incoming.close());
  @override
  Stream get stream => incoming.stream;
  @override
  WebSocketSink get sink => _sink;
  @override
  Future<void> get ready => Future.value();
  @override
  String? get protocol => null;
  int? code; // what the server closed with (set before closing incoming)
  @override
  int? get closeCode => code;
  @override
  String? get closeReason => null;
}

void main() {
  late List<Uri> uris;
  late List<FakeChannel> channels;
  late JarvisSocket s;

  JarvisSocket make() {
    uris = [];
    channels = [];
    return JarvisSocket(
      ServerConfig(),
      device: 'ios',
      connector: (u) {
        uris.add(u);
        final c = FakeChannel();
        channels.add(c);
        return c;
      },
    );
  }

  test('session id format', () {
    s = make();
    expect(RegExp(r'^web-[0-9a-f]{8}$').hasMatch(s.sessionId), true);
    s.dispose();
  });

  test('backoff caps at 30s', () {
    var d = const Duration(seconds: 1);
    for (var i = 0; i < 10; i++) {
      d = JarvisSocket.nextDelay(d);
    }
    expect(d, const Duration(seconds: 30));
  });

  test('reconnect keeps session and single socket', () {
    fakeAsync((fa) {
      s = make();
      s.connect();
      s.connect();
      expect(channels.length, 1);
      fa.flushMicrotasks();
      expect(s.state.value, SocketState.open);
      channels[0].incoming.close();
      fa.flushMicrotasks();
      expect(s.state.value, SocketState.closed);
      fa.elapse(const Duration(milliseconds: 999));
      expect(channels.length, 1);
      fa.elapse(const Duration(milliseconds: 2));
      expect(channels.length, 2);
      expect(uris[1].queryParameters['session'], s.sessionId);
      expect(uris[0].queryParameters['session'], s.sessionId);
      expect(uris[1].queryParameters['device'], 'ios');
      s.connect();
      expect(channels.length, 2);
      s.dispose();
    });
  });

  test('pong is not emitted', () {
    fakeAsync((fa) {
      s = make();
      final got = <Map<String, dynamic>>[];
      s.messages.listen(got.add);
      s.connect();
      fa.flushMicrotasks();
      channels[0].incoming.add('{"type":"pong"}');
      channels[0].incoming.add('not json');
      channels[0].incoming.add('[1]');
      channels[0].incoming.add('{"type":"x"}');
      fa.flushMicrotasks();
      expect(got, [
        {'type': 'x'},
      ]);
      s.dispose();
    });
  });

  test('send returns false when closed, true when open', () {
    fakeAsync((fa) {
      s = make();
      expect(s.send({'type': 'a'}), false);
      s.connect();
      expect(s.send({'type': 'a'}), false);
      fa.flushMicrotasks();
      expect(s.send({'type': 'a'}), true);
      expect(channels[0].sent, [
        jsonEncode({'type': 'a'}),
      ]);
      s.dispose();
    });
  });

  test('heartbeat pings every 20s', () {
    fakeAsync((fa) {
      s = make();
      s.connect();
      fa.flushMicrotasks();
      fa.elapse(const Duration(seconds: 20));
      expect(channels[0].sent, ['{"type":"ping"}']);
      s.dispose();
    });
  });

  test('stale socket reconnects after 60s silence', () {
    fakeAsync((fa) {
      s = make();
      s.connect();
      fa.flushMicrotasks();
      fa.elapse(const Duration(seconds: 80));
      fa.flushMicrotasks();
      expect(s.state.value, SocketState.closed);
      fa.elapse(const Duration(seconds: 1));
      expect(channels.length, 2);
      s.dispose();
    });
  });

  test('any frame resets staleness', () {
    fakeAsync((fa) {
      s = make();
      s.connect();
      fa.flushMicrotasks();
      for (var i = 0; i < 5; i++) {
        fa.elapse(const Duration(seconds: 40));
        channels[0].incoming.add('{"type":"pong"}');
        fa.flushMicrotasks();
      }
      expect(s.state.value, SocketState.open);
      s.dispose();
    });
  });

  test('reconnectNow skips backoff; no-op when open; dispose stops', () {
    fakeAsync((fa) {
      s = make();
      s.connect();
      fa.flushMicrotasks();
      s.reconnectNow();
      expect(channels.length, 1);
      channels[0].incoming.close();
      fa.flushMicrotasks();
      s.reconnectNow();
      expect(channels.length, 2);
      channels[1].incoming.close();
      fa.flushMicrotasks();
      s.dispose();
      fa.elapse(const Duration(minutes: 1));
      expect(channels.length, 2);
    });
  });

  test('reconnectNow after a long silence replaces the dead socket', () {
    fakeAsync((fa) {
      final made = <FakeChannel>[];
      final sock = JarvisSocket(
        ServerConfig(),
        device: 'ios',
        connector: (u) {
          final c = FakeChannel();
          made.add(c);
          return c;
        },
      );
      sock.connect();
      fa.flushMicrotasks();
      expect(sock.state.value, SocketState.open);
      // the app slept 25 s: no onDone ever came, the TCP link is gone
      fa.elapse(const Duration(seconds: 25));
      sock.reconnectNow();
      fa.flushMicrotasks();
      expect(made.length, 2);
      sock.dispose();
    });
  });

  test('1008 (token refused) stops reconnecting and reports it; a later connect works', () {
    fakeAsync((fa) {
      final made = <FakeChannel>[];
      var rejected = 0;
      final sock = JarvisSocket(
        ServerConfig(),
        device: 'ios',
        onRejected: () => rejected++,
        connector: (u) {
          final c = FakeChannel();
          made.add(c);
          return c;
        },
      );
      sock.connect();
      fa.flushMicrotasks();
      made[0]
        ..code = 1008
        ..incoming.close();
      fa.flushMicrotasks();
      expect(sock.state.value, SocketState.closed);
      expect(rejected, 1);
      fa.elapse(const Duration(minutes: 2));
      expect(made.length, 1); // ws.ts: retrying would only repeat the refusal
      sock.reconnectNow();
      expect(made.length, 1);
      // signed in again: the app connects on purpose
      sock.connect();
      expect(made.length, 2);
      sock.dispose();
    });
  });

  test('reconnectNow keeps a socket that was just heard from', () {
    fakeAsync((fa) {
      final made = <FakeChannel>[];
      final sock = JarvisSocket(
        ServerConfig(),
        device: 'ios',
        connector: (u) {
          final c = FakeChannel();
          made.add(c);
          return c;
        },
      );
      sock.connect();
      fa.flushMicrotasks();
      sock.reconnectNow();
      expect(made.length, 1);
      sock.dispose();
    });
  });
}
