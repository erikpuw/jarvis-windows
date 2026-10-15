"""hhpanda không còn dùng trong media: không còn code phim/hhpanda, media chỉ còn YouTube + file local."""
import asyncio, re, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.tools import media_search as m


def test_no_hhpanda_in_python_sources():
    hits = []
    for p in [ROOT / "server.py", *(ROOT / "engine").rglob("*.py")]:
        if re.search(r"hhpanda\.st|search_phim|pw_scrape_episodes|media_select_", p.read_text(encoding="utf-8")):
            hits.append(p.name)
    assert not hits, hits
    assert not (ROOT / "engine" / "tools" / "media_play.py").exists()


def test_phim_query_falls_back_to_youtube(monkeypatch):
    async def fake_yt(query, max_results=4, verbatim=False):
        return [{"id": "abcdefghijk", "title": "T", "url": "u", "embed_url": "e", "source": "youtube"}]
    monkeypatch.setattr(m, "search_youtube", fake_yt)
    out = asyncio.run(m.execute_media_search({"query": "xem phim tiên nghịch tập 3"}))
    assert out["results"][0]["source"] == "youtube"
    assert "| Tên bài |" in out["text"] and out["episodes"] == []
