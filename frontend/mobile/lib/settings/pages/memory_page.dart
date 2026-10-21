import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:jarvis_mobile/chat/lucide_glyphs.dart';
import 'package:jarvis_mobile/chat/morph_icon.dart';
import 'package:jarvis_mobile/net/api_client.dart';
import 'package:jarvis_mobile/settings/action_button.dart';
import 'package:jarvis_mobile/settings/mem_widgets.dart';
import 'package:jarvis_mobile/settings/page_scaffold.dart';
import 'package:jarvis_mobile/settings/pages.dart';
import 'package:jarvis_mobile/settings/sd_widgets.dart';
import 'package:jarvis_mobile/theme/tokens.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:jarvis_mobile/auth/auth_controller.dart';

/// Bộ nhớ (pages.ts memoryPage + memory.ts): seven tabs of records, search, paging, a detail editor with the dependency-checked delete,
/// re-embed, evolution files and gym records. On a phone the list and the editor take turns (`.show-detail-mobile`).

const _pageSize = 50;
const _memoryKindKey = 'jarvis.settings.memory_kind';

class _Def {
  const _Def(
    this.cat,
    this.endpoint,
    this.responseKey,
    this.countKey,
    this.fields,
  );
  final MemCat cat;
  final String endpoint;
  final String responseKey;
  final String? countKey;
  final List<String> fields;
  String get id => cat.id;
  String get label => cat.label;
  Color get color => cat.color;
}

// MEMORY_CATEGORIES + EDITABLE_MEMORY_FIELDS (memory.ts); tools / wiki_path stay read-only in "Thông tin hệ thống".
const _defs = <_Def>[
  _Def(
    MemCat(
      id: 'learning',
      label: 'Learnings',
      color: Color(0xFFA78BFA),
      icon: brainGlyph,
      activeIcon: lightbulbGlyph,
    ),
    '/api/learnings/list',
    'learnings',
    'learnings',
    ['type', 'semantic_key', 'content', 'source', 'importance', 'embedding'],
  ),
  _Def(
    MemCat(
      id: 'workflow',
      label: 'Workflows',
      color: Color(0xFF22D3EE),
      icon: workflowGlyph,
      activeIcon: rotateCwGlyph,
    ),
    '/api/workflows/list',
    'workflows',
    'workflows',
    [
      'intent',
      'tool_chain',
      'sample_queries',
      'success_evidence',
      'validation_count',
    ],
  ),
  _Def(
    MemCat(
      id: 'outcome',
      label: 'Outcomes',
      color: Color(0xFFF59E0B),
      icon: targetGlyph,
      activeIcon: checkCheckGlyph,
    ),
    '/api/outcomes/list',
    'outcomes',
    'outcomes',
    ['tools', 'query', 'status', 'result', 'traces'],
  ),
  _Def(
    MemCat(
      id: 'correction',
      label: 'Sửa công cụ',
      color: Color(0xFFFB923C),
      icon: wrenchGlyph,
      activeIcon: hammerGlyph,
    ),
    '/api/corrections/list',
    'corrections',
    'corrections',
    ['query', 'wrong_tool', 'right_tool', 'count'],
  ),
  _Def(
    MemCat(
      id: 'conversation',
      label: 'Conversations',
      color: Color(0xFF60A5FA),
      icon: messageSquareGlyph,
      activeIcon: messagesSquareGlyph,
    ),
    '/api/conversations',
    'conversations',
    'conversations',
    ['role', 'content', 'session_id'],
  ),
  _Def(
    MemCat(
      id: 'gym',
      label: 'Gym Memory',
      color: Color(0xFFEC4899),
      icon: dumbbellGlyph,
      activeIcon: activityGlyph,
    ),
    '/api/gym/list',
    'items',
    'gym',
    ['title', 'content', 'type'],
  ),
  _Def(
    MemCat(
      id: 'evolution',
      label: 'Evolution',
      color: Color(0xFF34D399),
      icon: dnaGlyph,
      activeIcon: sproutGlyph,
    ),
    '/api/evolution/list',
    'items',
    null,
    ['content'],
  ),
  _Def(
    MemCat(
      id: 'user',
      label: 'Người dùng',
      color: Color(0xFFF43F5E),
      icon: userRoundGlyph,
      activeIcon: userCheckGlyph,
    ),
    '/api/users/list',
    'items',
    'user',
    ['username', 'display_name', 'role', 'user_pronoun', 'ai_pronoun'],
  ),
];

const _longFields = [
  'content',
  'result',
  'traces',
  'tool_chain',
  'sample_queries',
  'success_evidence',
  'embedding',
];
const _numberFields = ['importance', 'validation_count', 'memory_id', 'count'];

