"""win_control chạy trên cua-driver: vòng lặp LLM -> tool, cổng xác nhận, danh sách cho phép.
Dùng cua-driver và LLM giả — không mở app, không đụng chuột/bàn phím thật.
Run: python -m pytest tests/test_cua_control.py"""
import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.tools import windows_control as wc


class FakeCua:
    """Thay CuaSession: ghi lại mọi lời gọi, trả kết quả dựng sẵn theo tên tool."""

    def __init__(self, results=None):
        self.results = results or {}
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def call(self, tool, args):
        self.calls.append((tool, dict(args)))
        r = self.results.get(tool, {"is_error": False, "text": "ok", "data": {}})
        return r(args) if callable(r) else r


def _say(*actions):
    """LLM giả: mỗi phần tử là dict (sẽ thành JSON) hoặc chuỗi thô."""
    it = iter(actions)

    async def ask(messages):
        a = next(it)
        return a if isinstance(a, str) else json.dumps(a)

    return ask


def _run(actions, cua=None, confirm_answers=(True,), max_steps=None):
    cua = cua or FakeCua()
    asked = []
    answers = iter(confirm_answers)

    async def confirm(message):
        asked.append(message)
        return next(answers, True)

    out = asyncio.run(wc.run_cua_task(
        "mở notepad", None, None,
        session_factory=lambda: cua, ask_llm=_say(*actions), confirm=confirm, max_steps=max_steps,
    ))
    return out, cua, asked


@pytest.fixture(autouse=True)
def _default_confirm_each(monkeypatch):
    monkeypatch.delenv("CUA_CONFIRM", raising=False)


STATE = {"is_error": False, "text": "", "data": {"snapshot_id": "s00000001", "elements": [
    {"element_index": 3, "role": "Button", "label": "Save", "actions": ["invoke"]}]}}
READ = {"tool": "get_window_state", "args": {"pid": 1, "window_id": 2}}
CLICK3 = {"tool": "click", "args": {"pid": 1, "window_id": 2, "element_index": 3}}

WINDOWS = {"is_error": False, "text": "", "data": {"windows": [
    {"pid": 10, "window_id": 20, "app_name": "notepad.exe", "title": "Untitled - Notepad", "is_on_screen": True},
    {"pid": 3, "window_id": 4, "app_name": "cua-driver.exe", "title": "Cua.AgentCursorOverlay.default", "is_on_screen": True},
]}}


def test_read_tools_need_no_confirmation_and_finish_text_is_returned():
    out, cua, asked = _run([
        {"tool": "list_windows", "args": {"on_screen_only": True}},
        {"finish": "Notepad đang mở."},
    ], FakeCua({"list_windows": WINDOWS}))
    assert out == "Notepad đang mở." and asked == []
    assert cua.calls == [("list_windows", {"on_screen_only": True})]


def test_list_windows_observation_hides_the_cua_overlay_window():
    seen = []

    async def ask(messages):
        seen.append(messages[-1]["content"])
        return json.dumps({"finish": "xong"}) if len(seen) > 1 else json.dumps({"tool": "list_windows", "args": {}})

    asyncio.run(wc.run_cua_task("x", None, None, session_factory=lambda: FakeCua({"list_windows": WINDOWS}),
                                ask_llm=ask, confirm=None))
    assert "Untitled - Notepad" in seen[1] and "window_id=20" in seen[1] and "AgentCursorOverlay" not in seen[1]


def test_mutating_tool_needs_confirmation_and_refusal_stops_without_calling_driver():
    out, cua, asked = _run([READ, CLICK3], FakeCua({"get_window_state": STATE}), confirm_answers=(False,))
    assert out.startswith("Lỗi") and len(asked) == 1 and [c[0] for c in cua.calls] == ["get_window_state"]


def test_confirm_off_skips_the_prompt_for_normal_clicks(monkeypatch):
    monkeypatch.setenv("CUA_CONFIRM", "off")
    out, cua, asked = _run([READ, CLICK3, {"finish": "xong"}], FakeCua({"get_window_state": STATE}))
    assert out == "xong" and asked == [] and [c[0] for c in cua.calls] == ["get_window_state", "click"]


def test_risky_label_still_asks_when_confirm_is_off(monkeypatch):
    monkeypatch.setenv("CUA_CONFIRM", "off")
    state = {"is_error": False, "text": "", "data": {"snapshot_id": "s00000001", "elements": [
        {"element_index": 3, "role": "Button", "label": "Delete all files", "actions": ["invoke"]}]}}
    out, cua, asked = _run([
        {"tool": "get_window_state", "args": {"pid": 1, "window_id": 2}},
        {"tool": "click", "args": {"pid": 1, "window_id": 2, "element_index": 3}},
    ], FakeCua({"get_window_state": state}), confirm_answers=(False,))
    assert len(asked) == 1 and "Delete all files" in asked[0]
    assert out.startswith("Lỗi") and [c[0] for c in cua.calls] == ["get_window_state"]


