---
name: mcp_call
description: Gọi một tool trên MCP server bất kỳ (gitnexus, headroom, agentmemory, browser, semble) để tra cứu thông tin code, nén context, ghi nhớ, hoặc điều khiển trình duyệt.
usage: |
  Gọi qua execute_command với command_name="mcp_call" và args là JSON chứa:
  {
    "server": "tên_server_mcp",
    "tool": "tên_tool",
    "arguments": { ... các tham số của tool ... }
  }

  Ví dụ tra cứu code:
  args={"server": "gitnexus", "tool": "gitnexus_query", "arguments": {"query": "cách xử lý authentication"}}

  Ví dụ nén context:
  args={"server": "headroom", "tool": "headroom_compress", "arguments": {"content": "nội dung cần nén..."}}

  Ví dụ ghi nhớ (cách khác ngoài remember command):
  args={"server": "agentmemory", "tool": "memory_save", "arguments": {"content": "nội dung", "type": "fact", "concepts": "tag1,tag2"}}

  Các MCP server có sẵn: gitnexus (code graph), headroom (nén context), agentmemory (bộ nhớ), browser (trình duyệt), semble.
available_servers:
  - gitnexus: gitnexus_query, gitnexus_context, gitnexus_impact, gitnexus_route_map, gitnexus_detect_changes
  - headroom: headroom_compress, headroom_retrieve, headroom_stats
  - agentmemory: memory_save, memory_recall, memory_smart_search
---
