"""Quản lý các prompt kết quả: tóm tắt tool, synthesizer, turn_status (spec 2026-09-25 mục 2)."""
import importlib
import logging
from engine.prompts import load, persona

log = logging.getLogger("jarvis.prompts.results")

_TOOL_SUMMARY_MODULES: dict[str, str] = {
    "get_cgv_movies": "engine.tools.search_engine",
    "get_epic_free_games": "engine.tools.search_engine",
    "get_market_data": "engine.tools.search_engine",
    "search_news": "engine.tools.search_engine",
    "weather_search": "engine.tools.weather_engine",
    "search_products": "engine.tools.shop_engine",
    "read_note": "engine.tools.note_engine",
    "take_note": "engine.tools.note_engine",
    "query_history": "engine.tools.history_engine",
}

_DEFAULT_RULES = (
    "QUY TẮC ĐỊNH DẠNG CHUNG:\n"
    "- Trình bày kết quả rõ ràng, mạch lạc, ngắn gọn.\n"
    "- Giữ nguyên các cú pháp Markdown hình ảnh và liên kết từ kết quả công cụ."
)


def build_tool_summary_prompt(tool_name: str, content: str = "") -> str:
    """Xây dựng prompt tóm tắt kết quả tool cho LLM vòng 2."""
    rules = ""
    # Ép dùng định dạng bảng phim/video nếu phát hiện kết quả chứa thẻ search_media (loại trừ CGV)
    if tool_name == "search_media" or ("search_media" in content and "get_cgv_movies" not in content):
        try:
            from engine.tools.media_search import summary_rules
            rules = summary_rules(content)
        except Exception as e:
            log.warning("Failed to import media_search summary_rules: %s", e)
    else:
        module_path = _TOOL_SUMMARY_MODULES.get(tool_name)
        if module_path:
            try:
                module = importlib.import_module(module_path)
                rules = module.SUMMARY_RULES.get(tool_name, "")
            except Exception as e:
                log.warning("Failed to load SUMMARY_RULES for %s: %s", tool_name, e)

    if not rules:
        rules = _DEFAULT_RULES

    return load("tool_summary", persona_short=persona.short(), rules=rules)


def build_synthesis_prompt() -> str:
    """Xây dựng prompt tổng hợp kết quả đa agent cho orchestrator synthesizer."""
    return load("synthesis", persona_short=persona.short())


def build_turn_status(action_declined: bool = False, route: str = "") -> str:
    """Xây dựng khối chỉ thị <turn_status> (tool_status, answer_policy)."""
    items = []
    if route == "general_knowledge":
        items.append(
            "<answer_policy>\n"
            "Dữ liệu Wikipedia (nếu có) chỉ để bổ sung. Nếu không có hoặc không liên quan, "
            "hãy trả lời bằng kiến thức sẵn có của bạn; chỉ nói không biết khi thực sự không biết.\n"
            "</answer_policy>"
        )

    # Nhánh chat không bao giờ chạy công cụ: lượt thường cũng phải biết điều đó, không chỉ lượt bị từ chối
    # (chat từng bịa "đã kiểm tra… hệ thống ổn định", log 2026-09-25 15:16).
    if route != "general_knowledge":  # nhánh tra cứu đã có dữ liệu Wikipedia nên không nhận tool_status
        items.append(load("tool_status_declined" if action_declined else "tool_status_none").rstrip("\n"))

    if not items:
        return ""
    content = "\n\n".join(items)
    return load("turn_status", content=content)
