import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:jarvis_mobile/net/api_client.dart';
import 'package:jarvis_mobile/settings/action_button.dart';
import 'package:jarvis_mobile/settings/health_poller.dart';
import 'package:jarvis_mobile/settings/page_scaffold.dart';
import 'package:jarvis_mobile/settings/pages.dart';
import 'package:jarvis_mobile/settings/sd_widgets.dart';
import 'package:jarvis_mobile/theme/tokens.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';
import 'package:provider/provider.dart';

const _defaultHint = 'Giọng được áp dụng ngay cho phản hồi âm thanh tiếp theo.';

Future<String?> _pickAudio() async {
  final files = await FilePicker.pickFiles(type: FileType.audio);
  return files.isEmpty ? null : files.first.path;
}

class _Voice {
  const _Voice(this.name, this.label, this.kind);

  factory _Voice.from(Object? v) {
    final m = v is Map ? v : const {};
    return _Voice('${m['name']}', '${m['label'] ?? m['name']}', '${m['kind']}');
  }

  final String name;
  final String label;
  final String kind;
}

/// Giọng đọc (pages.ts voicePage + index.ts loadVoices / fillVoiceSelect / fillRuntime / bindActions).
class VoicePage extends StatefulWidget {
  /// [pickAudio] chooses the clone sample (a file path, null when cancelled); the app uses the system picker.
  const VoicePage({super.key, this.pickAudio});

  final Future<String?> Function()? pickAudio;

  @override
  State<VoicePage> createState() => _VoicePageState();
}

class _VoicePageState extends State<VoicePage> {
  late final ApiClient _api = context.read<ApiClient>();
  final _cloneName = TextEditingController();
  Map<String, dynamic> _runtime = const {};
  String? _statusError;
  List<_Voice> _voices = const [];
  String? _selected;
  bool _supported = true; // engine == vieneu
  bool _loadingVoices = true;
  String _hint = _defaultHint;
  String? _cloneFile;
  (String, bool)? _saveFb;
  (String, bool)? _cloneFb;

  @override
  void initState() {
    super.initState();
    _loadStatus();
    _loadVoices();
  }

  @override
  void dispose() {
    _cloneName.dispose();
    super.dispose();
  }

  Future<void> _loadStatus() async {
    try {
      final s = await _api.get<Map<String, dynamic>>(statusPath);
      if (!mounted) return;
      final rt = s['runtime'];
      setState(() => _runtime = rt is Map ? rt.cast<String, dynamic>() : {});
    } catch (e) {
      if (mounted) setState(() => _statusError = '$e');
    }
  }

  List<_Voice> _parse(Object? list) =>
      list is List ? [for (final v in list) _Voice.from(v)] : const [];

  Future<void> _loadVoices() async {
    try {
      final data = await _api.get<Map<String, dynamic>>('/api/tts/voices');
      if (!mounted) return;
      final supported = data['engine'] == 'vieneu';
      setState(() {
        _loadingVoices = false;
        _supported = supported;
        if (supported) {
          _voices = _parse(data['voices']);
          final cur = '${data['current'] ?? ''}';
          _selected = _voices.any((v) => v.name == cur) ? cur : null;
        } else {
          _hint = 'Engine TTS hiện tại không hỗ trợ chọn giọng ở đây.';
        }
      });
    } catch (e) {
      if (mounted) {
        setState(() {
          _loadingVoices = false;
          _hint = 'Không lấy được danh sách giọng ($e). Kiểm tra TTS server.';
        });
      }
    }
  }

  Future<bool?> _saveVoice() async {
    final voice = _selected ?? '';
    if (voice.isEmpty) throw ApiException('Chưa chọn giọng');
    // /api/tts/voice switches the running TTS immediately (the .env key alone does not)
    final res = await _api.post<Map<String, dynamic>>('/api/tts/voice', {
      'voice': voice,
    });
    if (res['success'] != true) {
      throw ApiException('${res['error'] ?? 'Không lưu được giọng'}');
    }
    return null;
  }

