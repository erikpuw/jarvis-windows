import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';

import 'dart:io' show HttpClient;

import 'package:http/http.dart' as http;
import 'package:http/io_client.dart';

import 'server_config.dart';

class ApiException implements Exception {
  final int? status;
  final String message;
  ApiException(this.message, {this.status});
  @override
  String toString() => message;
}

class ApiClient {
  ApiClient(this.cfg, {http.Client? client, Duration? requestTimeout})
    : _client = client ?? IOClient(httpClient()),
      _timeout = requestTimeout ?? timeout;

  static const timeout = Duration(seconds: 20);
  // uvicorn closes idle keep-alive connections after 5 s; dart:io keeps them 15 s and would reuse a dead one.
  static const idleTimeout = Duration(seconds: 3);
  static HttpClient httpClient() => HttpClient()..idleTimeout = idleTimeout;
  static const _closedEarly = 'Connection closed before full header';
  static const uploadTimeout = Duration(seconds: 120);
  static final memoryApi = RegExp(
    r'^/api/(learnings|memories|workflows|outcomes|corrections|conversations|evolution|memory-control|history|logs|auth|users|settings|prompts)(/|\?|$)',
  );

  final ServerConfig cfg;
  final http.Client _client;
  final Duration _timeout;
  String memoryToken = '';
  VoidCallback? onLocked;

  /// Forgets the memory token here and on the server (lock.ts lockAll).
  void lock() {
    final old = memoryToken;
    memoryToken = '';
    if (old.isEmpty) return;
    final req = http.Request('POST', cfg.http('/api/memory-lock/lock'))
      ..headers['X-Memory-Token'] = old;
    unawaited(
      _client.send(req).timeout(_timeout).then<void>((_) {}).catchError((_) {}),
    );
  }

  Future<T> get<T>(String path) => _send<T>(
    'GET',
    path,
    () => http.Request('GET', cfg.http(path)),
    _timeout,
  );

  Future<T> post<T>(String path, Object? body) => _send<T>(
    'POST',
    path,
    () => http.Request('POST', cfg.http(path))
      ..headers['Content-Type'] = 'application/json'
      ..body = jsonEncode(body),
    _timeout,
  );

  Future<T> delete<T>(String path) => _send<T>(
    'DELETE',
    path,
    () => http.Request('DELETE', cfg.http(path)),
    _timeout,
  );

  /// POSTs the file as multipart field "file" (ruling R1) next to the text [fields] (the clone upload sends the voice's name).
  Future<Map<String, dynamic>> upload(
    String path,
    String filePath, {
    Map<String, String> fields = const {},
  }) async {
    final req = http.MultipartRequest('POST', cfg.http(path))
      ..fields.addAll(fields)
      ..files.add(await http.MultipartFile.fromPath('file', filePath));
    return _send<Map<String, dynamic>>(
      'POST',
      path,
      () => req,
      uploadTimeout,
      retry: false, // a MultipartRequest cannot be sent twice
    );
  }

  Future<T> _send<T>(
    String method,
    String path,
    http.BaseRequest Function() make,
    Duration t, {
    bool retry = true,
  }) async {
    final memory = memoryApi.hasMatch(path);
    http.Response? res;
    // A pooled keep-alive connection the server already closed fails before any header came back, so the request never
    // reached it: every method goes again once on a fresh connection (a GET also on any other ClientException).
    // If that fails too the browser's own wording is shown, as the web does.
    for (var attempt = 0; res == null; attempt++) {
      final req = make();
      if (memoryToken.isNotEmpty) {
        req.headers['X-Memory-Token'] = memoryToken;
        req.headers['Authorization'] = 'Bearer $memoryToken';
      }
      try {
        res = await http.Response.fromStream(
          await _client.send(req).timeout(t),
        );
      } on TimeoutException {
        throw ApiException('Máy chủ không phản hồi sau ${t.inSeconds}s');
      } on http.ClientException catch (e) {
        debugPrint('[api] $method $path: $e');
        final again = retry && (method == 'GET' || '$e'.contains(_closedEarly));
        if (!again || attempt > 0) throw ApiException('Failed to fetch');
      }
    }
    if ((memory || path.startsWith('/api/auth/')) && res.statusCode == 401) {
      memoryToken = '';
      onLocked?.call();
    }
    dynamic body;
    try {
      body = jsonDecode(utf8.decode(res.bodyBytes, allowMalformed: true));
    } catch (_) {
      try {
        body = jsonDecode(res.body);
      } catch (_) {}
    }
    if (res.statusCode < 200 || res.statusCode >= 300) {
      String? pick(String k) {
        final v = body is Map ? body[k] : null;
        return v == null || v == '' ? null : v.toString();
      }

      throw ApiException(
        pick('error') ??
            pick('code') ??
            pick('detail') ??
            '$method $path → HTTP ${res.statusCode}',
        status: res.statusCode,
      );
    }
    if (body is! T) {
      throw ApiException(
        '$method $path → phản hồi không hợp lệ',
        status: res.statusCode,
      );
    }
    return body;
  }
}
