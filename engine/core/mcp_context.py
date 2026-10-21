"""
MCP Context — chủ động quét và gọi các MCP tools phù hợp, tự động inject kết quả vào context.

Quét động tất cả tools khả dụng từ MCP Hub, loại bỏ khai báo thủ công.
"""

import asyncio
import json
import logging
import re
from typing import Optional, Any

log = logging.getLogger("jarvis.mcp_context")

_MAX_MCP_CALLS = 2
_MAX_TOKENS = 1200  # budget cho MCP context


def _estimate_tokens(text: str) -> int:
    return len(text) // 4 + 1


def _remove_diacritics(text: str) -> str:
    replacements = {
        'à': 'a', 'á': 'a', 'ạ': 'a', 'ả': 'a', 'ã': 'a',
        'â': 'a', 'ầ': 'a', 'ấ': 'a', 'ậ': 'a', 'ẩ': 'a', 'ẫ': 'a',
        'ă': 'a', 'ằ': 'a', 'ắ': 'a', 'ặ': 'a', 'ẳ': 'a', 'ẵ': 'a',
        'è': 'e', 'é': 'e', 'ẹ': 'e', 'ẻ': 'e', 'ẽ': 'e',
        'ê': 'e', 'ề': 'e', 'ế': 'e', 'ệ': 'e', 'ể': 'e', 'ễ': 'e',
        'ì': 'i', 'í': 'i', 'ị': 'i', 'ỉ': 'i', 'ĩ': 'i',
        'ò': 'o', 'ó': 'o', 'ọ': 'o', 'ỏ': 'o', 'õ': 'o',
        'ô': 'o', 'ồ': 'o', 'ố': 'o', 'ộ': 'o', 'ổ': 'o', 'ỗ': 'o',
        'ơ': 'o', 'ờ': 'o', 'ớ': 'o', 'ợ': 'o', 'ở': 'o', 'ỡ': 'o',
        'ù': 'u', 'ú': 'u', 'ụ': 'u', 'ủ': 'u', 'ũ': 'u',
        'ư': 'u', 'ừ': 'u', 'ứ': 'u', 'ự': 'u', 'ử': 'u', 'ữ': 'u',
        'ỳ': 'y', 'ý': 'y', 'ỵ': 'y', 'ỷ': 'y', 'ỹ': 'y',
        'đ': 'd',
        'À': 'A', 'Á': 'A', 'Ạ': 'A', 'Ả': 'A', 'Ã': 'A',
        'Â': 'A', 'Ầ': 'A', 'Ấ': 'A', 'Ậ': 'A', 'Ẩ': 'A', 'Ẫ': 'A',
        'Ă': 'A', 'Ằ': 'A', 'Ắ': 'A', 'Ặ': 'A', 'Ẳ': 'A', 'Ẵ': 'A',
        'È': 'E', 'É': 'E', 'Ẹ': 'E', 'Ẻ': 'E', 'Ẽ': 'E',
        'Ê': 'E', 'Ề': 'E', 'Ế': 'E', 'Ệ': 'E', 'Ể': 'E', 'Ễ': 'E',
        'Ì': 'I', 'Í': 'I', 'Ị': 'I', 'Ỉ': 'I', 'Ĩ': 'I',
        'Ò': 'O', 'Ó': 'O', 'Ọ': 'O', 'Ỏ': 'O', 'Õ': 'O',
        'Ô': 'O', 'Ồ': 'O', 'Ố': 'O', 'Ộ': 'O', 'Ổ': 'O', 'Ỗ': 'O',
        'Ơ': 'O', 'Ờ': 'O', 'Ớ': 'O', 'Ợ': 'O', 'Ở': 'O', 'Ỡ': 'O',
        'Ù': 'U', 'Ú': 'U', 'Ụ': 'U', 'Ủ': 'U', 'Ũ': 'U',
        'Ư': 'U', 'Ừ': 'U', 'Ứ': 'U', 'Ự': 'U', 'Ử': 'U', 'Ữ': 'U',
        'Ỳ': 'Y', 'Ý': 'Y', 'Ỵ': 'Y', 'Ỷ': 'Y', 'Ỹ': 'Y',
        'Đ': 'D',
    }
    for vn_char, en_char in replacements.items():
        text = text.replace(vn_char, en_char)
    return text


