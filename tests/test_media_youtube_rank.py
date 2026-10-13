"""Câu nói tự nhiên không được làm lệch video được phát (log 2026-09-25 15:23).
"tôi muốn nghe nhạc making my way của sơn tùng mtp" từng phát "Toàn Bộ Drama MV Come My Way Của Sơn Tùng MTP"
vì các từ đệm "tôi muốn … của" được chấm điểm như từ khoá."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.tools import media_search as m

RESULTS = [  # thứ tự yt-dlp trả về thật cho truy vấn trên
    ("hdUw9fxX41c", "Toàn Bộ Drama MV Come My Way Của Sơn Tùng MTP Trong 16 Phút", "Đầu Xanh Mỏ Hỗn"),
    ("niPkap1ozUA", "SON TUNG M-TP | MAKING MY WAY | OFFICIAL VISUALIZER", "Sơn Tùng M-TP Official"),
    ("SlQR9iu09bQ", "SON TUNG M-TP x TYGA | COME MY WAY | OFFICIAL MUSIC VIDEO", "Sơn Tùng M-TP Official and Tyga"),
    ("JHSRTU31T14", "SƠN TÙNG M-TP | THERE'S NO ONE AT ALL (ANOTHER VERSION) | OFFICIAL MUS", "Sơn Tùng M-TP Official"),
]


def _fake_search(query, max_results=12):
    return [{"id": i, "title": t, "channel": c, "duration": 240, "source": "youtube",
             "embed_url": f"https://www.youtube.com/embed/{i}"} for i, t, c in RESULTS]


def test_natural_sentence_plays_the_requested_song(monkeypatch):
    monkeypatch.setattr(m, "_yt_search", _fake_search)
    q = m._strip_noise("tôi muốn nghe nhạc making my way của sơn tùng mtp")
    top = asyncio.run(m.search_youtube(q))[0]
    assert top["id"] == "niPkap1ozUA", top["title"]


def test_request_words_removed_only_for_youtube_ranking():
    assert m._strip_request_words("tôi muốn   making my way của sơn tùng mtp").split() == \
        ["making", "my", "way", "sơn", "tùng", "mtp"]
    assert m._strip_request_words("chúng ta của hiện tại") == "chúng ta hiện tại"


