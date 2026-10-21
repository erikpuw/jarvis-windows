"""Tin tức (ngài 2026-10-18): mỗi tin mang sapo thật của bài (og:description), không phải đoạn chữ cào từ trang."""
import asyncio
from types import SimpleNamespace

from scrapling.parser import Selector

from engine.tools import search_engine as S
from engine.tools.browser import JarvisScraplingBrowser as B, PageContent
from engine.turn.loop import RESULT_CHARS


def _page(head: str) -> Selector:
    return Selector(f"<html><head>{head}</head><body><p>menu</p></body></html>")


def test_description_prefers_og_then_meta_then_twitter():
    assert B._extract_description(_page(
        '<meta property="og:description" content=" Sapo OG "><meta name="description" content="meta">')) == "Sapo OG"
    assert B._extract_description(_page('<meta name="description" content="Sapo meta">')) == "Sapo meta"
    assert B._extract_description(_page('<meta name="twitter:description" content="Sapo tw">')) == "Sapo tw"
    assert B._extract_description(_page("")) == ""


def _run_news(monkeypatch, pages):
    urls = [f"https://vnexpress.net/bai-{i}.html" for i in range(len(pages))]

    async def fake_search(q, vietnam_only=True):
        return [SimpleNamespace(url=u, title=f"t{i}", snippet="s", source_host="vnexpress.net") for i, u in enumerate(urls)]

    async def fake_visit(url, timeout_ms=0):
        return pages[int(url[-6])]
    monkeypatch.setattr(S.browser, "search_news", fake_search)
    monkeypatch.setattr(S.browser, "visit_article", fake_visit)
    monkeypatch.setattr(S, "is_vietnam_news_url", lambda u, host_override="": True)
    monkeypatch.setattr(S, "is_news_article_url", lambda u, host_override="": True)
    monkeypatch.setattr(S, "_is_valid_news_content", lambda c: True)
    S._SEARCH_TTL_CACHE.clear()
    return asyncio.run(S.handle_news_search("tin nóng"))["display"]


def test_each_article_carries_its_sapo_whole(monkeypatch):
    sapo = "Ngân hàng Nhà nước giữ nguyên lãi suất điều hành trong tháng 10, " * 3
    pages = [PageContent(title=f"Bài {i}", url=f"https://vnexpress.net/bai-{i}.html", text_content=f"thân {i} " * 1000,
                         word_count=2000, description=sapo.strip()) for i in range(5)]
    display = _run_news(monkeypatch, pages)
    assert len(display) <= RESULT_CHARS
    assert display.count(f"📝 Sapo: {sapo.strip()}") == 5        # sapo không bị cắt
    assert all(f"thân {i}" in display for i in range(5))         # thân bài vẫn có, làm tư liệu


def test_article_without_sapo_has_no_sapo_line(monkeypatch):
    pages = [PageContent(title="Bài 0", url="https://vnexpress.net/bai-0.html", text_content="thân " * 300, word_count=300)]
    display = _run_news(monkeypatch, pages)
    assert "📝 Sapo" not in display and "thân" in display
