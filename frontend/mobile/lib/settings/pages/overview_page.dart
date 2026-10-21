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

/// Tổng quan (pages.ts overviewPage + index.ts loadStatus / loadDetailedHealth / fillRuntime / renderAppBadges): the one status line,
/// the hardware in a 2 x 2 grid, then flat sections under hairlines - polled every 5 s while the page is open.
class OverviewPage extends StatefulWidget {
  const OverviewPage({super.key});

  @override
  State<OverviewPage> createState() => _OverviewPageState();
}

class _OverviewPageState extends State<OverviewPage> {
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

  /// setDot(): ok / err / off from a flag of /api/settings/status (null while it has not answered).
  static (DotState, String) _dot(bool? flag, {bool offWhenFalse = false}) {
    if (flag == null) return (DotState.unknown, '—');
    if (flag) return (DotState.ok, 'Sẵn sàng');
    return offWhenFalse
        ? (DotState.off, 'Chưa bật')
        : (DotState.err, 'Lỗi kết nối');
  }

  @override
  Widget build(BuildContext context) {
    final page = settingsPages.firstWhere((p) => p.id == 'overview');
    final s = _poller.status;
    final h = _poller.health;
    final sys = _map(s?['system']);
    final rt = _map(s?['runtime']);
    final tokens = _map(s?['session_tokens']);

    // the service rows, in the page's order; their dots feed the summary line (updateOverviewSummary)
    (DotState, String) flag(String key, {bool off = false}) =>
        _dot(s == null ? null : s[key] == true, offWhenFalse: off);
    (DotState, String) infra(bool? ok, String bad) => ok == null
        ? (DotState.unknown, 'Đang kiểm tra…')
        : ok
        ? (DotState.ok, 'Sẵn sàng')
        : (DotState.err, bad);
    (String, DotState, String) row(String name, (DotState, String) d) =>
        (name, d.$1, d.$2);
    final rows = [
      row('Lõi trí tuệ', flag('intelligence_core_ok')),
      row('Máy chủ chính', flag('server_engine_ok')),
      row('Máy chủ LLM', flag('llm_server_ok')),
      row('Máy chủ giọng đọc', flag('tts_server_ok', off: true)),
      row(
        'Dịch vụ LLM',
        infra(
          h == null ? null : _map(h['llm'])['status'] == 'online',
          'Mất kết nối',
        ),
      ),
      row(
        'RAG',
        infra(
          h == null ? null : _map(h['rag'])['enabled'] == true,
          'Không hoạt động',
        ),
      ),
      row(
        'Cơ sở dữ liệu',
        infra(h == null ? null : _map(h['database'])['ok'] == true, 'Lỗi'),
      ),
      row('Trung tâm hệ thống', flag('server_engine_ok')),
    ];
    final failed = [
      for (final r in rows)
        if (r.$2 == DotState.err) r.$1,
    ];
    final checking = rows.any((r) => r.$2 == DotState.unknown);
    final summary = failed.isNotEmpty
        ? '${failed.length} dịch vụ lỗi: ${failed.join(', ')}'
        : checking
        ? 'Đang kiểm tra dịch vụ…'
        : 'Tất cả dịch vụ hoạt động';

    // hardware
    final cpu = (sys['cpu_percent'] as num?) ?? 0;
    final ram = (sys['ram_percent'] as num?) ?? 0;
    final ramUsed = (sys['ram_used_gb'] as num?) ?? 0;
    final ramTotal = (sys['ram_total_gb'] as num?) ?? 0;
    final gpus = (sys['gpus'] as List?)?.map(_map).toList() ?? const [];
    num gpuPct = 0;
    String gpuName = 'Không phát hiện GPU chuyên dụng';
    if (gpus.isNotEmpty) {
      final g0 = gpus.first;
      final mem = (g0['mem_used_mb'] as num?) ?? 0;
      final tot =
          (g0['mem_total_mb'] as num?) ?? (g0['vram_total_mb'] as num?) ?? 0;
      gpuPct = tot > 0
          ? (mem / tot * 100).round()
          : ((g0['util_percent'] as num?) ?? 0);
      final name = '${g0['name'] ?? ''}'.replaceFirst(
        RegExp(r'NVIDIA\s*', caseSensitive: false),
        '',
      );
      gpuName = '$name · ${(mem / 1024).round()}GB';
    }
    final loaded = s != null;

    // fillRuntime(): the TTS line
    final engine = rt['tts_engine'];
    final engineName = engine == 'vieneu'
        ? 'VieNeu'
        : engine == 'edge'
        ? 'Edge-TTS'
        : 'Chưa bật';
    final voice = engine == 'vieneu'
        ? rt['vieneu_voice']
        : engine == 'edge'
        ? rt['edge_voice']
        : '';
    final ttsLine = voice != null && '$voice'.isNotEmpty
        ? '$engineName · $voice'
        : engineName;
    String dash(Object? v) => v == null || '$v'.isEmpty ? '—' : '$v';
    final apps = ((s?['open_apps'] as List?) ?? const [])
        .map((e) => '$e')
        .toList();

    return PageScaffold(
      page: page,
      body: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const SizedBox(height: 4),
          Row(
            children: [
              StatusDot(
                failed.isNotEmpty
                    ? DotState.err
                    : checking
                    ? DotState.unknown
                    : DotState.ok,
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Text(
                  summary,
                  style: TextStyle(
                    fontSize: JTokens.fsInput,
                    fontWeight: FontWeight.w500,
                    color: failed.isEmpty && checking
                        ? JTokens.muted
                        : JTokens.text,
                  ),
                ),
              ),
            ],
          ),
          if (_poller.statusError != null)
            SdEmpty(
              'Không tải được trạng thái: ${_poller.statusError}',
              error: true,
            ),
          if (_poller.healthError != null)
            SdEmpty(
              'Không kiểm tra được dịch vụ: ${_poller.healthError}',
              error: true,
            ),
          const SizedBox(height: 20),
          _Metrics([
            _Metric('CPU', loaded ? '${jsNum(cpu)}%' : '—', meter: cpu),
            _Metric(
              'RAM',
              loaded ? '${jsNum(ram)}%' : '—',
              meter: ram,
              sub: loaded ? '${jsNum(ramUsed)} / ${jsNum(ramTotal)} GB' : '',
            ),
            _Metric(
              'VRAM GPU',
              loaded ? '${jsNum(gpuPct)}%' : '—',
              meter: gpuPct,
              sub: loaded ? gpuName : '',
            ),
            _Metric(
              'Thời gian chạy',
              loaded ? formatUptime(s['uptime_seconds'] as num?) : '—',
              sub: 'Cổng máy chủ ${loaded ? (s['server_port'] ?? 8340) : '—'}',
            ),
          ]),
          const SizedBox(height: 20),
          _Section(LucideIcons.shield, 'Dịch vụ', [
            for (var i = 0; i < rows.length; i++)
              StatusRow(
                name: rows[i].$1,
                state: rows[i].$2,
                text: rows[i].$3,
                dense: true,
                last: i == rows.length - 1,
              ),
          ]),
          const SizedBox(height: 28),
          _Section(LucideIcons.server, 'Mô hình & kết nối', [
            SdKv([
              ('Mô hình LLM', dash(rt['llm_model'])),
              ('Mô hình embedding', dash(rt['embed_model'])),
              ('TTS đang chạy', loaded ? ttsLine : '—'),
              (
                'MCP đã kết nối',
                loaded
                    ? '${s['mcp_connected'] ?? 0} / ${s['mcp_total'] ?? 0}'
                    : '—',
              ),
              (
                'Gọi tên (@)',
                loaded ? formatNumber(s['mentions_count'] as num?) : '—',
              ),
              (
                'Kỹ năng · Lệnh',
                loaded
                    ? '${formatNumber(s['skill_count'] as num?)} · ${formatNumber(s['command_count'] as num?)}'
                    : '—',
              ),
            ]),
          ]),
          const SizedBox(height: 28),
          _Section(LucideIcons.brain, 'Dữ liệu tri thức', [
            SdKv([
              (
                'Bản ghi bộ nhớ',
                loaded ? formatNumber(s['memory_count'] as num?) : '—',
              ),
              (
                'Hội thoại',
                loaded
                    ? formatNumber(s['conversation_turn_count'] as num?)
                    : '—',
              ),
              ('Tác vụ', loaded ? formatNumber(s['task_count'] as num?) : '—'),
              (
                'Kỹ năng đã nạp',
                loaded ? formatNumber(s['skill_count'] as num?) : '—',
              ),
              (
                'Lệnh hỗ trợ',
                loaded ? formatNumber(s['command_count'] as num?) : '—',
              ),
            ]),
          ]),
          const SizedBox(height: 28),
          _Section(LucideIcons.activity, 'Token phiên làm việc', [
            SdKv([
              (
                'Tổng',
                tokens.isEmpty ? '—' : formatNumber(tokens['total'] as num?),
              ),
              (
                'Đầu vào',
                tokens.isEmpty ? '—' : formatNumber(tokens['input'] as num?),
              ),
              (
                'Đầu ra',
                tokens.isEmpty ? '—' : formatNumber(tokens['output'] as num?),
              ),
            ]),
          ]),
          const SizedBox(height: 28),
          _Section(LucideIcons.layoutGrid, 'Ứng dụng đang mở', [
            if (!loaded)
              const SdEmpty('Đang quét…', pad: false)
            else if (apps.isEmpty)
              const SdEmpty('Không có ứng dụng đáng chú ý.', pad: false)
            else
              Wrap(
                spacing: 6,
                runSpacing: 6,
                children: [for (final a in apps.take(6)) SdBadge(a)],
              ),
          ]),
        ],
      ),
    );
  }
}

