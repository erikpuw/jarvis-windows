import 'package:jarvis_mobile/auth/auth_controller.dart';
import 'package:flutter/material.dart';
import 'package:jarvis_mobile/net/api_client.dart';
import 'package:jarvis_mobile/settings/action_button.dart';
import 'package:jarvis_mobile/settings/page_scaffold.dart';
import 'package:jarvis_mobile/settings/pages.dart';
import 'package:jarvis_mobile/settings/sd_widgets.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';
import 'package:provider/provider.dart';

/// Người dùng (pages.ts userPage + index.ts loadPreferences / btn-save-prefs): the same three fields and body as the web.
class UserPage extends StatefulWidget {
  const UserPage({super.key});

  @override
  State<UserPage> createState() => _UserPageState();
}

class _UserPageState extends State<UserPage> {
  late final ApiClient _api = context.read<ApiClient>();
  final _name = TextEditingController();
  final _honorific = TextEditingController();
  final _calendar = TextEditingController();
  String? _loadError;
  (String, bool)? _feedback;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _name.dispose();
    _honorific.dispose();
    _calendar.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final p = await _api.get<Map<String, dynamic>>(
        '/api/settings/preferences',
      );
      if (!mounted) return;
      _name.text = '${p['user_name'] ?? ''}';
      _honorific.text = '${p['honorific'] ?? ''}';
      _calendar.text = '${p['calendar_accounts'] ?? ''}';
    } catch (e) {
      if (mounted) setState(() => _loadError = '$e');
    }
  }

  Future<bool?> _save() async {
    setState(() => _feedback = null);
    await _api.post<dynamic>('/api/settings/preferences', {
      'user_name': _name.text.trim(),
      'honorific': _honorific.text.trim(),
      'calendar_accounts': _calendar.text.trim(),
    });
    if (mounted) {
      final auth = context.read<AuthController?>();
      await auth?.refreshUser();
    }
    return null;
  }

  @override
  Widget build(BuildContext context) {
    final page = settingsPages.firstWhere((p) => p.id == 'user');
    return PageScaffold(
      page: page,
      body: SdGrid(
        children: [
          SdCard(
            icon: LucideIcons.userRound,
            title: 'Hồ sơ người dùng & Tương tác',
            children: [
              if (_loadError != null)
                SdEmpty('Không tải được thông tin: $_loadError', error: true),
              SdFormGroup(
                label: 'Tên hiển thị của bạn',
                children: [
                  SdInput(
                    key: const Key('field:user_name'),
                    controller: _name,
                    hint: 'Ví dụ: Erik',
                  ),
                ],
              ),
              SdFormGroup(
                label: 'Cách JARVIS xưng hô với bạn',
                children: [
                  SdInput(
                    key: const Key('field:honorific'),
                    controller: _honorific,
                    hint: 'Ví dụ: Bạn, Anh, Boss...',
                  ),
                ],
              ),
              SdFormGroup(
                label: 'Tài khoản Google Calendar đồng bộ',
                children: [
                  SdInput(
                    key: const Key('field:calendar_accounts'),
                    controller: _calendar,
                    hint: 'email@gmail.com',
                  ),
                ],
              ),
              Row(
                mainAxisAlignment: MainAxisAlignment.end,
                children: [
                  Flexible(
                    child: ActionButton(
                      kind: ActionKind.save,
                      label: 'Lưu thông tin cá nhân',
                      primary: true,
                      task: _save,
                      onFeedback: (t, ok) =>
                          setState(() => _feedback = (t, ok)),
                    ),
                  ),
                ],
              ),
              SdFeedback(_feedback),
            ],
          ),
        ],
      ),
    );
  }
}
