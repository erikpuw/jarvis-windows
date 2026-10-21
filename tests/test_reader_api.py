"""Unit tests for /api/reader endpoint. Run: python -m pytest tests/test_reader_api.py"""
import asyncio
from unittest.mock import AsyncMock, patch
from engine.UIUX.ui_engine import read_article_api


def test_reader_api_rejects_invalid_urls():
    res = asyncio.run(read_article_api("not-a-valid-url"))
    assert res.status_code == 400


def test_reader_api_returns_clean_article_data():
    fake_page = type("Page", (), {
        "text_content": "Day la noi dung bai bao test ve cong nghe AI.",
        "title": "Tieu de bai bao test"
    })()
    with patch("engine.tools.browser.browser.visit_article", AsyncMock(return_value=fake_page)):
        res = asyncio.run(read_article_api("https://vnexpress.net/ai-technology"))
        assert res["title"] == "Tieu de bai bao test"
        assert "noi dung bai bao test" in res["content"]
        assert res["source"] == "VnExpress"
        assert res["url"] == "https://vnexpress.net/ai-technology"


def test_reader_api_returns_404_when_no_content():
    fake_page = type("Page", (), {"text_content": "", "title": ""})()
    with patch("engine.tools.browser.browser.visit_article", AsyncMock(return_value=fake_page)):
        res = asyncio.run(read_article_api("https://tuoitre.vn/empty-page"))
        assert res.status_code == 404


def test_reader_api_filters_css_and_styling_noise():
    raw_content = (
        ".tdi_31{min-height:0}\n"
        ".tdi_33,.tdc-columns{display:block;width:100%}\n"
        "@media (min-width:768px){.tdi_38{margin-left:-15px}}\n"
        ".tdb-breadcrumbs{margin-bottom:11px;font-family:var(--td_font);color:#747474}\n\n"
        "Nvidia RTX Spark N1X mang den kha nang chay mo hinh AI tren laptop.\n"
        "Day la noi dung thuc su cua bai bao cong nghe."
    )
    fake_page = type("Page", (), {
        "text_content": raw_content,
        "title": "Trải nghiệm Nvidia RTX Spark N1X"
    })()
    with patch("engine.tools.browser.browser.visit_article", AsyncMock(return_value=fake_page)):
        res = asyncio.run(read_article_api("https://mmosite.vn/trai-nghiem-nvidia-rtx-spark-n1x"))
        assert res["title"] == "Trải nghiệm Nvidia RTX Spark N1X"
        assert ".tdi_31" not in res["content"]
        assert "min-height" not in res["content"]
        assert "@media" not in res["content"]
        assert "Nvidia RTX Spark N1X mang den kha nang chay mo hinh AI" in res["content"]
        assert "Day la noi dung thuc su cua bai bao cong nghe." in res["content"]

