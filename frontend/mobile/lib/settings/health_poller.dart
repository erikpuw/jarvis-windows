import 'dart:async';

import 'package:flutter/widgets.dart';
import 'package:jarvis_mobile/net/api_client.dart';

/// index.ts: both probes of the status pages. /api/settings/status carries the hardware, services and counts; the apps list
/// is only filled with `apps=true`.
const statusPath = '/api/settings/status?apps=true';

/// index.ts startHealthPolling: loadStatus + loadDetailedHealth now and every 5 s while the page is open, skipped while the app is
/// in the background (web: document.hidden). A failed probe keeps the last data and exposes its error text.
class HealthPoller extends ChangeNotifier {
  HealthPoller(this._api);

  static const interval = Duration(seconds: 5);

  final ApiClient _api;
  Map<String, dynamic>? status;
  Map<String, dynamic>? health;
  String? statusError;
  String? healthError;
  Timer? _timer;
  bool _disposed = false;

  void start() {
    _load();
    _timer = Timer.periodic(interval, (_) {
      final life = WidgetsBinding.instance.lifecycleState;
      if (life == null || life == AppLifecycleState.resumed) _load();
    });
  }

  Future<void> _load() => Future.wait([_loadStatus(), _loadHealth()]);

  Future<void> _loadStatus() async {
    try {
      final data = await _api.get<Map<String, dynamic>>(statusPath);
      if (_disposed) return;
      status = data;
      statusError = null;
    } catch (e) {
      if (_disposed) return;
      statusError = '$e';
    }
    notifyListeners();
  }

  Future<void> _loadHealth() async {
    try {
      final data = await _api.get<Map<String, dynamic>>('/api/health/detailed');
      if (_disposed) return;
      if (data['status'] == 'online') health = data;
      healthError = null;
    } catch (e) {
      if (_disposed) return;
      healthError = '$e';
    }
    notifyListeners();
  }

  @override
  void dispose() {
    _disposed = true;
    _timer?.cancel();
    super.dispose();
  }
}
