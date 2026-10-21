import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:jarvis_mobile/net/api_client.dart';
import 'package:jarvis_mobile/net/server_config.dart';

ApiClient make(MockClient m) => ApiClient(ServerConfig(), client: m);

void main() {
  test('a GET retries once when the pooled connection was closed', () async {
    var calls = 0;
    final api = make(
      MockClient((r) async {
        if (calls++ == 0) {
          throw http.ClientException(
            'Connection closed before full header was received',
          );
        }
        return http.Response('{"ok":true}', 200);
      }),
    );
    expect(await api.get<Map<String, dynamic>>('/api/mcp/servers'), {
      'ok': true,
    });
    expect(calls, 2);
  });

  test('a request that fails twice shows the web wording', () async {
    var calls = 0;
    final api = make(
      MockClient((r) async {
        calls++;
        throw http.ClientException(
          'Connection closed before full header was received',
        );
      }),
    );
    await expectLater(
      api.get('/api/mcp/servers'),
      throwsA(
        isA<ApiException>().having((e) => e.message, 'm', 'Failed to fetch'),
      ),
    );
    expect(calls, 2);
  });

  test('http client idle timeout is shorter than the server keep-alive', () {
    expect(ApiClient.httpClient().idleTimeout, ApiClient.idleTimeout);
    expect(ApiClient.idleTimeout, lessThan(const Duration(seconds: 5)));
  });

  test(
    'a POST retries once on closed-before-header, not on other errors',
    () async {
      var calls = 0;
      final api = make(
        MockClient((r) async {
          if (calls++ == 0) {
            throw http.ClientException(
              'Connection closed before full header was received',
            );
          }
          return http.Response('{"ok":true}', 200);
        }),
      );
      expect(await api.post<Map<String, dynamic>>('/api/x', {}), {'ok': true});
      expect(calls, 2);
      calls = 0;
      final other = make(
        MockClient((r) async {
          calls++;
          throw http.ClientException('Connection reset by peer');
        }),
      );
      await expectLater(other.post('/api/x', {}), throwsA(isA<ApiException>()));
      expect(calls, 1);
    },
  );

  test('memory api gets token header', () async {
    http.BaseRequest? seen;
    final api = make(
      MockClient((r) async {
        seen = r;
        return http.Response('{"ok":true}', 200);
      }),
    )..memoryToken = 'tok';
    await api.get<Map<String, dynamic>>('/api/learnings/list');
    expect(seen!.headers['X-Memory-Token'], 'tok');
  });

  test('api attaches token to all requests when authenticated (matching web)', () async {
    http.BaseRequest? seen;
    final api = make(
      MockClient((r) async {
        seen = r;
        return http.Response('{}', 200);
      }),
    )..memoryToken = 'tok';
    await api.get<Map<String, dynamic>>('/api/settings/catalog');
    expect(seen!.headers['X-Memory-Token'], 'tok');
    expect(seen!.headers['Authorization'], 'Bearer tok');
  });

  test('request without token sends no auth headers', () async {
    http.BaseRequest? seen;
    final api = make(
      MockClient((r) async {
        seen = r;
        return http.Response('{}', 200);
      }),
    );
    await api.get<Map<String, dynamic>>('/api/settings/catalog');
    expect(seen!.headers.containsKey('X-Memory-Token'), false);
    expect(seen!.headers.containsKey('Authorization'), false);
  });

  test('401 on memory api fires onLocked', () async {
    var locked = 0;
    final api = make(MockClient((r) async => http.Response('{}', 401)))
      ..onLocked = () => locked++;
    await expectLater(
      api.get('/api/history'),
      throwsA(isA<ApiException>().having((e) => e.status, 'status', 401)),
    );
    expect(locked, 1);
  });

  test('error body message surfaces', () async {
    final api = make(
      MockClient((r) async => http.Response('{"error":"boom"}', 500)),
    );
    await expectLater(
      api.get('/api/x'),
      throwsA(isA<ApiException>().having((e) => e.message, 'message', 'boom')),
    );
  });

  test('error without body falls back to METHOD path', () async {
    final api = make(MockClient((r) async => http.Response('nope', 502)));
    await expectLater(
      api.post('/api/x', {'a': 1}),
      throwsA(
        isA<ApiException>().having(
          (e) => e.message,
          'message',
          'POST /api/x → HTTP 502',
        ),
      ),
    );
  });

  test('post sends json', () async {
    late http.Request seen;
    final api = make(
      MockClient((r) async {
        seen = r;
        return http.Response('{"n":1}', 200);
      }),
    );
    final out = await api.post<Map<String, dynamic>>('/api/x', {'a': 1});
    expect(out['n'], 1);
    expect(seen.headers['Content-Type'], startsWith('application/json'));
    expect(jsonDecode(seen.body), {'a': 1});
  });

  test('upload sends multipart file field', () async {
    final f = File('${Directory.systemTemp.path}/speech.wav')
      ..writeAsBytesSync([1, 2, 3]);
    late http.BaseRequest seen;
    final api = make(
      MockClient.streaming((r, body) async {
        seen = r;
        final bytes = await body.expand((c) => c).toList();
        expect(
          utf8.decode(bytes, allowMalformed: true),
          allOf(contains('name="file"'), contains('filename="speech.wav"')),
        );
        return http.StreamedResponse(
          Stream.value(utf8.encode('{"text":"hi"}')),
          200,
        );
      }),
    );
    final out = await api.upload('/api/stt', f.path);
    expect(out['text'], 'hi');
    expect(seen.method, 'POST');
    expect(seen.url.path, '/api/stt');
  });

  test('timeout message', () async {
    final api = ApiClient(
      ServerConfig(),
      client: MockClient(
        (r) => Future.delayed(
          const Duration(seconds: 5),
          () => http.Response('{}', 200),
        ),
      ),
      requestTimeout: const Duration(milliseconds: 20),
    );
    await expectLater(
      api.get('/api/x'),
      throwsA(
        isA<ApiException>().having(
          (e) => e.message,
          'm',
          startsWith('Máy chủ không phản hồi sau'),
        ),
      ),
    );
  });

  test(
    'a 2xx body of the wrong shape is an ApiException, not a TypeError',
    () async {
      final api = make(MockClient((r) async => http.Response('', 200)));
      await expectLater(
        api.get<Map<String, dynamic>>('/api/settings/status'),
        throwsA(isA<ApiException>()),
      );
    },
  );
}
