import sys
import uuid
from pathlib import Path
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.UIUX import ui_engine, memory_lock
from engine.core.memory import init_db

app = FastAPI()
app.include_router(ui_engine.router)
app.include_router(memory_lock.lock_router)
client = TestClient(app)


@pytest.fixture(autouse=True)
def _setup(monkeypatch):
    monkeypatch.setenv("USER_NAME", "erikpuw")
    monkeypatch.setenv("HONORIFIC", "sir")
    monkeypatch.setenv("CALENDAR_ACCOUNTS", "auto")
    init_db()
    memory_lock._tokens.clear()
    yield
    memory_lock._tokens.clear()


def test_user_preferences_isolation():
    u1 = f"user1_{uuid.uuid4().hex[:6]}"
    u2 = f"user2_{uuid.uuid4().hex[:6]}"

    # 1. Login as Member u1
    res1 = client.post("/api/auth/login", json={"username": u1})
    assert res1.status_code == 200
    token1 = res1.json()["token"]

    # 2. GET preferences as u1 -> should have u1's defaults (NOT erikpuw / sir from .env)
    res_pref1 = client.get("/api/settings/preferences", headers={"Authorization": f"Bearer {token1}"})
    assert res_pref1.status_code == 200
    data1 = res_pref1.json()
    assert data1["user_name"] == u1
    assert data1["honorific"] != "sir"  # Isolated from .env's 'sir'

    # 3. u1 updates their preferences
    res_update = client.post(
        "/api/settings/preferences",
        json={"user_name": f"{u1} Full", "honorific": "Chị", "calendar_accounts": "u1@gmail.com"},
        headers={"Authorization": f"Bearer {token1}"}
    )
    assert res_update.status_code == 200
    assert res_update.json()["success"] is True

    # 4. Verify u1's preferences were updated
    res_check = client.get("/api/settings/preferences", headers={"Authorization": f"Bearer {token1}"})
    assert res_check.json() == {
        "user_name": f"{u1} Full",
        "honorific": "Chị",
        "calendar_accounts": "u1@gmail.com"
    }

    # 5. Login as Member u2
    res2 = client.post("/api/auth/login", json={"username": u2})
    token2 = res2.json()["token"]

    # u2 must NOT see u1's preferences!
    res_pref2 = client.get("/api/settings/preferences", headers={"Authorization": f"Bearer {token2}"})
    data2 = res_pref2.json()
    assert data2["user_name"] == u2
    assert data2["honorific"] != "Chị"
    assert data2["calendar_accounts"] == ""
