import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:jarvis_mobile/net/api_client.dart';
import 'package:jarvis_mobile/settings/mem_widgets.dart';
import 'package:jarvis_mobile/settings/page_scaffold.dart';
import 'package:jarvis_mobile/settings/pages.dart';
import 'package:jarvis_mobile/settings/sd_widgets.dart';
import 'package:jarvis_mobile/theme/tokens.dart';
import 'package:provider/provider.dart';

const _sky = Color(0xFF38BDF8);

/// Kết nối MCP (pages.ts mcpPage + index.ts loadMcpServers / renderMcpList / the toggle, add and JSON handlers).
class McpPage extends StatefulWidget {
  const McpPage({super.key});

  @override
  State<McpPage> createState() => _McpPageState();
}

class _McpPageState extends State<McpPage> {
  late final ApiClient _api = context.read<ApiClient>();
  final _search = TextEditingController();
  final _name = TextEditingController();
  final _command = TextEditingController();
  final _args = TextEditingController();
  final _url = TextEditingController();
  List<Map<String, dynamic>> _servers = [];
  int _total = 0;
  int _connected = 0;
  bool _loading = true;
  String? _error;
  bool _showJson = false;
  bool _jsonCopied = false;
  String _type = 'stdio';
  (String, bool)? _addFeedback;
  bool _adding = false;
  final _busy = <String>{};
  final _timers = <Timer>[];

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    for (final c in [_search, _name, _command, _args, _url]) {
      c.dispose();
    }
    for (final t in _timers) {
      t.cancel();
    }
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final res = await _api.get<Map<String, dynamic>>('/api/mcp/servers');
      if (!mounted) return;
      if (res['success'] != true) {
        setState(() {
          _loading = false;
          _error = 'Lỗi đọc cấu hình MCP: ${res['error'] ?? 'Unknown error'}';
        });
        return;
      }
      final servers = res['servers'] is List
          ? [
              for (final e in res['servers'] as List)
                Map<String, dynamic>.from(e as Map),
            ]
          : <Map<String, dynamic>>[];
      setState(() {
        _servers = servers;
        _total = (res['total'] as num?)?.toInt() ?? servers.length;
        _connected =
            (res['connected'] as num?)?.toInt() ??
            servers.where((s) => s['status'] == 'connected').length;
        _error = null;
        _loading = false;
      });
    } catch (e) {
      if (mounted) {
        setState(() {
          _loading = false;
          _error = 'Lỗi kết nối API MCP: $e';
        });
      }
    }
  }

  /// A change to the list takes a moment to connect: reload now and once more after 4 s (index.ts).
  Future<void> _reloadSoon() async {
    await _load();
    _timers.add(
      Timer(const Duration(seconds: 4), () {
        if (mounted) _load();
      }),
    );
  }

  Future<void> _toggle(String name, bool enabled) async {
    setState(() => _busy.add(name));
    try {
      await _api.post<dynamic>(
        '/api/mcp/servers/${Uri.encodeComponent(name)}/enabled',
        {'enabled': !enabled},
      );
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.maybeOf(context)?.showSnackBar(
          SnackBar(content: Text('Không đổi được trạng thái MCP: $e')),
        );
      }
    }
    if (!mounted) return;
    setState(() => _busy.remove(name));
    await _reloadSoon();
  }

  Future<void> _add() async {
    setState(() {
      _adding = true;
      _addFeedback = null;
    });
    final stdio = _type == 'stdio';
    try {
      await _api.post<dynamic>('/api/mcp/servers', {
        'name': _name.text.trim(),
        'type': _type,
        'command': stdio ? _command.text.trim() : null,
        'args': stdio
            ? [
                for (final l in _args.text.split(RegExp(r'\r?\n')))
                  if (l.trim().isNotEmpty) l.trim(),
              ]
            : <String>[],
        'url': stdio ? null : _url.text.trim(),
      });
      if (!mounted) return;
      for (final c in [_name, _command, _args, _url]) {
        c.clear();
      }
      setState(() => _addFeedback = ('Đã thêm, đang kết nối…', true));
      await _reloadSoon();
    } catch (e) {
      if (mounted) setState(() => _addFeedback = ('$e', false));
    } finally {
      if (mounted) setState(() => _adding = false);
    }
  }

  String get _jsonText =>
      const JsonEncoder.withIndent('  ').convert({'servers': _servers});

  void _copyJson() {
    Clipboard.setData(ClipboardData(text: _jsonText));
    setState(() => _jsonCopied = true);
    _timers.add(
      Timer(const Duration(seconds: 2), () {
        if (mounted) setState(() => _jsonCopied = false);
      }),
    );
  }

  Widget _stat(String value, String label, {bool ok = false}) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      Text(
        value,
        style: TextStyle(
          fontSize: JTokens.fsHeading,
          fontWeight: FontWeight.w700,
          color: ok ? JTokens.ok : Colors.white,
          fontFeatures: const [FontFeature.tabularFigures()],
        ),
      ),
      Text(
        label,
        style: const TextStyle(fontSize: JTokens.fsSmall, color: JTokens.muted),
      ),
    ],
  );

  Widget _summary() => Container(
    padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 18),
    decoration: BoxDecoration(
      color: JTokens.surface,
      borderRadius: BorderRadius.circular(12),
      border: Border.all(color: JTokens.border),
    ),
    child: Wrap(
      spacing: 20,
      runSpacing: 12,
      crossAxisAlignment: WrapCrossAlignment.center,
      children: [
        _stat('$_total', 'Máy chủ cấu hình'),
        _stat('$_connected', 'Đang kích hoạt', ok: true),
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
          decoration: BoxDecoration(
            color: const Color(0x08FFFFFF),
            borderRadius: BorderRadius.circular(8),
            border: Border.all(color: JTokens.border),
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Text(
                'Tệp cấu hình:',
                style: TextStyle(
                  fontSize: JTokens.fsSmall,
                  color: JTokens.muted,
                ),
              ),
              const SizedBox(width: 8),
              Flexible(
                child: Text(
                  'config/mcp_config.json',
                  style: memMono.copyWith(
                    fontSize: JTokens.fsSmall,
                    color: _sky,
                  ),
                ),
              ),
            ],
          ),
        ),
      ],
    ),
  );

  Widget _jsonBox() => Container(
    key: const Key('mcp-json'),
    padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
    decoration: BoxDecoration(
      color: const Color(0xD90F172A),
      borderRadius: BorderRadius.circular(10),
      border: Border.all(color: const Color(0x4038BDF8)),
    ),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Container(
          padding: const EdgeInsets.only(bottom: 8),
          decoration: const BoxDecoration(
            border: Border(bottom: BorderSide(color: JTokens.border)),
          ),
          child: Row(
            children: [
              Expanded(
                child: Text.rich(
                  TextSpan(
                    children: [
                      const TextSpan(text: 'Nội dung '),
                      TextSpan(text: 'config/mcp_config.json', style: memMono),
                    ],
                  ),
                  style: const TextStyle(
                    fontSize: JTokens.fsSmall,
                    color: JTokens.muted,
                  ),
                ),
              ),
              InkWell(
                borderRadius: BorderRadius.circular(4),
                onTap: _copyJson,
                child: Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 8,
                    vertical: 3,
                  ),
                  decoration: BoxDecoration(
                    color: const Color(0x14FFFFFF),
                    borderRadius: BorderRadius.circular(4),
                  ),
                  child: Text(
                    _jsonCopied ? 'Đã chép!' : 'Sao chép',
                    style: const TextStyle(
                      fontSize: JTokens.fsSmall,
                      color: Colors.white,
                    ),
                  ),
                ),
              ),
            ],
          ),
        ),
        const SizedBox(height: 10),
        ConstrainedBox(
          constraints: const BoxConstraints(maxHeight: 320),
          child: SingleChildScrollView(
            child: Text(
              _jsonText,
              style: memMono.copyWith(
                fontSize: JTokens.fsSmall,
                height: 1.5,
                color: const Color(0xFFCBD5E1),
              ),
            ),
          ),
        ),
      ],
    ),
  );

  Widget _item(Map<String, dynamic> s) {
    final name = '${s['name']}';
    final enabled = s['enabled'] != false;
    final conn = s['status'] == 'connected';
    final args = s['args'] is List
        ? [for (final a in s['args'] as List) '$a']
        : <String>[];
    String first(Object? a, Object? b, String c) =>
        '${a ?? ''}'.isNotEmpty ? '$a' : ('${b ?? ''}'.isNotEmpty ? '$b' : c);
    final cmd = [first(s['command'], s['url'], 'stdio'), ...args].join(' ');
    final state = conn
        ? 'Đã kết nối'
        : !enabled
        ? 'Tạm tắt'
        : s['status'] == 'connecting'
        ? 'Đang kết nối'
        : 'Chưa kết nối';
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      decoration: BoxDecoration(
        color: const Color(0x05FFFFFF),
        borderRadius: BorderRadius.circular(9),
        border: Border.all(color: JTokens.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              StatusDot(conn ? DotState.ok : DotState.off),
              const SizedBox(width: 10),
              Expanded(
                child: Row(
                  children: [
                    Flexible(
                      child: Text(
                        name,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(
                          fontSize: JTokens.fsUi,
                          fontWeight: FontWeight.w600,
                          color: Colors.white,
                        ),
                      ),
                    ),
                    const SizedBox(width: 14),
                    Flexible(
                      child: Text(
                        '${s['type'] ?? 'stdio'}',
                        maxLines: 1,
                        overflow: TextOverflow.clip,
                        style: const TextStyle(
                          fontSize: JTokens.fsSmall,
                          color: JTokens.muted,
                        ),
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 8),
              Text(
                state,
                style: TextStyle(
                  fontSize: JTokens.fsSmall,
                  color: conn ? JTokens.ok : JTokens.muted,
                ),
              ),
              const SizedBox(width: 10),
              MemButton(
                key: Key('mcp-toggle:$name'),
                label: enabled ? 'Tắt' : 'Bật',
                height: 28,
                fontSize: JTokens.fsSmall,
                onPressed: _busy.contains(name)
                    ? null
                    : () => _toggle(name, enabled),
              ),
            ],
          ),
          const SizedBox(height: 8),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
            decoration: BoxDecoration(
              color: const Color(0x4D000000),
              borderRadius: BorderRadius.circular(6),
              border: Border.all(color: const Color(0x0DFFFFFF)),
            ),
            child: Text(
              cmd,
              style: const TextStyle(fontSize: JTokens.fsSmall, color: _sky),
            ),
          ),
        ],
      ),
    );
  }

  Widget _list() {
    if (_loading) {
      return const SdEmpty(
        'Đang nạp thông tin MCP Servers từ config/mcp_config.json…',
      );
    }
    if (_error != null) return SdEmpty(_error!, error: true);
    final q = _search.text.trim().toLowerCase();
    final shown = q.isEmpty
        ? _servers
        : _servers
              .where(
                (s) =>
                    '${s['name']}'.toLowerCase().contains(q) ||
                    '${s['command'] ?? ''}'.toLowerCase().contains(q),
              )
              .toList();
    if (shown.isEmpty) {
      return const SdEmpty(
        'Chưa có máy chủ MCP nào được cấu hình trong config/mcp_config.json.',
      );
    }
    return Column(
      children: [
        for (var i = 0; i < shown.length; i++) ...[
          if (i > 0) const SizedBox(height: 10),
          _item(shown[i]),
        ],
      ],
    );
  }

  Widget _typeSelect() => Container(
    key: const Key('mcp-add-type'),
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
        value: _type,
        dropdownColor: JTokens.surface,
        iconEnabledColor: JTokens.muted,
        style: const TextStyle(color: JTokens.text, fontSize: JTokens.fsUi),
        items: const [
          DropdownMenuItem(
            value: 'stdio',
            child: Text('stdio (chạy lệnh trên máy)'),
          ),
          DropdownMenuItem(value: 'http', child: Text('http')),
          DropdownMenuItem(value: 'sse', child: Text('sse')),
        ],
        onChanged: (v) => setState(() => _type = v ?? 'stdio'),
      ),
    ),
  );

  Widget _addCard() {
    final stdio = _type == 'stdio';
    return SdCard(
      title: 'Thêm máy chủ MCP',
      children: [
        Padding(
          padding: const EdgeInsets.only(bottom: 18),
          child: SdNote([
            const TextSpan(text: 'Loại '),
            sdCode('stdio'),
            const TextSpan(
              text: ' chạy một lệnh ngay trên máy này: chỉ thêm lệnh bạn tin tưởng. Chỉ thêm và bật/tắt được từ chính máy chạy JARVIS.',
            ),
          ]),
        ),
        SdFormGroup(
          label: 'Tên',
          children: [
            SdInput(
              key: const Key('mcp-add-name'),
              controller: _name,
              hint: 'Ví dụ: context7',
            ),
          ],
        ),
        SdFormGroup(label: 'Loại', children: [_typeSelect()]),
        if (stdio) ...[
          SdFormGroup(
            label: 'Lệnh',
            children: [
              SdInput(
                key: const Key('mcp-add-command'),
                controller: _command,
                hint: 'Ví dụ: npx',
              ),
            ],
          ),
          SdFormGroup(
            label: 'Tham số (mỗi dòng một tham số)',
            children: [
              SdInput(
                key: const Key('mcp-add-args'),
                controller: _args,
                hint: '-y\n@upstash/context7-mcp',
                minLines: 3,
                maxLines: 6,
              ),
            ],
          ),
        ] else
          SdFormGroup(
            label: 'URL',
            children: [
              SdInput(
                key: const Key('mcp-add-url'),
                controller: _url,
                hint: 'https://...',
              ),
            ],
          ),
        Align(
          alignment: Alignment.centerLeft,
          child: ElevatedButton(
            onPressed: _adding ? null : _add,
            style: ElevatedButton.styleFrom(
              backgroundColor: JTokens.accent,
              minimumSize: const Size(0, 36),
              elevation: 0,
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(8),
              ),
            ),
            child: const Text(
              'Thêm và kết nối',
              style: TextStyle(
                fontSize: JTokens.fsUi,
                fontWeight: FontWeight.w600,
                color: Color(0xFF04121C),
              ),
            ),
          ),
        ),
        SdFeedback(_addFeedback),
      ],
    );
  }

  @override
  Widget build(BuildContext context) {
    final page = settingsPages.firstWhere((p) => p.id == 'mcp');
    return PageScaffold(
      page: page,
      body: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          _summary(),
          const SizedBox(height: 6),
          Row(
            children: [
              Expanded(
                child: SdSearchBox(
                  key: const Key('mcp-search'),
                  controller: _search,
                  hint: 'Lọc máy chủ MCP...',
                  onChanged: (_) => setState(() {}),
                ),
              ),
              const SizedBox(width: 12),
              MemButton(
                label: 'Xem JSON cấu hình',
                onPressed: () => setState(() => _showJson = !_showJson),
              ),
            ],
          ),
          if (_showJson) ...[const SizedBox(height: 14), _jsonBox()],
          const SizedBox(height: 14),
          SdCard(
            title: 'Danh sách máy chủ ngoại vi (MCP Servers)',
            children: [_list()],
          ),
          const SizedBox(height: 6),
          _addCard(),
        ],
      ),
    );
  }
}
