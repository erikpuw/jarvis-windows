"""The <capabilities> card is only loaded on the chat path (server.generate_response_stream,
after routing decided no tool runs this turn). Measured 2026-09-23: listing agent
identifiers there made the chat model say "tôi sẽ gọi agent desktop/Goose/vietlott" and
promise results it never produces. The card must describe WHAT Jarvis can do in plain
concepts, say no tool runs in this turn, and never name agents.

Run: python tests/test_capability_card.py
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine import prompts  # noqa: E402
from engine.prompts import catalog  # noqa: E402
from engine.prompts.chat import build_chat_system_prompt, load_offer_protocol  # noqa: E402
from engine.orchestrator.registry import AGENT_REGISTRY  # noqa: E402

# Thẻ tự nhận thức thật sự nằm trong prompt là <capabilities> + <offer_protocol> ghép lại
# (xem engine/prompts/chat.py::build_chat_system_prompt), giống hệt _get_capability_card() cũ.
_CAPABILITY_CARD = (
    prompts.load("capabilities")
    + "\n\n"
    + load_offer_protocol()
)


def _card() -> str:
    assert _CAPABILITY_CARD in build_chat_system_prompt(), "card not wired into the chat prompt"
    return _CAPABILITY_CARD


def test_card_names_no_agent_identifier():
    # 2026-09-25 (ngài duyệt): thẻ được nêu TÊN agent dạng "Agent Desktop" để chat trả lời khi được hỏi;
    # vẫn cấm dạng định danh (@desktop, `desktop`, desktop:) vốn khiến model nói "tôi sẽ gọi agent …".
    card = _card()
    for name in AGENT_REGISTRY:
        # "email"/"notes" are also plain words; an identifier is "name:", `name`, **name** or @name.
        assert not re.search(rf"(`{name}`|\*\*{name}\*\*|@{name}\b|\b{name}\s*:)", card, re.I), name


def test_card_says_no_tool_runs_this_turn_and_no_promises():
    # Spec §6 (2026-09-24): thay câu "KHÔNG có công cụ nào được chạy... nói ngắn gọn rằng ngài
    # chỉ cần ra lệnh trực tiếp" bằng câu cho phép Jarvis xin phép chạy MỘT việc qua <ask_user>.
    card = _card().lower()
    assert "ask_user" in card, card  # xin phép qua thẻ, không tự nhận đã/sẽ làm
    # 2026-10-01: câu "không có công cụ nào chạy" do <tool_status> (turn_status, sát câu hỏi) nói mỗi lượt,
    # không còn nằm trong giao thức tĩnh (giao thức ngắn đo được thẻ sai 3% thay vì 22%).
    status = prompts.load("tool_status_none").lower()
    assert "không có công cụ nào chạy" in status and "không nói là đã làm" in status, status


def test_card_still_lists_what_jarvis_can_do():
    card = _card().lower()
    for concept in ("ứng dụng", "email", "thời tiết", "tin tức", "màn hình", "ghi chú", "nhạc"):
        assert concept in card, concept


if __name__ == "__main__":
    for t in (test_card_names_no_agent_identifier, test_card_says_no_tool_runs_this_turn_and_no_promises,
              test_card_still_lists_what_jarvis_can_do):
        try:
            t()
            print("PASS", t.__name__)
        except AssertionError as e:
            print("FAIL", t.__name__, "->", str(e)[:160])
