// Bộ nhớ (pages.ts memoryPage + memory.ts): summary, the seven tabs, search, paging, detail editor, the dependency-checked delete flow,
// re-embed, evolution update, gym, bulk delete.
import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:jarvis_mobile/chat/lucide_glyphs.dart';
import 'package:jarvis_mobile/settings/action_button.dart';
import 'package:jarvis_mobile/settings/pages/memory_page.dart';

import '../chat/fakes.dart';
import 'fixtures.dart';

Map<String, http.Response Function(http.Request)> _base() => {
  'GET /api/memory-control/summary': (_) => jsonOk(memorySummaryJson()),
  'GET /api/learnings/list': (_) => jsonOk(learningsJson()),
  'GET /api/workflows/list': (_) => jsonOk(workflowsJson()),
  'GET /api/corrections/list': (_) => jsonOk(correctionsJson()),
  'GET /api/evolution/list': (_) => jsonOk(evolutionJson()),
  'GET /api/gym/list': (_) => jsonOk(gymJson()),
  'GET /api/users/list': (_) => jsonOk(usersJson()),
};

Future<List<http.Request>> _pump(
  WidgetTester t, {
  Map<String, http.Response Function(http.Request)> extra = const {},
}) async {
  final calls = <http.Request>[];
  await pumpPage(
    t,
    const MemoryPage(),
    routed({..._base(), ...extra}, calls: calls),
  );
  await t.pumpAndSettle();
  return calls;
}

Iterable<http.Request> _to(List<http.Request> c, String m, String path) =>
    c.where((r) => r.method == m && r.url.path == path);

String _field(WidgetTester t, String name) => t
    .widget<TextField>(
      find.descendant(
        of: find.byKey(Key('field:$name')),
        matching: find.byType(TextField),
      ),
    )
    .controller!
    .text;

Future<void> _openRecord(WidgetTester t, int id) async {
  await t.tap(find.byKey(Key('rec:$id')));
  await t.pumpAndSettle();
}

Future<void> _cat(WidgetTester t, String id) async {
  await t.ensureVisible(find.byKey(Key('cat:$id')));
  await t.tap(find.byKey(Key('cat:$id')));
  await t.pumpAndSettle();
}

/// A tap that opens a dialog: the busy button spins for ever, so step the frames by hand instead of pumpAndSettle.
Future<void> _tapAction(WidgetTester t, String text) async {
  await t.tap(find.text(text));
  await t.pump();
  await t.pump(const Duration(milliseconds: 400));
}

Future<void> _tapText(WidgetTester t, String text) async {
  await t.tap(find.text(text));
  await t.pumpAndSettle();
}

