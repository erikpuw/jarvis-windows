import 'package:flutter/material.dart';
import 'package:jarvis_mobile/chat/lucide_glyphs.dart';
import 'package:jarvis_mobile/chat/markdown_view.dart';
import 'package:jarvis_mobile/net/api_client.dart';
import 'package:jarvis_mobile/net/server_config.dart';
import 'package:jarvis_mobile/settings/mem_widgets.dart';
import 'package:jarvis_mobile/settings/page_scaffold.dart';
import 'package:jarvis_mobile/settings/pages.dart';
import 'package:jarvis_mobile/theme/tokens.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:jarvis_mobile/chat/sessions_controller.dart';

/// Nhật ký (logs.ts): session list and reader, plus the three log files.
const _logLines = 300;
const _logsTabKey = 'jarvis.settings.logs_tab';

class _Tab {
  const _Tab(this.cat, [this.path]);
  final MemCat cat;
  final String? path;
  String get id => cat.id;
  String get label => cat.label;
}

const _tabs = <_Tab>[
  _Tab(
    MemCat(
      id: 'history',
      label: 'Lịch sử chat',
      color: Color(0xFF60A5FA),
      icon: messagesSquareGlyph,
    ),
  ),
  _Tab(
    MemCat(
      id: 'jarvis',
      label: 'Jarvis log',
      color: Color(0xFFA78BFA),
      icon: scrollTextGlyph,
    ),
    '/api/logs?lines=$_logLines',
  ),
  _Tab(
    MemCat(
      id: 'security',
      label: 'Log bảo mật',
      color: Color(0xFFF59E0B),
      icon: shieldAlertGlyph,
    ),
    '/api/logs/security?lines=$_logLines',
  ),
  _Tab(
    MemCat(
      id: 'tts',
      label: 'Log TTS',
      color: Color(0xFF22D3EE),
      icon: audioLinesGlyph,
    ),
    '/api/logs/tts?lines=$_logLines',
  ),
];

const _sourceLabel = {
  'web': 'Web',
  'telegram': 'Telegram',
  'legacy': 'Cũ (chưa có phiên)',
};
const _sourceShort = {'web': 'Web', 'telegram': 'Telegram', 'legacy': 'Cũ'};
// the device that opened a web session (none for sessions older than session_devices)
const _deviceShort = {
  'ios': 'iOS',
  'android': 'Android',
  'desktop': 'PC',
  'mobile': 'Mobile',
};

String _two(int n) => n.toString().padLeft(2, '0');

String _hm(DateTime d) => '${_two(d.hour)}:${_two(d.minute)}';

String _dayLabel(DateTime d) {
  final now = DateTime.now();
  bool same(DateTime a, DateTime b) =>
      a.year == b.year && a.month == b.month && a.day == b.day;
  if (same(d, now)) return 'Hôm nay';
  if (same(d, now.subtract(const Duration(days: 1)))) return 'Hôm qua';
  return '${_two(d.day)}/${_two(d.month)}/${d.year}';
}

DateTime _at(Object? seconds) => DateTime.fromMillisecondsSinceEpoch(
  ((seconds as num?) ?? 0).toInt() * 1000,
);

String _errOr(Object? e) => (e == null || e == '') ? 'lỗi không rõ' : '$e';

bool _truthy(Object? v) => v != null && v != '' && v != 0 && v != false;

class LogsPage extends StatefulWidget {
  const LogsPage({super.key});

  @override
  State<LogsPage> createState() => _LogsPageState();
}

class _LogsPageState extends State<LogsPage> {
  late final ApiClient _api = context.read<ApiClient>();
  String _active = 'history';
  String _owner = '';
  List<Map<String, dynamic>> _users = [];
  String? _openSession;
  String? _openSource;
  int _loadSeq = 0; // a slow answer of a tab the user already left must not overwrite the one on screen
  int _listSeq = 0;
  int _detailSeq = 0;

  // The session reader: a note or the messages.
  String? _readerNote;
  List<Map<String, dynamic>>? _messages;
  String? _sessionsNote;
  List<Map<String, dynamic>>? _sessions;
  String? _logNote;
  String? _logText;

