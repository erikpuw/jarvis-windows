import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../net/api_client.dart';
import 'auth_user.dart';

const String prefTokenKey = 'jarvis_token';
const String prefUserKey = 'jarvis_user';

class AuthController extends ChangeNotifier {
  void setAuthenticatedForTesting([AuthUser? user, String token = 'test_token']) {
    _currentUser = user ?? AuthUser(id: 'admin', username: 'admin', role: 'admin');
    _api.memoryToken = token;
    _isLoading = false;
    notifyListeners();
  }
  final ApiClient _api;

  AuthUser? _currentUser;
  bool _isLoading = false;
  String? _error;

  AuthController(this._api);

  AuthUser? get currentUser => _currentUser;
  bool get isAuthenticated => _currentUser != null && _api.memoryToken.isNotEmpty;
  bool get isLoading => _isLoading;
  String? get error => _error;

  Future<void> init() async {
    _isLoading = true;
    _error = null;
    notifyListeners();

    try {
      final prefs = await SharedPreferences.getInstance();
      final token = prefs.getString(prefTokenKey);
      if (token != null && token.isNotEmpty) {
        _api.memoryToken = token;
        try {
          final res = await _api.get<Map<String, dynamic>>('/api/auth/me');
          if (res['success'] == true && res['user'] != null) {
            _currentUser = AuthUser.fromJson(Map<String, dynamic>.from(res['user'] as Map));
            await prefs.setString(prefUserKey, jsonEncode(_currentUser!.toJson()));
            _isLoading = false;
            notifyListeners();
            return;
          }
        } catch (e) {
          debugPrint('[auth] Token check failed: $e');
        }
        // Token hết hạn hoặc không hợp lệ
        _api.memoryToken = '';
        _currentUser = null;
        await prefs.remove(prefTokenKey);
        await prefs.remove(prefUserKey);
        await prefs.remove('jarvis_active_session_id');
      }
    } catch (e) {
      debugPrint('[auth] Init error: $e');
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  /// Refreshes user profile from server to keep name, pronouns, and preferences in sync.
  Future<void> refreshUser() async {
    if (_api.memoryToken.isEmpty) return;
    try {
      final res = await _api.get<Map<String, dynamic>>('/api/auth/me');
      if (res['success'] == true && res['user'] != null) {
        _currentUser = AuthUser.fromJson(Map<String, dynamic>.from(res['user'] as Map));
        final prefs = await SharedPreferences.getInstance();
        await prefs.setString(prefUserKey, jsonEncode(_currentUser!.toJson()));
        notifyListeners();
      }
    } catch (e) {
      debugPrint('[auth] Refresh user error: $e');
    }
  }

  Future<bool> loginMember(String username) async {
    final trimmed = username.trim();
    if (trimmed.isEmpty) {
      _error = 'Vui lòng nhập tên hiển thị.';
      notifyListeners();
      return false;
    }
    return _doLogin({'username': trimmed});
  }

  Future<bool> loginAdmin(String password) async {
    if (password.isEmpty) {
      _error = 'Vui lòng nhập mật khẩu quản trị.';
      notifyListeners();
      return false;
    }
    return _doLogin({'username': 'admin', 'password': password});
  }

  Future<bool> _doLogin(Map<String, dynamic> payload) async {
    _isLoading = true;
    _error = null;
    notifyListeners();

    try {
      final res = await _api.post<Map<String, dynamic>>('/api/auth/login', payload);
      if (res['success'] == true && res['token'] != null) {
        final token = res['token'].toString();
        _api.memoryToken = token;

        if (res['user'] != null) {
          _currentUser = AuthUser.fromJson(Map<String, dynamic>.from(res['user'] as Map));
        } else {
          _currentUser = AuthUser(
            id: payload['username'] == 'admin' ? 'admin' : 'member',
            username: payload['username'].toString(),
            role: payload['username'] == 'admin' ? 'admin' : 'member',
          );
        }

        final prefs = await SharedPreferences.getInstance();
        await prefs.setString(prefTokenKey, token);
        await prefs.setString(prefUserKey, jsonEncode(_currentUser!.toJson()));
        await prefs.remove('jarvis_active_session_id');

        _isLoading = false;
        notifyListeners();
        return true;
      } else {
        _error = res['error']?.toString() ?? 'Đăng nhập không thành công';
      }
    } catch (e) {
      _error = e.toString().replaceFirst(RegExp(r'^Exception:\s*'), '');
    } finally {
      _isLoading = false;
      notifyListeners();
    }
    return false;
  }

  Future<void> logout() async {
    try {
      await _api.post<dynamic>('/api/auth/logout', {});
    } catch (_) {}

    _api.memoryToken = '';
    _currentUser = null;
    _error = null;

    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(prefTokenKey);
    await prefs.remove(prefUserKey);
    await prefs.remove('jarvis_active_session_id');

    notifyListeners();
  }
}
