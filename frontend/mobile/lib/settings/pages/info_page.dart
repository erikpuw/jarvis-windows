import 'package:flutter/material.dart';
import 'package:jarvis_mobile/chat/lucide_glyphs.dart';
import 'package:jarvis_mobile/chat/markdown_view.dart';
import 'package:jarvis_mobile/net/api_client.dart';
import 'package:jarvis_mobile/net/server_config.dart';
import 'package:jarvis_mobile/settings/mem_widgets.dart';
import 'package:jarvis_mobile/settings/page_scaffold.dart';
import 'package:jarvis_mobile/settings/pages.dart';
import 'package:jarvis_mobile/settings/sd_widgets.dart';
import 'package:jarvis_mobile/theme/tokens.dart';
import 'package:provider/provider.dart';

/// Thông tin (pages.ts infoPage + index.ts loadReadme): the version bar and README.md through the chat's markdown view,
/// as one flat page without a card border (styles.css `.sd-info-container`).
class InfoPage extends StatefulWidget {
  const InfoPage({super.key});

  @override
  State<InfoPage> createState() => _InfoPageState();
}

class _InfoPageState extends State<InfoPage> {
  late final ApiClient _api = context.read<ApiClient>();
  String? _readme;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final res = await _api.get<Map<String, dynamic>>('/api/system/readme');
      if (!mounted) return;
      final content = res['content'];
      setState(() {
        if (res['success'] == true && content is String && content.isNotEmpty) {
          _readme = content;
          _error = null;
        } else {
          _readme = null;
          _error =
              'Không tải được tài liệu README.md: ${res['error'] ?? 'File không tồn tại'}';
        }
      });
    } catch (e) {
      if (mounted) {
        setState(() {
          _readme = null;
          _error = 'Lỗi nạp tài liệu README.md: $e';
        });
      }
    }
  }

  Widget _pill(String key, Widget value) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
    decoration: BoxDecoration(
      color: const Color(0x0AFFFFFF),
      borderRadius: BorderRadius.circular(6),
      border: Border.all(color: const Color(0x0FFFFFFF)),
    ),
    child: Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Text(
          key,
          style: const TextStyle(
            fontSize: JTokens.fsSmall,
            color: JTokens.muted,
          ),
        ),
        const SizedBox(width: 6),
        Flexible(child: value),
      ],
    ),
  );

  Widget _doc() {
    if (_error != null) return SdEmpty(_error!, error: true);
    final text = _readme;
    if (text == null) {
      return const SdEmpty('Đang nạp nội dung tài liệu README.md…');
    }
    final cfg = context.read<ServerConfig>();
    return MarkdownView(text, resolveUrl: (u) => cfg.http(u).toString());
  }

  @override
  Widget build(BuildContext context) {
    final page = settingsPages.firstWhere((p) => p.id == 'info');
    const strong = TextStyle(
      fontSize: JTokens.fsSmall,
      fontWeight: FontWeight.w600,
      color: Colors.white,
    );
    return PageScaffold(
      page: page,
      body: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Wrap(
            spacing: 12,
            runSpacing: 8,
            children: [
              _pill('Phiên bản:', const Text('v$appVersion', style: strong)),
              _pill(
                'Nền tảng:',
                const Text('Windows · Desktop Native', style: strong),
              ),
              _pill(
                'Nguồn dữ liệu:',
                Text(
                  'README.md',
                  style: memMono.copyWith(
                    fontSize: JTokens.fsSmall,
                    color: const Color(0xFF38BDF8),
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          Align(
            alignment: Alignment.centerLeft,
            child: MemButton(
              label: 'Tải lại tài liệu',
              icon: activityGlyph,
              onPressed: _load,
            ),
          ),
          const SizedBox(height: 8),
          _doc(),
        ],
      ),
    );
  }
}
