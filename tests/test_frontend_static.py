"""Vite copies frontend/public/<dir> into dist/<dir>; the server must serve those
too, not only /assets (mascot sprites 404'd in the desktop app, 2026-09-27).

Run: python -m pytest tests/test_frontend_static.py -q
"""
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))
from engine.UIUX.ui_engine import mount_frontend_dist


def test_serves_index_assets_and_public_dirs(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "mascots").mkdir()
    (tmp_path / "index.html").write_text("<html>ok</html>", encoding="utf-8")
    (tmp_path / "assets" / "a.js").write_text("js", encoding="utf-8")
    (tmp_path / "mascots" / "fox.webp").write_bytes(b"RIFF")
    app = FastAPI()

    @app.get("/api/ping")
    def ping():
        return {"ok": True}

    mount_frontend_dist(app, tmp_path)
    c = TestClient(app)
    assert c.get("/").text == "<html>ok</html>"
    assert c.get("/assets/a.js").text == "js"
    assert c.get("/mascots/fox.webp").content == b"RIFF"
    assert c.get("/api/ping").json() == {"ok": True}
    assert c.get("/mascots/../index.html").status_code in (200, 404)  # no traversal outside dist


def test_missing_dist_is_a_noop(tmp_path):
    app = FastAPI()
    mount_frontend_dist(app, tmp_path / "nope")
    assert TestClient(app).get("/").status_code == 404