  final _scroll = ScrollController();

  _Tab get _tab => _tabs.firstWhere((t) => t.id == _active);
  bool get _reading => _active == 'history' && _openSession != null;

  @override
  void initState() {
    super.initState();
    SharedPreferences.getInstance().then((prefs) {
      if (!mounted) return;
      final saved = prefs.getString(_logsTabKey);
      if (saved != null &&
          saved != _active &&
          _tabs.any((t) => t.id == saved)) {
        _showTab(saved);
      }
    });
    _load();
  }

  @override
  void dispose() {
    _scroll.dispose();
    super.dispose();
  }

  void _toEnd() => WidgetsBinding.instance.addPostFrameCallback((_) {
    if (_scroll.hasClients) _scroll.jumpTo(_scroll.position.maxScrollExtent);
  });

  void _showTab(String id) {
    setState(() {
      _active = id;
      _openSession = null;
    });
    SharedPreferences.getInstance().then((p) => p.setString(_logsTabKey, id));
    _load();
  }

  Future<void> _load() async {
    final seq = ++_loadSeq;
    final tab = _tab;
    if (tab.id == 'history') {
      await _loadSessionList();
      if (_openSession != null) await _loadSessionDetail();
      return;
    }
    setState(() {
      _logNote = 'Đang tải…';
      _logText = null;
    });
    try {
      final data = await _api.get<Map<String, dynamic>>(tab.path!);
      if (seq != _loadSeq || !mounted) return;
      setState(() {
        if (data['success'] == true) {
          _logNote = null;
          _logText = '${data['logs'] ?? ''}';
          _toEnd();
        } else {
          _logNote = 'Không tải được ${tab.label}: ${_errOr(data['error'])}';
        }
      });
    } catch (_) {
      if (seq != _loadSeq || !mounted) return;
      setState(() => _logNote = 'Lỗi kết nối khi tải.');
    }
  }

  void _setMessages(List raw) {
    if (raw.isEmpty) {
      _messages = null;
      _readerNote = 'Chưa có hội thoại nào được lưu.';
      return;
    }
    _readerNote = null;
    _messages = [for (final m in raw) Map<String, dynamic>.from(m as Map)];
    _toEnd();
  }

  Future<void> _loadSessionList() async {
    final seq = ++_listSeq;
    setState(() {
      _sessionsNote = 'Đang tải…';
      _sessions = null;
      if (_openSession == null) {
        _readerNote = 'Chọn một phiên ở bên trái để xem.';
        _messages = null;
      }
    });
    try {
      final data = await _api.get<Map<String, dynamic>>(
        '/api/conversations/sessions?limit=50&user=${Uri.encodeComponent(_owner)}',
      );
      if (seq != _listSeq || !mounted) return;
      if (data['success'] != true) {
        setState(
          () => _sessionsNote =
              'Không tải được danh sách phiên chat: ${_errOr(data['error'])}',
        );
        return;
      }
      final rows = [
        for (final s in (data['sessions'] as List?) ?? const [])
          Map<String, dynamic>.from(s as Map),
      ];
      setState(() {
        _users = [
          for (final u in (data['users'] as List?) ?? const [])
            Map<String, dynamic>.from(u as Map),
        ];
        if (rows.isEmpty) {
          _sessionsNote = 'Chưa có phiên chat nào.';
        } else {
          _sessionsNote = null;
          _sessions = rows;
        }
      });
    } catch (_) {
      if (seq == _listSeq && mounted) {
        setState(() => _sessionsNote = 'Lỗi kết nối khi tải.');
      }
    }
  }

  void _selectSession(String id, String? source) {
    setState(() {
      _openSession = id;
      _openSource = source;
    });
    _loadSessionDetail();
  }

