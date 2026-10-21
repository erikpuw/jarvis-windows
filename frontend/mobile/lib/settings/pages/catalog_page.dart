import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:jarvis_mobile/net/api_client.dart';
import 'package:jarvis_mobile/settings/action_button.dart';
import 'package:jarvis_mobile/settings/mem_widgets.dart';
import 'package:jarvis_mobile/settings/page_scaffold.dart';
import 'package:jarvis_mobile/settings/pages.dart';
import 'package:jarvis_mobile/settings/sd_widgets.dart';
import 'package:jarvis_mobile/theme/tokens.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';
import 'package:provider/provider.dart';

/// What differs between the six catalog pages (pages.ts agentsPage ... pluginsPage + index.ts loadMentions ... renderPluginsList).
class _Cat {
  const _Cat({
    required this.key,
    required this.noun,
    required this.icon,
    required this.tint,
    required this.placeholder,
    required this.countLabel,
    required this.loading,
    required this.empty,
    required this.badge,
  });

  /// the key inside /api/settings/catalog
  final String key;

  /// the word in "Lỗi nạp danh sách `noun`: ..."
  final String noun;
  final IconData icon;

  /// the icon box colour (agents keep the accent)
  final Color tint;
  final String placeholder;
  final String countLabel;
  final String loading;
  final String empty;
  final String badge;
}

const _pink = Color(0xFFF472B6);
const _amber = Color(0xFFFBBF24);
const _blue = Color(0xFF60A5FA);
const _green = Color(0xFF4ADE80);
const _purple = Color(0xFFC084FC);

const _cats = <String, _Cat>{
  'agents': _Cat(
    key: 'mentions',
    noun: 'Mention',
    icon: LucideIcons.bot,
    tint: JTokens.accent,
    placeholder: 'Tìm mention theo tên hoặc chức năng...',
    countLabel: 'Mention dùng được',
    loading: 'Đang nạp danh sách Mention…',
    empty: 'Không tìm thấy mention nào phù hợp.',
    badge: 'Sẵn sàng',
  ),
  'hooks': _Cat(
    key: 'hooks',
    noun: 'Hooks',
    icon: LucideIcons.webhook,
    tint: _pink,
    placeholder: 'Tìm kiếm Hook theo tên, sự kiện, tệp tin...',
    countLabel: 'Hooks từ hooks/',
    loading: 'Đang nạp danh sách Hooks từ thư mục hooks/…',
    empty: 'Chưa có Hook nào được nạp từ thư mục hooks/.',
    badge: 'Đang kích hoạt',
  ),
  'skills': _Cat(
    key: 'skills',
    noun: 'Skills',
    icon: LucideIcons.star,
    tint: _amber,
    placeholder: 'Tìm kiếm Kỹ năng theo tên, danh mục, từ khoá...',
    countLabel: 'Skills từ skills/',
    loading: 'Đang nạp danh sách Skills từ thư mục skills/…',
    empty: 'Không tìm thấy Kỹ năng nào trong thư mục skills/.',
    badge: 'Đã nạp',
  ),
  'prompts': _Cat(
    key: 'prompts',
    noun: 'Prompts',
    icon: LucideIcons.file,
    tint: _blue,
    placeholder: 'Tìm kiếm Prompt theo tên, tệp tin, mục đích...',
    countLabel: 'Prompts từ prompt/',
    loading: 'Đang nạp danh sách Prompts từ thư mục prompt/…',
    empty: 'Không tìm thấy Prompt nào trong thư mục prompt/.',
    badge: '',
  ),
  'commands': _Cat(
    key: 'commands',
    noun: 'Commands',
    icon: LucideIcons.terminal,
    tint: _green,
    placeholder: 'Tìm lệnh theo tên hoặc cú pháp...',
    countLabel: 'Lệnh / dùng được',
    loading: 'Đang nạp danh sách lệnh…',
    empty: 'Không tìm thấy lệnh nào phù hợp.',
    badge: 'Sẵn sàng',
  ),
  'plugins': _Cat(
    key: 'plugins',
    noun: 'Plugins',
    icon: LucideIcons.puzzle,
    tint: _purple,
    placeholder: 'Tìm kiếm Plugin theo tên, runtime, tệp tin...',
    countLabel: 'Plugins từ plugins/',
    loading: 'Đang nạp danh sách Plugins từ thư mục plugins/…',
    empty: 'Chưa có Plugin nào được nạp từ thư mục plugins/.',
    badge: 'Hoạt động',
  ),
};