const _fieldLabels = {
  'type': 'Loại (Type)',
  'id': 'Mã bản ghi (ID)',
  'created_at': 'Tạo lúc (Created At)',
  'updated_at': 'Cập nhật lúc (Updated At)',
  'semantic_key': 'Khóa ngữ nghĩa (Semantic Key)',
  'mem_type': 'Loại bộ nhớ (Type)',
  'memory_id': 'Memory ID',
  'wiki_scope': 'Wiki Scope',
  'tool_chain': 'Tool Chain',
  'sample_queries': 'Mẫu câu truy vấn (Sample Queries)',
  'success_evidence': 'Bằng chứng thành công (Success Evidence)',
  'validation_count': 'Số lần kiểm chứng (Validation Count)',
  'status': 'Trạng thái (Status)',
  'wiki_path': 'Đường dẫn Wiki (Wiki Path)',
  'query': 'Câu hỏi / Truy vấn (Query)',
  'result': 'Kết quả (Result)',
  'traces': 'Dấu vết thực thi (Traces)',
  'tools': 'Công cụ',
  'wrong_tool': 'Đã dùng',
  'right_tool': 'Nên dùng',
  'count': 'Số lần sửa',
  'importance': 'Độ quan trọng (Importance 1-10)',
  'source': 'Nguồn gốc (Source)',
  'content': 'Nội dung (Content)',
  'title': 'Tiêu đề (Title)',
  'tags': 'Nhãn thẻ (Tags)',
  'role': 'Vai trò (Role)',
  'session_id': 'Phiên làm việc (Session ID)',
  'username': 'Tên đăng nhập (Username)',
  'display_name': 'Tên hiển thị (Display Name)',
  'user_pronoun': 'Xưng hô người dùng (User Pronoun)',
  'ai_pronoun': 'Xưng hô AI (AI Pronoun)',
  'embedding':
      'Vector embedding (JSON, để trống = xoá, gõ recompute = tính lại)',
  'embedding_dim': 'Số chiều embedding',
  'embedding_model': 'Model embedding',
  'device': 'Thiết bị',
};

// the device that opened a chat session (memory.ts DEVICE_LABELS)
const _deviceLabels = {
  'ios': 'iPhone/iPad · iOS',
  'android': 'Android',
  'desktop': 'Máy tính',
  'mobile': 'Điện thoại',
  'telegram': 'Telegram',
};

String _fieldLabel(String field) =>
    _fieldLabels[field] ??
    field
        .split('_')
        .map((w) => w.isEmpty ? w : w[0].toUpperCase() + w.substring(1))
        .join(' ');

/// memoryValueText: objects as indented JSON, null as "".
String _valueText(Object? v) => v is Map || v is List
    ? const JsonEncoder.withIndent('  ').convert(v)
    : v == null
    ? ''
    : '$v';

/// JS truthiness of the values a record holds.
bool _truthy(Object? v) => v != null && v != '' && v != 0 && v != false;

/// JS `a || b || c` over the strings of an answer.
String _firstOr(List<Object?> candidates, String fallback) {
  for (final c in candidates) {
    if (_truthy(c)) return '$c';
  }
  return fallback;
}

String _cut(String s, int n) => s.length > n ? s.substring(0, n) : s;

String _two(int n) => n.toString().padLeft(2, '0');

String _formatMetadataValue(String key, Object? value) {
  if (key == 'device') {
    return _deviceLabels['$value'] ?? 'Không rõ (phiên cũ)';
  }
  if (value is num &&
      (key.contains('time') ||
          key.contains('at') ||
          (value > 1500000000 && value < 2500000000))) {
    final ms = value > 1e11 ? value : value * 1000;
    final d = DateTime.fromMillisecondsSinceEpoch(ms.toInt());
    // toLocaleString("vi-VN", 2-digit...): "10:30:45 19/10/2026"
    return '${_two(d.hour)}:${_two(d.minute)}:${_two(d.second)} ${_two(d.day)}/${_two(d.month)}/${d.year}';
  }
  return _valueText(value);
}

String _itemTitle(Map<String, dynamic> item) {
  for (final k in const [
    'title',
    'display_name',
    'username',
    'semantic_key',
    'intent',
    'query',
    'content',
  ]) {
    final v = item[k];
    if (v != null && '$v'.trim().isNotEmpty) return _valueText(v);
  }
  return '#${item['id']}';
}

String _itemPreview(Map<String, dynamic> item) {
  if (item.containsKey('wrong_tool')) {
    return '${_valueText(item['wrong_tool'])} → ${_valueText(item['right_tool'])} · ${_valueText(item['count'])} lần';
  }
  final v =
      item['content'] ??
      item['result'] ??
      item['success_evidence'] ??
      item['mem_type'] ??
      item['source'] ??
      '';
  return _cut(_valueText(v).replaceAll(RegExp(r'\s+'), ' '), 160);
}

class MemoryPage extends StatefulWidget {
  const MemoryPage({super.key});

  @override
  State<MemoryPage> createState() => _MemoryPageState();
}

class _MemoryPageState extends State<MemoryPage> {
  late final ApiClient _api = context.read<ApiClient>();
  final _search = TextEditingController();
  String _kind = 'learning';
  List<Map<String, dynamic>> _items = [];
  String? _selectedId;
  int _offset = 0;
  int _total = 0;
  Map<String, int> _summary = {};
  bool _detail = false; // .show-detail-mobile
  bool _loading = true;
  String? _error;
  int _formGen =
      0; // a new list load re-creates the editor with the stored values
  final Set<String> _bulk = {};
  bool _bulkDeleting = false;
  bool _bulkRan = false;

  _Def get _def => _defs.firstWhere((d) => d.id == _kind);

