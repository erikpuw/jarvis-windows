import asyncio

from engine.tools import registry as R


def _run(name, args, ctx=None):
    return asyncio.run(R.run(name, args, ctx))


def _quiet(monkeypatch):
    monkeypatch.setattr("engine.core.trace_logger.TraceLogger.log_trace", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr("engine.core.guardrails.verify_output", lambda n, a: (True, ""))


def test_open_close_app_use_model_args(monkeypatch):
    _quiet(monkeypatch)
    seen = []

    async def fake_open(name):
        seen.append(("open", name)); return True

    async def fake_close(name):
        seen.append(("close", name)); return False
    monkeypatch.setattr("engine.tools.desktop_automation.open_application", fake_open)
    monkeypatch.setattr("engine.tools.desktop_automation.close_application", fake_close)
    assert _run("open_app", {"app_name": "task manager"}).outcome == "success"
    assert _run("close_app", {"app_name": "word"}).outcome == "failed"   # "...: Thất bại"
    assert seen == [("open", "task manager"), ("close", "word")]


def test_capture_screen_without_ws_says_cannot(monkeypatch):
    _quiet(monkeypatch)

    async def fake_shot(path):
        return True
    monkeypatch.setattr("engine.tools.screen.take_screenshot_file", fake_shot)
    res = _run("capture_screen", {}, R.ToolContext())
    assert "không thể" in res.text.lower()


def test_play_media_passes_query_and_source(monkeypatch):
    _quiet(monkeypatch)
    got = {}

    async def fake_media(arguments, ws=None, safe_ws_send_json=None):
        got.update(arguments); return "Đang phát"
    monkeypatch.setattr("engine.tools.media_search.execute_media_search", fake_media)
    _run("play_media", {"query": "see tình"}, R.ToolContext(user_text="mở bài see tình"))
    assert got["query"] == "see tình" and got["source"] == "youtube"


def test_change_tools_kind():
    for name in ("open_app", "close_app", "win_control", "capture_screen", "play_media"):
        assert R.kind(name) == "change"


def test_system_status_report_is_displayed_in_full():
    """DB outcome #28 (2026-10-14): model tóm tắt báo cáo, bỏ tên tiến trình, giờ bật máy, pin → hiện nguyên bảng."""
    assert R.display("system_status") is True
