// Fake backend data shaped like the real responses (engine/UIUX/ui_engine.py api_settings_status, health_detailed,
// api_get_preferences, api_tts_voices ...), shared by the Settings page tests and the screenshot test.
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:jarvis_mobile/net/api_client.dart';
import 'package:jarvis_mobile/net/server_config.dart';
import 'package:jarvis_mobile/theme/app_theme.dart';
import 'package:provider/provider.dart';

const jsonHeaders = {'content-type': 'application/json; charset=utf-8'};

http.Response jsonOk(Object body, [int status = 200]) =>
    http.Response(jsonEncode(body), status, headers: jsonHeaders);

Map<String, dynamic> statusJson() => {
  'intelligence_core_ok': true,
  'server_engine_ok': true,
  'llm_server_ok': true,
  'tts_server_ok': true,
  'session_active': false,
  'memory_count': 1234,
  'messages_count': 480,
  'conversation_turn_count': 240,
  'task_count': 3,
  'server_port': 8340,
  'uptime_seconds': 3665,
  'skill_count': 12,
  'command_count': 40,
  'hooks_loaded': 4,
  'env_keys_set': {
    'llama': true,
    'fish_audio': true,
    'fish_voice_id': true,
    'user_name': 'Erik',
  },
  'open_apps': ['Code', 'Chrome', 'Spotify'],
  'mcp_total': 3,
  'mcp_connected': 2,
  'mcp_servers': {'fs': 'connected', 'git': 'connected', 'web': 'error'},
  'plugins_loaded': 1,
  'system': {
    'ram_percent': 47.0,
    'ram_used_gb': 7.5,
    'ram_total_gb': 16.0,
    'cpu_percent': 12.5,
    'gpus': [
      {
        'name': 'NVIDIA GeForce RTX 4070',
        'vram_total_mb': 12288.0,
        'mem_used_mb': 4700,
        'mem_total_mb': 12288,
        'util_percent': 31,
        'temp_c': 54,
      },
    ],
    'npus': ['Intel(R) AI Boost'],
  },
  'mentions_count': 15,
  'runtime': {
    'llm_model': 'Qwen3-8B',
    'embed_model': 'embeddinggemma-300m',
    'tts_engine': 'vieneu',
    'vieneu_voice': 'Ngoc Huyen',
    'edge_voice': 'vi-VN-HoaiMyNeural',
  },
  'session_tokens': {'input': 12000, 'output': 3400, 'total': 15400},
};

Map<String, dynamic> healthJson({
  bool llm = true,
  bool rag = true,
  bool db = true,
}) => {
  'status': 'online',
  'llm': {
    'status': llm ? 'online' : 'chờ kết nối',
    'port': 8080,
    'message': '',
    'url': 'http://127.0.0.1:8080/v1',
    'response_time_ms': 42.5,
  },
  'embed': {'status': 'online', 'port': 8081, 'message': '', 'url': ''},
  'stream_tts': {'status': 'online', 'port': 8082, 'message': '', 'url': ''},
  'rag': {'enabled': rag, 'total_chunks': 320, 'files_count': 5},
  'database': {'ok': db, 'size_kb': 2048.5},
  'timestamp': 1760000000.0,
};

Map<String, dynamic> voicesJson() => {
  'engine': 'vieneu',
  'default': 'Ngoc Huyen',
  'current': 'Ngoc Huyen',
  'voices': [
    {
      'name': 'Ngoc Huyen',
      'label': 'Ngọc Huyền (nữ miền Bắc)',
      'kind': 'preset',
    },
    {'name': 'Binh', 'label': 'Bình (nam miền Bắc)', 'kind': 'preset'},
    {'name': 'Giong cua toi', 'label': 'Giong cua toi', 'kind': 'clone'},
  ],
};

/// A MockClient that answers by `METHOD /path`; unknown routes are 404 like FastAPI. [calls] collects every request.
MockClient routed(
  Map<String, http.Response Function(http.Request)> routes, {
  List<http.Request>? calls,
}) => MockClient((req) async {
  calls?.add(req);
  final h = routes['${req.method} ${req.url.path}'];
  return h == null
      ? http.Response(
          jsonEncode({'detail': 'Not Found'}),
          404,
          headers: jsonHeaders,
        )
      : h(req);
});

/// Mounts one settings page on a phone-sized surface with the providers the app gives it.
Future<ApiClient> pumpPage(
  WidgetTester t,
  Widget page,
  http.Client client, {
  Size size = const Size(390, 760),
}) async {
  t.view
    ..physicalSize = size * 3
    ..devicePixelRatio = 3;
  addTearDown(t.view.reset);
  final cfg = ServerConfig();
  final api = ApiClient(cfg, client: client);
  await t.pumpWidget(
    MultiProvider(
      providers: [
        ChangeNotifierProvider.value(value: cfg),
        Provider<ApiClient>.value(value: api),
      ],
      child: MaterialApp(
        theme: buildAppTheme(),
        home: Scaffold(backgroundColor: Colors.black, body: page),
      ),
    ),
  );
  await t.pump(const Duration(milliseconds: 50));
  return api;
}

// Bộ nhớ / Nhật ký: answers shaped like ui_engine.py (api_memory_control_summary, api_learnings_list, api_workflows_list,
// api_evolution_list, api_gym_list, api_history, _tail_log, api_conversations_sessions / _session).
Map<String, dynamic> memorySummaryJson() => {
  'success': true,
  'counts': {
    'learnings': 2,
    'workflows': 1,
    'outcomes': 3,
    'corrections': 4,
    'conversations': 120,
    'gym': 5,
    'user': 8,
  },
};