  @override
  void initState() {
    super.initState();
    SharedPreferences.getInstance().then((prefs) {
      if (!mounted) return;
      final auth = context.read<AuthController?>();
      final isAdmin = auth?.currentUser?.isAdmin ?? true;
      const memberKinds = ['conversation', 'learning', 'evolution', 'gym'];
      final savedKind = prefs.getString(_memoryKindKey);
      if (savedKind != null && _defs.any((d) => d.id == savedKind)) {
        if (isAdmin || memberKinds.contains(savedKind)) {
          if (savedKind != _kind) {
            setState(() {
              _kind = savedKind;
              _offset = 0;
              _selectedId = null;
              _detail = false;
            });
            _load();
            return;
          }
        }
      }
    });
    _load();
  }

  @override
  void dispose() {
    _search.dispose();
    super.dispose();
  }

  Map<String, dynamic>? get _selected {
    for (final it in _items) {
      if ('${it['id']}' == _selectedId) return it;
    }
    return null;
  }

  Future<void> _loadSummary() async {
    try {
      final data = await _api.get<Map<String, dynamic>>(
        '/api/memory-control/summary',
      );
      if (data['success'] == true && data['counts'] is Map) {
        _summary = (data['counts'] as Map).map(
          (k, v) => MapEntry('$k', (v as num).toInt()),
        );
      }
    } catch (e) {
      debugPrint(
        '[memory] failed to load memory summary: $e',
      ); // web: console.error only
    }
  }

  int _loadSeq =
      0; // a slow answer for a tab already left must not fill the tab now shown

  Future<void> _load() async {
    final seq = ++_loadSeq;
    setState(() {
      _loading = true;
      _error = null;
      _bulk.clear();
    });
    final def = _def;
    try {
      await _loadSummary();
      if (!mounted || seq != _loadSeq) return;
      final query = Uri(
        queryParameters: {
          'q': _search.text.trim(),
          'limit': '$_pageSize',
          'offset': '$_offset',
        },
      ).query;
      final data = await _api.get<Map<String, dynamic>>(
        '${def.endpoint}?$query',
      );
      if (!mounted || seq != _loadSeq) return;
      if (data['success'] != true) {
        throw ApiException(_firstOr([data['error']], 'request_failed'));
      }
      final raw = data['items'] ?? data[def.responseKey] ?? const [];
      final items = [
        for (final e in raw as List) Map<String, dynamic>.from(e as Map),
      ];
      setState(() {
        _items = items;
        _total = (data['total'] as num?)?.toInt() ?? items.length;
        if (_selected == null) {
          _selectedId = items.isEmpty ? null : '${items.first['id']}';
        }
        _formGen++;
        _loading = false;
      });
    } catch (e) {
      if (mounted && seq == _loadSeq) {
        setState(() {
          _error = 'Lỗi tải bộ nhớ: $e';
          _loading = false;
        });
      }
    }
  }

  void _pick(String kind) {
    if (kind == _kind) return;
    setState(() {
      _kind = kind;
      _offset = 0;
      _selectedId = null;
      _detail = false;
    });
    SharedPreferences.getInstance().then((p) => p.setString(_memoryKindKey, kind));
    _load();
  }

  void _find() {
    _offset = 0;
    _load();
  }

  void _page(int delta) {
    _offset = (_offset + delta).clamp(0, 1 << 30);
    _detail = false;
    _load();
  }

  num _idNum(Map<String, dynamic> item) =>
      num.tryParse('${item['id']}') ?? 0;

  Future<bool?> _reembed(int? id) async {
    final res = await _api.post<Map<String, dynamic>>(
      '/api/learnings/reembed',
      {'id': id},
    );
    if (res['success'] != true) {
      throw ApiException(
        'Không thể tính lại embedding: ${_firstOr([res['error']], 'reembed_failed')}',
      );
    }
    return null;
  }

  Future<bool?> _reembedAll() async {
    if (!await memConfirm(
      context,
      'Tính lại embedding cho TOÀN BỘ bản ghi học? Đây có thể mất vài phút.',
    )) {
      return false;
    }
    return _reembed(null);
  }

  Future<bool?> _save(Map<String, Object?> values) async {
    final item = _selected;
    if (item == null) return false;
    final Map<String, dynamic> result;
    if (_kind == 'evolution') {
      result = await _api.post<Map<String, dynamic>>('/api/evolution/update', {
        'id': '${item['id']}',
        'content': values['content'],
      });
    } else if (_kind == 'user') {
      result = await _api.post<Map<String, dynamic>>('/api/users/update', {
        'id': '${item['id']}',
        'values': values,
      });
    } else if (_kind == 'gym') {
      result = {'success': true};
    } else {
      result = await _api.post<Map<String, dynamic>>(
        '/api/memory-control/update',
        {'kind': _kind, 'id': _idNum(item), 'values': values},
      );
    }
    if (result['success'] != true) {
      throw ApiException(
        'Không thể lưu bản ghi: ${_firstOr([result['error'], result['code']], 'update_failed')}',
      );
    }
    return null;
  }

  Future<Map<String, dynamic>> _gymDelete(String id) =>
      _api.delete<Map<String, dynamic>>(
        '/api/gym/delete?id=${Uri.encodeQueryComponent(id)}',
      );

