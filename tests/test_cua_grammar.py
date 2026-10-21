"""win_control theo grammar (2026-10-14): mỗi bước model chỉ ra được {"tool": <tool cua hợp lệ>, "args": đúng kiểu
cua-driver v0.34} hoặc {"finish": "..."}; think 128. Code vẫn giữ mọi chốt (thiếu tham số, snapshot, xác nhận)."""
import asyncio
from types import SimpleNamespace

from engine.tools.desktop_control import cua_runner as C


def _branches():
    return {b["properties"]["tool"]["const"]: b for b in C.ACTION_SCHEMA["anyOf"] if "tool" in b["properties"]}


def test_schema_has_one_branch_per_cua_tool_plus_finish():
    assert set(_branches()) == set(C._CUA_TOOLS)
    finish = [b for b in C.ACTION_SCHEMA["anyOf"] if "finish" in b["properties"]]
    assert len(finish) == 1 and finish[0]["required"] == ["finish"]


def test_args_follow_allowed_required_and_cua_driver_types():
    for tool, (allowed, required, _) in C._CUA_TOOLS.items():
        args = _branches()[tool]["properties"]["args"]
        assert set(args["properties"]) == allowed and args["additionalProperties"] is False, tool
        # window_id: code tự điền từ cửa sổ đã biết (_remember_windows) nên grammar không bắt buộc
        assert set(args["required"]) == required - {"window_id"}, tool
    click = _branches()["click"]["properties"]["args"]["properties"]
    assert click["pid"]["type"] == click["window_id"]["type"] == click["element_index"]["type"] == "integer"
    assert _branches()["scroll"]["properties"]["args"]["properties"]["direction"]["enum"] == ["up", "down", "left", "right"]
    assert _branches()["hotkey"]["properties"]["args"]["properties"]["keys"]["items"]["type"] == "string"
    assert _branches()["list_windows"]["properties"]["args"]["properties"]["on_screen_only"]["type"] == "boolean"


def test_cua_llm_sends_grammar_and_think_budget(monkeypatch):
    calls = []

    async def fake_llm(**kw):
        calls.append(kw)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"finish": "Xong."}'))])
    monkeypatch.setattr("engine.server.llm_server.call_llm", fake_llm)
    assert asyncio.run(C._cua_llm([{"role": "user", "content": "Task: x"}])) == '{"finish": "Xong."}'
    kw = calls[0]
    assert kw["thinking"] is True and kw["thinking_budget"] == 128 and kw["temperature"] == 0.0
    assert kw["response_format"]["json_schema"]["schema"] is C.ACTION_SCHEMA