def test_tools_outside_the_allowlist_are_refused_and_never_reach_the_driver():
    out, cua, _ = _run([
        {"tool": "kill_app", "args": {"pid": 1}},
        {"tool": "clipboard_read", "args": {}},
        {"finish": "Lỗi: không làm được"},
    ])
    assert cua.calls == [] and out.startswith("Lỗi")


def test_pixel_and_foreground_arguments_are_stripped_and_screenshots_are_never_requested(monkeypatch):
    monkeypatch.setenv("CUA_CONFIRM", "off")
    _, cua, _ = _run([
        READ,
        {"tool": "click", "args": {"pid": 1, "window_id": 2, "element_index": 3, "x": 5, "y": 6,
                                   "delivery_mode": "foreground"}},
        {"tool": "get_window_state", "args": {"pid": 1, "window_id": 2, "include_screenshot": True}},
        {"finish": "xong"},
    ], FakeCua({"get_window_state": STATE}))
    assert cua.calls[1] == ("click", {"pid": 1, "window_id": 2, "element_index": 3, "snapshot_id": "s00000001"})
    assert cua.calls[2][1]["include_screenshot"] is False


def test_input_without_a_target_window_is_refused_so_nothing_types_into_the_desktop(monkeypatch):
    monkeypatch.setenv("CUA_CONFIRM", "off")
    out, cua, _ = _run([
        {"tool": "type_text", "args": {"text": "hello"}},
        {"tool": "click", "args": {"pid": 1, "window_id": 2}},
        {"finish": "Lỗi: thiếu đích"},
    ])
    assert cua.calls == [] and out.startswith("Lỗi")


def test_state_observation_is_capped_and_reports_the_total(monkeypatch):
    els = [{"element_index": i, "role": "Button", "label": f"b{i}", "actions": ["invoke"]} for i in range(300)]
    seen = []

    async def ask(messages):
        seen.append(messages[-1]["content"])
        return json.dumps({"tool": "get_window_state", "args": {"pid": 1, "window_id": 2}}) if len(seen) == 1 \
            else json.dumps({"finish": "xong"})

    asyncio.run(wc.run_cua_task("x", None, None, ask_llm=ask, confirm=None, session_factory=lambda: FakeCua(
        {"get_window_state": {"is_error": False, "text": "", "data": {"elements": els, "total_element_count": 300}}})))
    obs = seen[1]
    assert obs.count("[") <= wc._CUA_MAX_ROWS + 5 and "300" in obs and "b0" in obs and "b299" not in obs


def test_only_the_latest_window_snapshot_stays_in_the_conversation():
    els = {"is_error": False, "text": "", "data": {"elements": [
        {"element_index": 0, "role": "Button", "label": "Save", "actions": ["invoke"]}]}}
    seen = []
    script = iter([{"tool": "get_window_state", "args": {"pid": 1, "window_id": 2}},
                   {"tool": "get_window_state", "args": {"pid": 1, "window_id": 2}}, {"finish": "xong"}])

    async def ask(messages):
        seen.append(messages)
        return json.dumps(next(script))

    asyncio.run(wc.run_cua_task("x", None, None, ask_llm=ask, confirm=None,
                                session_factory=lambda: FakeCua({"get_window_state": els})))
    final = " ".join(m["content"] for m in seen[-1] if m["role"] == "user")
    assert final.count('"Save"') == 1


def _update_page(*rows):
    els = [{"element_index": i, "role": role, "label": label, "parent_index": 27, "actions": ["invoke"]}
           for i, (role, label) in enumerate(rows)]
    return {"is_error": False, "text": "", "data": {"snapshot_id": "s00000001", "elements": els}}


PREVIEW_PAGE = _update_page(
    ("Button", "Check for updates"),
    ("Text", "2026-09 Preview Update (KB5124010) (26200.9550) is available."),
    ("Text", "Some spacer"),
    ("Hyperlink", "Download & install"),
    ("Button", "Install all"),
)


def _click_after_state(page, index, monkeypatch, mode="off"):
    monkeypatch.setenv("CUA_CONFIRM", mode)
    return _run([
        {"tool": "get_window_state", "args": {"pid": 1, "window_id": 2}},
        {"tool": "click", "args": {"pid": 1, "window_id": 2, "element_index": index}},
        {"finish": "xong"},
    ], FakeCua({"get_window_state": page}), confirm_answers=(True,))


def test_install_button_of_a_preview_update_is_refused_even_when_confirm_is_off(monkeypatch):
    out, cua, asked = _click_after_state(PREVIEW_PAGE, 3, monkeypatch)
    assert [c[0] for c in cua.calls] == ["get_window_state"] and asked == [] and out == "xong"


def test_install_button_of_a_preview_update_is_refused_in_each_mode_without_even_asking(monkeypatch):
    out, cua, asked = _click_after_state(PREVIEW_PAGE, 3, monkeypatch, mode="each")
    assert [c[0] for c in cua.calls] == ["get_window_state"] and asked == []


