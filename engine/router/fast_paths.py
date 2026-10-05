"""Các lối tắt không dùng LLM (spec §4 bước 1, 3, 4)."""
import logging
import re


log = logging.getLogger("jarvis.router.fast_paths")

# "Ghi chú (Notepad)": model dịch tên app rồi kèm tên gốc trong ngoặc; Windows chỉ biết tên gốc.
_ORIGINAL_APP_NAME = re.compile(r"\(\s*([A-Za-z0-9][A-Za-z0-9 .+#&'-]*?)\s*\)")

# Tên gọi khác của agent khi gõ @; còn lại tra thẳng AGENT_REGISTRY (có bỏ tiền tố agent_).
VOICE_CONTROL = re.compile(  # nguyên văn route_agents._VOICE_CONTROL
    r"^\s*(?:(?:hãy|xin|vui\s+lòng|jarvis)[,\s]+)*(?:"
    r"(?:điều\s+khiển|control)\s+(?:máy|màn\s+hình|chuột|windows)\b"
    r"|(?:thu\s+nhỏ|phóng\s+to|phóng\s+lớn|khôi\s+phục|minimi[sz]e|maximi[sz]e|restore)\s+(?:cửa\s+sổ|ứng\s+dụng|app|window)\b)",
    re.I,
)

# Khiếu nại "gọi nhầm agent" (nguyên văn route_agents._ROUTING_COMPLAINT_RES). Van an toàn thứ hai ở
# learning.unlearn_last_route: chỉ kích hoạt khi có agent outcome thành công ≤10 phút.
_ROUTING_COMPLAINT_RES = [
    re.compile(p, re.I) for p in (
        r"sao (lại|mà|tự (ý|động)).{0,25}(gọi|chạy)",
        r"gọi (agent )?(bừa|tùm lum|lung tung|linh tinh)",
        r"lại gọi agents?",
        r"tự động chạy",
        r"tự ý (gọi|chạy)",
        r"không (cần|có yêu cầu|bảo).{0,25}(gọi|chạy)",
        r"đừng (gọi|chạy)",
        r"đang hỏi.{0,40}(mà|sao|nhưng).{0,40}(gọi|chạy)",
        r"dạy.{0,30}(mới|chỉ).{0,20}(chạy|gọi|kêu)",
        r"ai (bảo|cho phép).{0,25}(gọi|chạy)",
    )
]


_PLAN_MENTION = re.compile(r"^@plans?(?![\w])[\s,:]*(.*)$", re.I | re.S)


def plan_mention(text: str) -> str | None:
    """'@plans hôm nay ăn gì' -> 'hôm nay ăn gì': cửa vào DUY NHẤT của chế độ mục tiêu (engine/plans, 2026-09-27).
    Không có mục tiêu sau @plans -> None (đi luồng thường)."""
    m = _PLAN_MENTION.match(text or "")
    goal = m.group(1).strip() if m else ""
    return goal or None


_JOBS_MENTION = re.compile(r"^@jobs?(?![\w])[\s,:]*(.*)$", re.I | re.S)


def jobs_mention(text: str) -> str | None:
    """'@jobs tìm' -> 'tìm'; '@jobs' -> '' (trợ giúp). Không phải @jobs -> None (spec 2026-09-27 mục 5)."""
    m = _JOBS_MENTION.match(text or "")
    return m.group(1).strip() if m else None


_COMMAND_MENTION = re.compile(r"^@commands/([\w-]+)\.md(?![\w])[\s,:]*(.*)$", re.I | re.S)


def command_mention(text: str) -> tuple[str, str] | None:
    """'@commands/search_products.md máy giặt' -> ('search_products', 'máy giặt'). Tool lạ hoặc không phải @commands/ -> None."""
    m = _COMMAND_MENTION.match(text or "")
    if not m:
        return None
    from engine.prompts import catalog
    tool = m.group(1).lower()
    return (tool, m.group(2).strip()) if tool in catalog.tool_to_agent_map() else None


_TOOL_NAMED = re.compile(
    r"^\s*(?:(?:hãy|xin|vui\s+lòng|jarvis)[,\s]+)*(?:dùng|sử\s+dụng|chạy|thực\s+hiện|gọi|run)\s+(?:lại\s+)?"
    r"(?:lệnh\s+|tool\s+|công\s+cụ\s+)?[`@/]*([a-z][a-z0-9_]*)", re.I)


