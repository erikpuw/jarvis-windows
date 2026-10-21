import asyncio

from engine.tools import registry as R


def _quiet(monkeypatch):
    monkeypatch.setattr("engine.core.trace_logger.TraceLogger.log_trace", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr("engine.core.guardrails.verify_output", lambda n, a: (True, ""))


def test_weather_uses_location(monkeypatch):
    _quiet(monkeypatch)
    got = {}

    async def fake(location, hourly=False, question=""):
        got["loc"], got["q"] = location, question; return "28°C"
    monkeypatch.setattr("engine.tools.weather_engine.weather_search", fake)
    ctx = R.ToolContext(user_text="ngày mai hà nội thế nào")
    assert asyncio.run(R.run("weather", {"location": "hà nội"}, ctx)).text == "28°C"
    assert got == {"loc": "hà nội", "q": "ngày mai hà nội thế nào"}


def test_news_returns_display(monkeypatch):
    _quiet(monkeypatch)

    async def fake(query):
        return {"display": f"tin {query}"}
    monkeypatch.setattr("engine.tools.search_engine.handle_news_search", fake)
    assert asyncio.run(R.run("search_news", {"topic": "bão"})).text == "tin bão"


def test_knowledge_empty_is_no_result(monkeypatch):
    _quiet(monkeypatch)

    async def fake(query, route=None, flow_tracker=None):
        return ""
    monkeypatch.setattr("engine.core.mcp_context.build_mcp_context", fake)
    res = asyncio.run(R.run("lookup_knowledge", {"query": "napoleon"}))
    assert res.outcome == "no_result"


def test_gym_passes_only_given_fields(monkeypatch):
    _quiet(monkeypatch)
    got = {}

    def fake(arguments, **kwargs):
        got.update(arguments); return {"text": "ok"}
    monkeypatch.setattr("engine.tools.gym_engine.run_gym_tool", fake)
    args, err = R.validate("gym", {"action": "stats", "days": "14"}, set(R.names()))
    assert err is None
    asyncio.run(R.run("gym", args))
    assert got == {"action": "stats", "days": 14}


def test_gym_keeps_done_false(monkeypatch):
    _quiet(monkeypatch)
    got = {}

    def fake(arguments, **kwargs):
        got.update(arguments); return {"text": "ok"}
    monkeypatch.setattr("engine.tools.gym_engine.run_gym_tool", fake)
    args, err = R.validate("gym", {"action": "log_habit", "habit": "chạy bộ", "done": "false"}, set(R.names()))
    assert err is None
    asyncio.run(R.run("gym", args))
    assert got == {"action": "log_habit", "habit": "chạy bộ", "done": False}


def test_read_tools_are_read_kind():
    for name in ("weather", "search_news", "market_price", "search_products", "cinema", "free_games",
                 "lunar_today", "zodiac", "legal_lookup", "vn_admin_lookup", "lookup_knowledge"):
        assert R.kind(name) == "read" and R.description(name)


def test_news_uses_final_article_url_not_google_redirect(monkeypatch):
    """Log 2026-10-12 03:29: link news.google.com/rss/articles/... 300+ ký tự, model chép hỏng link."""
    from types import SimpleNamespace
    from engine.tools import search_engine as S
    from engine.tools.browser import PageContent
    gn = "https://news.google.com/rss/articles/CBMi" + "x" * 300
    final = "https://baonghean.vn/dell-xps-16-10339207.html"

    async def fake_search(q, vietnam_only=True):
        return [SimpleNamespace(url=gn, title="t", snippet="s", source_host="baonghean.vn")]

    async def fake_visit(url, timeout_ms=0):
        return PageContent(title="Dell XPS", url=final, text_content="nội dung bài báo " * 50, word_count=100)
    monkeypatch.setattr(S.browser, "search_news", fake_search)
    monkeypatch.setattr(S.browser, "visit_article", fake_visit)
    monkeypatch.setattr(S, "is_vietnam_news_url", lambda u, host_override="": True)
    monkeypatch.setattr(S, "is_news_article_url", lambda u, host_override="": True)
    monkeypatch.setattr(S, "_is_valid_news_content", lambda c: True)
    S._SEARCH_TTL_CACHE.clear()
    display = asyncio.run(S.handle_news_search("dell xps"))["display"]
    assert final in display and gn not in display


def test_market_price_offers_summary():
    """Log 2026-10-12 03:26: "giá tổng hợp" không gọi tool vì mô tả không nhắc bảng tổng hợp."""
    assert "tổng hợp" in R.description("market_price")
    item = R.parameters("market_price")["properties"]["item"]["description"]
    assert "tổng hợp" in item


_OIL_2026_10 = ("Loại xăng dầu\nDầu hỏa 2-K\nDO 0,001S Mức 5\nXăng E10 RON 95 Mức 3\nGiá Xăng dầu  Ngày \n12-10-2026 00:29\n"
                "Loại xăng dầu\nGiá vùng 1 (VNĐ)\nGiá vùng 2 (VNĐ)\nDầu hỏa 2-K\n30,630\n31,240\nDO 0,001S Mức 5\n30,520\n31,130\n"
                "Xăng E10 RON 95 Mức 3\n28,250\n28,810\nXăng E5 RON 92 Mức 2\n27,700\n28,250\nNguồn: giaxanghomnay.com\n"
                "Xăng E10 RON 95 Mức 3\n")


def test_fuel_rows_follow_page_labels():
    """baomoi 2026-10: nhãn đổi "E10 RON 95-III" → "E10 RON 95 Mức 3"; khớp cứng tên cũ → "đang cập nhật"."""
    from engine.tools.search_engine import _parse_fuel_rows
    assert _parse_fuel_rows(_OIL_2026_10) == [
        ("Dầu hỏa 2-K", "30.630", "31.240"), ("DO 0,001S Mức 5", "30.520", "31.130"),
        ("Xăng E10 RON 95 Mức 3", "28.250", "28.810"), ("Xăng E5 RON 92 Mức 2", "27.700", "28.250")]
    assert _parse_fuel_rows("Xăng E5 RON 92-II 27.700 28.250") == [("Xăng E5 RON 92-II", "27.700", "28.250")]


_FX_2026_10 = ("Tỷ giá ngoại tệ VIETCOMBANK\nMã NT\nMua tiền mặt (VNĐ)\nMua chuyển khoản (VNĐ)\nBán tiền mặt (VNĐ)\n"
               "Bán chuyển khoản (VNĐ)\nDKK \nKrone Đan Mạch\n-\n3819.45\n3965.59\n-\nEUR \nĐồng Euro\n28331.73\n28617.9\n"
               "29826.12\n-\nJPY \nYên Nhật\n157.62\n159.21\n168.47\n-\nUSD \nĐô la Mỹ\n25660\n25690\n26070\n-\n"
               "Tin tức Tỷ giá USD hôm nay (11-10)\n")


def test_fx_rows_parse_all_codes():
    from engine.tools.search_engine import _parse_fx_rows
    rows = _parse_fx_rows(_FX_2026_10)
    assert rows == {"DKK": ("Krone Đan Mạch", "3.819 VNĐ", "3.966 VNĐ"),
                    "EUR": ("Đồng Euro", "28.332 VNĐ", "29.826 VNĐ"),
                    "JPY": ("Yên Nhật", "157,62 VNĐ", "168,47 VNĐ"),
                    "USD": ("Đô la Mỹ", "25.660 VNĐ", "26.070 VNĐ")}


def test_fx_codes_requested():
    from engine.tools.search_engine import _parse_fx_rows, _fx_requested
    rows = _parse_fx_rows(_FX_2026_10)
    assert _fx_requested("tỷ giá euro", rows) == ["EUR"]
    assert _fx_requested("EUR", rows) == ["EUR"]
    assert _fx_requested("yên nhật và usd", rows) == ["JPY", "USD"]
    assert _fx_requested("tỷ giá ngoại tệ", rows) == []


def test_news_splits_budget_so_every_article_fits_the_answer_round(monkeypatch):
    """Log 2026-10-13 01:29: 3 bài = 11.487 ký tự, vòng trả lời cắt ở 8.000 → mất bài cuối. Chia đều mỗi bài."""
    from types import SimpleNamespace
    from engine.tools import search_engine as S
    from engine.tools.browser import PageContent
    from engine.turn.loop import RESULT_CHARS
    urls = [f"https://vnexpress.net/bai-{i}.html" for i in range(5)]

    async def fake_search(q, vietnam_only=True):
        return [SimpleNamespace(url=u, title=f"t{i}", snippet="s", source_host="vnexpress.net") for i, u in enumerate(urls)]

    async def fake_visit(url, timeout_ms=0):
        n = url[-6]
        return PageContent(title=f"Bài số {n}", url=url, text_content=f"đoạn {n} " * 1000, word_count=2000)
    monkeypatch.setattr(S.browser, "search_news", fake_search)
    monkeypatch.setattr(S.browser, "visit_article", fake_visit)
    monkeypatch.setattr(S, "is_vietnam_news_url", lambda u, host_override="": True)
    monkeypatch.setattr(S, "is_news_article_url", lambda u, host_override="": True)
    monkeypatch.setattr(S, "_is_valid_news_content", lambda c: True)
    S._SEARCH_TTL_CACHE.clear()
    display = asyncio.run(S.handle_news_search("tin nóng"))["display"]
    assert len(display) <= RESULT_CHARS
    assert all(f"Bài số {i}" in display and f"đoạn {i}" in display for i in range(5))


def test_market_price_routes_electricity_and_water(monkeypatch):
    """Log 2026-10-21: query 'nước', 'nước sinh hoạt', 'điện', 'điện sinh hoạt' phải trỏ đúng source, không fallback vàng."""
    from engine.tools import search_engine as S
    visited_urls = []

    async def fake_visit_and_eval(url, script):
        visited_urls.append(url)
        return ""

    monkeypatch.setattr(S.browser, "visit_and_evaluate", fake_visit_and_eval)

    visited_urls.clear()
    asyncio.run(S.handle_market_query("nước sinh hoạt"))
    assert len(visited_urls) == 1 and "sonha.net.vn" in visited_urls[0]

    visited_urls.clear()
    asyncio.run(S.handle_market_query("nước"))
    assert len(visited_urls) == 1 and "sonha.net.vn" in visited_urls[0]

    visited_urls.clear()
    asyncio.run(S.handle_market_query("điện"))
    assert len(visited_urls) == 1 and "luatvietnam.vn" in visited_urls[0]

    # 3. Tra cứu qua user_text khi query trống
    visited_urls.clear()
    asyncio.run(S.handle_market_query("", user_text="xem giá nước sinh hoạt"))
    assert len(visited_urls) == 1 and "sonha.net.vn" in visited_urls[0]

    visited_urls.clear()
    asyncio.run(S.handle_market_query("", user_text="giá điện sinh hoạt"))
    assert len(visited_urls) == 1 and "luatvietnam.vn" in visited_urls[0]

    visited_urls.clear()
    asyncio.run(S.handle_market_query("điện sinh hoạt"))
    assert len(visited_urls) == 1 and "luatvietnam.vn" in visited_urls[0]