def test_install_all_is_still_allowed_when_a_preview_update_is_listed(monkeypatch):
    out, cua, asked = _click_after_state(PREVIEW_PAGE, 4, monkeypatch)
    assert [c[0] for c in cua.calls] == ["get_window_state", "click"]


def test_install_button_of_a_normal_update_is_not_mistaken_for_preview(monkeypatch):
    page = _update_page(
        ("Text", "2026-09 Cumulative Update for Windows 11 (KB5124011) is available."),
        ("Hyperlink", "Download & install"),
    )
    out, cua, asked = _click_after_state(page, 1, monkeypatch, mode="each")
    assert [c[0] for c in cua.calls] == ["get_window_state", "click"] and len(asked) == 1


def test_the_refusal_is_reported_back_to_the_model(monkeypatch):
    monkeypatch.setenv("CUA_CONFIRM", "off")
    seen = []
    script = iter([{"tool": "get_window_state", "args": {"pid": 1, "window_id": 2}},
                   {"tool": "click", "args": {"pid": 1, "window_id": 2, "element_index": 3}}, {"finish": "xong"}])

    async def ask(messages):
        seen.append(messages[-1]["content"])
        return json.dumps(next(script))

    asyncio.run(wc.run_cua_task("x", None, None, ask_llm=ask, confirm=None,
                                session_factory=lambda: FakeCua({"get_window_state": PREVIEW_PAGE})))
    assert "preview" in seen[2].lower()


def test_driver_error_is_fed_back_to_the_model_instead_of_crashing(monkeypatch):
    monkeypatch.setenv("CUA_CONFIRM", "off")
    bad = {"is_error": True, "text": "window_id 2 is closed, stale, or invalid.", "data": {}}
    seen = []
    script = iter([READ, CLICK3, {"finish": "Lỗi: cửa sổ đã đóng"}])

    async def ask(messages):
        seen.append(messages[-1]["content"])
        return json.dumps(next(script))

    out = asyncio.run(wc.run_cua_task("x", None, None, ask_llm=ask, confirm=None,
                                      session_factory=lambda: FakeCua({"click": bad, "get_window_state": STATE})))
    assert "stale" in seen[2] and out.startswith("Lỗi")


def test_repeating_the_same_action_stops_the_run(monkeypatch):
    monkeypatch.setenv("CUA_CONFIRM", "off")
    out, cua, _ = _run([READ, CLICK3, CLICK3, CLICK3], FakeCua({"get_window_state": STATE}), max_steps=6)
    assert out.startswith("Lỗi") and "lặp" in out and [c[0] for c in cua.calls] == ["get_window_state", "click"]


def test_step_cap_ends_with_an_error():
    ls = {"tool": "list_windows", "args": {}}
    out, cua, _ = _run([ls, {"tool": "list_windows", "args": {"on_screen_only": True}}, ls], max_steps=3)
    assert out.startswith("Lỗi") and "3 bước" in out


def test_two_unparseable_replies_in_a_row_stop_the_run():
    out, cua, _ = _run(["blah", "still not json"])
    assert out.startswith("Lỗi") and cua.calls == []


def test_json_wrapped_in_prose_or_fences_is_still_understood():
    out, _, _ = _run(['Được rồi:\n```json\n{"finish": "xong"}\n```'])
    assert out == "xong"


def test_missing_driver_returns_a_clear_error():
    class Missing:
        async def __aenter__(self):
            raise FileNotFoundError("cua-driver")

        async def __aexit__(self, *exc):
            return False

    out = asyncio.run(wc.run_cua_task("x", None, None, session_factory=Missing, ask_llm=_say(), confirm=None))
    assert out.startswith("Lỗi") and "CUA_DRIVER_PATH" in out


def test_empty_task_is_an_error():
    assert asyncio.run(wc.run_cua_task("  ", None, None, session_factory=FakeCua, ask_llm=_say())).startswith("Lỗi")


def test_dispatcher_sends_window_state_requests_to_the_fast_path_and_the_rest_to_cua(monkeypatch):
    seen = {}

    async def fake_state(text, ws, send, **kw):
        seen["state"] = text
        return "state-ran"

    async def fake_cua(task, ws, send, **kw):
        seen["cua"] = task
        return "cua-ran"

    monkeypatch.setattr(wc, "run_window_state_workflow", fake_state)
    monkeypatch.setattr(wc, "run_cua_task", fake_cua)
    assert asyncio.run(wc.run_win_control_workflow("@control phóng to notepad", None, None)) == "state-ran"
    assert asyncio.run(wc.run_win_control_workflow('@control mở notepad gõ "hi"', None, None)) == "cua-ran"
    assert seen["cua"] == 'mở notepad gõ "hi"'


def test_legacy_hardcoded_workflows_and_uitars_are_gone():
    for name in ("run_notepad_text_workflow", "run_edge_omnibox_workflow", "run_windows_update_workflow",
                 "execute_windows_control", "win_control_backend"):
        assert not hasattr(wc, name), name
    assert not (Path(__file__).parent.parent / "engine" / "tools" / "uitars_agent.py").exists()


