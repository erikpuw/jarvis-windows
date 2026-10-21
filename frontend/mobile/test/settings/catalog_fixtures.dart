// Công cụ pages: answers shaped like ui_engine.py (api_settings_catalog / _scan_mentions / _scan_catalog_files,
// api_get_mcp_servers / _mcp_server_views, api_get_readme), shared by the page tests and the screenshot test.

Map<String, dynamic> catalogJson() => {
  'success': true,
  'mentions': [
    {
      'id': 'rag',
      'name': 'rag',
      'file': 'engine/rag',
      'description': 'Hỏi kho tài liệu đã nạp',
      'example': '@rag <câu hỏi>',
      'mention': '@rag',
    },
    {
      'id': 'weather',
      'name': 'weather',
      'file': 'weather.py',
      'description': 'Xem dự báo thời tiết',
      'example': '@weather <city>',
      'mention': '@weather',
    },
  ],
  'hooks': [
    {
      'name': 'logger',
      'file': 'logger.py',
      'description': 'Ghi log mọi tin nhắn',
      'events': ['on_startup', 'on_message_receive'],
      'runtime': 'python',
      'active': true,
      'file_path': 'hooks/logger.py',
    },
  ],
  'skills': [
    {
      'name': 'git-helper',
      'folder': 'git-helper',
      'description': 'Trợ lý thao tác git',
      'category': 'dev',
      'tags': ['git', 'commit'],
      'file_path': 'skills/git-helper/SKILL.md',
    },
    {
      'name': 'cooking',
      'folder': 'cooking',
      'description': 'Công thức nấu ăn',
      'category': 'general',
      'tags': <String>[],
      'file_path': 'skills/cooking/SKILL.md',
    },
  ],
  'prompts': [
    {
      'id': 'general_chat',
      'name': 'general_chat.md',
      'title': 'General Chat',
      'description': 'Prompt trò chuyện chung',
      'size_bytes': 120,
      'lines_count': 7,
      'file_path': 'prompt/general_chat.md',
      'content': '# General Chat\nBạn là JARVIS.',
    },
  ],
  'commands': [
    {
      'name': 'help',
      'file': 'slash_commands.py',
      'description': 'Liệt kê mọi lệnh / đang dùng được.',
      'usage': '/help',
      'category': 'tool',
      'tags': <String>[],
      'file_path': 'engine/server/slash_commands.py',
      'example': '/help',
    },
    {
      'name': 'note',
      'file': 'note.py',
      'description': 'Ghi chú nhanh',
      'usage': '/note <content>',
      'category': 'tool',
      'tags': ['write'],
      'file_path': 'engine/tools/catalog/note.py',
      'example': '/note <content>',
    },
  ],
  'plugins': [
    {
      'name': 'spotify',
      'file': 'spotify.py',
      'description': 'Điều khiển Spotify',
      'runtime': 'python',
      'active': true,
      'file_path': 'plugins/spotify.py',
    },
  ],
};

Map<String, dynamic> mcpServersJson() => {
  'success': true,
  'total': 3,
  'connected': 1,
  'servers': [
    {
      'name': 'filesystem',
      'type': 'stdio',
      'enabled': true,
      'status': 'connected',
      'command': 'npx',
      'args': ['-y', '@modelcontextprotocol/server-filesystem', '/data'],
    },
    {
      'name': 'search',
      'type': 'stdio',
      'enabled': false,
      'status': 'disabled',
      'command': 'uvx',
      'args': ['--api-key', '••••'],
    },
    {
      'name': 'remote',
      'type': 'http',
      'enabled': true,
      'status': 'connecting',
      'command': '',
    },
  ],
};

Map<String, dynamic> readmeJson() => {
  'success': true,
  'content': '# JARVIS\n\nTrợ lý **AI** chạy cục bộ.\n\n- Chat\n- Giọng nói',
};

// Bản đồ mã: answer shaped like ui_engine.py api_graphfy -> engine/UIUX/graphfy.py scan (nodes {id,label,lane}, edges {from,to,kind}).
Map<String, dynamic> graphfyJson() {
  Map<String, String> n(String id, String lane) => {
    'id': id,
    'label': id.split('/').last,
    'lane': lane,
  };
  return {
    'success': true,
    'nodes': [
      n('server', 'input'),
      n('security', 'input'),
      n('UIUX', 'input'),
      n('server/ws_dispatcher', 'input'),
      n('tools', 'turn'),
      n('prompts', 'turn'),
      n('main', 'turn'),
      n('server/llm_server', 'llm'),
      n('server/tts_manager', 'output'),
      n('server/voice_streamer', 'output'),
      n('core/memory', 'memory'),
      n('core/learning', 'memory'),
      n('core/rag_engine', 'ingestion'),
      n('chunking', 'ingestion'),
      n('core/dream', 'background'),
      n('core/json_parser', 'support'),
      n('core/new_thing', 'other'),
    ],
    'edges': [
      {'from': 'main', 'to': 'server/llm_server', 'kind': 'llm'},
      {'from': 'core/learning', 'to': 'server/llm_server', 'kind': 'llm'},
      {'from': 'core/dream', 'to': 'server/llm_server', 'kind': 'llm'},
      {'from': 'server/ws_dispatcher', 'to': 'main', 'kind': 'import'},
      {'from': 'main', 'to': 'server/tts_manager', 'kind': 'import'},
      {
        'from': 'server/tts_manager',
        'to': 'server/voice_streamer',
        'kind': 'import',
      },
      {'from': 'main', 'to': 'core/memory', 'kind': 'import'},
      {'from': 'core/memory', 'to': 'core/json_parser', 'kind': 'import'},
      {'from': 'core/rag_engine', 'to': 'chunking', 'kind': 'import'},
      {'from': 'server', 'to': 'main', 'kind': 'import'},
      {'from': 'tools', 'to': 'core/memory', 'kind': 'import'},
      {'from': 'UIUX', 'to': 'core/memory', 'kind': 'import'},
    ],
  };
}