void main() {
  testWidgets('category tabs morph their icon in place; icons are morphicons', (
    t,
  ) async {
    await _pump(t);
    expect(byGlyph(lightbulbGlyph), findsOneWidget); // learning is active
    expect(byGlyph(workflowGlyph), findsOneWidget);
    final bulb = t.state(byGlyph(lightbulbGlyph));
    final workflow = t.state(byGlyph(workflowGlyph));
    await t.ensureVisible(find.byKey(const Key('cat:workflow')));
    await t.tap(find.byKey(const Key('cat:workflow')));
    await t.pump(const Duration(milliseconds: 50));
    expect(identical(t.state(byGlyph(rotateCwGlyph).first), workflow), isTrue);
    expect(identical(t.state(byGlyph(brainGlyph).first), bulb), isTrue);
    await t.pumpAndSettle();
    expect(byGlyph(lightbulbGlyph), findsNothing);
    expect(byGlyph(searchGlyph), findsOneWidget);
    expect(byGlyph(chevronLeftGlyph), findsOneWidget);
    expect(byGlyph(chevronRightGlyph), findsOneWidget);
    expect(
      find.widgetWithText(ActionButton, 'Xoá đã chọn (0)'),
      findsOneWidget,
    );
  });

  testWidgets('loads the summary and the first tab with the web query', (
    t,
  ) async {
    final calls = await _pump(t);
    expect(_to(calls, 'GET', '/api/memory-control/summary'), hasLength(1));
    final list = _to(calls, 'GET', '/api/learnings/list').single;
    expect(list.url.queryParameters, {'q': '', 'limit': '50', 'offset': '0'});
    // the page head and the seven tabs, the count pills of the six that have one
    for (final s in [
      'Bộ nhớ',
      'Learnings',
      'Workflows',
      'Outcomes',
      'Sửa công cụ',
      'Conversations',
      'Gym Memory',
      'Evolution',
      'Tìm',
      'Chọn tất cả',
      'Xoá đã chọn (0)',
      'Tính lại tất cả embedding',
      'Trước',
      'Sau',
      '1–2 / 2',
    ]) {
      expect(find.text(s), findsOneWidget, reason: s);
    }
    expect(find.text('120'), findsOneWidget); // conversations pill
    expect(find.text('4'), findsOneWidget); // corrections pill
    expect(
      find.descendant(
        of: find.byKey(const Key('cat:user')),
        matching: find.text('8'),
      ),
      findsOneWidget,
    ); // user pill
    // card: title = semantic_key, the type tag, the content as preview
    expect(find.text('coffee_preference'), findsOneWidget);
    expect(find.text('preference'), findsOneWidget);
    expect(find.text('Ngài thích cà phê đen không đường'), findsOneWidget);
  });

  testWidgets('a request error shows the page error, not an empty list', (
    t,
  ) async {
    await _pump(
      t,
      extra: {
        'GET /api/learnings/list': (_) =>
            jsonOk({'success': false, 'error': 'db_locked'}),
      },
    );
    expect(find.text('Lỗi tải bộ nhớ: db_locked'), findsOneWidget);
    expect(find.text('Không có dữ liệu'), findsNothing);
  });

  testWidgets('an HTTP failure shows the backend text', (t) async {
    await _pump(
      t,
      extra: {
        'GET /api/learnings/list': (_) =>
            jsonOk({'success': false, 'error': 'boom'}, 500),
      },
    );
    expect(find.text('Lỗi tải bộ nhớ: boom'), findsOneWidget);
  });

  testWidgets('an empty tab shows the empty box with the category name', (
    t,
  ) async {
    await _pump(
      t,
      extra: {
        'GET /api/learnings/list': (_) =>
            jsonOk({'success': true, 'learnings': [], 'total': 0}),
      },
    );
    expect(find.text('Không có dữ liệu'), findsOneWidget);
    expect(
      find.text(
        'Nhóm Learnings chưa có bản ghi nào hoặc không khớp từ khóa tìm kiếm.',
      ),
      findsOneWidget,
    );
    expect(find.text('0–0 / 0'), findsOneWidget);
  });

  testWidgets(
    'a tab loads its own endpoint from offset 0; evolution has no checkboxes',
    (t) async {
      final calls = await _pump(t);
      await _cat(t, 'workflow');
      expect(_to(calls, 'GET', '/api/workflows/list'), hasLength(1));
      expect(find.text('tra cứu giá vàng'), findsOneWidget); // title = intent
      expect(
        find.text('Đã trả lời đúng giá'),
        findsOneWidget,
      ); // preview = success_evidence
      expect(
        find.text('Tính lại tất cả embedding'),
        findsNothing,
      ); // learnings only

      await _cat(t, 'correction');
      expect(find.text('web_search → play_music · 2 lần'), findsOneWidget);

      await _cat(t, 'evolution');
      expect(find.text('Xưng hô ngắn gọn.'), findsOneWidget);
      expect(find.byKey(const Key('sel:style')), findsNothing);
      final all = t.widget<Checkbox>(find.byKey(const Key('select-all')));
      expect(all.onChanged, isNull); // disabled
    },
  );

  testWidgets('search sends q trimmed and starts from offset 0', (t) async {
    final calls = await _pump(t);
    await t.enterText(
      find.descendant(
        of: find.byKey(const Key('memory-search')),
        matching: find.byType(TextField),
      ),
      '  cà phê ',
    );
    await _tapText(t, 'Tìm');
    final last = _to(calls, 'GET', '/api/learnings/list').last;
    expect(last.url.queryParameters['q'], 'cà phê');
    expect(last.url.queryParameters['offset'], '0');
  });

  testWidgets('paging moves by 50 and shows the range', (t) async {
    final calls = await _pump(
      t,
      extra: {
        'GET /api/learnings/list': (_) => jsonOk(learningsJson(total: 120)),
      },
    );
    expect(find.text('1–2 / 120'), findsOneWidget);
    await _tapText(t, 'Sau');
    expect(
      _to(
        calls,
        'GET',
        '/api/learnings/list',
      ).last.url.queryParameters['offset'],
      '50',
    );
    await _tapText(t, 'Trước');
    expect(
      _to(
        calls,
        'GET',
        '/api/learnings/list',
      ).last.url.queryParameters['offset'],
      '0',
    );
  });

  testWidgets(
    'a record opens its editor with fields, system info and a way back',
    (t) async {
      await _pump(t);
      await _openRecord(t, 42);
      expect(find.text('Bản ghi #42'), findsOneWidget);
      expect(find.text('← Danh sách'), findsOneWidget);
      for (final s in [
        'Loại (Type)',
        'Khóa ngữ nghĩa (Semantic Key)',
        'Nội dung (Content)',
        'Nguồn gốc (Source)',
        'Độ quan trọng (Importance 1-10)',
        'Vector embedding (JSON, để trống = xoá, gõ recompute = tính lại)',
        'Thông tin hệ thống',
        'Mã bản ghi (ID):',
        'Model embedding:',
        'Xóa',
        'Lưu thay đổi',
        'Tính lại embedding',
      ]) {
        expect(find.text(s), findsOneWidget, reason: s);
      }
      expect(_field(t, 'content'), 'Ngài thích cà phê đen không đường');
      expect(_field(t, 'importance'), '7');
      expect(
        find.text('Tìm'),
        findsNothing,
      ); // the list is hidden on a phone while the editor is open
      await _tapText(t, '← Danh sách');
      expect(find.text('Tìm'), findsOneWidget);
    },
  );

  testWidgets('save posts every editable field; numbers as numbers', (t) async {
    Map<String, dynamic>? body;
    final calls = await _pump(
      t,
      extra: {
        'POST /api/memory-control/update': (r) {
          body = jsonDecode(r.body) as Map<String, dynamic>;
          return jsonOk({'success': true});
        },
      },
    );
    await _openRecord(t, 42);
    await t.enterText(
      find.descendant(
        of: find.byKey(const Key('field:content')),
        matching: find.byType(TextField),
      ),
      'Ngài thích trà',
    );
    await t.tap(find.text('Lưu thay đổi'));
    await t.pumpAndSettle(const Duration(seconds: 2));
    expect(body, {
      'kind': 'learning',
      'id': 42,
      'values': {
        'type': 'preference',
        'semantic_key': 'coffee_preference',
        'content': 'Ngài thích trà',
        'source': 'chat',
        'importance': 7,
        'embedding': '[0.1, 0.2]',
      },
    });
    // after a good save the list is read again
    expect(_to(calls, 'GET', '/api/learnings/list'), hasLength(2));
  });

  testWidgets('a failed save shows the backend code and keeps the editor', (
    t,
  ) async {
    await _pump(
      t,
      extra: {
        'POST /api/memory-control/update': (_) =>
            jsonOk({'success': false, 'code': 'not_found'}, 404),
      },
    );
    await _openRecord(t, 42);
    await t.tap(find.text('Lưu thay đổi'));
    await t.pumpAndSettle(const Duration(seconds: 2));
    expect(find.text('not_found'), findsOneWidget); // alert(message)
    expect(find.text('Bản ghi #42'), findsOneWidget);
  });

  testWidgets('delete asks the dependencies, then confirms, then deletes', (
    t,
  ) async {
    final order = <String>[];
    Map<String, dynamic>? body;
    await _pump(
      t,
      extra: {
        'GET /api/memory-control/dependencies': (r) {
          order.add('dependencies ${r.url.query}');
          return jsonOk({
            'success': true,
            'preview': {'related_workflows': 0, 'related_outcomes': 1},
          });
        },
        'POST /api/memory-control/delete': (r) {
          order.add('delete');
          body = jsonDecode(r.body) as Map<String, dynamic>;
          return jsonOk({'success': true});
        },
      },
    );
    await _openRecord(t, 42);
    await _tapAction(t, 'Xóa');
    expect(order, ['dependencies kind=learning&id=42']);
    expect(
      find.textContaining('Xác nhận xóa sau khi kiểm tra quan hệ:'),
      findsOneWidget,
    );
    expect(find.textContaining('"related_outcomes": 1'), findsOneWidget);
    await t.tap(find.byKey(const Key('confirm-ok')));
    await t.pumpAndSettle(const Duration(seconds: 2));
    expect(order.last, 'delete');
    expect(body, {'kind': 'learning', 'id': 42});
  });

  testWidgets('cancelling the confirm deletes nothing', (t) async {
    var deleted = false;
    await _pump(
      t,
      extra: {
        'GET /api/memory-control/dependencies': (_) =>
            jsonOk({'success': true, 'preview': {}}),
        'POST /api/memory-control/delete': (_) {
          deleted = true;
          return jsonOk({'success': true});
        },
      },
    );
    await _openRecord(t, 42);
    await _tapAction(t, 'Xóa');
    await t.tap(find.text('Hủy'));
    await t.pumpAndSettle(const Duration(seconds: 2));
    expect(deleted, isFalse);
  });

  testWidgets('a dependency preview that fails stops before any delete', (
    t,
  ) async {
    var deleted = false;
    await _pump(
      t,
      extra: {
        'GET /api/memory-control/dependencies': (_) =>
            jsonOk({'success': false, 'code': 'not_found'}, 404),
        'POST /api/memory-control/delete': (_) {
          deleted = true;
          return jsonOk({'success': true});
        },
      },
    );
    await _openRecord(t, 42);
    await t.tap(find.text('Xóa'));
    await t.pumpAndSettle(const Duration(seconds: 2));
    expect(deleted, isFalse);
    expect(find.text('not_found'), findsOneWidget);
  });

  testWidgets(
    're-embed one posts its id; re-embed all confirms and posts null',
    (t) async {
      final bodies = <Map<String, dynamic>>[];
      await _pump(
        t,
        extra: {
          'POST /api/learnings/reembed': (r) {
            bodies.add(jsonDecode(r.body) as Map<String, dynamic>);
            return jsonOk({'success': true, 'updated': 1});
          },
        },
      );
      await _tapAction(t, 'Tính lại tất cả embedding');
      expect(
        find.text(
          'Tính lại embedding cho TOÀN BỘ bản ghi học? Đây có thể mất vài phút.',
        ),
        findsOneWidget,
      );
      await t.tap(find.byKey(const Key('confirm-ok')));
      await t.pumpAndSettle(const Duration(seconds: 2));
      expect(bodies, [
        {'id': null},
      ]);
      await _openRecord(t, 43);
      await t.tap(find.text('Tính lại embedding'));
      await t.pumpAndSettle(const Duration(seconds: 2));
      expect(bodies.last, {'id': 43});
    },
  );

  testWidgets('a re-embed failure shows the web message', (t) async {
    await _pump(
      t,
      extra: {
        'POST /api/learnings/reembed': (_) =>
            jsonOk({'success': false, 'error': 'embedder_off'}),
      },
    );
    await _openRecord(t, 43);
    await t.tap(find.text('Tính lại embedding'));
    await t.pumpAndSettle(const Duration(seconds: 2));
    expect(
      find.text('Không thể tính lại embedding: embedder_off'),
      findsOneWidget,
    );
  });

  testWidgets(
    'evolution saves through /api/evolution/update and cannot be deleted',
    (t) async {
      Map<String, dynamic>? body;
      await _pump(
        t,
        extra: {
          'POST /api/evolution/update': (r) {
            body = jsonDecode(r.body) as Map<String, dynamic>;
            return jsonOk({'success': true});
          },
        },
      );
      await _cat(t, 'evolution');
      await t.tap(find.byKey(const Key('rec:style')));
      await t.pumpAndSettle();
      expect(find.text('STYLE.md'), findsNWidgets(2)); // the head shows the file name (and the system info the title), not "Bản ghi #"
      expect(find.text('Xóa'), findsNothing);
      expect(find.text('Tính lại embedding'), findsNothing);
      await t.enterText(
        find.descendant(
          of: find.byKey(const Key('field:content')),
          matching: find.byType(TextField),
        ),
        'Xưng hô: Ngài.',
      );
      await t.tap(find.text('Lưu thay đổi'));
      await t.pumpAndSettle(const Duration(seconds: 2));
      expect(body, {'id': 'style', 'content': 'Xưng hô: Ngài.'});
    },
  );

  testWidgets('gym: delete uses DELETE /api/gym/delete; no save button', (
    t,
  ) async {
    final calls = await _pump(
      t,
      extra: {
        'DELETE /api/gym/delete': (_) => jsonOk({'success': true}),
      },
    );
    await _cat(t, 'gym');
    await t.tap(find.byKey(const Key('rec:profile_1')));
    await t.pumpAndSettle();
    expect(find.text('Lưu thay đổi'), findsNothing);
    await _tapAction(t, 'Xóa');
    expect(
      find.text('Xóa bản ghi tập luyện: Hồ sơ Gym: Erik?'),
      findsOneWidget,
    );
    await t.tap(find.byKey(const Key('confirm-ok')));
    await t.pumpAndSettle(const Duration(seconds: 2));
    final del = _to(calls, 'DELETE', '/api/gym/delete').single;
    expect(del.url.queryParameters, {'id': 'profile_1'});
    expect(_to(calls, 'GET', '/api/memory-control/dependencies'), isEmpty);
  });

  testWidgets(
    'user: save uses POST /api/users/update; delete uses DELETE /api/users/delete; admin cannot be deleted',
    (t) async {
      final calls = await _pump(
        t,
        extra: {
          'POST /api/users/update': (_) => jsonOk({'success': true}),
          'DELETE /api/users/delete': (_) => jsonOk({'success': true}),
        },
      );
      await _cat(t, 'user');
      // Admin has save button but no delete button
      await t.tap(find.byKey(const Key('rec:admin')));
      await t.pumpAndSettle();
      expect(find.text('Lưu thay đổi'), findsOneWidget);
      expect(find.text('Xóa'), findsNothing);
      await t.tap(find.text('← Danh sách'));
      await t.pumpAndSettle();

      // Member user has both save and delete buttons
      await t.tap(find.byKey(const Key('rec:user-user2_223dd6')));
      await t.pumpAndSettle();
      expect(find.text('Lưu thay đổi'), findsOneWidget);
      expect(find.text('Xóa'), findsOneWidget);
      await _tapAction(t, 'Xóa');
      expect(
        find.textContaining('Xóa người dùng:'),
        findsOneWidget,
      );
      await t.tap(find.byKey(const Key('confirm-ok')));
      await t.pumpAndSettle(const Duration(seconds: 2));
      final del = _to(calls, 'DELETE', '/api/users/delete').single;
      expect(del.url.queryParameters, {'id': 'user-user2_223dd6'});
    },
  );

  testWidgets(
    'user bulk delete: uses DELETE /api/users/delete; ignores admin in select-all',
    (t) async {
      final userCalls = <http.Request>[];
      await _pump(
        t,
        extra: {
          'DELETE /api/users/delete': (r) {
            userCalls.add(r);
            return jsonOk({'success': true});
          },
        },
      );
      await _cat(t, 'user');
      // Admin should have NO checkbox, only member user has checkbox
      expect(find.byKey(const Key('sel:admin')), findsNothing);
      expect(find.byKey(const Key('sel:user-user2_223dd6')), findsOneWidget);

      await t.tap(find.byKey(const Key('select-all')));
      await t.pumpAndSettle();
      expect(find.text('Xoá đã chọn (1)'), findsOneWidget);
      await _tapAction(t, 'Xoá đã chọn (1)');
      expect(find.textContaining('Xoá 1 bản ghi Người dùng?'), findsOneWidget);
      await t.tap(find.byKey(const Key('confirm-ok')));
      await t.pump();
      await t.pump(const Duration(milliseconds: 400));
      expect(userCalls.length, 1);
      expect(userCalls.single.url.queryParameters['id'], 'user-user2_223dd6');
      await t.pumpAndSettle(const Duration(seconds: 2));
    },
  );

  testWidgets(
    'bulk delete: one confirm, one delete per record, failures listed',
    (t) async {
      final ids = <dynamic>[];
      await _pump(
        t,
        extra: {
          'POST /api/memory-control/delete': (r) {
            final b = jsonDecode(r.body) as Map<String, dynamic>;
            ids.add(b['id']);
            return b['id'] == 43
                ? jsonOk({'success': false, 'code': 'locked_row'})
                : jsonOk({'success': true});
          },
        },
      );
      await t.tap(find.byKey(const Key('select-all')));
      await t.pumpAndSettle();
      expect(find.text('Xoá đã chọn (2)'), findsOneWidget);
      await _tapAction(t, 'Xoá đã chọn (2)');
      expect(find.textContaining('Xoá 2 bản ghi Learnings?'), findsOneWidget);
      expect(find.textContaining('• coffee_preference'), findsOneWidget);
      await t.tap(find.byKey(const Key('confirm-ok')));
      await t.pump();
      await t.pump(const Duration(milliseconds: 400));
      expect(ids, [42, 43]);
      expect(
        find.textContaining('Đã xoá 1/2. Lỗi:\n#43 wake_time: locked_row'),
        findsOneWidget,
      );
      await t.pumpAndSettle(
        const Duration(seconds: 2),
      ); // let the feedback and the snackbar go
    },
  );

  testWidgets('a slow tab does not overwrite the tab opened after it', (
    t,
  ) async {
    final slow = Completer<http.Response>();
    final routes = _base();
    await pumpPage(
      t,
      const MemoryPage(),
      MockClient((req) {
        if (req.url.path == '/api/learnings/list') return slow.future;
        return Future.value(routes['${req.method} ${req.url.path}']!(req));
      }),
    );
    await t.pump();
    await t.pump(const Duration(milliseconds: 50));
    for (var i = 0; i < 20; i++) {
      await t.pump(const Duration(milliseconds: 100));
    }
    await _cat(t, 'workflow');
    expect(find.byKey(const Key('rec:7')), findsOneWidget);
    slow.complete(jsonOk(learningsJson()));
    await t.pumpAndSettle();
    expect(find.byKey(const Key('rec:7')), findsOneWidget);
    expect(find.byKey(const Key('rec:42')), findsNothing);
  });
}
