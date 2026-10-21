"""Số phiên bản có một nguồn duy nhất: file VERSION ở gốc repo."""
import asyncio
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_version_file_is_semver():
    assert re.fullmatch(r"\d+\.\d+\.\d+", (ROOT / "VERSION").read_text(encoding="utf-8").strip())


def test_health_reports_version_file():
    from engine.UIUX.ui_engine import health
    assert asyncio.run(health())["version"] == (ROOT / "VERSION").read_text(encoding="utf-8").strip()


def test_readme_links_version_file_instead_of_hardcoding():
    head = (ROOT / "README.md").read_text(encoding="utf-8").splitlines()[:10]
    assert any("(VERSION)" in line for line in head)
    assert not any(line.startswith("**Version ") for line in head)


def test_env_has_no_version_copy():
    env = ROOT / ".env"
    assert not env.exists() or "JARVIS_VERSION" not in env.read_text(encoding="utf-8")


def test_dashboard_version_comes_from_version_file():
    # frontend/vite.config.ts injects __APP_VERSION__; it must read VERSION, not .env
    cfg = (ROOT / "frontend" / "vite.config.ts").read_text(encoding="utf-8")
    assert "VERSION" in cfg and "JARVIS_VERSION" not in cfg
