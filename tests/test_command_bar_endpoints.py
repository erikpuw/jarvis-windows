import pytest
from starlette.requests import Request
from fastapi import FastAPI
from fastapi.testclient import TestClient
from engine.UIUX.ui_engine import router, api_command_bar_context, api_command_bar_skills


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


@pytest.mark.asyncio
async def test_api_command_bar_direct_call_no_args():
    req = Request({"type": "http", "headers": []})
    res_ctx = await api_command_bar_context(req)
    assert res_ctx["success"] is True
    assert "mentions" in res_ctx
    assert "files" in res_ctx

    res_skills = await api_command_bar_skills()
    assert res_skills["success"] is True
    assert "commands" in res_skills
    assert "skills" in res_skills


@pytest.mark.asyncio
async def test_api_command_bar_with_mock_request():
    scope = {
        "type": "http",
        "headers": [],
    }
    req = Request(scope)
    res_ctx = await api_command_bar_context(request=req)
    assert res_ctx["success"] is True
    assert isinstance(res_ctx["mentions"], list)
    assert isinstance(res_ctx["files"], list)

    res_skills = await api_command_bar_skills()
    assert res_skills["success"] is True
    assert isinstance(res_skills["commands"], list)


def test_api_command_bar_http_endpoints(client):
    res = client.get("/api/command-bar/context")
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True

    res2 = client.get("/api/command-bar/skills")
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["success"] is True
