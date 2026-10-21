import 'package:flutter/material.dart';
import 'package:jarvis_mobile/net/api_client.dart';
import 'package:jarvis_mobile/net/server_config.dart';
import 'package:jarvis_mobile/settings/action_button.dart';
import 'package:jarvis_mobile/settings/health_poller.dart';
import 'package:jarvis_mobile/settings/page_scaffold.dart';
import 'package:jarvis_mobile/settings/pages.dart';
import 'package:jarvis_mobile/settings/sd_widgets.dart';
import 'package:jarvis_mobile/theme/tokens.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';
import 'package:provider/provider.dart';

/// Kết nối & API (pages.ts connectPage + index.ts bindActions). Besides the web's two cards it has the app-only "Địa chỉ server".
///
/// The feedback under a button is what runAction writes: its okText on success ("Đã lưu"), the thrown message on failure - the
/// web overwrites the nicer text its handlers set with setFeedback, so that is what its users see.
class ConnectPage extends StatefulWidget {
  const ConnectPage({super.key});

  @override
  State<ConnectPage> createState() => _ConnectPageState();
}

class _ConnectPageState extends State<ConnectPage> {
  late final ApiClient _api = context.read<ApiClient>();
  late final TextEditingController _serverUrl;
  final _llamaKey = TextEditingController();
  final _llamaUrl = TextEditingController();
  final _fishKey = TextEditingController();
  String? _urlError;
  String _llamaNote = 'Chưa cấu hình khoá.';
  bool _llamaNoteError = false;
  final _feedback = <String, (String, bool)?>{};

  @override
  void initState() {
    super.initState();
    _serverUrl = TextEditingController(
      text: context.read<ServerConfig>().baseUrl,
    );
    _loadStatus();
  }

  @override
  void dispose() {
    _serverUrl.dispose();
    _llamaKey.dispose();
    _llamaUrl.dispose();
    _fishKey.dispose();
    super.dispose();
  }

  /// loadStatus(): the note under the key says whether the key and URL are configured.
  Future<void> _loadStatus() async {
    try {
      final s = await _api.get<Map<String, dynamic>>(statusPath);
      if (!mounted) return;
      final keys = s['env_keys_set'];
      setState(() {
        _llamaNoteError = false;
        _llamaNote = keys is Map && keys['llama'] == true
            ? 'Đã cấu hình khoá và URL máy chủ.'
            : 'Chưa cấu hình khoá.';
      });
    } catch (e) {
      if (mounted) {
        setState(() {
          _llamaNoteError = true;
          _llamaNote = 'Không tải được trạng thái: $e';
        });
      }
    }
  }

  Future<void> _saveKey(String name, String value) async {
    final r = await _api.post<Map<String, dynamic>>('/api/settings/keys', {
      'key_name': name,
      'key_value': value,
    });
    if (r['success'] == false) {
      throw ApiException('${r['error'] ?? 'Không lưu được $name'}');
    }
  }

  /// testKey(): an empty key tests the one saved on the server.
  Future<void> _test(String path, String key, String invalid) async {
    final r = await _api.post<Map<String, dynamic>>(
      path,
      key.isEmpty ? <String, dynamic>{} : {'key_value': key},
    );
    if (r['valid'] != true) {
      final e = r['error'];
      throw ApiException(e == null || e == '' ? invalid : '$e');
    }
  }

  Future<bool?> _saveAll() async {
    final llama = _llamaKey.text.trim();
    if (llama.isEmpty) throw ApiException('Missing Server API Key');
    await _saveKey('LOCAL_API_KEY', llama);
    final fish = _fishKey.text.trim();
    if (fish.isNotEmpty) await _saveKey('TTS_LOCAL_KEY', fish);
    _loadStatus();
    return null;
  }

  Future<bool?> _saveUrl() async {
    final url = _llamaUrl.text.trim();
    if (url.isEmpty) throw ApiException('Nhập URL máy chủ');
    await _saveKey('LOCAL_URL', url);
    return null;
  }

  Future<void> _saveServerUrl(String value) async {
    final trimmed = value.trim();
    final uri = Uri.tryParse(trimmed);
    if (uri == null || !uri.hasScheme || uri.host.isEmpty) {
      setState(() => _urlError = 'Địa chỉ URL không hợp lệ');
      return;
    }
    try {
      await context.read<ServerConfig>().setBaseUrl(trimmed);
      if (mounted) setState(() => _urlError = null);
    } on FormatException catch (e) {
      if (mounted) setState(() => _urlError = e.message);
    }
  }

  void _fb(String id, String text, bool ok) =>
      setState(() => _feedback[id] = (text, ok));

  ActionButton _action(
    String id,
    ActionKind kind,
    String label,
    Future<bool?> Function() task, {
    bool primary = false,
  }) => ActionButton(
    kind: kind,
    label: label,
    primary: primary,
    task: () {
      setState(() => _feedback[id] = null); // clearFeedback()
      return task();
    },
    onFeedback: (text, ok) => _fb(id, text, ok),
  );

