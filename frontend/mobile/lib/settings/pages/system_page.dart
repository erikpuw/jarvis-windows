import 'package:flutter/material.dart';
import 'package:jarvis_mobile/net/api_client.dart';
import 'package:jarvis_mobile/settings/format.dart';
import 'package:jarvis_mobile/settings/health_poller.dart';
import 'package:jarvis_mobile/settings/page_scaffold.dart';
import 'package:jarvis_mobile/settings/pages.dart';
import 'package:jarvis_mobile/settings/sd_widgets.dart';
import 'package:jarvis_mobile/theme/tokens.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';
import 'package:provider/provider.dart';

/// Hệ thống (pages.ts systemPage + index.ts loadStatus / loadDetailedHealth / renderGpuList / renderAppBadges): polled every 5 s
/// while the page is open.
class SystemPage extends StatefulWidget {
  const SystemPage({super.key});

  @override
  State<SystemPage> createState() => _SystemPageState();
}

class _SystemPageState extends State<SystemPage> {
  late final HealthPoller _poller;

  @override
  void initState() {
    super.initState();
    _poller = HealthPoller(context.read<ApiClient>())
      ..addListener(() => setState(() {}))
      ..start();
  }

  @override
  void dispose() {
    _poller.dispose();
    super.dispose();
  }

  static Map<String, dynamic> _map(Object? v) =>
      v is Map ? v.cast<String, dynamic>() : const {};

  /// updateServiceRow(): the dot, and the detail or, without one, "Đang chạy" / "Mất kết nối".
  Widget _service(String name, bool? ok, String detail, {bool last = false}) =>
      StatusRow(
        name: name,
        state: ok == null
            ? DotState.unknown
            : ok
            ? DotState.ok
            : DotState.err,
        text: ok == null
            ? 'Đang kiểm tra…'
            : detail.isNotEmpty
            ? detail
            : ok
            ? 'Đang chạy'
            : 'Mất kết nối',
        last: last,
      );