  Future<void> _chooseFile() async {
    final path = await (widget.pickAudio ?? _pickAudio)();
    if (path != null && mounted) setState(() => _cloneFile = path);
  }

  Future<bool?> _upload() async {
    final name = _cloneName.text.trim();
    final file = _cloneFile;
    if (name.isEmpty || file == null) {
      throw ApiException('Nhập tên giọng và chọn file mẫu trước');
    }
    final Map<String, dynamic> res;
    try {
      res = await _api.upload(
        '/api/tts/voices/clone',
        file,
        fields: {'name': name},
      );
    } on ApiException catch (e) {
      // the web's own fallback text when the body has no error
      if (e.status != null && e.message.endsWith('HTTP ${e.status}')) {
        throw ApiException('Lỗi ${e.status}');
      }
      rethrow;
    }
    if (res['success'] == false) {
      throw ApiException('${res['error'] ?? 'Lỗi'}');
    }
    if (mounted) {
      setState(() {
        _voices = _parse(res['voices']);
        _selected = _voices.any((v) => v.name == name) ? name : null;
        _hint = 'Đã thêm giọng "$name". Bấm "Lưu giọng" để dùng.';
      });
    }
    return null;
  }

  Widget _engineTile(String name, String key, String engine) {
    final running = _runtime['tts_engine'] == engine;
    final current = '${_runtime[key] ?? ''}';
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
      decoration: BoxDecoration(
        color: const Color(0x05FFFFFF),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: JTokens.border),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.only(top: 5),
            child: StatusDot(running ? DotState.ok : DotState.off),
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  name,
                  style: const TextStyle(
                    fontSize: JTokens.fsUi,
                    color: JTokens.text,
                  ),
                ),
                const SizedBox(height: 2),
                Text(
                  '${current.isEmpty ? '—' : current}${running ? ' · đang chạy' : ''}',
                  style: const TextStyle(
                    fontSize: JTokens.fsSmall,
                    color: JTokens.muted,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _select() {
    final items = <DropdownMenuItem<String>>[];
    for (final (title, kind) in const [
      ('Giọng có sẵn', 'preset'),
      ('Giọng clone của bạn', 'clone'),
    ]) {
      final group = _voices.where((v) => v.kind == kind).toList();
      if (group.isEmpty) continue;
      items.add(
        DropdownMenuItem<String>(
          enabled: false,
          value: '__group:$kind',
          child: Text(
            title,
            style: const TextStyle(
              fontSize: JTokens.fsSmall,
              fontWeight: FontWeight.w600,
              color: JTokens.muted,
            ),
          ),
        ),
      );
      for (final v in group) {
        items.add(
          DropdownMenuItem<String>(value: v.name, child: Text(v.label)),
        );
      }
    }
    return Container(
      key: const Key('voice-select'),
      height: 40,
      padding: const EdgeInsets.symmetric(horizontal: 12),
      decoration: BoxDecoration(
        color: JTokens.surface2,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: JTokens.borderStrong),
      ),
      child: DropdownButtonHideUnderline(
        child: DropdownButton<String>(
          isExpanded: true,
          value: _selected,
          hint: Text(
            _loadingVoices ? 'Đang tải danh sách giọng…' : '',
            style: const TextStyle(color: JTokens.muted),
          ),
          items: items,
          dropdownColor: JTokens.surface,
          iconEnabledColor: JTokens.muted,
          style: Theme.of(context).textTheme.bodyMedium!
              .copyWith(color: JTokens.text, fontSize: JTokens.fsUi),
          onChanged: (v) => setState(() => _selected = v),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final page = settingsPages.firstWhere((p) => p.id == 'voice');
    return PageScaffold(
      page: page,
      body: SdGrid(
        children: [
          SdCard(
            icon: LucideIcons.activity,
            title: 'Engine đang chạy',
            children: [
              _engineTile('VieNeu TTS', 'vieneu_voice', 'vieneu'),
              const SizedBox(height: 8),
              _engineTile('Edge-TTS', 'edge_voice', 'edge'),
              const SizedBox(height: 12),
              if (_statusError != null)
                SdEmpty(
                  'Không tải được trạng thái: $_statusError',
                  error: true,
                ),
              SdNote([
                const TextSpan(text: 'Chỉ đọc từ '),
                sdCode('.env'),
                const TextSpan(text: '. Muốn đổi engine: sửa '),
                sdCode('VIENEU_TTS_ENABLED'),
                const TextSpan(text: ' / '),
                sdCode('EDGE_TTS_ENABLED'),
                const TextSpan(text: ' (chỉ bật một), giọng Edge ở '),
                sdCode('TTS_LOCAL_MODEL'),
                const TextSpan(text: ', rồi khởi động lại JARVIS.'),
              ]),
            ],
          ),
          SdCard(
            icon: LucideIcons.volume2,
            title: 'Giọng VieNeu',
            children: [
              if (_supported)
                SdFormGroup(
                  label: 'Chọn giọng nói',
                  children: [_select(), SdNote.text(_hint)],
                )
              else
                Padding(
                  padding: const EdgeInsets.only(bottom: 18),
                  child: SdNote.text(_hint),
                ),
              Row(
                mainAxisAlignment: MainAxisAlignment.end,
                children: [
                  Flexible(
                    child: ActionButton(
                      kind: ActionKind.save,
                      label: 'Lưu giọng',
                      primary: true,
                      task: () {
                        setState(() => _saveFb = null);
                        return _saveVoice();
                      },
                      onFeedback: (t, ok) => setState(() => _saveFb = (t, ok)),
                    ),
                  ),
                ],
              ),
              SdFeedback(_saveFb),
            ],
          ),
          SdCard(
            icon: LucideIcons.userRound,
            title: 'Tạo giọng clone',
            children: [
              const SdLead([
                TextSpan(
                  text: 'Mẫu 3–8 giây, một người nói, ít tạp âm, đọc rõ và chậm — tốc độ đọc sẽ theo mẫu.',
                ),
              ]),
              SdFormGroup(
                label: 'Tên giọng clone',
                children: [
                  SdInput(
                    key: const Key('field:Tên giọng clone'),
                    controller: _cloneName,
                    hint: 'Ví dụ: Giọng trợ lý cá nhân',
                  ),
                ],
              ),
              SdFormGroup(
                label: 'Tệp mẫu âm thanh',
                children: [
                  Row(
                    children: [
                      OutlinedButton(
                        onPressed: _chooseFile,
                        style: OutlinedButton.styleFrom(
                          side: const BorderSide(color: JTokens.borderStrong),
                          minimumSize: const Size(0, 36),
                          shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(6),
                          ),
                        ),
                        child: const Text(
                          'Chọn tệp',
                          style: TextStyle(
                            fontSize: JTokens.fsSmall,
                            color: JTokens.text,
                          ),
                        ),
                      ),
                      const SizedBox(width: 10),
                      Expanded(
                        child: Text(
                          _cloneFile == null
                              ? 'Chưa chọn tệp'
                              : _cloneFile!.split(RegExp(r'[\\/]')).last,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(
                            fontSize: JTokens.fsSmall,
                            color: JTokens.muted,
                          ),
                        ),
                      ),
                    ],
                  ),
                ],
              ),
              Align(
                alignment: Alignment.centerLeft,
                child: ActionButton(
                  kind: ActionKind.upload,
                  label: 'Tải lên & Huấn luyện',
                  okText: 'Đã tải mẫu',
                  task: () {
                    setState(() => _cloneFb = null);
                    return _upload();
                  },
                  onFeedback: (t, ok) => setState(() => _cloneFb = (t, ok)),
                ),
              ),
              SdFeedback(_cloneFb),
            ],
          ),
        ],
      ),
    );
  }
}
