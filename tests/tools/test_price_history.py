"""So giá với lần tra trước (ngài 2026-10-18): dùng kết quả market_price đã lưu trong outcomes, code tính chênh lệch."""
import json
import sqlite3
from datetime import datetime

import pytest

from engine.tools import price_history as P

NOW = datetime(2026, 10, 18, 9, 0)
OLD = ("#### ⛽ Giá Xăng Dầu (Petrolimex)\n\n| Sản phẩm | Vùng 1 | Vùng 2 |\n| :---: | :---: | :---: |\n"
       "| Xăng E5 RON 92 | 26.670 VNĐ. | 27.200 VNĐ. |\n| Dầu hỏa 2-K | 30.410 VNĐ. | 31.010 VNĐ. |\n\n"
       "| Ngoại tệ | Mua | Bán |\n| :---: | :---: | :---: |\n| JPY (Yên Nhật) | 157,83 VNĐ. | 168,70 VNĐ. |\n")
NEW = ("#### ⛽ Giá Xăng Dầu (Petrolimex)\n\n| Sản phẩm | Vùng 1 | Vùng 2 |\n| :---: | :---: | :---: |\n"
       "| Xăng E5 RON 92 | 26.870 VNĐ. | 27.400 VNĐ. |\n| Dầu hỏa 2-K | 30.410 VNĐ. | 31.010 VNĐ. |\n")


def _db(tmp_path, rows):
    path = tmp_path / "jarvis.db"
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE outcomes (id INTEGER PRIMARY KEY, tools TEXT, query TEXT, status TEXT, result TEXT,"
              " traces TEXT, created_at REAL)")
    for tools, status, result, when in rows:
        c.execute("INSERT INTO outcomes (tools, query, status, result, traces, created_at) VALUES (?,?,?,?,?,?)",
                  (tools, "q", status, "", json.dumps([{"tool": "market_price", "result": result}]), when.timestamp()))
    c.commit(); c.close()
    return path


@pytest.mark.parametrize("text,expected", [
    ("giá xăng hôm qua với hôm nay có gì thay đổi", True), ("giá vàng tăng hay giảm", True),
    ("so với hôm trước tỷ giá thế nào", True), ("giá xăng hôm nay", False), ("giá vàng", False),
])
def test_wants_compare(text, expected):
    assert P.wants_compare(text) is expected


def test_parse_rows_keys_by_item_and_column():
    rows = P.parse_rows(OLD)
    assert rows[("Xăng E5 RON 92", "Vùng 1")] == 26670 and rows[("JPY (Yên Nhật)", "Bán")] == 168.70


def test_compare_with_previous_day(tmp_path):
    db = _db(tmp_path, [("market_price", "success", OLD, datetime(2026, 10, 17, 8, 30)),
                        ("market_price", "success", NEW, datetime(2026, 10, 18, 8, 0))])   # cùng ngày: không phải "trước"
    text = P.compare(NEW, now=NOW, db_path=db)
    assert "So với lần tra 08:30 ngày 17/10" in text
    assert "- Xăng E5 RON 92 (Vùng 1): tăng 200, nay 26.870" in text
    assert "- Xăng E5 RON 92 (Vùng 2): tăng 200, nay 27.400" in text
    assert "Dầu hỏa" not in text and "|" not in text              # chỉ báo mục đổi giá, không vẽ lại bảng
    assert "2 mục khác không đổi" in text


def test_no_change(tmp_path):
    db = _db(tmp_path, [("market_price", "success", NEW, datetime(2026, 10, 16, 20, 0))])
    assert "Không có thay đổi so với lần tra 20:00 ngày 16/10" in P.compare(NEW, now=NOW, db_path=db)


def test_skips_failed_and_unrelated_runs(tmp_path):
    db = _db(tmp_path, [("market_price", "success", OLD, datetime(2026, 10, 15, 8, 0)),
                        ("market_price", "failed", NEW.replace("26.870", "1"), datetime(2026, 10, 17, 8, 0)),
                        ("market_price", "success", "| Bậc | Giá |\n|---|---|\n| Bậc 1 | 1.984 |", datetime(2026, 10, 17, 9, 0))])
    assert "So với lần tra 08:00 ngày 15/10" in P.compare(NEW, now=NOW, db_path=db)


def test_no_previous_lookup(tmp_path):
    db = _db(tmp_path, [])
    assert "Chưa có lần tra giá nào trước hôm nay" in P.compare(NEW, now=NOW, db_path=db)


@pytest.mark.parametrize("question,appended", [("giá xăng hôm qua với hôm nay có gì thay đổi", True), ("giá xăng", False)])
def test_market_price_appends_comparison_only_when_asked(monkeypatch, question, appended):
    import asyncio
    from engine.tools import registry as R

    async def fake_market(item, user_text=""):
        return NEW
    monkeypatch.setattr("engine.tools.search_engine.handle_market_query", fake_market)
    monkeypatch.setattr(P, "compare", lambda text: "📈 SO SÁNH")
    out = asyncio.run(R.run("market_price", {"item": "xăng"}, R.ToolContext(user_text=question))).text
    assert out.startswith(NEW.strip()[:20]) and ("📈 SO SÁNH" in out) is appended