  Future<Map<String, dynamic>> _userDelete(String id) =>
      _api.delete<Map<String, dynamic>>(
        '/api/users/delete?id=${Uri.encodeQueryComponent(id)}',
      );

  Future<bool?> _delete() async {
    final item = _selected;
    if (item == null) return false;
    final kind = _kind;
        if (kind == 'user') {
      if (item['id'] == 'admin' || item['role'] == 'admin') {
        throw ApiException('Không thể xóa tài khoản Quản trị viên (Admin)!');
      }
      if (!await memConfirm(
        context,
        'Xóa người dùng: ${_itemTitle(item)}?',
      )) {
        return false;
      }
      try {
        final r = await _userDelete('${item['id']}');
        if (r['success'] != true) {
          throw ApiException(_firstOr([r['error']], 'delete_failed'));
        }
      } on ApiException catch (e) {
        throw ApiException('Không thể xóa người dùng: ${e.message}');
      }
      return null;
    }
    if (kind == 'gym') {
      if (!await memConfirm(
        context,
        'Xóa bản ghi tập luyện: ${_itemTitle(item)}?',
      )) {
        return false;
      }
      try {
        final r = await _gymDelete('${item['id']}');
        if (r['success'] != true) {
          throw ApiException(_firstOr([r['error']], 'delete_failed'));
        }
      } on ApiException catch (e) {
        throw ApiException('Không thể xóa bản ghi: ${e.message}');
      }
      return null;
    }
    final dep = await _api.get<Map<String, dynamic>>(
      '/api/memory-control/dependencies?kind=${Uri.encodeQueryComponent(kind)}&id=${Uri.encodeQueryComponent('${item['id']}')}',
    );
    if (dep['success'] != true) {
      throw ApiException(
        'Không thể xóa bản ghi: ${_firstOr([dep['code']], 'dependency_preview_failed')}',
      );
    }
    final preview = const JsonEncoder.withIndent('  ').convert(dep['preview']);
    if (!mounted ||
        !await memConfirm(
          context,
          'Xác nhận xóa sau khi kiểm tra quan hệ:\n\n$preview',
        )) {
      return false;
    }
    final r = await _api.post<Map<String, dynamic>>(
      '/api/memory-control/delete',
      {'kind': kind, 'id': _idNum(item)},
    );
    if (r['success'] != true) {
      throw ApiException(
        'Không thể xóa bản ghi: ${_firstOr([r['code']], 'delete_failed')}',
      );
    }
    return null;
  }

  /// Deletes the ticked records one by one through the same delete API (one confirm for the group).
  Future<bool?> _deleteBulk() async {
    if (_bulkDeleting || _bulk.isEmpty) return false;
    final kind = _kind;
    final def = _def;
    final targets = _items.where((i) => _bulk.contains('${i['id']}')).toList();
    final names = targets
        .take(10)
        .map((i) => '• ${_cut(_itemTitle(i), 60)}')
        .join('\n');
    final more = targets.length > 10
        ? '\n… và ${targets.length - 10} mục khác'
        : '';
    if (!await memConfirm(
      context,
      'Xoá ${targets.length} bản ghi ${def.label}?\n\n$names$more',
    )) {
      return false;
    }
    _bulkRan = true;
    setState(() => _bulkDeleting = true);
    final failures = <String>[];
    for (final item in targets) {
      try {
        if (kind == 'user' &&
            (item['id'] == 'admin' || item['role'] == 'admin')) {
          throw ApiException('Không thể xóa tài khoản Quản trị viên (Admin)!');
        }
        final r = kind == 'gym'
            ? await _gymDelete('${item['id']}')
            : kind == 'user'
                ? await _userDelete('${item['id']}')
                : await _api.post<Map<String, dynamic>>(
                    '/api/memory-control/delete',
                    {'kind': kind, 'id': _idNum(item)},
                  );
        if (r['success'] != true) {
          throw ApiException(
            _firstOr([r['code'], r['error']], 'delete_failed'),
          );
        }
      } catch (e) {
        failures.add('#${item['id']} ${_cut(_itemTitle(item), 40)}: $e');
      }
    }
    if (mounted) setState(() => _bulkDeleting = false);
    if (failures.isNotEmpty) {
      throw ApiException(
        'Đã xoá ${targets.length - failures.length}/${targets.length}. Lỗi:\n${failures.join('\n')}',
      );
    }
    return null;
  }

  Future<void> _afterBulk(bool ok) async {
    if (mounted) setState(() => _bulkDeleting = false);
    if (!_bulkRan) return;
    _bulkRan = false;
    _selectedId = null;
    if (mounted) await _load();
  }

  Future<void> _afterDelete(bool ok) async {
    if (!ok || !mounted) return;
    _selectedId = null;
    await _load();
  }

  Future<void> _reload(bool ok) async {
    if (mounted) await _load();
  }