def test_element_index_without_a_snapshot_is_refused_so_the_model_cannot_guess(monkeypatch):
    monkeypatch.setenv("CUA_CONFIRM", "off")
    out, cua, _ = _run([CLICK3, {"finish": "Lỗi: chưa đọc cửa sổ"}])
    assert cua.calls == [] and out.startswith("Lỗi")


def test_the_latest_snapshot_id_is_attached_to_element_actions(monkeypatch):
    monkeypatch.setenv("CUA_CONFIRM", "off")
    states = iter(["s00000001", "s00000002"])
    cua = FakeCua({"get_window_state": lambda a: {"is_error": False, "text": "", "data": {
        "snapshot_id": next(states), "elements": [{"element_index": 3, "role": "Button", "label": "Save"}]}}})
    _run([READ, READ, CLICK3, {"finish": "xong"}], cua)
    assert cua.calls[-1][1]["snapshot_id"] == "s00000002"


def test_finish_written_as_a_tool_call_is_still_understood():
    for reply in ({"tool": "finish", "args": {"result": "xong"}}, {"tool": "done", "args": {"message": "xong"}},
                  {"tool": "finish", "args": {"finish": "xong"}}, {"finish": {"result": "xong"}}):
        out, cua, _ = _run([reply])
        assert out == "xong" and cua.calls == [], reply


def test_finish_without_any_result_text_is_an_error_not_a_fake_success():
    out, _, _ = _run([{"finish": ""}])
    assert out.startswith("Lỗi")


BG_REFUSED = {"is_error": True, "data": {}, "text": "Background delivery is not available for target window class "
              "'Chrome_WidgetWin_1' on this event kind (text_input). Retry this action with delivery_mode=foreground."}


def _refused_then_ok(results):
    it = iter(results)
    return lambda args: next(it)


def test_keyboard_tools_retry_in_foreground_when_background_is_refused(monkeypatch):
    monkeypatch.setenv("CUA_CONFIRM", "off")
    ok = {"is_error": False, "text": "Typed 3 char(s)", "data": {}}
    cua = FakeCua({"get_window_state": STATE, "type_text": _refused_then_ok([BG_REFUSED, ok])})
    typing = {"tool": "type_text", "args": {"pid": 1, "window_id": 2, "element_index": 3, "text": "abc"}}
    out, cua, _ = _run([READ, typing, {"finish": "xong"}], cua)
    tries = [c[1] for c in cua.calls if c[0] == "type_text"]
    assert len(tries) == 2 and "delivery_mode" not in tries[0] and tries[1]["delivery_mode"] == "foreground"


def test_pointer_tools_never_fall_back_to_foreground(monkeypatch):
    monkeypatch.setenv("CUA_CONFIRM", "off")
    cua = FakeCua({"get_window_state": STATE, "click": BG_REFUSED})
    _run([READ, CLICK3, {"finish": "Lỗi: không bấm được"}], cua)
    assert [c[0] for c in cua.calls] == ["get_window_state", "click"]


def test_window_id_is_filled_from_the_last_snapshot_of_that_pid(monkeypatch):
    monkeypatch.setenv("CUA_CONFIRM", "off")
    key = {"tool": "press_key", "args": {"pid": 1, "key": "Enter"}}
    _, cua, _ = _run([READ, key, {"finish": "xong"}], FakeCua({"get_window_state": STATE}))
    assert cua.calls[-1] == ("press_key", {"pid": 1, "key": "Enter", "window_id": 2})


def test_finish_flag_with_the_text_in_another_key_is_understood():
    for reply in ({"finish": True, "result": "xong"}, {"finish": None, "message": "xong"},
                  {"finish": "", "summary": "xong"}, {"tool": "finish", "args": {}, "result": "xong"}):
        out, _, _ = _run([reply])
        assert out == "xong", reply


def test_finish_with_args_given_as_a_plain_string_is_understood():
    out, _, _ = _run([{"tool": "finish", "args": "Lỗi: không thấy nút"}])
    assert out == "Lỗi: không thấy nút"


# ---------------------------------------------------------------------------
# taskbar / Start menu qua pywinauto (cua-driver không thấy hai bề mặt này)
# ---------------------------------------------------------------------------

class FakeShell(FakeCua):
    pass


SHELL_STATE = {"is_error": False, "text": "", "data": {"total_element_count": 3, "elements": [
    {"element_index": 0, "role": "Button", "label": "Start"},
    {"element_index": 1, "role": "Button", "label": "Microsoft Edge - 1 running window"},
    {"element_index": 2, "role": "Button", "label": "Shut down"}]}}


