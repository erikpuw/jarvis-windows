import 'package:flutter/material.dart';

import '../net/api_client.dart';
import '../theme/tokens.dart';

/// main.ts getActiveToken: the whitespace-delimited word that ends at the caret.
({String token, int start, int end}) activeToken(String value, int caret) {
  final end = caret.clamp(0, value.length);
  var start = end;
  while (start > 0 && !RegExp(r'\s').hasMatch(value[start - 1])) {
    start--;
  }
  return (token: value.substring(start, end), start: start, end: end);
}

class SuggestItem {
  const SuggestItem(this.name, this.desc, this.tab, this.icon);
  final String name;
  final String desc;
  final String tab; // 'command' | 'feature' | 'file'
  final String icon;
}

/// The `/` and `@` autocomplete of the command bar (main.ts "Suggestions Autocomplete Logic"): data from
/// /api/command-bar/skills (commands) and /api/command-bar/context (mentions, files), fetched when the input gets focus.
class SuggestController extends ChangeNotifier {
  SuggestController(this._api, this.input) {
    input.addListener(_onInput);
  }

  final ApiClient _api;
  final TextEditingController input;

  List<Map<String, dynamic>> _commands = const [];
  List<Map<String, dynamic>> _mentions = const [];
  List<String> _files = const [];
  String? _type; // '/' | '@'
  String _filter = '';
  String _tab = 'all';
  List<SuggestItem> _items = const [];

  String? get type => _type;
  String get tab => _tab;
  List<SuggestItem> get items => _items;
  bool get visible => _type != null;
  List<(String, String)> get tabs => _type == '/'
      ? const [('all', 'Lệnh')]
      : const [
          ('all', 'Tất cả'),
          ('feature', 'Tính năng'),
          ('file', 'Tệp tin'),
        ];

  Future<void> prefetch() async {
    try {
      final skills = await _api.get<Map<String, dynamic>>(
        '/api/command-bar/skills',
      );
      if (skills['success'] == true) {
        _commands = _maps(skills['commands']);
      }
      final ctx = await _api.get<Map<String, dynamic>>(
        '/api/command-bar/context',
      );
      if (ctx['success'] == true) {
        _mentions = _maps(ctx['mentions']);
        final f = ctx['files'];
        _files = f is List ? [for (final e in f) '$e'] : const [];
      }
    } catch (e) {
      debugPrint('[suggest] failed to fetch suggestions data: $e');
    }
  }

  static List<Map<String, dynamic>> _maps(Object? v) => v is List
      ? [
          for (final e in v)
            if (e is Map<String, dynamic>) e,
        ]
      : const [];

  void _onInput() {
    final caret = input.selection.isValid
        ? input.selection.baseOffset
        : input.text.length;
    final t = activeToken(input.text, caret).token;
    if (t.startsWith('/') || t.startsWith('@')) {
      if (t[0] != _type) _tab = 'all';
      _type = t[0];
      _filter = t.substring(1);
      _rebuild();
    } else {
      hide();
    }
  }

  void setTab(String id) {
    _tab = id;
    _rebuild();
  }

  void _rebuild() {
    final q = _filter.toLowerCase();
    bool match(String name, String desc) =>
        name.toLowerCase().contains(q) || desc.toLowerCase().contains(q);
    final out = <SuggestItem>[];
    if (_type == '/') {
      final seen = <String>{};
      for (final c in _commands) {
        final name = '${c['name']}';
        final desc = '${c['description'] ?? ''}';
        if (match(name, desc) && seen.add('/$name') && _tab == 'all') {
          out.add(SuggestItem('/$name', desc, 'command', '⚡'));
        }
      }
    } else {
      final all = _tab == 'all';
      if (all || _tab == 'feature') {
        for (final m in _mentions) {
          final name = '${m['name']}';
          final desc = '${m['description'] ?? ''}';
          if (match(name, desc)) {
            out.add(SuggestItem('@$name', desc, 'feature', '✨'));
          }
        }
      }
      if (all || _tab == 'file') {
        for (final f in _files) {
          if (f.toLowerCase().contains(q)) {
            out.add(SuggestItem('@$f', f, 'file', '📄'));
          }
        }
      }
    }
    _items = out;
    notifyListeners();
  }

