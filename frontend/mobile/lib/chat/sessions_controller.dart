import 'dart:async';
import 'dart:collection';

import 'package:flutter/foundation.dart';

import '../net/api_client.dart';
import '../net/jarvis_socket.dart';
import 'chat_controller.dart';

class SessionItem {
  const SessionItem({
    required this.id,
    required this.title,
    required this.lastMsg,
  });
  final String id;
  final String title;
  final int lastMsg;
}

/// sessions.ts groupLabel: compare local calendar days, including DST changes.
String sessionGroup(int lastMsgSec, DateTime now) {
  final last = DateTime.fromMillisecondsSinceEpoch(lastMsgSec * 1000);
  final days = DateTime.utc(
    now.year,
    now.month,
    now.day,
  ).difference(DateTime.utc(last.year, last.month, last.day)).inDays;
  return days <= 0
      ? 'Hôm nay'
      : days == 1
      ? 'Hôm qua'
      : 'Cũ hơn';
}

class SessionsController extends ChangeNotifier {
  SessionsController(this._socket, this._api, this._chat) {
    _locked = _chat.turnRunning;
    _chat.addListener(_onChat);
    _sessionSub = _socket.sessionEvents.listen(_onSession);
    _messageSub = _socket.messages.listen((m) {
      final id = _socket.sessionId;
      if (m['type'] == 'stream_end' && id != null && _listed.add(id)) {
        unawaited(refresh());
      }
    });
  }
  final JarvisSocket _socket;
  final ApiClient _api;
  final ChatController _chat;
  late final StreamSubscription<SessionEvent> _sessionSub;
  late final StreamSubscription<Map<String, dynamic>> _messageSub;
  List<SessionItem> _items = [];
  final _listed = <String>{};
  String? _activeId;
  String? _shown;
  String? _pendingSwitchFor;
  int _historyToken = 0;
  int _refreshToken = 0;
  bool _disposed = false;
  late bool _locked;

  List<SessionItem> get items => UnmodifiableListView(_items);
  String? get activeId => _activeId;
  bool get locked => _chat.turnRunning;

  void _onChat() {
    if (_locked == locked) return;
    _locked = locked;
    notifyListeners();
  }

  Future<void> refresh() async {
    final token = ++_refreshToken;
    try {
      final data = await _api.get<Map<String, dynamic>>(
        '/api/sessions/mine?limit=50',
      );
      if (_disposed || token != _refreshToken || data['success'] == false) {
        return;
      }
      final rows = data['sessions'];
      if (rows is! List) return;
      _items = [
        for (final row in rows)
          if (row is Map && row['session_id'] is String)
            SessionItem(
              id: row['session_id'] as String,
              title: '${row['title'] ?? row['session_id']}',
              lastMsg: (row['last_msg'] as num?)?.toInt() ?? 0,
            ),
      ];
      _listed.addAll(_items.map((s) => s.id));
      notifyListeners();
    } catch (_) {
      // sessions.ts: keep the last list on a failed refresh.
    }
  }

  Future<void> pick(String id) async {
    if (locked) return;
    _shown = _pendingSwitchFor = _activeId = id;
    _socket.switchSession(id);
    notifyListeners();
    unawaited(refresh());
    await _showHistory(id);
  }

  Future<void> _showHistory(String id) async {
    final token = ++_historyToken;
    _chat.clearChat(keepWelcome: false);
    try {
      final data = await _api.get<Map<String, dynamic>>(
        '/api/sessions/mine/${Uri.encodeComponent(id)}',
      );
      if (_disposed || token != _historyToken || data['success'] == false) {
        return;
      }
      final rows = data['messages'];
      if (rows is List) {
        _chat.showHistory(rows.whereType<Map<String, dynamic>>().toList());
      }
    } catch (_) {
      // A failed history fetch leaves the empty chat, as main.ts showHistory.
    }
  }

  void startNew() {
    if (locked) return;
    _shown = _pendingSwitchFor = _activeId = null;
    _historyToken++;
    _chat.reset();
    _socket.switchSession(null);
    notifyListeners();
    unawaited(refresh());
  }

  void _onSession(SessionEvent e) {
    _activeId = e.id;
    _chat.onNewSocket();
    if (e.resumed) {
      if (_pendingSwitchFor != e.id && !locked) unawaited(_showHistory(e.id));
    } else if (_shown != e.id) {
      _historyToken++;
      _chat.clearChat();
    }
    _pendingSwitchFor = null;
    _shown = e.id;
    notifyListeners();
  }

  void sessionDeleted(String id) {
    if (id == _socket.sessionId) startNew();
    unawaited(refresh());
  }

  void clear() {
    _items = [];
    _activeId = _shown = _pendingSwitchFor = null;
    _listed.clear();
    _historyToken++;
    _refreshToken++;
    notifyListeners();
  }

  @override
  void dispose() {
    _disposed = true;
    _chat.removeListener(_onChat);
    _sessionSub.cancel();
    _messageSub.cancel();
    super.dispose();
  }
}