def _run_shell(actions, shell, cua=None, confirm_answers=(True,)):
    cua = cua or FakeCua()
    asked = []
    answers = iter(confirm_answers)

    async def confirm(message):
        asked.append(message)
        return next(answers, True)

    out = asyncio.run(wc.run_cua_task("x", None, None, session_factory=lambda: cua, shell=shell,
                                      ask_llm=_say(*actions), confirm=confirm))
    return out, cua, shell, asked


def test_shell_tools_go_to_the_shell_backend_need_no_pid_and_ask_before_clicking():
    shell = FakeShell({"shell_state": SHELL_STATE})
    out, cua, shell, asked = _run_shell([
        {"tool": "shell_state", "args": {}},
        {"tool": "shell_click", "args": {"element_index": 0}},
        {"finish": "Đã mở Start."},
    ], shell)
    assert out == "Đã mở Start." and cua.calls == []
    assert shell.calls == [("shell_state", {}), ("shell_click", {"element_index": 0})]
    assert len(asked) == 1 and "Start" in asked[0]


def test_shell_state_lists_the_taskbar_rows_for_the_model():
    seen = []
    script = iter([{"tool": "shell_state", "args": {"query": "edge"}}, {"finish": "xong"}])

    async def ask(messages):
        seen.append(messages[-1]["content"])
        return json.dumps(next(script))

    asyncio.run(wc.run_cua_task("x", None, None, ask_llm=ask, confirm=None, session_factory=FakeCua,
                                shell=FakeShell({"shell_state": SHELL_STATE})))
    assert "Microsoft Edge - 1 running window" in seen[1] and "[1] Button" in seen[1]


def test_shutdown_style_buttons_in_the_shell_still_ask_when_confirm_is_off(monkeypatch):
    monkeypatch.setenv("CUA_CONFIRM", "off")
    shell = FakeShell({"shell_state": SHELL_STATE})
    out, _, shell, asked = _run_shell([
        {"tool": "shell_state", "args": {}},
        {"tool": "shell_click", "args": {"element_index": 2}},
    ], shell, confirm_answers=(False,))
    assert len(asked) == 1 and "Shut down" in asked[0] and out.startswith("Lỗi")
    assert [c[0] for c in shell.calls] == ["shell_state"]


def test_shell_click_and_set_text_need_an_element_index():
    out, _, shell, _ = _run_shell([
        {"tool": "shell_click", "args": {}},
        {"tool": "shell_set_text", "args": {"text": "abc"}},
        {"finish": "Lỗi: thiếu"},
    ], FakeShell())
    assert shell.calls == [] and out.startswith("Lỗi")


def test_shell_set_text_is_confirmed_like_any_other_input():
    shell = FakeShell({"shell_state": SHELL_STATE})
    _, _, shell, asked = _run_shell([
        {"tool": "shell_state", "args": {}},
        {"tool": "shell_set_text", "args": {"element_index": 0, "text": "calculator"}},
        {"finish": "xong"},
    ], shell)
    assert len(asked) == 1 and "calculator" in asked[0]
    assert shell.calls[-1] == ("shell_set_text", {"element_index": 0, "text": "calculator"})


class FakeEl:
    """Phần tử pywinauto giả: chỉ có những pattern được khai báo."""

    def __init__(self, ctype, name, auto_id="", patterns=("invoke",), log=None):
        self.element_info = type("I", (), {"control_type": ctype, "name": name, "automation_id": auto_id})()
        self._patterns, self.log = patterns, log if log is not None else []
        self.iface_value = type("V", (), {"SetValue": lambda s, t: self.log.append(("set", t))})() \
            if "value" in patterns else None

    def _do(self, how):
        if how not in self._patterns:
            raise RuntimeError(f"no {how} pattern")
        self.log.append((how, self.element_info.name))

    def invoke(self): self._do("invoke")
    def toggle(self): self._do("toggle")
    def select(self): self._do("select")


class FakeSurface:
    def __init__(self, els):
        self._els = els

    def descendants(self):
        return self._els


def _shell(els):
    return wc.ShellUia(surfaces=lambda: [FakeSurface(els)])


def test_shell_state_keeps_actionable_rows_and_filters_by_query():
    els = [FakeEl("Pane", ""), FakeEl("Button", "Start", "StartButton", ("toggle",)),
           FakeEl("Button", "Microsoft Edge - 1 running window"), FakeEl("Text", "clock text"),
           FakeEl("Edit", "Search box", "SearchTextBox", ("value",)), FakeEl("Button", "", "")]
    sh = _shell(els)
    r = asyncio.run(sh.call("shell_state", {}))
    assert [e["label"] for e in r["data"]["elements"]] == ["Start", "Microsoft Edge - 1 running window", "Search box"]
    assert r["data"]["total_element_count"] == 3
    r = asyncio.run(sh.call("shell_state", {"query": "EDGE"}))
    assert [e["label"] for e in r["data"]["elements"]] == ["Microsoft Edge - 1 running window"]
    assert r["data"]["total_element_count"] == 3 and r["data"]["elements"][0]["element_index"] == 1