  Future<void> _loadSessionDetail() async {
    final id = _openSession;
    if (id == null) {
      setState(() {
        _readerNote = 'Chọn một phiên ở bên trái để xem.';
        _messages = null;
      });
      return;
    }
    final seq = ++_detailSeq;
    setState(() {
      _readerNote = 'Đang tải…';
      _messages = null;
    });
    try {
      final data = await _api.get<Map<String, dynamic>>(
        '/api/conversations/session/${Uri.encodeComponent(id)}',
      );
      if (seq != _detailSeq || _openSession != id || !mounted) return;
      setState(() {
        if (data['success'] == true) {
          _setMessages((data['messages'] as List?) ?? const []);
        } else {
          _messages = null;
          _readerNote = 'Không tải được phiên chat: ${_errOr(data['error'])}';
        }
      });
    } catch (_) {
      if (seq == _detailSeq && mounted) {
        setState(() {
          _messages = null;
          _readerNote = 'Lỗi kết nối khi tải.';
        });
      }
    }
  }

  Future<void> _deleteCurrentSession() async {
    final sid = _openSession;
    if (sid == null) return;
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: JTokens.surface,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(16),
          side: const BorderSide(color: JTokens.border),
        ),
        title: const Text(
          'Xóa phiên chat',
          style: TextStyle(
            fontSize: 18,
            fontWeight: FontWeight.bold,
            color: JTokens.text,
          ),
        ),
        content: Text(
          'Bạn có chắc chắn muốn xóa toàn bộ lịch sử của phiên chat "$sid" không?',
          style: const TextStyle(fontSize: 14, color: JTokens.muted),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(false),
            child: const Text('Hủy', style: TextStyle(color: JTokens.muted)),
          ),
          TextButton(
            key: const Key('delete-session-confirm-btn'),
            onPressed: () => Navigator.of(ctx).pop(true),
            child: const Text(
              'Xóa',
              style: TextStyle(
                color: Color(0xFFF87171),
                fontWeight: FontWeight.bold,
              ),
            ),
          ),
        ],
      ),
    );
    if (confirmed == true && mounted) {
      try {
        final res = await _api.delete<Map<String, dynamic>>(
          '/api/conversations/session/${Uri.encodeComponent(sid)}',
        );
        if (res['success'] == true) {
          if (!mounted) return;
          context.read<SessionsController?>()?.sessionDeleted(sid);
          setState(() {
            _openSession = null;
            _detailSeq++;
            _readerNote = 'Đã xóa phiên chat.';
            _messages = null;
          });
          await _loadSessionList();
        } else {
          if (!mounted) return;
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Text(
                'Không thể xóa phiên: ${res['error'] ?? 'lỗi không rõ'}',
              ),
            ),
          );
        }
      } catch (e) {
        if (!mounted) return;
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('Lỗi khi xóa phiên: $e')));
      }
    }
  }

  void _back() {
    setState(() {
      _openSession = null;
      _detailSeq++;
      _readerNote = 'Chọn một phiên ở bên trái để xem.';
      _messages = null;
    });
  }

  @override
  Widget build(BuildContext context) {
    final page = settingsPages.firstWhere((p) => p.id == 'logs');
    final history = _active == 'history';
    return PageScaffold(
      page: page,
      scrollable: false,
      showDescription: false, // #page-logs .sd-page-head p {display:none}
      body: Padding(
        padding: const EdgeInsets.fromLTRB(16, 0, 16, 10),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            MemPanel(
              padding: const EdgeInsets.fromLTRB(10, 8, 10, 8),
              child: MemCatNav(
                cats: [for (final t in _tabs) t.cat],
                active: _active,
                onSelect: (id) {
                  if (id != _active) _showTab(id);
                },
              ),
            ),
            const SizedBox(height: 8),
            Expanded(
              child: MemPanel(
                padding: const EdgeInsets.all(12),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    if (!_reading)
                      Row(
                        children: [
                          Expanded(
                            child: Text(
                              _tab.label,
                              style: const TextStyle(
                                fontSize: JTokens.fsUi,
                                fontWeight: FontWeight.w600,
                                color: JTokens.text,
                              ),
                            ),
                          ),
                          MemButton(label: 'Làm mới', onPressed: _load),
                        ],
                      ),
                    if (history) _subbar(),
                    Expanded(child: history ? _historyBody() : _logBody()),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _subbar() {
    if (!_reading) {
      return DropdownButton<String>(
        key: const Key('history-owner-filter'),
        value: _owner,
        isExpanded: true,
        items: [
          const DropdownMenuItem(value: '', child: Text('Tất cả')),
          for (final u in _users)
            DropdownMenuItem(value: '${u['id']}', child: Text('${u['name']}')),
        ],
        onChanged: (v) {
          if (v == null) return;
          setState(() => _owner = v);
          _loadSessionList();
        },
      );
    }
    return Padding(
      padding: const EdgeInsets.only(top: 10),
      child: Row(
        children: [
          Flexible(
            child: MemButton(label: '← Danh sách phiên chat', onPressed: _back),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              '${_openSource != null ? '${_sourceLabel[_openSource] ?? _openSource} · ' : ''}$_openSession',
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(
                fontSize: JTokens.fsSmall,
                color: JTokens.muted,
              ),
            ),
          ),
          const SizedBox(width: 8),
          GestureDetector(
            key: const Key('history-delete-session-btn'),
            onTap: _deleteCurrentSession,
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
              decoration: BoxDecoration(
                color: const Color(0x1AF87171),
                borderRadius: BorderRadius.circular(6),
                border: Border.all(color: const Color(0x33F87171)),
              ),
              child: const Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Icon(
                    Icons.delete_outline,
                    size: 14,
                    color: Color(0xFFF87171),
                  ),
                  SizedBox(width: 4),
                  Text(
                    'Xóa phiên',
                    style: TextStyle(
                      fontSize: JTokens.fsSmall,
                      fontWeight: FontWeight.w500,
                      color: Color(0xFFF87171),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _note(String text) => Center(
    child: Padding(
      padding: const EdgeInsets.symmetric(vertical: 50, horizontal: 20),
      child: Text(
        text,
        textAlign: TextAlign.center,
        style: const TextStyle(fontSize: JTokens.fsSmall, color: JTokens.muted),
      ),
    ),
  );

  Widget _historyBody() => Padding(
    padding: const EdgeInsets.only(top: 10),
    child: Container(
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        border: Border.all(color: JTokens.border),
        borderRadius: BorderRadius.circular(12),
      ),
      child: _reading ? _reader() : _sessionList(),
    ),
  );

  Widget _sessionList() {
    final rows = _sessions;
    if (rows == null) return _note(_sessionsNote ?? '');
    return ListView.separated(
      itemCount: rows.length,
      separatorBuilder: (_, _) => const SizedBox(height: 4),
      itemBuilder: (_, i) {
        final s = rows[i];
        final id = '${s['session_id']}';
        final source = '${s['source']}';
        final device = source == 'web' && _truthy(s['device'])
            ? _deviceShort['${s['device']}']
            : null;
        final when = _at(s['last_msg']);
        final (bg, fg) = switch (source) {
          'web' => (const Color(0x2E60A5FA), const Color(0xFF93C5FD)),
          'telegram' => (const Color(0x2E22D3EE), const Color(0xFF67E8F9)),
          _ => (const Color(0x2E94A3B8), const Color(0xFFCBD5E1)),
        };
        return GestureDetector(
          behavior: HitTestBehavior.opaque,
          onTap: () => _selectSession(id, source),
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 11, vertical: 9),
            decoration: BoxDecoration(
              color: id == _openSession ? const Color(0x1A0EA5E9) : null,
              borderRadius: BorderRadius.circular(10),
              border: Border.all(
                color: id == _openSession
                    ? const Color(0x590EA5E9)
                    : Colors.transparent,
              ),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Container(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 8,
                        vertical: 2,
                      ),
                      decoration: BoxDecoration(
                        color: bg,
                        borderRadius: BorderRadius.circular(999),
                      ),
                      child: Text(
                        device != null
                            ? '${_sourceShort['web']} · $device'
                            : (_sourceShort[source] ?? source),
                        style: TextStyle(
                          fontSize: JTokens.fsLabel,
                          fontWeight: FontWeight.w600,
                          color: fg,
                        ),
                      ),
                    ),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        _truthy(s['title']) ? '${s['title']}' : id,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(
                          fontSize: JTokens.fsSmall,
                          color: JTokens.text,
                        ),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 4),
                Text(
                  _truthy(s['user_name'])
                      ? '${s['user_name']}'
                      : '${s['user_id'] ?? ''}',
                  style: const TextStyle(
                    fontSize: JTokens.fsLabel,
                    color: JTokens.muted,
                  ),
                ),
                Text(
                  '${s['msg_count']} tin · ${_dayLabel(when)} ${_hm(when)}',
                  style: const TextStyle(
                    fontSize: JTokens.fsSmall,
                    color: JTokens.muted,
                  ),
                ),
              ],
            ),
          ),
        );
      },
    );
  }

  Widget _reader() {
    final msgs = _messages;
    if (msgs == null) return _note(_readerNote ?? '');
    final cfg = context.read<ServerConfig>();
    final children = <Widget>[];
    var lastDay = '';
    for (final m in msgs) {
      final date = _at(m['created_at']);
      final day = _dayLabel(date);
      if (day != lastDay) {
        lastDay = day;
        children.add(
          Padding(
            padding: const EdgeInsets.only(top: 6, bottom: 2),
            child: Text(
              day.toUpperCase(),
              textAlign: TextAlign.center,
              style: const TextStyle(
                fontSize: JTokens.fsLabel,
                letterSpacing: 1.5,
                color: JTokens.muted,
              ),
            ),
          ),
        );
      }
      final user = m['role'] == 'user';
      children.add(
        Align(
          alignment: user ? Alignment.centerRight : Alignment.centerLeft,
          child: ConstrainedBox(
            constraints: BoxConstraints(
              maxWidth: MediaQuery.sizeOf(context).width * 0.94,
            ),
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 11, vertical: 7),
              decoration: BoxDecoration(
                color: user ? const Color(0x1A0EA5E9) : const Color(0x0AFFFFFF),
                border: Border.all(
                  color: user
                      ? const Color(0x380EA5E9)
                      : const Color(0x17FFFFFF),
                ),
                borderRadius: BorderRadius.only(
                  topLeft: const Radius.circular(12),
                  topRight: const Radius.circular(12),
                  bottomLeft: Radius.circular(user ? 12 : 3),
                  bottomRight: Radius.circular(user ? 3 : 12),
                ),
              ),
              child: Column(
                crossAxisAlignment: user
                    ? CrossAxisAlignment.end
                    : CrossAxisAlignment.start,
                mainAxisSize: MainAxisSize.min,
                children: [
                  MarkdownView(
                    '${m['content'] ?? ''}'.trim(),
                    resolveUrl: (u) => cfg.http(u).toString(),
                  ),
                  const SizedBox(height: 2),
                  Text(
                    _hm(date),
                    style: const TextStyle(
                      fontSize: JTokens.fsLabel,
                      color: JTokens.muted,
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      );
    }
    return ListView.separated(
      controller: _scroll,
      padding: const EdgeInsets.all(4),
      itemCount: children.length,
      separatorBuilder: (_, _) => const SizedBox(height: 6),
      itemBuilder: (_, i) => children[i],
    );
  }

  Widget _logBody() {
    final text = _logText;
    final Widget content;
    if (text == null) {
      content = Text(_logNote ?? '', style: _logStyle(const Color(0xA6FFFFFF)));
    } else {
      final lines = text.split('\n');
      content = ListView.builder(
        controller: _scroll,
        itemCount: lines.length,
        itemBuilder: (_, i) {
          final line = lines[i];
          final color = line.contains('ERROR')
              ? const Color(0xFFEF4444)
              : line.contains('WARNING')
              ? const Color(0xFFF59E0B)
              : line.contains('INFO')
              ? const Color(0xFF38BDF8)
              : const Color(0xA6FFFFFF);
          return Padding(
            padding: const EdgeInsets.symmetric(vertical: 1),
            child: Text(line, style: _logStyle(color)),
          );
        },
      );
    }
    return Container(
      margin: const EdgeInsets.only(top: 10),
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      decoration: BoxDecoration(
        color: const Color(0x2E000000),
        borderRadius: BorderRadius.circular(8),
      ),
      child: content,
    );
  }

  TextStyle _logStyle(Color c) =>
      memMono.copyWith(fontSize: JTokens.fsLabel, height: 1.55, color: c);
}
