"""Trang Agents của giao diện liệt kê theo danh mục (catalog), không theo file .py: agent tra cứu dùng chung một runner."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.UIUX import ui_engine


def test_agents_page_lists_every_catalog_agent_with_its_tool():
    cards = {c["id"]: c for c in ui_engine._scan_agents()}
    assert "search" not in cards
    assert cards["weather"]["tools"] == ["weather_search"] and cards["weather"]["file"] == "agent_search.py"
    assert cards["shop"]["mention"] == "@shop" and cards["shop"]["example"] != "@shop"
    assert {"desktop", "email", "web"} <= set(cards)