def _query_matches_tool(query: str, tool_name: str, description: str) -> bool:
    """Kiểm tra xem yêu cầu của người dùng có khớp ngữ nghĩa với tool/mô tả không."""
    q_lower = query.lower()
    q_nodia = _remove_diacritics(q_lower)
    
    # 1. So khớp trực tiếp tên tool
    t_clean = tool_name.lower().replace("_", " ").replace("-", " ")
    if t_clean in q_lower or t_clean in q_nodia:
        return True
        
    # 2. Tách từ khóa từ tên tool và mô tả để tìm kiếm thông minh
    keywords = set(re.findall(r'[a-zA-Z0-9_đđà-ỹ]+', t_clean + " " + description.lower()))
    
    # Lọc bỏ các từ dừng (stop words) cực ngắn để tránh false positive
    stop_words = {"mcp", "tool", "a", "an", "the", "to", "for", "in", "of", "and", "or", "with", "của", "và", "để", "cho"}
    keywords = {kw for kw in keywords if len(kw) >= 3 and kw not in stop_words}
    
    hits = 0
    for kw in keywords:
        kw_nodia = _remove_diacritics(kw)
        # So khớp nguyên từ
        if re.search(r'(?<![a-z0-9])' + re.escape(kw) + r'(?![a-z0-9])', q_lower) or \
           re.search(r'(?<![a-z0-9])' + re.escape(kw_nodia) + r'(?![a-z0-9])', q_nodia):
            hits += 1
            if hits >= 2:  # Cần khớp từ 2 từ khóa trở lên để kích hoạt (hoặc 1 nếu mô tả rất ngắn)
                return True
                
    return hits >= 1 if len(keywords) <= 3 else False


def _is_chitchat_query(query: str) -> bool:
    """Loại bỏ các câu chào hỏi/cảm ơn xã giao cực ngắn trước khi gọi Wikipedia."""
    q_lower = query.lower().strip()
    words = q_lower.split()
    if len(words) <= 2:
        return True
    chitchat_kw = ["chào", "hello", "hi ", "cảm ơn", "thank", "tạm biệt", "bye", "ok", "ừ", "yes", "no"]
    if any(kw in q_lower for kw in chitchat_kw):
        return True
    return False


_WIKI_CALL_TIMEOUT = 6.0
_WIKI_SEARCH_LIMIT = 3
_WIKI_SUMMARIES = 2
_WIKI_MAX_TERMS = 6
# Question scaffolding stripped before searching; longest phrases go first.
_WIKI_FILLER_PHRASES = (
    "cho tôi biết", "cho mình biết", "cho em biết", "cho tôi hỏi", "cho mình hỏi",
    "bạn có biết", "bạn biết", "hãy kể", "kể cho tôi", "kể về", "giới thiệu về",
    "tìm hiểu về", "tìm hiểu", "tra cứu", "thông tin về",
    "là gì", "là ai", "như thế nào", "ra sao", "thế nào", "tại sao", "vì sao",
    "những thay đổi", "các thay đổi", "thay đổi", "sự kiện", "diễn ra",
    "có những", "có các", "những gì", "điều gì", "cái gì", "khi nào", "ở đâu",
    "bao nhiêu", "được không",
)
_WIKI_FILLER_WORDS = {
    "gì", "nào", "không", "hả", "ạ", "nhỉ", "vậy", "thế", "nhé", "hãy", "giúp",
    "xin", "hỏi", "về", "của", "những", "các", "có", "thì", "là", "và", "với",
    "jarvis", "ơi", "mình", "tôi", "bạn", "em", "anh", "chị",
}
_HTML_TAG = re.compile(r"<[^>]+>")


