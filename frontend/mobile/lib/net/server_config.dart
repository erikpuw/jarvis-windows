import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

class ServerConfig extends ChangeNotifier {
  static const defaultUrl = 'https://jarvis.tail8b8885.ts.net:8340';
  static const _key = 'server_url';

  String _baseUrl = defaultUrl;
  String get baseUrl => _baseUrl;

  Future<void> load() async {
    final saved = (await SharedPreferences.getInstance()).getString(_key);
    if (saved != null && saved.isNotEmpty) {
      _baseUrl = saved;
      notifyListeners();
    }
  }

  Future<void> setBaseUrl(String url) async {
    final u = url.trim().replaceFirst(RegExp(r'/+$'), '');
    final uri = Uri.tryParse(u);
    if (uri == null ||
        !(uri.scheme == 'http' || uri.scheme == 'https') ||
        uri.host.isEmpty) {
      throw const FormatException(
        'URL phải bắt đầu bằng http:// hoặc https://',
      );
    }
    await (await SharedPreferences.getInstance()).setString(_key, u);
    _baseUrl = u;
    notifyListeners();
  }

  Uri http(String path) => Uri.parse('$_baseUrl$path');

  Uri ws(String path, Map<String, String> query) {
    final b = Uri.parse(_baseUrl);
    return b.replace(
      scheme: b.scheme == 'https' ? 'wss' : 'ws',
      path: path,
      queryParameters: query.isEmpty ? null : query,
    );
  }
}