def test_shell_click_tries_invoke_then_toggle_then_select_and_never_uses_the_mouse():
    log = []
    els = [FakeEl("Button", "Start", "StartButton", ("toggle",), log), FakeEl("ListItem", "Calculator", "", ("select",), log),
           FakeEl("Button", "Edge", "", ("invoke", "toggle"), log)]
    sh = _shell(els)
    asyncio.run(sh.call("shell_state", {}))
    for i in range(3):
        assert asyncio.run(sh.call("shell_click", {"element_index": i}))["is_error"] is False
    assert log == [("toggle", "Start"), ("select", "Calculator"), ("invoke", "Edge")]


def test_shell_click_reports_an_element_that_supports_no_background_action():
    sh = _shell([FakeEl("Button", "Odd", "", ())])
    asyncio.run(sh.call("shell_state", {}))
    r = asyncio.run(sh.call("shell_click", {"element_index": 0}))
    assert r["is_error"] and "Odd" in r["text"]


def test_shell_set_text_sets_the_value_pattern_and_refuses_non_fields():
    log = []
    sh = _shell([FakeEl("Edit", "Search box", "SearchTextBox", ("value",), log), FakeEl("Button", "Start", "", ("toggle",), log)])
    asyncio.run(sh.call("shell_state", {}))
    assert asyncio.run(sh.call("shell_set_text", {"element_index": 0, "text": "calculator"}))["is_error"] is False
    assert log == [("set", "calculator")]
    assert asyncio.run(sh.call("shell_set_text", {"element_index": 1, "text": "x"}))["is_error"] is True


def test_shell_actions_require_a_prior_shell_state_and_a_valid_index():
    sh = _shell([FakeEl("Button", "Start", "", ("toggle",))])
    r = asyncio.run(sh.call("shell_click", {"element_index": 0}))
    assert r["is_error"] and "shell_state" in r["text"]
    asyncio.run(sh.call("shell_state", {}))
    assert asyncio.run(sh.call("shell_click", {"element_index": 9}))["is_error"]


def test_a_refused_element_click_points_the_model_to_shell_click():
    seen = []
    script = iter([{"tool": "click", "args": {"pid": 0, "window_id": 0, "element_index": 5}}, {"finish": "Lỗi: x"}])

    async def ask(messages):
        seen.append(messages[-1]["content"])
        return json.dumps(next(script))

    asyncio.run(wc.run_cua_task("x", None, None, ask_llm=ask, confirm=None, session_factory=FakeCua, shell=FakeShell()))
    assert "shell_click" in seen[1]


def test_uri_launch_with_pid_0_lists_real_windows_for_the_model(monkeypatch):
    """jarvis.log 2026-10-12 05:26: launch_app ms-settings trả pid 0, model tìm cửa sổ pid 0 → bỏ cuộc."""
    monkeypatch.setenv("CUA_CONFIRM", "off")
    monkeypatch.setattr("engine.tools.desktop_control.cua_runner._URI_WINDOW_WAIT", 0)
    settings = {"is_error": False, "text": "", "data": {"windows": [
        {"pid": 77, "window_id": 88, "app_name": "SystemSettings.exe", "title": "Settings", "is_on_screen": True}]}}
    launched = {"is_error": False, "text": "✅ Launched ms-settings:windowsupdate (pid 0) in background.", "data": {}}
    seen = []

    async def ask(messages):
        seen.append(messages[-1]["content"])
        if len(seen) == 1:
            return json.dumps({"tool": "launch_app", "args": {"name": "ms-settings:windowsupdate"}})
        return json.dumps({"finish": "xong"})

    asyncio.run(wc.run_cua_task("cập nhật windows", None, None,
                                session_factory=lambda: FakeCua({"launch_app": launched, "list_windows": settings}),
                                ask_llm=ask, confirm=None))
    assert "pid=77 window_id=88" in seen[1] and "Settings" in seen[1]


@pytest.mark.parametrize("pid", [77, "77"])
def test_window_id_is_filled_from_listed_windows(monkeypatch, pid):
    """DB 2026-10-12 18:52: 'cập nhật windows update' dừng ở "thiếu tham số" — sau launch pid 0 code đã liệt kê
    cửa sổ, nhưng chỉ nhớ window_id sau get_window_state, nên get_window_state {pid} (thiếu window_id) bị từ chối."""
    monkeypatch.setenv("CUA_CONFIRM", "off")
    monkeypatch.setattr("engine.tools.desktop_control.cua_runner._URI_WINDOW_WAIT", 0)
    settings = {"is_error": False, "text": "", "data": {"windows": [
        {"pid": 77, "window_id": 88, "app_name": "SystemSettings.exe", "title": "Settings", "is_on_screen": True}]}}
    launched = {"is_error": False, "text": "✅ Launched ms-settings:windowsupdate (pid 0) in background.", "data": {}}
    cua = FakeCua({"launch_app": launched, "list_windows": settings, "get_window_state": STATE})
    out = asyncio.run(wc.run_cua_task("cập nhật windows", None, None, session_factory=lambda: cua, confirm=None,
                                      ask_llm=_say({"tool": "launch_app", "args": {"name": "ms-settings:windowsupdate"}},
                                                   {"tool": "get_window_state", "args": {"pid": pid}},
                                                   {"finish": "xong"})))
    assert out == "xong"
    assert ("get_window_state", {"pid": 77, "window_id": 88, "include_screenshot": False}) in cua.calls


