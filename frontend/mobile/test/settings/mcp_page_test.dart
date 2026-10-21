// Kết nối MCP (pages.ts mcpPage + index.ts loadMcpServers / renderMcpList / the toggle, add and JSON handlers).
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:jarvis_mobile/settings/pages/mcp_page.dart';

import 'catalog_fixtures.dart';
import 'fixtures.dart';

Future<List<http.Request>> _pump(
  WidgetTester t, {
  Map<String, http.Response Function(http.Request)> extra = const {},
}) async {
  final calls = <http.Request>[];
  await pumpPage(
    t,
    const McpPage(),
    routed({
      'GET /api/mcp/servers': (_) => jsonOk(mcpServersJson()),
      ...extra,
    }, calls: calls),
    size: const Size(390, 1400),
  );
  await t.pump(const Duration(milliseconds: 50));
  return calls;
}

void main() {
  testWidgets('summary, list rows and the command line of each server', (
    t,
  ) async {
    final calls = await _pump(t);
    expect(calls.where((c) => c.url.path == '/api/mcp/servers').length, 1);
    for (final s in [
      'Kết nối MCP',
      'Máy chủ cấu hình',
      'Đang kích hoạt',
      'Tệp cấu hình:',
      'config/mcp_config.json',
      'Danh sách máy chủ ngoại vi (MCP Servers)',
      'filesystem',
      'search',
      'remote',
      'Đã kết nối',
      'Tạm tắt',
      'Đang kết nối',
      'npx -y @modelcontextprotocol/server-filesystem /data',
      'uvx --api-key ••••',
      'stdio',
      'http',
    ]) {
      expect(find.text(s), findsWidgets, reason: s);
    }
    expect(find.text('3'), findsOneWidget); // total
    expect(find.text('1'), findsOneWidget); // connected
    expect(find.text('Tắt'), findsNWidgets(2));
    expect(find.text('Bật'), findsOneWidget);
  });

  testWidgets('filter matches name or command', (t) async {
    await _pump(t);
    await t.enterText(find.byKey(const Key('mcp-search')), 'uvx');
    await t.pump();
    expect(find.text('search'), findsOneWidget);
    expect(find.text('filesystem'), findsNothing);
    await t.enterText(find.byKey(const Key('mcp-search')), 'zzz');
    await t.pump();
    expect(
      find.text(
        'Chưa có máy chủ MCP nào được cấu hình trong config/mcp_config.json.',
      ),
      findsOneWidget,
    );
  });

  testWidgets('Xem JSON cấu hình shows the servers JSON; Sao chép copies it', (
    t,
  ) async {
    String? copied;
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(SystemChannels.platform, (call) async {
          if (call.method == 'Clipboard.setData') {
            copied = (call.arguments as Map)['text'] as String?;
          }
          return null;
        });
    addTearDown(
      () => TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
          .setMockMethodCallHandler(SystemChannels.platform, null),
    );
    await _pump(t);
    expect(find.byKey(const Key('mcp-json')), findsNothing);
    await t.tap(find.text('Xem JSON cấu hình'));
    await t.pump();
    expect(find.byKey(const Key('mcp-json')), findsOneWidget);
    expect(find.text('Nội dung config/mcp_config.json'), findsOneWidget);
    await t.tap(find.text('Sao chép'));
    await t.pump();
    final expected = const JsonEncoder.withIndent('  ')
        .convert({'servers': mcpServersJson()['servers']});
    expect(copied, expected);
    expect(find.text('Đã chép!'), findsOneWidget);
    await t.pump(const Duration(milliseconds: 2100));
    expect(find.text('Đã chép!'), findsNothing);
  });

  testWidgets('toggle posts {enabled: !current} to the encoded name, reloads', (
    t,
  ) async {
    final calls = await _pump(
      t,
      extra: {
        'POST /api/mcp/servers/filesystem/enabled': (_) =>
            jsonOk({'success': true}),
        'POST /api/mcp/servers/search/enabled': (_) =>
            jsonOk({'success': true}),
      },
    );
    await t.tap(find.byKey(const Key('mcp-toggle:filesystem')));
    await t.pump(const Duration(milliseconds: 50));
    var post = calls.firstWhere((c) => c.method == 'POST');
    expect(post.url.path, '/api/mcp/servers/filesystem/enabled');
    expect(jsonDecode(post.body), {'enabled': false});
    expect(calls.where((c) => c.method == 'GET').length, 2);
    await t.tap(find.byKey(const Key('mcp-toggle:search')));
    await t.pump(const Duration(milliseconds: 50));
    post = calls.where((c) => c.method == 'POST').last;
    expect(jsonDecode(post.body), {'enabled': true});
    await t.pump(const Duration(seconds: 5)); // the second reload after 4 s
    expect(
      calls.where((c) => c.method == 'GET').length,
      greaterThanOrEqualTo(4),
    );
  });

  testWidgets("a refused toggle shows web's message", (t) async {
    await _pump(
      t,
      extra: {
        'POST /api/mcp/servers/filesystem/enabled': (_) => jsonOk({
          'success': false,
          'error': 'Chỉ quản lý MCP được từ chính máy chạy JARVIS.',
        }, 403),
      },
    );
    await t.tap(find.byKey(const Key('mcp-toggle:filesystem')));
    await t.pump(const Duration(milliseconds: 50));
    expect(
      find.text(
        'Không đổi được trạng thái MCP: Chỉ quản lý MCP được từ chính máy chạy JARVIS.',
      ),
      findsOneWidget,
    );
    await t.pump(const Duration(seconds: 5));
  });

  testWidgets('add form: stdio body with trimmed non-empty args lines', (
    t,
  ) async {
    final calls = await _pump(
      t,
      extra: {
        'POST /api/mcp/servers': (_) => jsonOk({'success': true}),
      },
    );
    for (final s in [
      'Thêm máy chủ MCP',
      'Tên',
      'Loại',
      'Lệnh',
      'Tham số (mỗi dòng một tham số)',
      'Thêm và kết nối',
    ]) {
      expect(find.text(s), findsWidgets, reason: s);
    }
    await t.enterText(find.byKey(const Key('mcp-add-name')), 'context7');
    await t.enterText(find.byKey(const Key('mcp-add-command')), 'npx');
    await t.enterText(
      find.byKey(const Key('mcp-add-args')),
      '-y\n\n  @upstash/context7-mcp \n',
    );
    await t.ensureVisible(find.text('Thêm và kết nối'));
    await t.tap(find.text('Thêm và kết nối'));
    await t.pump(const Duration(milliseconds: 50));
    final post = calls.firstWhere(
      (c) => c.method == 'POST' && c.url.path == '/api/mcp/servers',
    );
    expect(jsonDecode(post.body), {
      'name': 'context7',
      'type': 'stdio',
      'command': 'npx',
      'args': ['-y', '@upstash/context7-mcp'],
      'url': null,
    });
    expect(find.text('Đã thêm, đang kết nối…'), findsOneWidget);
    expect(
      t
          .widget<TextField>(
            find.descendant(
              of: find.byKey(const Key('mcp-add-name')),
              matching: find.byType(TextField),
            ),
          )
          .controller!
          .text,
      '',
    );
    await t.pump(const Duration(seconds: 5));
  });

  testWidgets('add form: http type sends url and null command', (t) async {
    final calls = await _pump(
      t,
      extra: {
        'POST /api/mcp/servers': (_) => jsonOk({'success': true}),
      },
    );
    await t.ensureVisible(find.byKey(const Key('mcp-add-type')));
    await t.tap(find.byKey(const Key('mcp-add-type')));
    await t.pump(const Duration(milliseconds: 300));
    await t.tap(find.text('http').last);
    await t.pump(const Duration(milliseconds: 300));
    expect(find.byKey(const Key('mcp-add-command')), findsNothing);
    expect(find.byKey(const Key('mcp-add-url')), findsOneWidget);
    await t.enterText(find.byKey(const Key('mcp-add-name')), 'r');
    await t.enterText(find.byKey(const Key('mcp-add-url')), 'https://x/y');
    await t.ensureVisible(find.text('Thêm và kết nối'));
    await t.tap(find.text('Thêm và kết nối'));
    await t.pump(const Duration(milliseconds: 50));
    final post = calls.firstWhere(
      (c) => c.method == 'POST' && c.url.path == '/api/mcp/servers',
    );
    expect(jsonDecode(post.body), {
      'name': 'r',
      'type': 'http',
      'command': null,
      'args': <String>[],
      'url': 'https://x/y',
    });
    await t.pump(const Duration(seconds: 5));
  });

  testWidgets('a refused add shows the server text', (t) async {
    await _pump(
      t,
      extra: {
        'POST /api/mcp/servers': (_) => jsonOk({
          'success': false,
          'error': 'Đã có máy chủ trùng tên.',
        }, 409),
      },
    );
    await t.ensureVisible(find.text('Thêm và kết nối'));
    await t.tap(find.text('Thêm và kết nối'));
    await t.pump(const Duration(milliseconds: 50));
    expect(find.text('Đã có máy chủ trùng tên.'), findsOneWidget);
  });

  testWidgets('success:false from the list shows Lỗi đọc cấu hình MCP', (
    t,
  ) async {
    await _pump(
      t,
      extra: {
        'GET /api/mcp/servers': (_) =>
            jsonOk({'success': false, 'error': 'hư', 'servers': []}),
      },
    );
    expect(find.text('Lỗi đọc cấu hình MCP: hư'), findsOneWidget);
  });

  testWidgets('an HTTP failure shows Lỗi kết nối API MCP', (t) async {
    await _pump(
      t,
      extra: {
        'GET /api/mcp/servers': (_) => jsonOk({'detail': 'down'}, 500),
      },
    );
    expect(find.text('Lỗi kết nối API MCP: down'), findsOneWidget);
  });
}
