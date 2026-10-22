"""Unit tests cho Jev-Style Standalone Server và Jev Gate."""

from unittest.mock import MagicMock, patch

import pytest
from starlette.testclient import TestClient

from engine.turn import jev_gate
from engine.turn.jev import server as jev_server


@pytest.fixture(autouse=True)
def reset_gate():
    jev_gate.close()
    yield
    jev_gate.close()


def test_jev_gate_availability_mocked():
    with patch("engine.turn.jev_gate._check_remote_server", return_value=True):
        assert jev_gate.is_available() is True

    with patch("engine.turn.jev_gate._check_remote_server", return_value=False), \
         patch("pathlib.Path.exists", return_value=True):
        assert jev_gate.is_available() is True


def test_jev_gate_remote_classify_success():
    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = {
        "is_chat": True,
        "confidence": 0.96,
        "answer": "chat",
        "dt_ms": 28.5
    }

    with patch("engine.turn.jev_gate._check_remote_server", return_value=True), \
         patch("httpx.Client.post", return_value=fake_resp):
        is_chat, conf = jev_gate.classify_chat("xin chào bạn")
        assert is_chat is True
        assert conf == 0.96


def test_jev_gate_remote_classify_fallback_local():
    """Khi remote server trả lỗi/offline, tự động fallback sang local engine."""
    mock_local_engine = MagicMock()
    mock_local_engine.decide.return_value = {
        "answer": "tool",
        "top_probability": 0.91,
        "probabilities": {"chat": 0.09, "tool": 0.91}
    }

    with patch("engine.turn.jev_gate._check_remote_server", return_value=False), \
         patch("engine.turn.jev_gate._get_engine", return_value=mock_local_engine):
        is_chat, conf = jev_gate.classify_chat("giá vàng hôm nay")
        assert is_chat is False
        assert conf == 0.91
        mock_local_engine.decide.assert_called_once()


def test_jev_server_api_endpoints():
    """Kiểm tra các endpoint REST API của standalone server."""
    mock_engine = MagicMock()
    mock_engine.decide.return_value = {
        "answer": "chat",
        "top_probability": 0.95,
        "probabilities": {"chat": 0.95, "tool": 0.05}
    }

    with patch("engine.turn.jev.server._ENGINE", mock_engine), \
         patch("engine.turn.jev.server._DEVICE", "CPU"):
        client = TestClient(jev_server.app)

        # GET /health
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["device"] == "CPU"

        # POST /classify
        resp = client.post("/classify", json={"text": "chào bạn nhé", "min_confidence": 0.85})
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_chat"] is True
        assert data["confidence"] == 0.95
        assert data["answer"] == "chat"
        assert "dt_ms" in data

        # POST /decide
        resp = client.post("/decide", json={
            "state": "Người dùng: test",
            "question": "test question",
            "options": {"a": "opt a", "b": "opt b"}
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "result" in data