@pytest.mark.parametrize("reply", [
    {"tool": "launch_app", "name": "notepad"},
    {"tool": "launch_app", "arguments": {"name": "notepad"}},
    {"tool": "launch_app", "parameters": {"name": "notepad"}},
])
def test_args_outside_the_args_key_are_accepted(monkeypatch, reply):
    """jarvis.log 2026-10-12 19:08: 12 bước 'launch_app {} -> Thiếu tham số: name' — tham số không nằm trong "args"."""
    monkeypatch.setenv("CUA_CONFIRM", "off")
    out, cua, _ = _run([reply, {"finish": "xong"}])
    assert out == "xong" and cua.calls == [("launch_app", {"name": "notepad"})]


def test_same_failed_action_twice_stops_the_run():
    """jarvis.log 2026-10-12 19:08: cùng lời gọi hỏng lặp đủ 12 bước rồi mới báo lỗi."""
    bad = {"tool": "get_window_state", "args": {}}
    out, cua, _ = _run([bad, bad, {"finish": "không tới đây"}])
    assert out.startswith("Lỗi:") and "Thiếu tham số" in out and cua.calls == []


def test_string_args_fill_the_single_required_param(monkeypatch):
    """jarvis.log 2026-10-12 19:12: model trả {"tool": "launch_app", "args": "ms-settings:windowsupdate"}."""
    monkeypatch.setenv("CUA_CONFIRM", "off")
    out, cua, _ = _run(['{"tool": "launch_app", "args": "notepad"}', {"finish": "xong"}])
    assert out == "xong" and cua.calls == [("launch_app", {"name": "notepad"})]


def _record_run(actions, results, monkeypatch, mode="off"):
    monkeypatch.setenv("CUA_CONFIRM", mode)
    monkeypatch.setattr("engine.tools.desktop_control.cua_runner._URI_WINDOW_WAIT", 0)
    cua = FakeCua(results)
    record = []
    out = asyncio.run(wc.run_cua_task("cập nhật windows", None, None, session_factory=lambda: cua,
                                      ask_llm=_say(*actions), confirm=None, record=record))
    return out, cua, record


SETTINGS_WIN = {"is_error": False, "text": "", "data": {"windows": [
    {"pid": 77, "window_id": 88, "app_name": "SystemSettings.exe", "title": "Settings", "is_on_screen": True}]}}
UPDATE_STATE = {"is_error": False, "text": "", "data": {"snapshot_id": "s1", "elements": [
    {"element_index": 25, "role": "Button", "label": "Check for updates", "actions": ["invoke"]}]}}


def test_record_saves_actions_by_label_not_index(monkeypatch):
    launched = {"is_error": False, "text": "✅ Launched ms-settings:windowsupdate (pid 0) in background.", "data": {}}
    out, cua, record = _record_run(
        [{"tool": "launch_app", "args": {"name": "ms-settings:windowsupdate"}},
         {"tool": "get_window_state", "args": {"pid": 77, "window_id": 88, "query": "Check"}},
         {"tool": "click", "args": {"pid": 77, "window_id": 88, "element_index": 25}},
         {"finish": "Đã bấm Check for updates."}],
        {"launch_app": launched, "list_windows": SETTINGS_WIN, "get_window_state": UPDATE_STATE}, monkeypatch)
    assert out == "Đã bấm Check for updates."
    assert record == [
        {"action": "launch_app", "name": "ms-settings:windowsupdate"},
        {"action": "click", "window": {"app": "SystemSettings.exe", "title": "Settings"},
         "target": {"role": "Button", "label": "Check for updates"}},
    ]


def test_record_marks_unknown_window(monkeypatch):
    out, cua, record = _record_run(
        [{"tool": "get_window_state", "args": {"pid": 5, "window_id": 6}},
         {"tool": "click", "args": {"pid": 5, "window_id": 6, "element_index": 3}},
         {"finish": "xong"}],
        {"get_window_state": STATE}, monkeypatch)
    assert record == [None]


REPLAY = [{"action": "launch_app", "name": "ms-settings:windowsupdate"},
          {"action": "click", "window": {"app": "SystemSettings.exe", "title": "Settings"},
           "target": {"role": "Button", "label": "Check for updates"}}]