String _s(Object? v) => v == null ? '' : '$v';

/// JS `a || b || c`: the first non-empty text.
String _or(Object? a, [Object? b, Object? c]) {
  for (final v in [a, b, c]) {
    if (_s(v).isNotEmpty) return _s(v);
  }
  return '';
}

List<String> _strings(Object? v) =>
    v is List ? [for (final e in v) '$e'] : const [];

/// settings/index.ts commandCall: `usage` is "/name `<param, ...>`".
String _commandCall(Map<String, dynamic> c) =>
    _or(c['usage'], '/${_s(c['name'])}');

/// Hooks, skills, prompts, commands, plugins and the @ list as the web renders them: one catalog fetch, search, cards.
class CatalogPage extends StatefulWidget {
  const CatalogPage({super.key, required this.category});

  /// a settings page id: agents, hooks, skills, prompts, commands or plugins.
  final String category;

  @override
  State<CatalogPage> createState() => _CatalogPageState();
}

class _CatalogPageState extends State<CatalogPage> {
  late final ApiClient _api = context.read<ApiClient>();
  late final _Cat _cat = _cats[widget.category]!;
  final _search = TextEditingController();
  List<Map<String, dynamic>> _items = [];
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _search.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final data = await _api.get<Map<String, dynamic>>(
        '/api/settings/catalog',
      );
      final raw = data[_cat.key];
      if (!mounted) return;
      setState(() {
        _items = raw is List
            ? [for (final e in raw) Map<String, dynamic>.from(e as Map)]
            : [];
        _loading = false;
      });
    } catch (e) {
      if (mounted) {
        setState(() {
          _error = '$e';
          _loading = false;
        });
      }
    }
  }

  /// index.ts search filters: what each page matches the typed text against.
  bool _matches(Map<String, dynamic> m, String q) {
    bool has(Object? v) => _s(v).toLowerCase().contains(q);
    return switch (widget.category) {
      'agents' => has(m['name']) || has(m['description']) || has(m['example']),
      'hooks' =>
        has(m['name']) ||
            has(m['description']) ||
            _strings(m['events']).any(has),
      'skills' =>
        has(m['name']) || has(m['description']) || _strings(m['tags']).any(has),
      'prompts' => has(m['name']) || has(m['title']) || has(m['description']),
      'commands' => has(m['name']) || has(m['description']) || has(m['usage']),
      _ => has(m['name']) || has(m['description']),
    };
  }

  String _title(Map<String, dynamic> m) => switch (widget.category) {
    'agents' => _s(m['mention']),
    'prompts' => _or(m['title'], m['name']),
    _ => _s(m['name']),
  };

  String _subtitle(Map<String, dynamic> m) => switch (widget.category) {
    'agents' => _s(m['file']),
    'hooks' => _or(m['file_path'], m['file']),
    'skills' => _or(m['file_path'], m['folder'], 'skills/'),
    'prompts' => _or(m['file_path'], m['name']),
    'commands' => _or(m['file_path'], m['file']),
    _ => _or(m['file_path'], m['file'], _or(m['runtime'], 'python')),
  };

  String _badge(Map<String, dynamic> m) => widget.category == 'prompts'
      ? '${(m['lines_count'] as num?) ?? 0} dòng'
      : _cat.badge;

  Future<void> _openPrompt(Map<String, dynamic> p) => showDialog<void>(
    context: context,
    builder: (_) => _PromptDialog(
      api: _api,
      prompt: p,
      onSaved: (content) => p['content'] = content,
    ),
  );

  Widget _card(Map<String, dynamic> m) {
    final cat = widget.category;
    final tags = switch (cat) {
      'hooks' => _strings(m['events']),
      'skills' => _strings(m['tags']),
      _ => const <String>[],
    };
    final call = cat == 'agents'
        ? _s(m['example'])
        : cat == 'commands'
        ? _commandCall(m)
        : '';
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: const Color(0x05FFFFFF),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: JTokens.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              Container(
                width: 36,
                height: 36,
                decoration: BoxDecoration(
                  color: _cat.tint.withValues(alpha: 0.1),
                  borderRadius: BorderRadius.circular(9),
                  border: Border.all(
                    color: _cat.tint.withValues(
                      alpha: cat == 'agents' ? 0.2 : 0.25,
                    ),
                  ),
                ),
                child: Icon(_cat.icon, size: 20, color: _cat.tint),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      _title(m),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                        fontSize: JTokens.fsBody,
                        fontWeight: FontWeight.w600,
                        color: Colors.white,
                        letterSpacing: -0.15,
                      ),
                    ),
                    Text(
                      _subtitle(m),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                        fontSize: JTokens.fsSmall,
                        color: JTokens.muted,
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 10),
              _StatusBadge(_badge(m)),
            ],
          ),
          const SizedBox(height: 12),
          Text(
            _s(m['description']),
            maxLines: 3,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(
              fontSize: JTokens.fsSmall,
              height: 1.5,
              color: JTokens.muted,
            ),
          ),
          if (tags.isNotEmpty) ...[
            const SizedBox(height: 20),
            _TagsRow(
              label: cat == 'hooks' ? 'Sự kiện lắng nghe:' : 'Từ khoá:',
              tags: tags,
              tint: cat == 'hooks' ? _pink : null,
            ),
          ],
          if (call.isNotEmpty) ...[
            const SizedBox(height: 12),
            _CmdBox(
              id: _s(m['name']),
              label: cat == 'agents'
                  ? 'Gõ trong command-bar:'
                  : 'Cú pháp trong command-bar:',
              call: call,
              note: cat == 'agents'
                  ? 'Hoặc nói/gõ tự nhiên, JARVIS tự chọn công cụ.'
                  : call.contains('<')
                  ? 'Thiếu nội dung bắt buộc thì JARVIS sẽ hỏi lại ở lượt sau.'
                  : 'Không cần tham số.',
            ),
          ],
          if (cat == 'prompts') ...[
            const SizedBox(height: 12),
            Align(
              alignment: Alignment.centerLeft,
              child: MemButton(
                key: Key('prompt:${_s(m['id'])}'),
                label: 'Xem nội dung prompt',
                onPressed: () => _openPrompt(m),
              ),
            ),
          ],
        ],
      ),
    );
  }

  Widget _body() {
    if (_loading) return SdEmpty(_cat.loading);
    if (_error != null) {
      return SdEmpty('Lỗi nạp danh sách ${_cat.noun}: $_error', error: true);
    }
    final q = _search.text.trim().toLowerCase();
    final shown = q.isEmpty
        ? _items
        : _items.where((m) => _matches(m, q)).toList();
    if (shown.isEmpty) return SdEmpty(_cat.empty);
    return SdGrid(children: [for (final m in shown) _card(m)]);
  }

  @override
  Widget build(BuildContext context) {
    final page = settingsPages.firstWhere((p) => p.id == widget.category);
    return PageScaffold(
      page: page,
      toolbar: Row(
        children: [
          Expanded(
            child: SdSearchBox(
              controller: _search,
              hint: _cat.placeholder,
              onChanged: (_) => setState(() {}),
            ),
          ),
          const SizedBox(width: 12),
          Text(
            '${_items.length}',
            style: const TextStyle(
              fontSize: JTokens.fsTitle,
              fontWeight: FontWeight.w700,
              color: Colors.white,
              fontFeatures: [FontFeature.tabularFigures()],
            ),
          ),
          const SizedBox(width: 8),
          Flexible(
            child: Text(
              _cat.countLabel,
              maxLines: 2,
              style: const TextStyle(
                fontSize: JTokens.fsSmall,
                color: JTokens.muted,
              ),
            ),
          ),
        ],
      ),
      body: _body(),
    );
  }
}

