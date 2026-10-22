"""Jev phải tự hồi phục trên CPU: scorer chết/treo, service 8083 lỗi, server khởi động lỗi.

Không nạp model thật: jev-score được giả bằng một tiến trình Python nhỏ.
"""
import subprocess
import sys
import time
from unittest.mock import MagicMock

import httpx
import pytest

from engine.turn import jev_gate as gate
from engine.turn.jev import jev_style_decision_gguf as runtime
from engine.turn.jev import server

READY = 'import sys,json; print(json.dumps({"ready": True}), flush=True); '


def fake_scorer(monkeypatch, script, **kwargs):
    real_popen = subprocess.Popen
    # chỉ kiểm tra I/O với tiến trình: bỏ nạp tokenizer (CI không cài `tokenizers`)
    monkeypatch.setattr(runtime.JevStyleDecisionGGUF, "_setup", lambda self, *args, **kw: None)
    monkeypatch.setattr(runtime.subprocess, "Popen",
                        lambda cmd, **kw: real_popen([sys.executable, "-c", READY + script], **kw))
    return runtime.JevStyleDecisionGGUF(model_dir=str(gate.DEFAULT_MODEL_DIR), gguf="fake.gguf",
                                        binary=sys.executable, **kwargs)


def engine_mock(alive=True):
    eng = MagicMock()
    eng.is_alive.return_value = alive
    eng.decide.return_value = {"answer": "chat", "top_probability": 0.97}
    return eng


@pytest.fixture(autouse=True)
def clean_state(monkeypatch, tmp_path):
    gate.close()
    monkeypatch.setattr(gate, "_ENGINE", None)
    monkeypatch.setattr(gate, "_REMOTE_AVAILABLE", None)
    monkeypatch.setattr(gate, "_REMOTE_REACHABLE", False, raising=False)
    monkeypatch.setattr(gate, "_LAST_REMOTE_CHECK", 0.0)
    monkeypatch.setattr(gate, "_LAST_LOCAL_FAILURE", float("-inf"), raising=False)
    monkeypatch.setattr(gate, "find_jev_binary", lambda use_cpu=False: tmp_path)
    monkeypatch.setattr(gate, "find_jev_gguf", lambda: tmp_path)
    monkeypatch.setattr(server, "_ENGINE", None)
    monkeypatch.setattr(server, "_LAST_INIT_FAILURE", float("-inf"), raising=False)
    monkeypatch.setattr(server, "find_jev_binary", lambda use_cpu=False: tmp_path)
    monkeypatch.setattr(server, "find_jev_gguf", lambda: tmp_path)
    yield
    monkeypatch.setattr(gate, "_ENGINE", None)