def _replay_run(results, monkeypatch, actions=(), answers=(True, True, True), mode="each"):
    monkeypatch.setenv("CUA_CONFIRM", mode)
    monkeypatch.setattr("engine.tools.desktop_control.cua_runner._URI_WINDOW_WAIT", 0)
    cua, asked, record = FakeCua(results), [], []
    it = iter(answers)

    async def confirm(msg):
        asked.append(msg)
        return next(it, True)
    seen = []

    async def ask(messages):
        seen.append(messages[1]["content"])
        return json.dumps(actions[len(seen) - 1]) if len(seen) <= len(actions) else json.dumps({"finish": "model xong"})
    out = asyncio.run(wc.run_cua_task("cập nhật windows", None, None, session_factory=lambda: cua, ask_llm=ask,
                                      confirm=confirm, record=record, replay=REPLAY))
    return out, cua, asked, record, seen


def test_replay_runs_saved_steps_with_fresh_index_and_asks_each(monkeypatch):
    launched = {"is_error": False, "text": "✅ Launched (pid 0)", "data": {}}
    state = {"is_error": False, "text": "", "data": {"snapshot_id": "s9", "elements": [
        {"element_index": 31, "role": "Button", "label": "Check for updates"}]}}
    out, cua, asked, record, seen = _replay_run(
        {"launch_app": launched, "list_windows": SETTINGS_WIN, "get_window_state": state}, monkeypatch)
    assert out.startswith("Đã làm lại các bước đã lưu")
    assert ("click", {"pid": 77, "window_id": 88, "element_index": 31, "snapshot_id": "s9"}) in cua.calls
    assert len(asked) == 2 and seen == [] and record == REPLAY


def test_replay_matches_window_title_substring(monkeypatch):
    wins = {"is_error": False, "text": "", "data": {"windows": [
        {"pid": 9, "window_id": 10, "app_name": "SystemSettings.exe", "title": "Settings - Windows Update"}]}}
    state = {"is_error": False, "text": "", "data": {"snapshot_id": "s2", "elements": [
        {"element_index": 4, "role": "Button", "label": "Check for updates"}]}}
    out, cua, *_ = _replay_run({"list_windows": wins, "get_window_state": state}, monkeypatch, mode="off")
    assert ("click", {"pid": 9, "window_id": 10, "element_index": 4, "snapshot_id": "s2"}) in cua.calls


def test_replay_drift_hands_over_to_model(monkeypatch):
    state = {"is_error": False, "text": "", "data": {"snapshot_id": "s3", "elements": [
        {"element_index": 2, "role": "Button", "label": "Pause updates"}]}}
    out, cua, asked, record, seen = _replay_run(
        {"list_windows": SETTINGS_WIN, "get_window_state": state}, monkeypatch, mode="off")
    assert out == "model xong" and "dừng ở bước 2" in seen[0]
    assert record == [REPLAY[0]]
    assert not any(c[0] == "click" for c in cua.calls)


def test_replay_refusal_stops(monkeypatch):
    out, cua, asked, *_ = _replay_run({"list_windows": SETTINGS_WIN}, monkeypatch, answers=(False,))
    assert out == "Lỗi: đã dừng ở bước 1 vì bạn không xác nhận." and cua.calls == []


def test_replay_risky_label_asks_even_when_confirm_off(monkeypatch):
    risky = [{"action": "click", "window": {"app": "SystemSettings.exe", "title": "Settings"},
              "target": {"role": "Button", "label": "Uninstall"}}]
    state = {"is_error": False, "text": "", "data": {"snapshot_id": "s4", "elements": [
        {"element_index": 7, "role": "Button", "label": "Uninstall"}]}}
    monkeypatch.setenv("CUA_CONFIRM", "off")
    asked = []

    async def confirm(msg):
        asked.append(msg)
        return False
    out = asyncio.run(wc.run_cua_task("gỡ", None, None, session_factory=lambda: FakeCua(
        {"list_windows": SETTINGS_WIN, "get_window_state": state}), ask_llm=_say({"finish": "x"}),
        confirm=confirm, replay=risky))
    assert len(asked) == 1 and out.startswith("Lỗi: đã dừng ở bước 1")


def test_replay_keeps_preview_install_block(monkeypatch):
    # review 2026-10-13: get_window_state lọc theo query bỏ mất dòng "Preview Update" phía trên → nút không bị chặn
    def state(args):
        els = PREVIEW_PAGE["data"]["elements"]
        q = (args.get("query") or "").casefold()
        return {**PREVIEW_PAGE, "data": {**PREVIEW_PAGE["data"],
                                         "elements": [e for e in els if q in e["label"].casefold()]}}
    monkeypatch.setenv("CUA_CONFIRM", "off")
    cua = FakeCua({"list_windows": SETTINGS_WIN, "get_window_state": state})
    step = [{"action": "click", "window": {"app": "SystemSettings.exe", "title": "Settings"},
             "target": {"role": "Hyperlink", "label": "Download & install"}}]
    out = asyncio.run(wc.run_cua_task("cập nhật", None, None, session_factory=lambda: cua,
                                      ask_llm=_say({"finish": "x"}), confirm=None, replay=step))
    assert "Preview" in out and not any(c[0] == "click" for c in cua.calls)
