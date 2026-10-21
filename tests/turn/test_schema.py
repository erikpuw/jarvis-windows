# tests/turn/test_schema.py
import pytest

from engine.tools import registry as R
from engine.turn import schema


@pytest.fixture(autouse=True)
def tools():
    R._reset_for_test()

    async def open_app(app_name: str) -> str:
        return ""

    async def cinema() -> str:
        return ""

    async def secret(x: str) -> str:
        return ""
    R._register_for_test(open_app, doc="Mở app.\n\napp_name: tên app\n")
    R._register_for_test(cinema, doc="Phim.")
    R._register_for_test(secret, doc="Ẩn.\n\nx: x\n", chat=False)
    yield
    R._reset_for_test()


def _tools(s):
    return [b["properties"]["tool"]["const"] for b in s["anyOf"]]


def test_full_schema_has_none_and_chat_tools_tool_first():
    """Log 2026-10-12 18:08: "say" trước "tool" + tool=none → Gemma viết câu hứa ("Để tôi lên thực đơn…") thay vì
    nội dung. JSON chỉ để chọn tool; none không có "say" (câu trả lời viết bằng chữ thường ở vòng sau)."""
    s = schema.build()
    assert _tools(s) == ["none", "open_app", "cinema"]
    b = s["anyOf"][1]
    assert list(b["properties"]) == ["tool", "say", "args"]
    assert b["properties"]["args"] == {"type": "object", "properties": {"app_name": {"type": "string",
                                       "description": "tên app"}}, "required": ["app_name"],
                                       "additionalProperties": False}
    assert b["required"] == ["tool", "say", "args"] and b["additionalProperties"] is False
    assert s["anyOf"][0] == {"type": "object", "properties": {"tool": {"const": "none"}}, "required": ["tool"],
                             "additionalProperties": False}


def test_only():
    assert _tools(schema.build(only="secret")) == ["secret"]


def test_response_format_wrapper():
    assert schema.response_format({"anyOf": []}) == {
        "type": "json_schema", "json_schema": {"name": "turn", "schema": {"anyOf": []}}}


def test_say_never_empty():
    """held-out 2026-10-12: 'vặn nhỏ âm lượng xuống' → {"say": "", "tool": "none"} — ngài không nhận được chữ nào."""
    for branch in schema.build()["anyOf"][1:]:
        assert branch["properties"]["say"] == {"type": "string", "minLength": 1}
