"""General offer skill: only one concrete offer, backed by one real tool."""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from engine.prompts.chat import build_chat_system_prompt
from engine.prompts.catalog import tool_list_text


def _block(name):
    m = re.search(rf"<{name}>\n(.*?)\n</{name}>", build_chat_system_prompt(), re.S)
    assert m, f"thiếu khối <{name}>"
    return m.group(1)


def test_capabilities_only_lists_what_the_system_can_do():
    caps = _block("capabilities")
    assert "<ask_user>" not in caps and "<action_run>" not in caps


def test_general_offer_skill_is_loaded_in_offer_protocol_with_dynamic_tool_whitelist():
    p = _block("offer_protocol")
    assert tool_list_text() in p
    assert "<ask_user>" in p and "<action_run>" in p
    assert "<ask_user>mở Notepad</ask_user>" in p and "<action_run>open_app</action_run>" in p
    assert "khớp" in p and "cùng một việc" in p


def test_general_offer_skill_keeps_original_app_names():
    p = _block("offer_protocol")
    assert "tên gốc" in p and "không dịch" in p and "ngoặc" in p


def test_general_offer_skill_defaults_to_no_offer_and_names_when_to_offer():
    """Đo 2026-10-01 (suggestion_probe, Gemma 4): 'mặc định chỉ trả lời' đặt TRƯỚC + tiêu chí cụ thể
    'đúng MỘT công cụ làm được ngay, ngài chưa tự làm' giảm thẻ sai 22% → 3% mà vẫn đề nghị đúng 76%."""
    p = _block("offer_protocol")
    assert p.splitlines()[0].startswith("Mặc định chỉ trả lời bằng lời")
    assert "đúng MỘT công cụ" in p and "ngài chưa tự làm" in p
    for quiet in ("trò chuyện", "cảm xúc", "phàn nàn", "tự làm"):
        assert quiet in p.split("Không dùng thẻ", 1)[1]


def test_general_offer_skill_stays_short():
    """Giao thức dài làm model đề nghị ở mọi lượt (2026-09-27, 2026-10-01): phần chữ ngoài danh sách công cụ ≤ 1000 ký tự."""
    p = _block("offer_protocol")
    assert len(p.replace(tool_list_text(), "")) <= 1000, len(p)


def test_legacy_offer_protocol_prompt_is_not_loaded():
    assert "Mặc định chỉ trả lời bằng lời, không gợi ý hay đề nghị gì thêm." not in build_chat_system_prompt()


def test_soul_rules_do_not_push_offers_and_name_only_real_blocks():
    """2026-09-27 (user: chat thường gợi ý ầm đùng): luật cứng nhắc 'đề nghị theo <offer_protocol>' 2 lần làm
    model coi đề nghị là việc nên làm; <offer_protocol> tự đủ. Luật chỉ được nhắc khối có thật trong prompt."""
    soul = _block("soul_rules")
    assert "<offer_protocol>" not in soul and "đề nghị" not in soul
    for ghost in ("<memory_context>", "<learned_experiences>", "<user_preferences>", "<mcp_data>", "<hook_context>"):
        assert ghost not in soul, ghost
    assert "<style_rules>" not in _block("identity")


def test_classifier_keeps_original_app_names():
    from engine.orchestrator.classifier import _SYSTEM
    assert "tên gốc" in _SYSTEM and "ngoặc" in _SYSTEM


def test_normal_chat_does_not_load_offer_protocol():
    from engine.prompts.chat import build_chat_messages
    msgs = build_chat_messages("chào bạn, hôm nay thế nào?", route="general")
    assert "<offer_protocol>" not in msgs[0]["content"]


def test_offer_seeking_chat_loads_offer_protocol():
    from engine.prompts.chat import build_chat_messages
    msgs = build_chat_messages("lười quá bạn có gợi ý bài hát cho tôi không?", route="general")
    assert "<offer_protocol>" in msgs[0]["content"]


def test_affirm_recognizes_retry_phrases():
    from engine.router.ask_user import reply_kind
    assert reply_kind("thử lại coi") == "affirm"
    assert reply_kind("thử lại đi") == "affirm"
    assert reply_kind("làm lại đi") == "affirm"
    assert reply_kind("ừ") == "affirm"


def test_normal_chat_does_not_load_capabilities():
    from engine.prompts.chat import build_chat_messages
    msgs = build_chat_messages("chào bạn, hôm nay thế nào?", route="general")
    assert "<capabilities>" not in msgs[0]["content"]


def test_caps_seeking_chat_loads_capabilities():
    from engine.prompts.chat import build_chat_messages
    msgs = build_chat_messages("bạn có thể làm được gì giúp tôi?", route="general")
    assert "<capabilities>" in msgs[0]["content"]