def remote(monkeypatch, handler):
    """Service 8083 giả; nạp model local trong JARVIS là lỗi."""
    real_client = httpx.Client
    monkeypatch.setattr(gate.httpx, "Client",
                        lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
    local = MagicMock(side_effect=AssertionError("không được nạp model thứ hai"))
    monkeypatch.setattr(gate, "JevStyleDecisionGGUF", local)
    return local


# --- lỗi 1: scorer chết thì gate phải nạp lại --------------------------------------------------
def test_dead_local_engine_is_replaced(monkeypatch):
    dead, fresh = engine_mock(alive=False), engine_mock()
    monkeypatch.setattr(gate, "_ENGINE", dead)
    monkeypatch.setattr(gate, "JevStyleDecisionGGUF", MagicMock(return_value=fresh))
    gate._REMOTE_AVAILABLE, gate._LAST_REMOTE_CHECK = False, time.monotonic()
    assert gate.classify_chat("Xin chào") == (True, 0.97)
    assert gate._ENGINE is fresh
    dead.close.assert_called_once()


def test_failed_start_backs_off(monkeypatch):
    ctor = MagicMock(side_effect=RuntimeError("không khởi động được"))
    monkeypatch.setattr(gate, "JevStyleDecisionGGUF", ctor)
    assert gate._get_engine() is None
    assert gate._get_engine() is None
    assert ctor.call_count == 1


# --- lỗi 2: scorer treo không được treo lượt chat ---------------------------------------------
def test_hung_scorer_times_out_and_is_killed(monkeypatch):
    eng = fake_scorer(monkeypatch, "import time; time.sleep(30)", request_timeout=0.5)
    try:
        t0 = time.monotonic()
        with pytest.raises(TimeoutError):
            eng._request({"cmd": "score"})
        assert time.monotonic() - t0 < 5
        assert not eng.is_alive()
    finally:
        eng.close()


def test_slow_cpu_scorer_within_timeout_is_answered(monkeypatch):
    eng = fake_scorer(monkeypatch, "import time; sys.stdin.readline(); time.sleep(1.2); "
                                   "print(json.dumps({'ok': 1}), flush=True); sys.stdin.readline()")
    try:
        assert eng._request({"cmd": "score"}) == {"ok": 1}
        assert eng.is_alive()
    finally:
        eng.close()


# --- lỗi 3: service 8083 có mặt nhưng lỗi -> router thường, không nạp model thứ hai -----------
@pytest.mark.parametrize("health", [
    httpx.Response(503, json={"status": "error"}),
    httpx.Response(200, json={"status": "error"}),
])
def test_unhealthy_remote_does_not_load_local(monkeypatch, health):
    local = remote(monkeypatch, lambda req: health)
    assert gate.classify_chat("Xin chào") == (False, 0.0)
    local.assert_not_called()


def test_busy_remote_does_not_load_local(monkeypatch):
    def slow(req):
        raise httpx.ReadTimeout("busy", request=req)
    local = remote(monkeypatch, slow)
    assert gate.classify_chat("Xin chào") == (False, 0.0)
    local.assert_not_called()


def test_remote_classify_error_does_not_load_local(monkeypatch):
    def handler(req):
        if req.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        return httpx.Response(503, json={"detail": "busy"})
    local = remote(monkeypatch, handler)
    assert gate.classify_chat("Xin chào") == (False, 0.0)
    local.assert_not_called()


@pytest.mark.parametrize("error", [httpx.ConnectError, httpx.ConnectTimeout])
def test_absent_remote_falls_back_to_local(monkeypatch, error):
    # Windows: cổng localhost không ai nghe thường hết giờ kết nối thay vì bị từ chối ngay
    def refuse(req):
        raise error("no listener", request=req)
    real_client = httpx.Client
    monkeypatch.setattr(gate.httpx, "Client",
                        lambda **kw: real_client(transport=httpx.MockTransport(refuse), **kw))
    monkeypatch.setattr(gate, "JevStyleDecisionGGUF", MagicMock(return_value=engine_mock()))
    assert gate.classify_chat("Xin chào") == (True, 0.97)


def test_remote_recovers_after_recheck(monkeypatch):
    state = {"ok": False}

    def handler(req):
        if req.url.path == "/health":
            return httpx.Response(200, json={"status": "ok" if state["ok"] else "error"})
        return httpx.Response(200, json={"is_chat": True, "confidence": 0.95, "answer": "chat"})
    remote(monkeypatch, handler)
    assert gate.classify_chat("Xin chào") == (False, 0.0)
    state["ok"] = True
    gate._LAST_REMOTE_CHECK = 0.0  # hết 5 giây chờ
    assert gate.classify_chat("Xin chào") == (True, 0.95)


# --- lỗi 4: run_jev.py phải báo đúng tình trạng và tự nạp lại ---------------------------------
def test_health_reports_dead_engine_and_restarts_it(monkeypatch):
    dead, fresh = engine_mock(alive=False), engine_mock()
    monkeypatch.setattr(server, "_ENGINE", dead)
    monkeypatch.setattr(server, "JevStyleDecisionGGUF", MagicMock(return_value=fresh))
    assert server.health()["status"] == "ok"
    assert server._ENGINE is fresh
    dead.close.assert_called_once()


def test_health_error_when_start_fails_then_backs_off(monkeypatch):
    ctor = MagicMock(side_effect=RuntimeError("lỗi nạp"))
    monkeypatch.setattr(server, "JevStyleDecisionGGUF", ctor)
    assert server.health()["status"] == "error"
    assert server.health()["status"] == "error"
    assert ctor.call_count == 1