class _Metric {
  const _Metric(this.label, this.value, {this.meter, this.sub = ''});

  final String label;
  final String value;
  final num? meter;
  final String sub;
}

/// `.sd-ov-metrics` on a phone: 2 x 2 with a hairline between the columns and above each row.
class _Metrics extends StatelessWidget {
  const _Metrics(this.items);

  final List<_Metric> items;

  @override
  Widget build(BuildContext context) {
    Widget cell(int i) => Expanded(
      child: Container(
        padding: EdgeInsets.fromLTRB(i.isEven ? 0 : 12, 8, 12, 10),
        decoration: BoxDecoration(
          border: Border(
            left: i.isEven
                ? BorderSide.none
                : const BorderSide(color: JTokens.border),
            top: i >= 2
                ? const BorderSide(color: JTokens.border)
                : BorderSide.none,
          ),
        ),
        child: _MetricCell(items[i]),
      ),
    );
    return Container(
      decoration: const BoxDecoration(
        border: Border(top: BorderSide(color: JTokens.border)),
      ),
      child: Column(
        children: [
          IntrinsicHeight(
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [cell(0), cell(1)],
            ),
          ),
          IntrinsicHeight(
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [cell(2), cell(3)],
            ),
          ),
        ],
      ),
    );
  }
}

