// Các trang danh mục (pages.ts agents/hooks/skills/prompts/commands/plugins + index.ts loadMentions ... renderPluginsList):
// one GET /api/settings/catalog, the web's cards, search rules, copy buttons, error lines and the prompt editor.
import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:jarvis_mobile/settings/pages/catalog_page.dart';

import 'catalog_fixtures.dart';
import 'fixtures.dart';

Future<List<http.Request>> _pump(
  WidgetTester t,
  String category, {
  Map<String, http.Response Function(http.Request)> extra = const {},
}) async {
  final calls = <http.Request>[];
  await pumpPage(
    t,
    CatalogPage(category: category),
    routed({
      'GET /api/settings/catalog': (_) => jsonOk(catalogJson()),
      ...extra,
    }, calls: calls),
  );
  await t.pump(const Duration(milliseconds: 50));
  return calls;
}

void main() {
  testWidgets('agents: mention cards with file, badge, example and note', (
    t,
  ) async {
    final calls = await _pump(t, 'agents');
    expect(calls.where((c) => c.url.path == '/api/settings/catalog').length, 1);
    for (final s in [
      'Gọi tên (@)',
      '@rag',
      'engine/rag',
      'Sẵn sàng',
      'Hỏi kho tài liệu đã nạp',
      'Gõ trong command-bar:',
      '@rag <câu hỏi>',
      '@weather',
      'Mention dùng được',
      'Tìm mention theo tên hoặc chức năng...',
    ]) {
      expect(find.text(s), findsWidgets, reason: s);
    }
    expect(find.text('2'), findsOneWidget); // the counter
    expect(find.text('Sao chép'), findsNWidgets(2));
    expect(
      find.text('Hoặc nói/gõ tự nhiên, JARVIS tự chọn công cụ.'),
      findsNWidgets(2),
    );
  });

  testWidgets('agents: search matches name, description and example', (
    t,
  ) async {
    await _pump(t, 'agents');
    await t.enterText(find.byType(TextField), 'thời tiết');
    await t.pump();
    expect(find.text('@weather'), findsOneWidget);
    expect(find.text('@rag'), findsNothing);
    await t.enterText(find.byType(TextField), '<câu hỏi>');
    await t.pump();
    expect(find.text('@rag'), findsOneWidget);
    expect(find.text('2'), findsOneWidget); // the counter keeps the full count
    await t.enterText(find.byType(TextField), 'zzz');
    await t.pump();
    expect(find.text('Không tìm thấy mention nào phù hợp.'), findsOneWidget);
  });

  testWidgets('copy puts the example on the clipboard and says Đã chép!', (
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
    await _pump(t, 'agents');
    await t.tap(find.byKey(const Key('copy:rag')));
    await t.pump();
    expect(copied, '@rag <câu hỏi>');
    expect(find.text('Đã chép!'), findsOneWidget);
    await t.pump(const Duration(milliseconds: 1600));
    expect(find.text('Đã chép!'), findsNothing);
  });

  testWidgets('hooks: events tags, file path, badge, search by event', (
    t,
  ) async {
    await _pump(t, 'hooks');
    for (final s in [
      'logger',
      'hooks/logger.py',
      'Đang kích hoạt',
      'Ghi log mọi tin nhắn',
      'Sự kiện lắng nghe:',
      'on_startup',
      'on_message_receive',
      'Hooks từ hooks/',
    ]) {
      expect(find.text(s), findsWidgets, reason: s);
    }
    await t.enterText(find.byType(TextField), 'on_startup');
    await t.pump();
    expect(find.text('logger'), findsOneWidget);
    await t.enterText(find.byType(TextField), 'zzz');
    await t.pump();
    expect(
      find.text('Chưa có Hook nào được nạp từ thư mục hooks/.'),
      findsOneWidget,
    );
  });

  testWidgets('skills: tags row only when there are tags, search by tag', (
    t,
  ) async {
    await _pump(t, 'skills');
    expect(find.text('git-helper'), findsOneWidget);
    expect(find.text('skills/git-helper/SKILL.md'), findsOneWidget);
    expect(find.text('Đã nạp'), findsNWidgets(2));
    expect(find.text('Từ khoá:'), findsOneWidget); // cooking has no tags
    expect(find.text('commit'), findsOneWidget);
    await t.enterText(find.byType(TextField), 'COMMIT');
    await t.pump();
    expect(find.text('git-helper'), findsOneWidget);
    expect(find.text('cooking'), findsNothing);
  });

  testWidgets('commands: usage, params note by "<", search by usage', (
    t,
  ) async {
    await _pump(t, 'commands');
    for (final s in [
      'Cú pháp trong command-bar:',
      '/help',
      '/note <content>',
      'engine/server/slash_commands.py',
      'Không cần tham số.',
      'Thiếu nội dung bắt buộc thì JARVIS sẽ hỏi lại ở lượt sau.',
      'Lệnh / dùng được',
    ]) {
      expect(find.text(s), findsWidgets, reason: s);
    }
    await t.enterText(find.byType(TextField), '<content>');
    await t.pump();
    expect(find.text('note'), findsOneWidget);
    expect(find.text('help'), findsNothing);
  });

  testWidgets('plugins: card with file path and Hoạt động', (t) async {
    await _pump(t, 'plugins');
    for (final s in [
      'spotify',
      'plugins/spotify.py',
      'Hoạt động',
      'Điều khiển Spotify',
      'Plugins từ plugins/',
    ]) {
      expect(find.text(s), findsWidgets, reason: s);
    }
  });

  testWidgets('an HTTP failure shows the web error line, not an empty list', (
    t,
  ) async {
    await _pump(
      t,
      'agents',
      extra: {
        'GET /api/settings/catalog': (_) => jsonOk({'error': 'hỏng'}, 500),
      },
    );
    expect(find.text('Lỗi nạp danh sách Mention: hỏng'), findsOneWidget);
    expect(find.text('0'), findsOneWidget);
  });

  testWidgets('loading line while the catalog is on its way', (t) async {
    final gate = Completer<void>();
    await pumpPage(
      t,
      const CatalogPage(category: 'hooks'),
      MockClient((_) async {
        await gate.future;
        return jsonOk(catalogJson());
      }),
    );
    expect(
      find.text('Đang nạp danh sách Hooks từ thư mục hooks/…'),
      findsOneWidget,
    );
    gate.complete();
    await t.pump(const Duration(milliseconds: 50));
    expect(find.text('logger'), findsOneWidget);
  });

  group('prompts', () {
    testWidgets('card: title, path, line count, button; editor shows content', (
      t,
    ) async {
      await _pump(t, 'prompts');
      for (final s in [
        'General Chat',
        'prompt/general_chat.md',
        '7 dòng',
        'Prompt trò chuyện chung',
        'Xem nội dung prompt',
        'Prompts từ prompt/',
      ]) {
        expect(find.text(s), findsWidgets, reason: s);
      }
      await t.tap(find.text('Xem nội dung prompt'));
      await t.pump(const Duration(milliseconds: 300));
      expect(find.text('Prompt: General Chat'), findsOneWidget);
      expect(
        find.text(
          'Lưu ghi đè prompt/general_chat.md và có hiệu lực ngay ở lượt kế tiếp.',
        ),
        findsOneWidget,
      );
      expect(find.text('Lưu prompt'), findsOneWidget);
      final field = t.widget<TextField>(find.byKey(const Key('prompt-editor')));
      expect(field.controller!.text, '# General Chat\nBạn là JARVIS.');
    });

    testWidgets('save posts {id, content} and shows Đã lưu prompt', (t) async {
      final calls = await _pump(
        t,
        'prompts',
        extra: {
          'POST /api/prompts/save': (_) => jsonOk({'success': true}),
        },
      );
      await t.tap(find.text('Xem nội dung prompt'));
      await t.pump(const Duration(milliseconds: 300));
      await t.enterText(find.byKey(const Key('prompt-editor')), 'mới');
      await t.tap(find.text('Lưu prompt'));
      await t.pump(const Duration(milliseconds: 100));
      final post = calls.firstWhere((c) => c.url.path == '/api/prompts/save');
      expect(jsonDecode(post.body), {'id': 'general_chat', 'content': 'mới'});
      expect(find.text('Đã lưu prompt'), findsOneWidget);
      await t.pump(const Duration(milliseconds: 1300));
      // reopening shows the saved text (web updates its cache)
      await t.tap(find.byKey(const Key('prompt-close')));
      await t.pump(const Duration(milliseconds: 300));
      await t.tap(find.text('Xem nội dung prompt'));
      await t.pump(const Duration(milliseconds: 300));
      expect(
        t
            .widget<TextField>(find.byKey(const Key('prompt-editor')))
            .controller!
            .text,
        'mới',
      );
    });

    testWidgets('a refused save shows the server text', (t) async {
      await _pump(
        t,
        'prompts',
        extra: {
          'POST /api/prompts/save': (_) => jsonOk({
            'success': false,
            'error': 'Prompt quá lớn (tối đa 256KB)',
          }),
        },
      );
      await t.tap(find.text('Xem nội dung prompt'));
      await t.pump(const Duration(milliseconds: 300));
      await t.tap(find.text('Lưu prompt'));
      await t.pump(const Duration(milliseconds: 100));
      expect(find.text('Prompt quá lớn (tối đa 256KB)'), findsOneWidget);
      await t.pump(const Duration(milliseconds: 1300));
    });

    testWidgets('an HTTP failure on save shows the error', (t) async {
      await _pump(
        t,
        'prompts',
        extra: {
          'POST /api/prompts/save': (_) => jsonOk({'detail': 'boom'}, 500),
        },
      );
      await t.tap(find.text('Xem nội dung prompt'));
      await t.pump(const Duration(milliseconds: 300));
      await t.tap(find.text('Lưu prompt'));
      await t.pump(const Duration(milliseconds: 100));
      expect(find.text('boom'), findsOneWidget);
      await t.pump(const Duration(milliseconds: 1300));
    });
  });
}
