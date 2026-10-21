import pytest

from engine.tools import registry as R
from engine.turn import outcome as O


@pytest.fixture(autouse=True)
def tools():
    R._reset_for_test()

    async def gym(action: str, measured_on: str = "", weight_kg: float = 0, days: int = 7) -> str:
        return ""

    async def weather(location: str) -> str:
        return ""
    R._register_for_test(gym, doc="Gym.\n\naction: việc\nmeasured_on: ngày\nweight_kg: kg\ndays: số ngày\n")
    R._register_for_test(weather, doc="Thời tiết.\n\nlocation: nơi\n")
    R.get("gym").parameters["properties"]["action"]["enum"] = ["record_bodyweight", "stats"]
    yield
    R._reset_for_test()


def _step(tool, args, outcome="success", **extra):
    return {"say": f"Tôi chạy {tool}.", "tool": tool, "args": args, "result": "ok", "outcome": outcome, **extra}


def test_status_of():
    assert O.status_of([_step("weather", {}), _step("weather", {})]) == "success"
    assert O.status_of([_step("weather", {}, "failed")]) == "failed"
    assert O.status_of([_step("weather", {}), _step("weather", {}, "no_result")]) == "partial"


def test_from_user_accepts_user_words_and_enums():
    assert O.from_user("weather", {"location": "Hà Nội"}, "thời tiết hà nội hôm nay")
    assert O.from_user("gym", {"action": "record_bodyweight", "weight_kg": 70.0}, "hôm nay tôi nặng 70kg")


def test_from_user_rejects_inferred_values():
    assert not O.from_user("gym", {"action": "record_bodyweight", "measured_on": "2026-10-12", "weight_kg": 70},
                           "hôm nay tôi nặng 70kg")
    assert not O.from_user("gym", {"action": "stats", "days": 14}, "thống kê 2 tuần")


def test_save_turn_records_outcome_and_workflow(monkeypatch):
    calls = {}

    class _LE:
        def record_outcome(self, *a):
            calls["outcome"] = a

        def save_workflow(self, *a):
            calls["workflow"] = a
    monkeypatch.setattr("engine.core.learning.get_learning_engine", lambda: _LE())
    steps = [_step("weather", {"location": "huế"}, cua_steps=None)]
    O.save_turn("Thời tiết Huế", steps, "Huế 28 độ, thưa ngài.", replay_id=7)
    tools, query, status, result, traces = calls["outcome"]
    assert (tools, query, status) == ("weather", "Thời tiết Huế", "success")
    assert traces == [{"tool": "weather", "args": {"location": "huế"}, "outcome": "success", "result": "ok",
                       "replay": 7}]
    q, chain, evidence = calls["workflow"]
    assert chain == [{"tool": "weather", "args": {"location": "huế"}, "say": "Tôi chạy weather."}]


def test_save_turn_keeps_cua_steps_and_skips_workflow_when_not_eligible(monkeypatch):
    calls = {}

    class _LE:
        def record_outcome(self, *a):
            calls["outcome"] = a

        def save_workflow(self, *a):
            calls["workflow"] = a
    monkeypatch.setattr("engine.core.learning.get_learning_engine", lambda: _LE())
    cua = [{"action": "launch_app", "name": "notepad"}]
    O.save_turn("x", [_step("weather", {"location": "huế"}, "failed", cua_steps=cua)], "lỗi")
    assert calls["outcome"][4][0]["cua_steps"] == cua and "workflow" not in calls
    O.save_turn("thời tiết huế", [_step("weather", {"location": "huế"})], "ok", workflow=False)
    assert "workflow" not in calls
