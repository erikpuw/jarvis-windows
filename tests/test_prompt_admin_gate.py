"""Kiểm tra rào chắn quyền Admin đối với Prompt hệ thống.
Chỉ có quyền Admin mới được phép đọc hoặc sửa Prompt hệ thống; non-admin nhận 403.
"""
import sys
from pathlib import Path
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.UIUX import ui_engine, memory_lock

PASSWORD = "mat-khau-admin-test"
app = FastAPI()
app.include_router(ui_engine.router)
app.include_router(memory_lock.lock_router)
client = TestClient(app)


@pytest.fixture(autouse=True)
def _setup_pass(monkeypatch):
    monkeypatch.setenv("MEMORY_PASSWORD", PASSWORD)
    memory_lock._tokens.clear()
    jarvis_prompt = Path(__file__).resolve().parents[1] / "prompt" / "jarvis.md"
    backup = jarvis_prompt.read_text(encoding="utf-8") if jarvis_prompt.exists() else None
    yield
    memory_lock._tokens.clear()
    if backup is not None:
        jarvis_prompt.write_text(backup, encoding="utf-8")


def test_prompts_save_forbidden_without_admin():
    res = client.post("/api/prompts/save", json={"id": "jarvis", "content": "test"})
    assert res.status_code == 403
    assert "Admin" in res.json().get("error", "")


def test_prompts_save_allowed_with_admin_token():
    # Unlock admin
    unlock = client.post("/api/memory-lock/unlock", json={"password": PASSWORD})
    token = unlock.json()["token"]
    res = client.post(
        "/api/prompts/save",
        json={"id": "jarvis", "content": "# Jarvis test"},
        headers={"X-Memory-Token": token},
    )
    # Thành công (hoặc ít nhất không bị chặn 403)
    assert res.status_code == 200
    assert res.json().get("success") is True


def test_catalog_prompts_hidden_without_admin():
    res = client.get("/api/settings/catalog")
    assert res.status_code == 200
    data = res.json()
    assert data["prompts"] == []


def test_catalog_prompts_visible_with_admin():
    unlock = client.post("/api/memory-lock/unlock", json={"password": PASSWORD})
    token = unlock.json()["token"]
    res = client.get("/api/settings/catalog", headers={"X-Memory-Token": token})
    assert res.status_code == 200
    data = res.json()
    assert len(data["prompts"]) > 0