Map<String, dynamic> learningsJson({int total = 2}) {
  final items = [
    {
      'id': 42,
      'type': 'preference',
      'semantic_key': 'coffee_preference',
      'content': 'Ngài thích cà phê đen không đường',
      'source': 'chat',
      'importance': 7,
      'created_at': 1760000000,
      'embedding': '[0.1, 0.2]',
      'embedding_model': 'embeddinggemma-300m',
      'embedding_dim': 2,
    },
    {
      'id': 43,
      'type': 'fact',
      'semantic_key': 'wake_time',
      'content': 'Dậy lúc 6 giờ sáng',
      'source': 'chat',
      'importance': 5,
      'created_at': 1760100000,
      'embedding': '',
      'embedding_model': '',
      'embedding_dim': 0,
    },
  ];
  return {'success': true, 'learnings': items, 'items': items, 'total': total};
}

Map<String, dynamic> workflowsJson() {
  final items = [
    {
      'id': 7,
      'tools': 'web_search,read_page',
      'intent': 'tra cứu giá vàng',
      'tool_chain': '["web_search","read_page"]',
      'sample_queries': '["giá vàng hôm nay"]',
      'success_evidence': 'Đã trả lời đúng giá',
      'validation_count': 3,
      'wiki_path': 'wiki/workflows/7.md',
      'created_at': 1760000000,
      'updated_at': 1760200000,
    },
  ];
  return {'success': true, 'workflows': items, 'items': items, 'total': 1};
}

Map<String, dynamic> correctionsJson() {
  final items = [
    {
      'id': 3,
      'query': 'mở nhạc',
      'wrong_tool': 'web_search',
      'right_tool': 'play_music',
      'count': 2,
      'created_at': 1760000000,
    },
  ];
  return {'success': true, 'corrections': items, 'items': items, 'total': 1};
}

Map<String, dynamic> evolutionJson() => {
  'success': true,
  'items': [
    {
      'id': 'style',
      'title': 'STYLE.md',
      'path': 'prompt/STYLE.md',
      'exists': true,
      'editable': true,
      'content': 'Xưng hô ngắn gọn.',
      'updated_at': 1760000000,
    },
    {
      'id': 'evolution',
      'title': 'Evolution.md',
      'path': 'prompt/Evolution.md',
      'exists': false,
      'editable': true,
      'content': '',
      'updated_at': null,
    },
  ],
  'total': 2,
};

Map<String, dynamic> gymJson() => {
  'success': true,
  'items': [
    {
      'id': 'profile_1',
      'type': 'profile',
      'record_type': 'profile',
      'profile_id': 1,
      'profile_name': 'Erik',
      'title': 'Hồ sơ Gym: Erik',
      'content': 'Hồ sơ tập luyện của Erik.',
      'date': '2026-10-01',
      'created_at': '2026-10-01T08:00:00',
    },
  ],
  'total': 1,
};

Map<String, dynamic> historyJson() {
  final now = DateTime.now().millisecondsSinceEpoch ~/ 1000;
  return {
    'success': true,
    'history': [
      {
        'id': 1,
        'role': 'user',
        'content': 'Chào Jarvis',
        'created_at': now - 60,
        'session_id': 'web-ab12cd34',
      },
      {
        'id': 2,
        'role': 'assistant',
        'content': 'Chào **Ngài**, tôi nghe đây.',
        'created_at': now - 30,
        'session_id': 'web-ab12cd34',
      },
    ],
  };
}

Map<String, dynamic> sessionsJson() {
  final now = DateTime.now().millisecondsSinceEpoch ~/ 1000;
  return {
    'success': true,
    'sessions': [
      {
        'session_id': 'web-ab12cd34',
        'msg_count': 12,
        'started_at': now - 3600,
        'last_msg': now - 60,
        'device': 'ios',
        'source': 'web',
      },
      {
        'session_id': 'tg-99',
        'msg_count': 3,
        'started_at': now - 90000,
        'last_msg': now - 86400,
        'device': null,
        'source': 'telegram',
      },
      {
        'session_id': 'legacy',
        'msg_count': 40,
        'started_at': 1700000000,
        'last_msg': 1700001000,
        'device': '',
        'source': 'legacy',
      },
    ],
  };
}

Map<String, dynamic> logsJson() => {
  'success': true,
  'logs': '2026-10-19 10:00:00 INFO server started\n2026-10-19 10:00:01 WARNING slow reply\n2026-10-19 10:00:02 ERROR llm down\nplain line',
};

Map<String, dynamic> usersJson() => {
  'success': true,
  'items': [
    {
      'id': 'admin',
      'username': 'admin',
      'display_name': 'Admin',
      'role': 'admin',
      'user_pronoun': '',
      'ai_pronoun': '',
      'title': '[ADMIN] Admin (@admin)',
      'created_at': 1710000000,
    },
    {
      'id': 'user-user2_223dd6',
      'username': 'user2_223dd6',
      'display_name': 'user2_223dd6',
      'role': 'member',
      'user_pronoun': '',
      'ai_pronoun': '',
      'title': '[MEMBER] user2_223dd6 (@user2_223dd6)',
      'created_at': 1710000100,
    },
  ],
  'total': 2,
};
