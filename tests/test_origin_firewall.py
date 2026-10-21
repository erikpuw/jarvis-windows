"""Origin check chống CSRF / Cross-Site WebSocket Hijacking (engine/security/firewall.py)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.security.firewall import is_request_origin_allowed


def _ok(origin, host="127.0.0.1:8340"):
    headers = {"host": host}
    if origin is not None:
        headers["origin"] = origin
    return is_request_origin_allowed(headers)


def test_default_rules(monkeypatch):
    monkeypatch.setenv("JARVIS_CORS_ORIGINS", "*")  # '*' bị bỏ qua → danh sách mặc định
    assert _ok(None)                                   # Telegram/httpx/curl
    assert _ok("http://localhost:5173")
    assert _ok("https://10.0.0.5:8340", host="10.0.0.5:8340")  # cùng origin
    assert not _ok("https://evil.com")
    assert not _ok("null")
    assert not _ok("http://100.64.1.2:5173")


def test_adding_tailscale_origin_keeps_localhost(monkeypatch):
    """README bảo đặt JARVIS_CORS_ORIGINS=http://<IP-Tailscale>:5173 — UI trên chính PC không được bị khoá."""
    monkeypatch.setenv("JARVIS_CORS_ORIGINS", "http://100.64.1.2:5173")
    assert _ok("http://100.64.1.2:5173")
    assert _ok("http://localhost:5173")
    assert not _ok("https://evil.com")