  /// Replaces the word under the caret with the choice and a space.
  void select(SuggestItem item) {
    final caret = input.selection.isValid
        ? input.selection.baseOffset
        : input.text.length;
    final tok = activeToken(input.text, caret);
    final text = input.text;
    final next =
        '${text.substring(0, tok.start)}${item.name} ${text.substring(tok.end)}';
    hide();
    input.value = TextEditingValue(
      text: next,
      selection: TextSelection.collapsed(
        offset: tok.start + item.name.length + 1,
      ),
    );
  }

  void hide() {
    if (_type == null) return;
    _type = null;
    _items = const [];
    notifyListeners();
  }

  @override
  void dispose() {
    input.removeListener(_onInput);
    super.dispose();
  }
}

/// The dropdown above the command bar (style.css `#command-suggest`).
class CommandSuggest extends StatelessWidget {
  const CommandSuggest({super.key, required this.controller});
  final SuggestController controller;

  static const _cyan = JTokens.cyan;

  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: controller,
    builder: (context, _) {
      if (!controller.visible) return const SizedBox.shrink();
      final items = controller.items;
      return TextFieldTapRegion(
        child: Container(
          constraints: const BoxConstraints(maxHeight: 220),
          clipBehavior: Clip.antiAlias,
          decoration: BoxDecoration(
            color: JTokens.surface,
            border: Border.all(color: JTokens.border),
            borderRadius: BorderRadius.circular(14),
            boxShadow: const [
              BoxShadow(
                color: Color(0xB3000000),
                blurRadius: 36,
                offset: Offset(0, -12),
              ),
            ],
          ),
          child: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                _tabs(),
                if (items.isEmpty)
                  const Padding(
                    padding: EdgeInsets.all(16),
                    child: Text(
                      'Không tìm thấy kết quả phù hợp.',
                      textAlign: TextAlign.center,
                      style: TextStyle(
                        fontSize: JTokens.fsSmall,
                        color: Color(0x66FFFFFF),
                        fontStyle: FontStyle.italic,
                      ),
                    ),
                  ),
                for (final it in items) _row(it),
              ],
            ),
          ),
        ),
      );
    },
  );

  Widget _tabs() => Container(
    padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
    decoration: const BoxDecoration(
      color: Color(0xFF0D0D0F),
      border: Border(bottom: BorderSide(color: JTokens.border)),
    ),
    child: Wrap(
      spacing: 6,
      runSpacing: 6,
      children: [
        for (final (id, label) in controller.tabs)
          GestureDetector(
            onTap: () => controller.setTab(id),
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
              decoration: BoxDecoration(
                color: controller.tab == id
                    ? JTokens.surface3
                    : Colors.transparent,
                border: Border.all(
                  color: controller.tab == id
                      ? const Color(0x1FFFFFFF)
                      : Colors.transparent,
                ),
                borderRadius: BorderRadius.circular(8),
              ),
              child: Text(
                label,
                style: TextStyle(
                  fontSize: JTokens.fsLabel,
                  color: controller.tab == id ? Colors.white : JTokens.textMuted,
                ),
              ),
            ),
          ),
      ],
    ),
  );

  Widget _row(SuggestItem it) => GestureDetector(
    behavior: HitTestBehavior.opaque,
    onTap: () => controller.select(it),
    child: Container(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
      decoration: const BoxDecoration(
        border: Border(bottom: BorderSide(color: Color(0x05FFFFFF))),
      ),
      child: Row(
        children: [
          SizedBox(
            width: 14,
            child: Text(
              it.icon,
              textAlign: TextAlign.center,
              style: TextStyle(
                fontSize: JTokens.fsSmall,
                color: _cyan.withValues(alpha: 0.6),
              ),
            ),
          ),
          const SizedBox(width: 10),
          Text(
            it.name,
            style: const TextStyle(
              fontSize: JTokens.fsSmall,
              color: Colors.white,
              fontWeight: FontWeight.w500,
            ),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Align(
              alignment: Alignment.centerRight,
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 260),
                child: Text(
                  it.desc,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                    fontSize: JTokens.fsLabel,
                    color: Color(0x66FFFFFF),
                  ),
                ),
              ),
            ),
          ),
        ],
      ),
    ),
  );
}
