# -*- coding: utf-8 -*-
"""Nguồn sự thật duy nhất cho tập tên lệnh có logic thực thi thật trong
engine.core.actions._execute_tool_inner.

Trước đây tập tên này bị chép tay riêng ở 2 nơi (whitelist redirect của
execute_command trong actions.py, và built_in_cmds trong guardrails.py) —
2 danh sách đó lệch nhau: khi 1 lệnh mới (vd. mcp_call) được thêm logic thật
vào actions.py nhưng bị quên thêm vào 1 trong 2 whitelist kia, lệnh đó bị
chặn/rơi vào nhánh "thành công" giả một cách âm thầm, không có lỗi nào lộ ra
cho tới khi có người thử gọi. Import từ đây thay vì tự chép tay 1 danh sách
mới để không lặp lại lớp lỗi này.

=== TOOL_REGISTRY — nơi điều phối tool duy nhất (đang xây dần theo batch) ===

`_execute_tool_inner` trong actions.py đang được tách dần từ 1 chuỗi
if/elif dài sang tra cứu qua `TOOL_REGISTRY` bên dưới. Trong lúc chuyển tiếp,
2 cơ chế cùng tồn tại: tool nào đã có mặt trong TOOL_REGISTRY thì dispatch qua
đây, tool nào chưa migrate thì vẫn chạy qua elif chain cũ trong actions.py.
Khi TOOL_REGISTRY chứa đủ mọi tool trong KNOWN_TOOL_NAMES, KNOWN_TOOL_NAMES
sẽ đổi thành `frozenset(TOOL_REGISTRY.keys())` để không thể lệch nhau nữa.

QUY TẮC khi thêm 1 handler vào TOOL_REGISTRY:
1. Chữ ký thống nhất: `async def handler(arguments, ws, safe_ws_send_json,
   conversation_history, **kwargs) -> str | dict`.
2. Handler KHÔNG được tự bắt Exception của chính nó và trả về chuỗi lỗi —
   để lỗi lộ ra ngoài, dispatch loop trung tâm trong actions.py sẽ bắt và
   định dạng thống nhất (giữ đúng hành vi cũ: cùng 1 định dạng thông báo lỗi
   cho MỌI tool, thay vì mỗi tool tự bịa 1 kiểu). Ngoại lệ: handler được phép
   tự try/except khi cần PHÂN LOẠI lỗi để trả thông báo khác nhau theo loại
   lỗi (vd. mcp_call phân biệt "server chưa kết nối" với "lỗi khác") — nhưng
   vẫn phải re-raise hoặc trả string lỗi rõ ràng, không được nuốt lỗi im lặng.
3. Logic thật (không chỉ delegate) nên đặt trong module tools sở hữu dữ liệu
   liên quan (xem map_engine.py làm mẫu), không viết logic nghiệp vụ ngay
   trong file này — file này chỉ chứa wrapper keo nối tham số + chính registry.
"""

KNOWN_TOOL_NAMES: frozenset[str] = frozenset({
    "check_mail",
    "check_calendar",
    "vietlott_analysis",
    "legal_lookup",
    "vietnam_data_lookup",
    "get_market_data",
    "search_products",
    "get_zodiac_data",
    "get_vannien_data",
    "get_cgv_movies",
    "get_epic_free_games",
    "search_news",
    "weather_search",
    "map_route",
    "map_pois",
    "read_screen",
    "cap_screen",
    "read_webcam",
    "open_app",
    "close_app",
    "search_media",
    "win_control",
    "mcp_call",
    "get_skill_stats",
    "get_skill_content",
    "office_tool",
    "rag_tool",
    "check_project",
    "check_security",
    "check_system",
    "dream",
    "install_extension",
    "take_note",
    "read_note",
    "query_history",
    "upscale_image",
    "web_research",
})


from typing import Awaitable, Callable

# ---------------------------------------------------------------------------
# Batch 1 — 11 tool delegate đơn giản nhất (2-6 dòng, chỉ gọi hàm module có
# sẵn trong engine/tools/). Wrapper ở đây chỉ là lớp keo nối tham số, không
# chứa logic nghiệp vụ — hành vi giữ nguyên 100% so với nhánh elif cũ.
# ---------------------------------------------------------------------------