def _wiki_search_query(query: str) -> str:
    """Turn a spoken question into Wikipedia search terms.

    MediaWiki search requires every term to match, so sending the whole
    sentence ("lịch sử việt nam năm 1945 có những thay đổi nào") found nothing
    even for well-covered topics.
    """
    text = re.sub(r"[?!.,;:\"'“”‘’()\[\]]", " ", query.lower())
    for phrase in sorted(_WIKI_FILLER_PHRASES, key=len, reverse=True):
        text = re.sub(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", " ", text)
    words = [w for w in text.split() if w not in _WIKI_FILLER_WORDS]
    return " ".join(words[:_WIKI_MAX_TERMS])


def _result_payload(result) -> Any:
    structured = getattr(result, "structuredContent", None)
    if isinstance(structured, dict):
        return structured
    parts = [
        item.text for item in (getattr(result, "content", None) or [])
        if getattr(item, "text", None)
    ]
    try:
        return json.loads("\n".join(parts))
    except (TypeError, ValueError):
        return None


async def _call_wiki_tool(hub, srv_name: str, tool_name: str, args: dict) -> Any:
    try:
        result = await asyncio.wait_for(
            hub.call_tool(srv_name, tool_name, args), timeout=_WIKI_CALL_TIMEOUT
        )
    except Exception as e:
        log.warning("[MCP Wikipedia] %s failed: %s", tool_name, e)
        return None
    return _result_payload(result) if result is not None else None


async def _build_wikipedia_context(hub, srv_name: str, query: str, budget: int) -> str:
    """Search by keywords, then fetch the top articles' summaries in parallel.

    The generic path used to call "the first two tools" of the server with the
    raw sentence, which on wikipedia-mcp meant search_wikipedia (no match for a
    whole sentence) and test_wikipedia_connectivity — two sequential ~3.5s
    calls that could never produce an article.
    """
    base = _wiki_search_query(query)
    attempts = [q for q in dict.fromkeys((base, " ".join(base.split()[:3]))) if q]
    hits: list = []
    used_query = ""
    for attempt in attempts:
        data = await _call_wiki_tool(
            hub, srv_name, "search_wikipedia", {"query": attempt, "limit": _WIKI_SEARCH_LIMIT}
        )
        hits = (data.get("results") if isinstance(data, dict) else None) or []
        if hits:
            used_query = attempt
            break
    if not hits:
        log.info("[MCP Wikipedia] No results for %r (from %r)", base, query)
        return ""

    top = [h for h in hits if isinstance(h, dict) and h.get("title")][:_WIKI_SUMMARIES]
    summaries = await asyncio.gather(*(
        _call_wiki_tool(hub, srv_name, "get_summary", {"title": h["title"]}) for h in top
    ))
    parts = []
    for hit, summary in zip(top, summaries):
        text = summary.get("summary") if isinstance(summary, dict) else None
        if not text:
            text = _HTML_TAG.sub("", hit.get("snippet") or "")
        if text and text.strip():
            parts.append(f"## {hit['title']}\n{text.strip()}")
    if not parts:
        return ""
    context = "\n\n".join(parts)
    max_chars = budget * 4
    if len(context) > max_chars:
        context = context[:max_chars] + "\n...(truncated)"
    log.info(
        "[MCP Wikipedia] query=%r (from %r) -> %d article(s), %d chars",
        used_query, query, len(parts), len(context),
    )
    return f"[{srv_name} -> Wikipedia]:\n{context}"


async def build_mcp_context(query: str, route: str | None = None, flow_tracker: Any = None) -> str:
    """Quét động toàn bộ các tool khả dụng từ MCP Hub, tự động chọn và gọi tool phù hợp."""
    if route in ["general", "general_knowledge"] and _is_chitchat_query(query):
        return ""

    from engine.server.mcp_server import get_mcp_hub
    hub = get_mcp_hub()
    stats = hub.get_stats()
    if stats.get("connected", 0) == 0:
        return ""

    # Quét tất cả tools đang có trên các mcp sessions
    try:
        all_mcp_tools = await hub.list_all_tools()
    except Exception as e:
        log.warning(f"Failed to list dynamic MCP tools: {e}")
        return ""

    matched_calls = []
    wiki_servers: list[str] = []
    for srv_name, tools in all_mcp_tools.items():
        is_wiki_srv = "wikipedia" in srv_name.lower()
        
        # Ở route chat thường, hoàn toàn không gọi bất kỳ MCP tool nào (bao gồm cả Wikipedia)
        if route == "general":
            continue
            
        # Ở route kiến thức bách khoa, chỉ cho phép duy nhất MCP Wikipedia
        if route == "general_knowledge" and not is_wiki_srv:
            continue
        if route == "general_knowledge" and is_wiki_srv:
            wiki_servers.append(srv_name)
            continue

        # Không tự gọi agentmemory khi ở route learning (đã có db lo)
        if route == "learning":
            continue
            
        for t in tools:
            tool_name = t["name"]
            desc = t.get("description", "")
            if _query_matches_tool(query, tool_name, desc):
                matched_calls.append((srv_name, tool_name, t.get("inputSchema", {})))
                
    if wiki_servers:
        return await _build_wikipedia_context(hub, wiki_servers[0], query, _MAX_TOKENS)

    if not matched_calls:
        return ""

    parts: list[str] = []
    budget = _MAX_TOKENS
    called = 0

    for srv_name, tool_name, schema in matched_calls:
        if called >= _MAX_MCP_CALLS or budget <= 0:
            break

        # Xác định tên tham số nhận chuỗi truy vấn (query / text / term / keyword)
        param_name = "query"
        properties = schema.get("properties", {})
        if properties:
            possible_names = ["query", "text", "term", "keyword", "search", "q"]
            for name in possible_names:
                if name in properties:
                    param_name = name
                    break
            else:
                # Lấy tham số đầu tiên nếu không có tên trùng khớp
                param_name = list(properties.keys())[0]

        result = await _call_mcp_tool_dynamic(hub, srv_name, tool_name, param_name, query, budget)
        if result:
            parts.append(f"[{srv_name} -> {tool_name}]:\n{result}")
            called += 1
            budget -= _estimate_tokens(result)
            
            # Ghi log chi tiết hệ thống
            log.info(f"[MCP Wikipedia] Search query: '{query}' | Service: {srv_name} | Response: {len(result)} chars")

    return "\n\n".join(parts) if parts else ""


async def _call_mcp_tool_dynamic(hub, srv_name: str, tool_name: str, param_name: str, query: str, budget: int) -> Optional[str]:
    """Gọi tool MCP động và trả về dữ liệu kết quả."""
    try:
        result = await hub.call_tool(srv_name, tool_name, {param_name: query})
        if result is None:
            return None

        text_parts = []
        if hasattr(result, "content"):
            for item in result.content:
                if hasattr(item, "text") and item.text:
                    text_parts.append(item.text)

        raw = "\n".join(text_parts) if text_parts else str(result)
        if not raw.strip():
            return None

        # Cắt theo budget để không làm tràn context
        max_chars = budget * 4
        if len(raw) > max_chars:
            raw = raw[:max_chars] + "\n...(truncated)"
        return raw

    except Exception as e:
        log.warning(f"Failed to call dynamic MCP tool '{tool_name}' on '{srv_name}': {e}")
        return None
