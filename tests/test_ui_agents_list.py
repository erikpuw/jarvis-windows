"""Trang Mention của giao diện liệt kê đúng những gì lệnh @ trong command-bar chấp nhận."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.UIUX import ui_engine
from engine.tools import registry


def test_mention_page_lists_what_at_accepts():
    cards = ui_engine._scan_mentions()
    ids = [c["id"] for c in cards]
    # engine/turn/entry: @rag, then any registry tool (chat or not) via tool_mention
    assert ids == ["rag"] + list(registry.names())
    by_id = {c["id"]: c for c in cards}
    assert by_id["weather"]["mention"] == "@weather"
    assert by_id["weather"]["example"].startswith("@weather")
    assert "dream" in by_id  # chat=False tools still answer to @dream


def test_commands_page_lists_what_slash_accepts():
    cmds = ui_engine._scan_catalog_files()["commands"]
    names = [c["name"] for c in cmds]
    # engine/server/slash_commands: /help, then any registry tool
    assert names == ["help"] + sorted(registry.names())
    assert all(c["usage"].startswith("/") for c in cmds)