async def _h_check_mail(arguments, ws, safe_ws_send_json, conversation_history, **kwargs):
    from engine.tools.mail_access import check_unread_mail
    return await check_unread_mail(
        ws=ws, safe_ws_send_json=safe_ws_send_json,
        max_results=arguments.get("max_results", 10),
    )


async def _h_check_calendar(arguments, ws, safe_ws_send_json, conversation_history, **kwargs):
    from engine.tools.mail_access import check_calendar
    return await check_calendar(
        ws=ws, safe_ws_send_json=safe_ws_send_json,
        max_results=arguments.get("max_results", 10),
    )


async def _h_vietlott_analysis(arguments, ws, safe_ws_send_json, conversation_history, **kwargs):
    from engine.tools.vietlott_engine.service import run_vietlott_analysis
    return await run_vietlott_analysis(arguments)


async def _h_legal_lookup(arguments, ws, safe_ws_send_json, conversation_history, **kwargs):
    from engine.tools.legal_engine import legal_lookup
    return await legal_lookup(arguments.get("query", ""))


async def _h_vietnam_data_lookup(arguments, ws, safe_ws_send_json, conversation_history, **kwargs):
    from engine.tools.search_engine import handle_vietnam_data_query
    return await handle_vietnam_data_query(arguments.get("query", ""), ws=ws)


async def _h_get_market_data(arguments, ws, safe_ws_send_json, conversation_history, **kwargs):
    from engine.tools.search_engine import handle_market_query
    query = arguments.get("query", "")
    user_text_val = kwargs.get("user_text", "")
    return await handle_market_query(query, user_text=user_text_val)


async def _h_search_products(arguments, ws, safe_ws_send_json, conversation_history, **kwargs):
    from engine.tools.shop_engine import search_products
    return await search_products(arguments.get("query", ""), ws=ws)


async def _h_get_zodiac_data(arguments, ws, safe_ws_send_json, conversation_history, **kwargs):
    from engine.tools.search_engine import handle_zodiac_query
    return await handle_zodiac_query(arguments.get("query", ""))


async def _h_get_vannien_data(arguments, ws, safe_ws_send_json, conversation_history, **kwargs):
    from engine.tools.search_engine import handle_vannien_query
    return await handle_vannien_query(arguments.get("query", ""))


async def _h_get_cgv_movies(arguments, ws, safe_ws_send_json, conversation_history, **kwargs):
    from engine.tools.search_engine import handle_cgv_movies_query
    query = arguments.get("query", "")
    user_text_val = kwargs.get("user_text", "")
    return await handle_cgv_movies_query(query, user_text=user_text_val)


async def _h_get_epic_free_games(arguments, ws, safe_ws_send_json, conversation_history, **kwargs):
    from engine.tools.search_engine import handle_epic_free_games_query
    query = arguments.get("query", "")
    user_text_val = kwargs.get("user_text", "")
    return await handle_epic_free_games_query(query, user_text=user_text_val)


async def _h_web_research(arguments, ws, safe_ws_send_json, conversation_history, **kwargs):
    from engine.tools.research_engine import web_research
    return await web_research(arguments.get("query", ""))


# name -> async def handler(arguments, ws, safe_ws_send_json, conversation_history, **kwargs)
# Điền dần theo batch — xem quy tắc ở docstring đầu file.
TOOL_REGISTRY: dict[str, Callable[..., Awaitable]] = {
    "check_mail": _h_check_mail,
    "check_calendar": _h_check_calendar,
    "vietlott_analysis": _h_vietlott_analysis,
    "legal_lookup": _h_legal_lookup,
    "vietnam_data_lookup": _h_vietnam_data_lookup,
    "get_market_data": _h_get_market_data,
    "search_products": _h_search_products,
    "get_zodiac_data": _h_get_zodiac_data,
    "get_vannien_data": _h_get_vannien_data,
    "get_cgv_movies": _h_get_cgv_movies,
    "get_epic_free_games": _h_get_epic_free_games,
    "web_research": _h_web_research,
}