/// `.sd-agent-status-badge`: the green pill with its dot.
class _StatusBadge extends StatelessWidget {
  const _StatusBadge(this.text);

  final String text;

  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 2),
    decoration: BoxDecoration(
      color: const Color(0x144ADE80),
      borderRadius: BorderRadius.circular(9999),
      border: Border.all(color: const Color(0x334ADE80)),
    ),
    child: Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(
          width: 6,
          height: 6,
          decoration: const BoxDecoration(
            shape: BoxShape.circle,
            color: JTokens.ok,
            boxShadow: [BoxShadow(color: Color(0x664ADE80), blurRadius: 4)],
          ),
        ),
        const SizedBox(width: 5),
        Text(
          text,
          style: const TextStyle(
            fontSize: JTokens.fsSmall,
            fontWeight: FontWeight.w600,
            color: JTokens.ok,
          ),
        ),
      ],
    ),
  );
}

/// `.sd-agent-tools-row`: a label and the tags with a comma between (hooks tint theirs pink); two lines at most.
class _TagsRow extends StatelessWidget {
  const _TagsRow({required this.label, required this.tags, this.tint});

  final String label;
  final List<String> tags;
  final Color? tint;

  @override
  Widget build(BuildContext context) {
    const sep = Text(
      ',',
      style: TextStyle(fontSize: JTokens.fsSmall, color: Color(0x5994A3B8)),
    );
    return ClipRect(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxHeight: 46),
        child: Wrap(
          crossAxisAlignment: WrapCrossAlignment.center,
          spacing: 4,
          runSpacing: 3,
          children: [
            Text(
              label,
              style: const TextStyle(
                fontSize: JTokens.fsSmall,
                fontWeight: FontWeight.w500,
                color: JTokens.muted,
              ),
            ),
            for (var i = 0; i < tags.length; i++) ...[
              if (i > 0) sep,
              Container(
                constraints: const BoxConstraints(maxWidth: 140),
                padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 1),
                decoration: BoxDecoration(
                  color:
                      tint?.withValues(alpha: 0.15) ?? const Color(0x0AFFFFFF),
                  borderRadius: BorderRadius.circular(3),
                  border: Border.all(
                    color:
                        tint?.withValues(alpha: 0.3) ?? const Color(0x12FFFFFF),
                  ),
                ),
                child: Text(
                  tags[i],
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(
                    fontSize: JTokens.fsSmall,
                    color: tint ?? const Color(0xD994A3B8),
                  ),
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

/// `.sd-agent-cmd-box`: the label, the call in a dark box with its Sao chép button, and the note under it.
class _CmdBox extends StatefulWidget {
  const _CmdBox({
    required this.id,
    required this.label,
    required this.call,
    required this.note,
  });

  final String id;
  final String label;
  final String call;
  final String note;

  @override
  State<_CmdBox> createState() => _CmdBoxState();
}

class _CmdBoxState extends State<_CmdBox> {
  bool _copied = false;
  Timer? _timer;

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  void _copy() {
    Clipboard.setData(ClipboardData(text: widget.call));
    setState(() => _copied = true);
    _timer?.cancel();
    _timer = Timer(const Duration(milliseconds: 1500), () {
      if (mounted) setState(() => _copied = false);
    });
  }

  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    children: [
      Text(
        widget.label,
        style: const TextStyle(
          fontSize: JTokens.fsSmall,
          fontWeight: FontWeight.w600,
          color: JTokens.accent,
          letterSpacing: 0.4,
        ),
      ),
      const SizedBox(height: 5),
      Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
        decoration: BoxDecoration(
          color: const Color(0x59000000),
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: const Color(0x0FFFFFFF)),
        ),
        child: Row(
          children: [
            Expanded(
              child: Text(
                widget.call,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(
                  fontSize: JTokens.fsUi,
                  fontWeight: FontWeight.w500,
                  color: Color(0xFF7DD3FC),
                ),
              ),
            ),
            const SizedBox(width: 8),
            InkWell(
              key: Key('copy:${widget.id}'),
              borderRadius: BorderRadius.circular(6),
              onTap: _copy,
              child: Container(
                padding: const EdgeInsets.symmetric(
                  horizontal: 10,
                  vertical: 4,
                ),
                decoration: BoxDecoration(
                  borderRadius: BorderRadius.circular(6),
                  border: Border.all(color: JTokens.borderStrong),
                ),
                child: Text(
                  _copied ? 'Đã chép!' : 'Sao chép',
                  style: const TextStyle(
                    fontSize: JTokens.fsSmall,
                    color: JTokens.text,
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
      const SizedBox(height: 6),
      Text(
        widget.note,
        style: const TextStyle(fontSize: JTokens.fsSmall, color: JTokens.muted),
      ),
    ],
  );
}

/// `#prompt-preview-modal`: the prompt's text in an editor; Lưu prompt overwrites `prompt/<id>.md` (POST /api/prompts/save).
class _PromptDialog extends StatefulWidget {
  const _PromptDialog({
    required this.api,
    required this.prompt,
    required this.onSaved,
  });

  final ApiClient api;
  final Map<String, dynamic> prompt;
  final void Function(String content) onSaved;

  @override
  State<_PromptDialog> createState() => _PromptDialogState();
}

class _PromptDialogState extends State<_PromptDialog> {
  late final _text = TextEditingController(text: _s(widget.prompt['content']));
  (String, bool)? _feedback;

  @override
  void dispose() {
    _text.dispose();
    super.dispose();
  }

  Future<bool?> _save() async {
    setState(() => _feedback = null);
    final res = await widget.api.post<Map<String, dynamic>>(
      '/api/prompts/save',
      {'id': widget.prompt['id'], 'content': _text.text},
    );
    if (res['success'] != true) {
      throw ApiException(_or(res['error'], 'Không lưu được prompt'));
    }
    widget.onSaved(_text.text);
    return null;
  }

  @override
  Widget build(BuildContext context) {
    final p = widget.prompt;
    final file = _or(p['file_path'], 'prompt/${_s(p['id'])}.md');
    OutlineInputBorder border(Color c) => OutlineInputBorder(
      borderRadius: BorderRadius.circular(8),
      borderSide: BorderSide(color: c),
    );
    return Dialog(
      backgroundColor: const Color(0xFF0F172A),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(12),
        side: const BorderSide(color: Color(0x5938BDF8)),
      ),
      insetPadding: const EdgeInsets.all(24),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Container(
            padding: const EdgeInsets.fromLTRB(20, 6, 8, 6),
            decoration: const BoxDecoration(
              border: Border(bottom: BorderSide(color: JTokens.border)),
            ),
            child: Row(
              children: [
                Expanded(
                  child: Text(
                    'Prompt: ${_or(p['title'], p['name'])}',
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                      fontSize: JTokens.fsBody,
                      fontWeight: FontWeight.w600,
                      color: Colors.white,
                    ),
                  ),
                ),
                IconButton(
                  key: const Key('prompt-close'),
                  icon: const Icon(
                    LucideIcons.x,
                    size: 18,
                    color: JTokens.muted,
                  ),
                  onPressed: () => Navigator.pop(context),
                ),
              ],
            ),
          ),
          Flexible(
            child: SingleChildScrollView(
              padding: const EdgeInsets.fromLTRB(20, 16, 20, 16),
              child: TextField(
                key: const Key('prompt-editor'),
                controller: _text,
                minLines: 12,
                maxLines: null,
                keyboardType: TextInputType.multiline,
                autocorrect: false,
                style: const TextStyle(
                  color: JTokens.text,
                  fontSize: JTokens.fsUi,
                  height: 1.6,
                ),
                decoration: InputDecoration(
                  filled: true,
                  fillColor: JTokens.surface2,
                  contentPadding: const EdgeInsets.symmetric(
                    horizontal: 14,
                    vertical: 12,
                  ),
                  border: border(JTokens.borderStrong),
                  enabledBorder: border(JTokens.borderStrong),
                  focusedBorder: border(JTokens.accent),
                ),
              ),
            ),
          ),
          Container(
            padding: const EdgeInsets.fromLTRB(20, 12, 20, 16),
            decoration: const BoxDecoration(
              border: Border(top: BorderSide(color: JTokens.border)),
            ),
            child: Row(
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      SdNote([
                        const TextSpan(text: 'Lưu ghi đè '),
                        sdCode(file),
                        const TextSpan(
                          text: ' và có hiệu lực ngay ở lượt kế tiếp.',
                        ),
                      ]),
                      SdFeedback(_feedback),
                    ],
                  ),
                ),
                const SizedBox(width: 12),
                ActionButton(
                  kind: ActionKind.save,
                  label: 'Lưu prompt',
                  okText: 'Đã lưu prompt',
                  primary: true,
                  task: _save,
                  onFeedback: (t, ok) => setState(() => _feedback = (t, ok)),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
