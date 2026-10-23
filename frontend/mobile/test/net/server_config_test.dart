import 'package:flutter_test/flutter_test.dart';
import 'package:jarvis_mobile/net/server_config.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  test('ws url swaps scheme', () {
    final cfg = ServerConfig();
    expect(
      cfg.ws('/ws/voice', {
        'device': 'ios',
        'session': 'web-0a1b2c3d',
      }).toString(),
      'wss://jarvis.tail8b8885.ts.net:8340/ws/voice?device=ios&session=web-0a1b2c3d',
    );
  });

  test('http keeps absolute README image URLs unchanged', () {
    final cfg = ServerConfig();
    for (final url in [
      'https://img.shields.io/badge/Python-3.11-blue',
      'http://example.com/image.png?size=2#preview',
    ]) {
      expect(cfg.http(url).toString(), url);
    }
  });

  test(
    'http preserves server prefixes, query and fragment for local assets',
    () async {
      final cfg = ServerConfig();
      await cfg.setBaseUrl('https://example.com:8340/jarvis');
      expect(
        cfg.http('/api/outputs/image.png?size=2#preview').toString(),
        'https://example.com:8340/jarvis/api/outputs/image.png?size=2#preview',
      );
    },
  );

  test('setBaseUrl rejects no scheme and trims slash', () async {
    final cfg = ServerConfig();
    await expectLater(cfg.setBaseUrl('abc'), throwsFormatException);
    await cfg.setBaseUrl('https://x:1/');
    expect(cfg.baseUrl, 'https://x:1');
  });

  test('url change takes effect on next ws/http call and persists', () async {
    final cfg = ServerConfig();
    var notified = 0;
    cfg.addListener(() => notified++);
    await cfg.setBaseUrl('http://10.0.0.5:8340');
    expect(notified, 1);
    expect(
      cfg.ws('/ws/voice', {'a': 'b'}).toString(),
      'ws://10.0.0.5:8340/ws/voice?a=b',
    );
    expect(cfg.http('/api/x').toString(), 'http://10.0.0.5:8340/api/x');
    final again = ServerConfig();
    await again.load();
    expect(again.baseUrl, 'http://10.0.0.5:8340');
  });

  test('load falls back to default', () async {
    final cfg = ServerConfig();
    await cfg.load();
    expect(cfg.baseUrl, ServerConfig.defaultUrl);
  });
}