  @override
  Widget build(BuildContext context) {
    final page = settingsPages.firstWhere((p) => p.id == 'connect');
    return PageScaffold(
      page: page,
      action: ActionButton(
        kind: ActionKind.refresh,
        label: 'Restart',
        danger: true,
        task: () async {
          await _api.post<dynamic>('/api/restart', <String, dynamic>{});
          return null;
        },
      ),
      body: SdGrid(
        children: [
          SdCard(
            icon: LucideIcons.server,
            title: 'Máy chủ JARVIS',
            children: [
              SdFormGroup(
                label: 'Địa chỉ server',
                last: true,
                children: [
                  SdInput(
                    key: const Key('server_url_input'),
                    controller: _serverUrl,
                    hint: 'https://...',
                    errorText: _urlError,
                    onSubmitted: _saveServerUrl,
                    onChanged: (v) {
                      if (_urlError != null) _saveServerUrl(v);
                    },
                  ),
                  SdNote.text(
                    'Địa chỉ máy chủ backend (Tailscale hoặc mạng cục bộ).',
                  ),
                ],
              ),
            ],
          ),
          SdCard(
            icon: LucideIcons.keyRound,
            title: 'Mô hình ngôn ngữ (LLM API)',
            children: [
              SdLead([
                const TextSpan(
                  text: 'JARVIS dùng server API Key để xác thực các cuộc gọi mô hình. Khoá được lưu vào file ',
                ),
                sdCode('.env'),
                const TextSpan(text: ' tại máy chủ cục bộ.'),
              ]),
              SdFormGroup(
                label: 'Server API Key (LOCAL_API_KEY)',
                children: [
                  SdInputRow(
                    input: SdInput(
                      key: const Key('field:Server API Key (LOCAL_API_KEY)'),
                      controller: _llamaKey,
                      hint: 'Nhập khoá API...',
                      obscure: true,
                    ),
                    button: _action(
                      'test-llama',
                      ActionKind.test,
                      'Kiểm tra',
                      () async {
                        await _test(
                          '/api/settings/test-llm',
                          _llamaKey.text.trim(),
                          'Invalid key',
                        );
                        return null;
                      },
                    ),
                  ),
                  SdFeedback(_feedback['test-llama']),
                  Text(
                    _llamaNote,
                    style: TextStyle(
                      fontSize: JTokens.fsSmall,
                      height: 1.5,
                      color: _llamaNoteError ? JTokens.err : JTokens.muted,
                    ),
                  ),
                ],
              ),
              SdFormGroup(
                label: 'Endpoint máy chủ LLM (LOCAL_URL)',
                last: true,
                children: [
                  SdInputRow(
                    input: SdInput(
                      key: const Key('field:Endpoint máy chủ LLM (LOCAL_URL)'),
                      controller: _llamaUrl,
                      hint: 'http://127.0.0.1:8080/v1',
                    ),
                    button: _action(
                      'save-llama-url',
                      ActionKind.save,
                      'Lưu URL',
                      _saveUrl,
                    ),
                  ),
                  SdFeedback(_feedback['save-llama-url']),
                ],
              ),
            ],
          ),
          SdCard(
            icon: LucideIcons.volume2,
            title: 'Dịch vụ giọng nói & TTS (Tuỳ chọn)',
            children: [
              SdFormGroup(
                label: 'Fish Audio / VieNeu API Key',
                last: true,
                children: [
                  SdInputRow(
                    input: SdInput(
                      key: const Key('field:Fish Audio / VieNeu API Key'),
                      controller: _fishKey,
                      hint: 'Nhập khoá TTS nếu dùng dịch vụ đám mây...',
                      obscure: true,
                    ),
                    button: _action(
                      'test-fish',
                      ActionKind.test,
                      'Kiểm tra TTS',
                      () async {
                        await _test(
                          '/api/settings/test-tts',
                          _fishKey.text.trim(),
                          'Invalid TTS key',
                        );
                        return null;
                      },
                    ),
                  ),
                  SdFeedback(_feedback['test-fish']),
                  SdNote.text(
                    'Đang sử dụng VieNeu TTS Engine nội bộ (cục bộ).',
                  ),
                ],
              ),
              const SizedBox(height: 16),
              Row(
                mainAxisAlignment: MainAxisAlignment.end,
                children: [
                  Flexible(
                    child: _action(
                      'save-keys',
                      ActionKind.save,
                      'Lưu toàn bộ cài đặt kết nối',
                      _saveAll,
                      primary: true,
                    ),
                  ),
                ],
              ),
              SdFeedback(_feedback['save-keys']),
            ],
          ),
        ],
      ),
    );
  }
}