def tool_name_command(text: str) -> str | None:
    """"Dùng lệnh check_system coi" -> 'check_system': ngài gọi đích danh một công cụ bằng động từ ra lệnh thì chạy đúng
    công cụ đó, không để gate/classifier đoán (log 2026-10-04). Hai tên công cụ trong câu = mơ hồ -> None."""
    m = _TOOL_NAMED.match(text or "")
    if not m:
        return None
    from engine.prompts import catalog
    tools = catalog.tool_to_agent_map()
    tool = m.group(1).lower()
    named = {w for w in re.findall(r"[a-z][a-z0-9_]*", text.lower()) if w in tools}
    return tool if tool in tools and named == {tool} else None


def forced_command(tool: str, value: str):
    """Lệnh tường minh /tool hoặc @commands/tool.md -> chạy đúng agent của tool, không để classifier đoán."""
    from engine.prompts import catalog
    from engine.router.types import RouteDecision
    agent = catalog.tool_to_agent_map().get(tool)
    if not agent or not value:
        return None
    return RouteDecision("agent", value, "mention", agent=agent)


_RAG_MENTION = re.compile(r"^@rag(?![\w])[\s,:]*(.*)$", re.I | re.S)


def rag_mention(text: str) -> str | None:
    """'@rag <câu hỏi|lệnh con>' -> phần sau; '@rag' -> '' (trợ giúp). Không phải @rag -> None.
    Phải chạy trước resolve_mention: không thì @rag rơi vào agent rag (bắt buộc có tệp đính kèm)."""
    m = _RAG_MENTION.match(text or "")
    return m.group(1).strip() if m else None


def resolve_mention(text: str) -> tuple[str | None, str]:
    """'@email xem thư' -> ('email', 'xem thư'). Mention lạ -> (None, phần sau mention). Không có @ -> (None, text)."""
    if not text.startswith("@"):
        return None, text
    parts = text.split(None, 1)
    rest = parts[1] if len(parts) > 1 else ""
    from engine.prompts import catalog
    name = catalog.resolve_alias(parts[0])
    return (name, rest) if name else (None, rest)


def is_routing_complaint(clean_text: str) -> bool:
    """User đang phàn nàn lượt agent vừa rồi (lẽ ra chỉ là chat)."""
    t = clean_text.lower()
    if any(p.search(t) for p in _ROUTING_COMPLAINT_RES):
        return True
    return "đang hỏi" in t and ("chạy" in t or "gọi" in t)


async def ask_reply(clean_text: str, attachment_context):
    """Spec §4 bước 2/2b: đáp câu <ask_user> vừa hỏi. Không LLM; đọc DB chỉ khi câu là khẳng định/phủ định."""
    import asyncio
    from engine.router.ask_user import ask_to_command, is_actionable, reply_kind
    from engine.router.types import RouteDecision
    if attachment_context is not None:
        return None
    kind = reply_kind(clean_text)
    if not kind:
        return None
    from engine.core import memory
    try:
        ask, tool = await asyncio.to_thread(memory.get_pending_offer)
    except Exception as exc:
        log.warning("[ROUTER] get_pending_offer failed: %s", exc)
        return None
    if not ask or not is_actionable(ask):
        return None
    if kind == "affirm":
        command = ask_to_command(ask)
        if len(command.split()) < 2:
            # "Được không ạ?" -> "", "...giúp không ạ?" -> "giúp": not an actionable
            # command, let the gate classify the reply normally instead (M1).
            return None
        from engine.prompts import catalog
        offerables = catalog.offerable_tools()
        if tool in offerables:
            agent = offerables[tool][0]
            m = _ORIGINAL_APP_NAME.search(command) if tool in ("open_app", "close_app") else None
            if m:
                command = f"{command.split()[0]} {m.group(1)}"
            return RouteDecision("replay", command, "ask_reply", agent=agent,
                                 workflow={"id": "offer", "agent": agent, "tool_chain": [tool]})
        return RouteDecision("orchestrator", command, "ask_reply")
    return RouteDecision("general", clean_text, "ask_reply")