class _MetricCell extends StatelessWidget {
  const _MetricCell(this.m);

  final _Metric m;

  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      Text(
        m.label,
        style: const TextStyle(fontSize: JTokens.fsSmall, color: JTokens.muted),
      ),
      const SizedBox(height: 2),
      Text(
        m.value,
        style: const TextStyle(
          fontSize: JTokens.fsInput,
          fontWeight: FontWeight.w600,
          height: 1.2,
          color: JTokens.text,
          fontFeatures: [FontFeature.tabularFigures()],
        ),
      ),
      if (m.meter != null) ...[const SizedBox(height: 6), Meter(m.meter!)],
      if (m.sub.isNotEmpty) ...[
        const SizedBox(height: 2),
        Text(
          m.sub,
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
          style: const TextStyle(
            fontSize: JTokens.fsSmall,
            color: JTokens.muted,
            fontFeatures: [FontFeature.tabularFigures()],
          ),
        ),
      ],
    ],
  );
}

/// `.sd-ov-section`: a hairline above, 14px, the heading, the content.
class _Section extends StatelessWidget {
  const _Section(this.icon, this.title, this.children);

  final IconData icon;
  final String title;
  final List<Widget> children;

  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.only(top: 14),
    decoration: const BoxDecoration(
      border: Border(top: BorderSide(color: JTokens.border)),
    ),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Padding(
          padding: const EdgeInsets.only(bottom: 10),
          child: Row(
            children: [
              Icon(icon, size: 16, color: JTokens.accent),
              const SizedBox(width: 8),
              Text(
                title,
                style: const TextStyle(
                  fontSize: JTokens.fsUi,
                  fontWeight: FontWeight.w600,
                  color: JTokens.text,
                ),
              ),
            ],
          ),
        ),
        ...children,
      ],
    ),
  );
}