  @override
  Widget build(BuildContext context) {
    final auth = context.watch<AuthController?>();
    final isAdmin = auth?.currentUser?.isAdmin ?? true;
    const memberKinds = ['conversation', 'learning', 'evolution', 'gym'];
    final visibleDefs = isAdmin ? _defs : _defs.where((d) => memberKinds.contains(d.id)).toList();
    if (!isAdmin && !memberKinds.contains(_kind)) {
      _kind = 'conversation';
    }
    final page = settingsPages.firstWhere((p) => p.id == 'memory');
    final selected = _selected;
    final showDetail = _detail && selected != null;
    return PageScaffold(
      page: page,
      scrollable: false,
      body: Padding(
        padding: const EdgeInsets.fromLTRB(16, 0, 16, 10),
        child: showDetail
            ? _MemoryDetail(
                key: ValueKey('$_kind:${selected['id']}:$_formGen'),
                def: _def,
                item: selected,
                onBack: () => setState(() => _detail = false),
                onSave: _save,
                onSaved: (ok) => ok ? _reload(ok) : Future.value(),
                onDelete: _delete,
                onDeleted: _afterDelete,
                onReembed: () =>
                    _reembed(num.tryParse('${selected['id']}')?.toInt()),
                onReembedded: _reload,
              )
            : Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  MemPanel(
                    padding: const EdgeInsets.fromLTRB(10, 8, 10, 8),
                    child: MemCatNav(
                      cats: [for (final d in visibleDefs) d.cat],
                      active: _kind,
                      onSelect: _pick,
                      counts: {
                        for (final d in visibleDefs)
                          if (d.countKey != null)
                            d.id: _summary[d.countKey] ?? _summary[d.id] ?? 0,
                      },
                    ),
                  ),
                  const SizedBox(height: 8),
                  Expanded(child: _listPanel()),
                ],
              ),
      ),
    );
  }

  Widget _listPanel() {
    final selectableItems = _kind == 'user'
        ? _items
            .where((i) => !(i['id'] == 'admin' || i['role'] == 'admin'))
            .toList()
        : _items;
    final all = selectableItems.isNotEmpty &&
        _bulk.length == selectableItems.length;
    final evolution = _kind == 'evolution';
    final status =
        '${(_offset + 1).clamp(0, _total)}–${(_offset + _items.length).clamp(0, _total)} / $_total';
    return MemPanel(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              Expanded(
                child: SdInput(
                  key: const Key('memory-search'),
                  controller: _search,
                  hint: 'Tìm trong nhóm đang chọn…',
                  onSubmitted: (_) => _find(),
                ),
              ),
              const SizedBox(width: 8),
              MemButton(
                label: 'Tìm',
                icon: searchGlyph,
                height: 38,
                onPressed: _find,
              ),
            ],
          ),
          Container(
            margin: const EdgeInsets.only(top: 12, bottom: 10),
            padding: const EdgeInsets.only(bottom: 8),
            decoration: const BoxDecoration(
              border: Border(bottom: BorderSide(color: Color(0x0FFFFFFF))),
            ),
            child: Row(
              children: [
                Expanded(
                  child: Row(
                    children: [
                      SizedBox(
                        width: 24,
                        height: 24,
                        child: Checkbox(
                          key: const Key('select-all'),
                          value: all ? true : (_bulk.isEmpty ? false : null),
                          tristate: true,
                          onChanged:
                              _bulkDeleting || selectableItems.isEmpty || evolution
                              ? null
                              : (_) => setState(() {
                                  if (all) {
                                    _bulk.clear();
                                  } else {
                                    _bulk.addAll(
                                      selectableItems.map((i) => '${i['id']}'),
                                    );
                                  }
                                }),
                          activeColor: JTokens.accent,
                          checkColor: const Color(0xFF04121C),
                          side: const BorderSide(
                            color: JTokens.muted,
                            width: 1.5,
                          ),
                        ),
                      ),
                      const SizedBox(width: 6),
                      const Flexible(
                        child: Text(
                          'Chọn tất cả',
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: TextStyle(
                            fontSize: JTokens.fsSmall,
                            color: JTokens.text,
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
                ActionButton(
                  kind: ActionKind.delete,
                  label: 'Xoá đã chọn (${_bulk.length})',
                  destructive: true,
                  compact: true,
                  enabled: !_bulkDeleting && _bulk.isNotEmpty,
                  okText: 'Đã xoá',
                  task: _deleteBulk,
                  onDone: _afterBulk,
                ),
              ],
            ),
          ),
          if (_kind == 'learning')
            Padding(
              padding: const EdgeInsets.only(bottom: 10),
              child: SizedBox(
                width: double.infinity,
                child: ActionButton(
                  kind: ActionKind.refresh,
                  label: 'Tính lại tất cả embedding',
                  compact: true,
                  okText: 'Đã tính lại embedding cho tất cả',
                  task: _reembedAll,
                  onDone: _reload,
                ),
              ),
            ),
          Expanded(child: _records()),
          Container(
            margin: const EdgeInsets.only(top: 4),
            padding: const EdgeInsets.only(top: 12),
            decoration: const BoxDecoration(
              border: Border(top: BorderSide(color: Color(0x0FFFFFFF))),
            ),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                MemButton(
                  label: 'Trước',
                  icon: chevronLeftGlyph,
                  height: 30,
                  fontSize: JTokens.fsSmall,
                  onPressed: _offset == 0 ? null : () => _page(-_pageSize),
                ),
                Flexible(
                  child: Container(
                    margin: const EdgeInsets.symmetric(horizontal: 4),
                    padding: const EdgeInsets.symmetric(
                      horizontal: 10,
                      vertical: 4,
                    ),
                    decoration: BoxDecoration(
                      color: const Color(0x0AFFFFFF),
                      borderRadius: BorderRadius.circular(9999),
                      border: Border.all(color: const Color(0x0FFFFFFF)),
                    ),
                    child: Text(
                      status,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                        fontSize: JTokens.fsSmall,
                        fontWeight: FontWeight.w500,
                        color: JTokens.muted,
                        fontFeatures: [FontFeature.tabularFigures()],
                      ),
                    ),
                  ),
                ),
                MemButton(
                  label: 'Sau',
                  icon: chevronRightGlyph,
                  iconAfter: true,
                  height: 30,
                  fontSize: JTokens.fsSmall,
                  onPressed: _offset + _pageSize >= _total
                      ? null
                      : () => _page(_pageSize),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _records() {
    if (_loading) {
      return const Align(
        alignment: Alignment.topLeft,
        child: SdEmpty('Đang tải danh sách bản ghi…'),
      );
    }
    if (_error != null) {
      return Align(
        alignment: Alignment.topLeft,
        child: SdEmpty(_error!, error: true),
      );
    }
    if (_items.isEmpty) {
      return SingleChildScrollView(
        child: _EmptyBox(
          icon: _def.cat.icon,
          title: 'Không có dữ liệu',
          sub:
              'Nhóm ${_def.label} chưa có bản ghi nào hoặc không khớp từ khóa tìm kiếm.',
        ),
      );
    }
    return ListView.separated(
      itemCount: _items.length,
      separatorBuilder: (_, _) => const SizedBox(height: 8),
      itemBuilder: (_, i) {
        final item = _items[i];
        final id = '${item['id']}';
        final isUserAdmin =
            _kind == 'user' && (id == 'admin' || item['role'] == 'admin');
        return _RecordCard(
          key: Key('rec:$id'),
          item: item,
          color: _def.color,
          selected: id == _selectedId,
          checkbox: _kind != 'evolution' && !isUserAdmin,
          checked: _bulk.contains(id),
          onToggle: () => setState(() {
            if (!_bulk.remove(id)) _bulk.add(id);
          }),
          onOpen: () => setState(() {
            _selectedId = id;
            _detail = true;
          }),
        );
      },
    );
  }
}

class _EmptyBox extends StatelessWidget {
  const _EmptyBox({required this.icon, required this.title, required this.sub});

  final MorphGlyph icon;
  final String title;
  final String sub;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 36, horizontal: 16),
    child: Column(
      children: [
        Container(
          width: 44,
          height: 44,
          margin: const EdgeInsets.only(bottom: 12),
          decoration: BoxDecoration(
            color: const Color(0x0AFFFFFF),
            borderRadius: BorderRadius.circular(12),
          ),
          child: Center(
            child: MorphIcon(
              icon: icon,
              size: 22,
              strokeWidth: 2,
              color: JTokens.muted,
            ),
          ),
        ),
        Padding(
          padding: const EdgeInsets.only(bottom: 4),
          child: Text(
            title,
            style: const TextStyle(
              fontSize: JTokens.fsBody,
              fontWeight: FontWeight.w600,
              color: JTokens.text,
            ),
          ),
        ),
        ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 240),
          child: Text(
            sub,
            textAlign: TextAlign.center,
            style: const TextStyle(
              fontSize: JTokens.fsSmall,
              height: 1.4,
              color: JTokens.muted,
            ),
          ),
        ),
      ],
    ),
  );
}

/// `.sd-mem-record-card`: category-coloured left edge, optional tick box, title + type tag, two lines of preview.
class _RecordCard extends StatelessWidget {
  const _RecordCard({
    super.key,
    required this.item,
    required this.color,
    required this.selected,
    required this.checkbox,
    required this.checked,
    required this.onToggle,
    required this.onOpen,
  });

  final Map<String, dynamic> item;
  final Color color;
  final bool selected;
  final bool checkbox;
  final bool checked;
  final VoidCallback onToggle;
  final VoidCallback onOpen;

  @override
  Widget build(BuildContext context) {
    final badge = [
      item['type'],
      item['mem_type'],
      item['status'],
    ].firstWhere(_truthy, orElse: () => null);
    return GestureDetector(
      behavior: HitTestBehavior.opaque,
      onTap: onOpen,
      child: Container(
        decoration: BoxDecoration(
          gradient: selected
              ? const LinearGradient(
                  colors: [Color(0x1400D2FF), Color(0x08FFFFFF)],
                )
              : null,
          color: selected ? null : const Color(0x05FFFFFF),
          borderRadius: BorderRadius.circular(8),
          border: Border.all(
            color: selected ? const Color(0x6600D2FF) : JTokens.border,
          ),
          boxShadow: selected
              ? const [
                  BoxShadow(
                    color: Color(0x40000000),
                    blurRadius: 12,
                    offset: Offset(0, 2),
                  ),
                ]
              : null,
        ),
        child: ClipRRect(
          borderRadius: BorderRadius.circular(7),
          child: IntrinsicHeight(
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Container(width: 3.5, color: color),
                Expanded(
                  child: Padding(
                    padding: const EdgeInsets.fromLTRB(12, 10, 12, 10),
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        if (checkbox) ...[
                          Padding(
                            padding: const EdgeInsets.only(top: 1),
                            child: SizedBox(
                              width: 20,
                              height: 20,
                              child: Checkbox(
                                key: Key('sel:${item['id']}'),
                                value: checked,
                                onChanged: (_) => onToggle(),
                                activeColor: JTokens.accent,
                                checkColor: const Color(0xFF04121C),
                                side: const BorderSide(
                                  color: JTokens.muted,
                                  width: 1.5,
                                ),
                              ),
                            ),
                          ),
                          const SizedBox(width: 10),
                        ],
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Row(
                                children: [
                                  Expanded(
                                    child: Text(
                                      _itemTitle(item),
                                      maxLines: 1,
                                      overflow: TextOverflow.ellipsis,
                                      style: const TextStyle(
                                        fontSize: JTokens.fsUi,
                                        fontWeight: FontWeight.w600,
                                        color: Colors.white,
                                      ),
                                    ),
                                  ),
                                  if (badge != null) ...[
                                    const SizedBox(width: 8),
                                    Container(
                                      padding: const EdgeInsets.symmetric(
                                        horizontal: 6,
                                        vertical: 1,
                                      ),
                                      decoration: BoxDecoration(
                                        color: const Color(0x0DFFFFFF),
                                        borderRadius: BorderRadius.circular(4),
                                        border: Border.all(
                                          color: const Color(0x12FFFFFF),
                                        ),
                                      ),
                                      child: Text(
                                        '$badge'.toLowerCase(),
                                        style: const TextStyle(
                                          fontSize: JTokens.fsSmall,
                                          fontWeight: FontWeight.w500,
                                          color: JTokens.muted,
                                        ),
                                      ),
                                    ),
                                  ],
                                ],
                              ),
                              const SizedBox(height: 4),
                              Text(
                                _itemPreview(item),
                                maxLines: 2,
                                overflow: TextOverflow.ellipsis,
                                style: const TextStyle(
                                  fontSize: JTokens.fsSmall,
                                  height: 1.45,
                                  color: JTokens.muted,
                                ),
                              ),
                            ],
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

/// `#memory-detail-container` on a phone: back button, badge + id (or file name), delete; one input per editable field; the read-only
/// "Thông tin hệ thống" box; and the pinned save / re-embed row.
class _MemoryDetail extends StatefulWidget {
  const _MemoryDetail({
    super.key,
    required this.def,
    required this.item,
    required this.onBack,
    required this.onSave,
    required this.onSaved,
    required this.onDelete,
    required this.onDeleted,
    required this.onReembed,
    required this.onReembedded,
  });

  final _Def def;
  final Map<String, dynamic> item;
  final VoidCallback onBack;
  final Future<bool?> Function(Map<String, Object?> values) onSave;
  final Future<void> Function(bool ok) onSaved;
  final Future<bool?> Function() onDelete;
  final Future<void> Function(bool ok) onDeleted;
  final Future<bool?> Function() onReembed;
  final Future<void> Function(bool ok) onReembedded;

  @override
  State<_MemoryDetail> createState() => _MemoryDetailState();
}

class _MemoryDetailState extends State<_MemoryDetail> {
  late final Map<String, TextEditingController> _controllers = {
    for (final f in widget.def.fields)
      f: TextEditingController(text: _valueText(widget.item[f])),
  };

  @override
  void dispose() {
    for (final c in _controllers.values) {
      c.dispose();
    }
    super.dispose();
  }

  Future<bool?> _save() => widget.onSave({
    for (final e in _controllers.entries)
      e.key: _numberFields.contains(e.key)
          ? (num.tryParse(e.value.text) ?? 0) // Number(""), as the number input
          : e.value.text,
  });

  Widget _field(String field) {
    final long = _longFields.contains(field);
    final number = _numberFields.contains(field);
    final rows = widget.def.id == 'evolution' ? 16 : 4;
    final label = _fieldLabel(field);
    OutlineInputBorder border(Color c) => OutlineInputBorder(
      borderRadius: BorderRadius.circular(8),
      borderSide: BorderSide(color: c),
    );
    return Padding(
      key: Key('field:$field'),
      padding: const EdgeInsets.only(bottom: 14),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(
            label,
            style: const TextStyle(
              fontSize: JTokens.fsSmall,
              fontWeight: FontWeight.w600,
              color: JTokens.text,
            ),
          ),
          const SizedBox(height: 6),
          ConstrainedBox(
            constraints: BoxConstraints(minHeight: long ? 120 : 0),
            child: TextField(
              controller: _controllers[field],
              keyboardType: number
                  ? const TextInputType.numberWithOptions(decimal: true)
                  : long
                  ? TextInputType.multiline
                  : TextInputType.text,
              minLines: long ? rows : 1,
              maxLines: long ? rows : 1,
              autocorrect: false,
              style: TextStyle(
                color: Colors.white,
                fontSize: JTokens.fsUi,
                height: long ? 1.6 : null,
              ),
              decoration: InputDecoration(
                hintText: 'Nhập $label…',
                hintStyle: const TextStyle(color: JTokens.textMuted),
                isDense: true,
                filled: true,
                fillColor: JTokens.surface2,
                contentPadding: const EdgeInsets.symmetric(
                  horizontal: 12,
                  vertical: 9,
                ),
                border: border(JTokens.borderStrong),
                enabledBorder: border(JTokens.borderStrong),
                focusedBorder: border(JTokens.accent),
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _meta() {
    final skip = {...widget.def.fields, 'editable'};
    final entries = widget.item.entries
        .where((e) => !skip.contains(e.key))
        .toList();
    if (entries.isEmpty) return const SizedBox.shrink();
    return Container(
      margin: const EdgeInsets.only(bottom: 16),
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      decoration: BoxDecoration(
        color: const Color(0x40000000),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: const Color(0x0FFFFFFF)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const Padding(
            padding: EdgeInsets.only(bottom: 8),
            child: Text(
              'Thông tin hệ thống',
              style: TextStyle(
                fontSize: JTokens.fsSmall,
                fontWeight: FontWeight.w600,
                letterSpacing: 0.65,
                color: JTokens.muted,
              ),
            ),
          ),
          for (final e in entries)
            Padding(
              padding: const EdgeInsets.only(bottom: 6),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.baseline,
                textBaseline: TextBaseline.alphabetic,
                children: [
                  Flexible(
                    child: Text(
                      '${_fieldLabel(e.key)}:',
                      style: const TextStyle(
                        fontSize: JTokens.fsSmall,
                        color: JTokens.muted,
                      ),
                    ),
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      _formatMetadataValue(e.key, e.value),
                      style: const TextStyle(
                        fontSize: JTokens.fsSmall,
                        color: JTokens.text,
                        fontFeatures: [FontFeature.tabularFigures()],
                      ),
                    ),
                  ),
                ],
              ),
            ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final def = widget.def;
    final evolution = def.id == 'evolution';
    return MemPanel(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Expanded(
            child: SingleChildScrollView(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Container(
                    padding: const EdgeInsets.only(bottom: 14),
                    margin: const EdgeInsets.only(bottom: 16),
                    decoration: const BoxDecoration(
                      border: Border(
                        bottom: BorderSide(color: Color(0x14FFFFFF)),
                      ),
                    ),
                    child: Row(
                      children: [
                        MemButton(
                          label: '← Danh sách',
                          onPressed: widget.onBack,
                        ),
                        const SizedBox(width: 12),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Container(
                                margin: const EdgeInsets.only(bottom: 4),
                                padding: const EdgeInsets.symmetric(
                                  horizontal: 8,
                                  vertical: 2,
                                ),
                                decoration: BoxDecoration(
                                  color: const Color(0x0AFFFFFF),
                                  borderRadius: BorderRadius.circular(6),
                                  border: Border.all(
                                    color: const Color(0x0FFFFFFF),
                                  ),
                                ),
                                child: Row(
                                  mainAxisSize: MainAxisSize.min,
                                  children: [
                                    MorphIcon(
                                      icon: def.cat.active,
                                      size: 14,
                                      strokeWidth: 2,
                                      color: def.color,
                                    ),
                                    const SizedBox(width: 6),
                                    Flexible(
                                      child: Text(
                                        def.label,
                                        maxLines: 1,
                                        overflow: TextOverflow.ellipsis,
                                        style: TextStyle(
                                          fontSize: JTokens.fsSmall,
                                          fontWeight: FontWeight.w600,
                                          color: def.color,
                                        ),
                                      ),
                                    ),
                                  ],
                                ),
                              ),
                              Text(
                                evolution
                                    ? _valueText(widget.item['title'])
                                    : def.id == 'user'
                                        ? _valueText(widget.item['display_name'] ?? widget.item['username'] ?? widget.item['id'])
                                        : 'Bản ghi #${widget.item['id']}',
                                style: const TextStyle(
                                  fontSize: JTokens.fsTitle,
                                  fontWeight: FontWeight.w700,
                                  color: Colors.white,
                                ),
                              ),
                            ],
                          ),
                        ),
                        if (!evolution && !(def.id == 'user' && (widget.item['id'] == 'admin' || widget.item['role'] == 'admin'))) ...[
                          const SizedBox(width: 12),
                          ActionButton(
                            kind: ActionKind.delete,
                            label: 'Xóa',
                            destructive: true,
                            height: 40,
                            okText: 'Đã xoá',
                            task: widget.onDelete,
                            onDone: widget.onDeleted,
                          ),
                        ],
                      ],
                    ),
                  ),
                  for (final f in def.fields) _field(f),
                  _meta(),
                ],
              ),
            ),
          ),
          Container(
            padding: const EdgeInsets.only(top: 10),
            decoration: const BoxDecoration(
              border: Border(top: BorderSide(color: Color(0x14FFFFFF))),
            ),
            child: Wrap(
              alignment: WrapAlignment.end,
              spacing: 8,
              runSpacing: 8,
              children: [
                if (def.id != 'gym')
                  ActionButton(
                    kind: ActionKind.save,
                    label: 'Lưu thay đổi',
                    primary: true,
                    height: 38,
                    minWidth: 130,
                    task: _save,
                    onDone: widget.onSaved,
                  ),
                if (def.id == 'learning')
                  ActionButton(
                    kind: ActionKind.refresh,
                    label: 'Tính lại embedding',
                    height: 40,
                    okText: 'Đã tính lại embedding cho #${widget.item['id']}',
                    task: widget.onReembed,
                    onDone: widget.onReembedded,
                  ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