  Widget _gpuItem(Map<String, dynamic> g) {
    final used = g['mem_used_mb'] as num?;
    final total = (g['mem_total_mb'] as num?) ?? (g['vram_total_mb'] as num?);
    final mem = used != null ? '${used.round()} MB' : '--';
    final tot = total != null && total != 0 ? '${total.round()} MB' : '--';
    final temp = g['temp_c'];
    const bold = TextStyle(fontWeight: FontWeight.w700);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          '${g['name'] ?? ''}',
          style: const TextStyle(
            fontSize: JTokens.fsUi,
            fontWeight: FontWeight.w600,
            color: JTokens.text,
          ),
        ),
        const SizedBox(height: 4),
        Text.rich(
          TextSpan(
            children: [
              const TextSpan(text: 'Bộ nhớ: '),
              TextSpan(text: '$mem / $tot', style: bold),
              if (temp != null && temp != 0) ...[
                const TextSpan(text: ' · Nhiệt độ: '),
                TextSpan(text: '$temp°C', style: bold),
              ],
            ],
          ),
          style: const TextStyle(
            fontSize: JTokens.fsSmall,
            color: JTokens.muted,
          ),
        ),
      ],
    );
  }

  Widget _npuItem(String name) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      Text(
        name,
        style: const TextStyle(
          fontSize: JTokens.fsUi,
          fontWeight: FontWeight.w600,
          color: JTokens.text,
        ),
      ),
      const SizedBox(height: 4),
      Row(
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
          const SizedBox(width: 6),
          const Expanded(
            child: Text(
              'Bộ tăng tốc trí tuệ nhân tạo NPU',
              style: TextStyle(fontSize: JTokens.fsSmall, color: JTokens.muted),
            ),
          ),
        ],
      ),
    ],
  );

  Widget _appRow(String name) => Row(
    children: [
      Container(
        width: 6,
        height: 6,
        decoration: const BoxDecoration(
          shape: BoxShape.circle,
          color: JTokens.ok,
        ),
      ),
      const SizedBox(width: 8),
      Expanded(
        child: Text(
          name,
          style: const TextStyle(
            fontSize: JTokens.fsSmall,
            color: JTokens.text,
          ),
        ),
      ),
    ],
  );

  List<Widget> _spaced(List<Widget> items) => [
    for (var i = 0; i < items.length; i++) ...[
      if (i > 0) const SizedBox(height: 8),
      items[i],
    ],
  ];

  @override
  Widget build(BuildContext context) {
    final page = settingsPages.firstWhere((p) => p.id == 'system');
    final s = _poller.status;
    final h = _poller.health;
    final sys = _map(s?['system']);
    final cpu = (sys['cpu_percent'] as num?) ?? 0;
    final ram = (sys['ram_percent'] as num?) ?? 0;
    final ramUsed = (sys['ram_used_gb'] as num?) ?? 0;
    final ramTotal = (sys['ram_total_gb'] as num?) ?? 0;
    final gpus = ((sys['gpus'] as List?) ?? const []).map(_map).toList();
    final npus = ((sys['npus'] as List?) ?? const []).map((e) => '$e').toList();
    final apps = ((s?['open_apps'] as List?) ?? const [])
        .map((e) => '$e')
        .toList();

    // loadDetailedHealth(): the three internal services
    final llm = _map(h?['llm']);
    final llmOk = llm['status'] == 'online';
    final rt = llm['response_time_ms'];
    final db = _map(h?['database']);
    final dbOk = db['ok'] == true;
    final sizeKb = db['size_kb'];
    final rag = _map(h?['rag']);
    final ragOk = rag['enabled'] == true;

    return PageScaffold(
      page: page,
      body: SdGrid(
        children: [
          SdCard(
            icon: LucideIcons.cpu,
            title: 'Tài nguyên máy chủ',
            children: [
              if (_poller.statusError != null)
                SdEmpty(
                  'Không tải được trạng thái: ${_poller.statusError}',
                  error: true,
                ),
              MeterRow(
                icon: LucideIcons.cpu,
                label: 'Vi xử lý CPU',
                value: s == null ? '—' : '${jsNum(cpu)}%',
                percent: cpu,
              ),
              MeterRow(
                icon: LucideIcons.memoryStick,
                label: 'Bộ nhớ RAM',
                value: s == null ? '—' : '${jsNum(ram)}%',
                percent: ram,
              ),
              SdNote.text(
                s == null
                    ? 'Đang tải thông số…'
                    : 'Đã dùng ${jsNum(ramUsed)} GB trên tổng số ${jsNum(ramTotal)} GB (${jsNum(ram)}%)',
              ),
            ],
          ),
          SdCard(
            icon: LucideIcons.gpu,
            title: 'Card đồ họa & Bộ tăng tốc (GPU / NPU)',
            children: [
              if (s == null)
                const SdEmpty('Đang quét phần cứng tăng tốc…')
              else if (gpus.isEmpty && npus.isEmpty)
                const SdEmpty('Không phát hiện GPU/NPU rời. Chạy trên CPU.')
              else
                ..._spaced([
                  for (final g in gpus) _gpuItem(g),
                  for (final n in npus) _npuItem(n),
                ]),
            ],
          ),
          SdCard(
            icon: LucideIcons.server,
            title: 'Trạng thái chi tiết dịch vụ nội bộ',
            children: [
              if (_poller.healthError != null)
                SdEmpty(
                  'Không kiểm tra được dịch vụ: ${_poller.healthError}',
                  error: true,
                ),
              _service(
                'llama.cpp / Mô hình suy luận',
                h == null ? null : llmOk,
                llmOk && rt != null && rt != 0
                    ? '${jsNum(rt as num)}ms'
                    : '${llm['status'] ?? 'offline'}',
              ),
              _service(
                'SQLite Memory Storage',
                h == null ? null : dbOk,
                sizeKb != null && sizeKb != 0
                    ? '${jsNum(sizeKb as num)} KB'
                    : (dbOk ? 'OK' : 'offline'),
              ),
              _service(
                'ChromaDB / Vector Search Engine',
                h == null ? null : ragOk,
                ragOk
                    ? '${rag['total_chunks'] ?? 0} chunks'
                    : 'không hoạt động',
                last: true,
              ),
            ],
          ),
          SdCard(
            icon: LucideIcons.layoutGrid,
            title: 'Ứng dụng Desktop đang phát hiện',
            children: [
              if (s == null)
                const SdEmpty('Đang quét ứng dụng chạy nền…')
              else if (apps.isEmpty)
                const SdEmpty('Không phát hiện ứng dụng desktop đang chạy.')
              else
                ..._spaced([for (final a in apps) _appRow(a)]),
            ],
          ),
        ],
      ),
    );
  }
}
