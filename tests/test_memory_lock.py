"""Khóa Memory Control bằng mật khẩu (docs/superpowers/specs/2026-10-04-memory-lock-design.md).

Mọi endpoint dữ liệu Memory phải trả 401 `locked` nếu thiếu token đúng; token chỉ có sau khi nhập đúng MEMORY_PASSWORD (trong .env).
Mật khẩu không có endpoint đặt/đổi. Chưa cấu hình thì khóa hẳn. Chạy qua FastAPI TestClient trong tiến trình, không mở server thật.

Run: python -m pytest tests/test_memory_lock.py
"""
import sys
import tempfile
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))

import engine.core.evolution as evolution
from engine.UIUX import ui_engine

PASSWORD = "mat-khau-thu-nghiem"
PREFIXES = ("/api/learnings", "/api/workflows", "/api/outcomes", "/api/conversations", "/api/notes", "/api/evolution", "/api/memory-control", "/api/history", "/api/logs")

app = FastAPI()
app.include_router(ui_engine.router)
client = TestClient(app)


@pytest.fixture(autouse=True)
def _password(monkeypatch):
    monkeypatch.setenv("MEMORY_PASSWORD", PASSWORD)
    from engine.UIUX import memory_lock
    memory_lock._tokens.clear()
    yield
    memory_lock._tokens.clear()


@pytest.fixture
def evo_files():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        style = root / "STYLE.md"
        style.write_text("# Luật\n- Xưng hô thân mật.\n", encoding="utf-8")
        old = (evolution.STYLE_FILE, evolution.EVOLUTION_LOG)
        evolution.STYLE_FILE, evolution.EVOLUTION_LOG = style, root / "Evolution.md"
        yield
        evolution.STYLE_FILE, evolution.EVOLUTION_LOG = old


def _unlock(pw=PASSWORD):
    return client.post("/api/memory-lock/unlock", json={"password": pw})


def _memory_routes():
    out = []
    for r in ui_engine.router.routes:
        path = getattr(r, "path", "")
        if path.startswith(PREFIXES):
            for m in r.methods - {"HEAD", "OPTIONS"}:
                out.append((m, path.replace("{session_id}", "x")))
    return out


def test_there_are_memory_routes_to_protect():
    assert len(_memory_routes()) >= 20


def test_every_memory_route_is_locked_without_a_token():
    for method, path in _memory_routes():
        res = client.request(method, path, json={})
        assert res.status_code == 401 and res.json() == {"detail": "locked"}, (method, path, res.status_code, res.text[:80])


def test_every_memory_route_is_locked_with_a_wrong_token():
    for method, path in _memory_routes():
        res = client.request(method, path, json={}, headers={"X-Memory-Token": "token-gia"})
        assert res.status_code == 401, (method, path, res.status_code)


def test_wrong_password_is_rejected_and_gives_no_token():
    res = _unlock("sai")
    assert res.status_code == 401
    assert res.json().get("code") == "wrong_password" and "token" not in res.json()


def test_no_limit_on_wrong_attempts():
    for _ in range(12):
        assert _unlock("sai").status_code == 401
    assert _unlock().status_code == 200


def test_right_password_opens_memory(evo_files):
    token = _unlock().json()["token"]
    res = client.get("/api/evolution/list", headers={"X-Memory-Token": token})
    assert res.status_code == 200 and res.json()["success"] is True


def test_each_unlock_gets_its_own_token_and_old_ones_stay_valid(evo_files):
    a, b = _unlock().json()["token"], _unlock().json()["token"]
    assert a != b
    for t in (a, b):
        assert client.get("/api/evolution/list", headers={"X-Memory-Token": t}).status_code == 200


def test_lock_revokes_the_token(evo_files):
    token = _unlock().json()["token"]
    assert client.post("/api/memory-lock/lock", headers={"X-Memory-Token": token}).json()["success"] is True
    assert client.get("/api/evolution/list", headers={"X-Memory-Token": token}).status_code == 401


def test_not_configured_means_locked_for_everyone(monkeypatch):
    monkeypatch.delenv("MEMORY_PASSWORD", raising=False)
    assert client.get("/api/memory-lock/status").json() == {"configured": False}
    res = _unlock("")
    assert res.status_code == 403 and res.json()["code"] == "not_configured"
    assert _unlock("bat-ky").status_code == 403
    assert client.get("/api/evolution/list", headers={"X-Memory-Token": ""}).status_code == 401


def test_blank_password_in_env_counts_as_not_configured(monkeypatch):
    monkeypatch.setenv("MEMORY_PASSWORD", "   ")
    assert client.get("/api/memory-lock/status").json() == {"configured": False}


def test_status_never_leaks_the_password():
    res = client.get("/api/memory-lock/status")
    assert res.status_code == 200 and res.json() == {"configured": True} and PASSWORD not in res.text


def test_no_endpoint_can_set_or_change_the_password():
    for tail in ("setup", "change", "password", "set", "reset", "update"):
        for method in ("POST", "PUT", "PATCH", "GET"):
            res = client.request(method, f"/api/memory-lock/{tail}", json={"password": "moi", "old": PASSWORD})
            assert res.status_code in (404, 405), (method, tail, res.status_code)
    assert _unlock("moi").status_code == 401 and _unlock().status_code == 200
