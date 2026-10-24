import pytest

from engine.turn import outcome as O


def _step(tool, args, outcome="success", **extra):
    return {"tool": tool, "args": args, "result": "ok", "outcome": outcome, **extra}


def test_status_of():
    assert O.status_of([_step("weather", {}), _step("weather", {})]) == "success"
    assert O.status_of([_step("weather", {}, "failed")]) == "failed"
    assert O.status_of([_step("weather", {}), _step("weather", {}, "no_result")]) == "partial"


@pytest.mark.parametrize("workflow", [True, False])
def test_save_turn_records_outcome_without_learning(monkeypatch, workflow):
    calls = {}

    class LE:
        def record_outcome(self, *args):
            calls["outcome"] = args

        def save_workflow(self, *args):
            pytest.fail("Tự học workflow đang tạm dừng")

    monkeypatch.setattr("engine.core.learning.get_learning_engine", lambda: LE())
    O.save_turn("Thời tiết Huế", [_step("weather", {"location": "huế"})], "Huế 28 độ.",
                replay_id=7, workflow=workflow)
    assert calls["outcome"] == ("weather", "Thời tiết Huế", "success", "Huế 28 độ.", [
        {"tool": "weather", "args": {"location": "huế"}, "outcome": "success", "result": "ok", "replay": 7}])


def test_save_turn_preserves_cua_steps_and_result_limit(monkeypatch):
    calls = []

    class LE:
        def record_outcome(self, *args):
            calls.append(args)

    monkeypatch.setattr("engine.core.learning.get_learning_engine", lambda: LE())
    cua = [{"action": "launch_app", "name": "notepad"}]
    O.save_turn("x", [_step("desktop", {}, "failed", cua_steps=cua)], "x" * 600)
    assert calls[0][2] == "failed"
    assert calls[0][3] == "x" * 500
    assert calls[0][4][0]["cua_steps"] == cua
    O.save_turn("chat", [], "ok")
    assert len(calls) == 1
