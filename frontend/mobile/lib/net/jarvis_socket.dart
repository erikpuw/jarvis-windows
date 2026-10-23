import 'dart:async';
import 'dart:convert';
import 'dart:math';

import 'package:clock/clock.dart';
import 'package:flutter/foundation.dart';
import 'package:web_socket_channel/io.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

import 'server_config.dart';

enum SocketState { connecting, open, closed }

/// Mirrors frontend/src/ws.ts: heartbeat, stale detection, backoff, one session id.
class JarvisSocket {
  JarvisSocket(
    this._cfg, {
    required this.device,
    this.tokenProvider,
    this.onRejected,
    WebSocketChannel Function(Uri)? connector,
    Random? random,
  }) : _connector = connector ?? IOWebSocketChannel.connect,
       _random = random ?? Random.secure() {
    _sessionId = _newSessionId(_random);
  }

  static const _heartbeat = Duration(seconds: 20);
  static const _staleAfter = Duration(seconds: 60);
  static const _minDelay = Duration(seconds: 1);
  static const _maxDelay = Duration(seconds: 30);

  final ServerConfig _cfg;
  final String device;
  final WebSocketChannel Function(Uri) _connector;
  final Random _random;
  late String _sessionId;
  String get sessionId => _sessionId;
  final String Function()? tokenProvider;

  /// The server closed with 1008 (token missing or refused); the socket stays closed until [connect] is called again.
  final VoidCallback? onRejected;
  bool _rejected = false;

  final _messages = StreamController<Map<String, dynamic>>.broadcast();
  final _state = ValueNotifier(SocketState.closed);

  WebSocketChannel? _channel;
  Timer? _reconnectTimer;
  Timer? _heartbeatTimer;
  Duration _delay = _minDelay;
  DateTime _lastData = DateTime.fromMillisecondsSinceEpoch(
    0,
  ); // wall clock: timers stand still while the app is suspended
  bool _disposed = false;

  Stream<Map<String, dynamic>> get messages => _messages.stream;
  ValueListenable<SocketState> get state => _state;

  static String _newSessionId(Random r) =>
      'web-${List.generate(4, (_) => r.nextInt(256).toRadixString(16).padLeft(2, '0')).join()}';

  static Duration nextDelay(Duration d) {
    final next = d * 2;
    return next > _maxDelay ? _maxDelay : next;
  }

  /// Called on purpose (start, login, reconnect timer): it also lifts a 1008 refusal, as after a new sign-in.
  void connect() {
    if (_disposed || _state.value != SocketState.closed) return;
    _rejected = false;
    _reconnectTimer?.cancel();
    _reconnectTimer = null;
    _state.value = SocketState.connecting;
    final WebSocketChannel ch;
    try {
      // URI rebuilt each attempt: the server URL can change at runtime.
      final tok = tokenProvider?.call();
      ch = _connector(
        _cfg.ws('/ws/voice', {
          'device': device,
          'session': sessionId,
          if (tok != null && tok.isNotEmpty) 'token': tok,
        }),
      );
    } catch (_) {
      _state.value = SocketState.closed;
      _scheduleReconnect();
      return;
    }
    _channel = ch;
    ch.ready.then((_) => _onOpen(ch), onError: (_) => _onClosed(ch));
    ch.stream.listen(
      (data) => _onData(ch, data),
      onDone: () => _onClosed(ch),
      onError: (_) => _onClosed(ch),
      cancelOnError: true,
    );
  }

  void _onOpen(WebSocketChannel ch) {
    if (_channel != ch) return;
    _state.value = SocketState.open;
    _delay = _minDelay;
    _lastData = clock.now();
    _heartbeatTimer?.cancel();
    _heartbeatTimer = Timer.periodic(_heartbeat, (_) {
      if (clock.now().difference(_lastData) > _staleAfter) {
        debugPrint('[ws] no traffic for 60s, reconnecting');
        ch.sink.close();
        _onClosed(ch);
        return;
      }
      send({'type': 'ping'});
    });
  }

  void _onData(WebSocketChannel ch, dynamic data) {
    if (_channel != ch) return;
    _lastData = clock.now();
    if (data is! String) return;
    try {
      final msg = jsonDecode(data);
      if (msg is! Map<String, dynamic> || msg['type'] == 'pong') return;
      _messages.add(msg);
    } catch (_) {
      debugPrint('[ws] bad message');
    }
  }

  void _onClosed(WebSocketChannel ch) {
    if (_channel != ch) return; // a stale socket closing late
    _channel = null;
    _heartbeatTimer?.cancel();
    _heartbeatTimer = null;
    _state.value = SocketState.closed;
    // ws.ts: 1008 = the server refused the token. Retrying would only repeat the refusal; the app signs out instead.
    if (ch.closeCode == 1008) {
      _rejected = true;
      onRejected?.call();
      return;
    }
    _scheduleReconnect();
  }

  void _scheduleReconnect() {
    if (_disposed) return;
    _reconnectTimer?.cancel();
    _reconnectTimer = Timer(_delay, () {
      _reconnectTimer = null;
      connect();
    });
    _delay = nextDelay(_delay);
  }

  /// Returns false when the socket was not open and the message was dropped.
  bool send(Map<String, dynamic> msg) {
    final ch = _channel;
    if (_state.value != SocketState.open || ch == null) return false;
    try {
      ch.sink.add(jsonEncode(msg));
      return true;
    } catch (_) {
      return false;
    }
  }

  /// Connects now (resets backoff) unless a socket is already open or connecting.
  /// An open socket that has been silent for a heartbeat is treated as dead: the OS often cuts the link while the app sleeps
  /// without ever reporting it, and a send would go into the void.
  void reconnectNow() {
    if (_disposed || _rejected) return;
    final ch = _channel;
    if (_state.value == SocketState.open &&
        ch != null &&
        clock.now().difference(_lastData) > _heartbeat) {
      ch.sink.close();
      _onClosed(ch);
    }
    if (_state.value != SocketState.closed) return;
    _delay = _minDelay;
    connect();
  }

  /// Disconnects immediately, cleans up timers, and marks state closed.
  void disconnect() {
    _reconnectTimer?.cancel();
    _reconnectTimer = null;
    _heartbeatTimer?.cancel();
    _heartbeatTimer = null;
    final ch = _channel;
    _channel = null;
    ch?.sink.close();
    _state.value = SocketState.closed;
  }

  /// Forcibly resets connection, optionally creating a fresh session ID (e.g. on user login/switch).
  void forceReconnect({bool resetSession = false}) {
    if (_disposed) return;
    disconnect();
    if (resetSession) {
      _sessionId = _newSessionId(_random);
    }
    _delay = _minDelay;
    connect();
  }

  void dispose() {
    _disposed = true;
    _reconnectTimer?.cancel();
    _heartbeatTimer?.cancel();
    final ch = _channel;
    _channel = null;
    ch?.sink.close();
    _messages.close();
    _state.dispose();
  }
}
