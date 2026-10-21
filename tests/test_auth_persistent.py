"""Kiểm tra hệ thống xác thực người dùng bền vững (Persistent Auth) và phân quyền Role."""
import sys
from pathlib import Path
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.UIUX import ui_engine, memory_lock
from engine.core.memory import init_db

PASSWORD = "mat-khau-admin-test"
app = FastAPI()
app.include_router(ui_engine.router)
app.include_router(memory_lock.lock_router)
client = TestClient(app)


@pytest.fixture(autouse=True)
def _setup(monkeypatch):
    monkeypatch.setenv("MEMORY_PASSWORD", PASSWORD)
    init_db()
    memory_lock._tokens.clear()
    yield
    memory_lock._tokens.clear()


def test_auth_login_admin_wrong_password():
    res = client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
    assert res.status_code == 401
    assert "chính xác" in res.json().get("error", "")


def test_auth_login_admin_success():
    res = client.post("/api/auth/login", json={"username": "admin", "password": PASSWORD})
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["user"]["role"] == "admin"
    token = data["token"]

    # Kiểm tra me
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["user"]["role"] == "admin"

    # Admin được quyền sửa prompt
    p = client.post(
        "/api/prompts/save",
        json={"id": "jarvis", "content": "# admin edit"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert p.status_code == 200


def test_auth_login_member_and_permissions():
    # Login as member erik
    res = client.post("/api/auth/login", json={"username": "erik"})
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["user"]["role"] == "member"
    token = data["token"]

    # Đổi giọng riêng
    v = client.post(
        "/api/user/voice",
        json={"voice": "vi-VN-HoaiMyNeural"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert v.status_code == 200
    assert v.json()["voice"] == "vi-VN-HoaiMyNeural"

    # Member bị chặn 403 khi vào prompt hệ thống
    p = client.post(
        "/api/prompts/save",
        json={"id": "jarvis", "content": "# hacker edit"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert p.status_code == 403

    # Logout
    out = client.post("/api/auth/logout", headers={"Authorization": f"Bearer {token}"})
    assert out.status_code == 200

    # Sau khi logout, token hết hạn
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 401
