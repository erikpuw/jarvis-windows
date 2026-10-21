"""Bảng Markdown mà tool gửi cho LLM vòng 2 phải đúng chuẩn GFM (frontend/src/markdown.ts dùng marked):

- search_products (shop_engine): không đưa cột toàn "—" (hàng Bách Hóa Xanh không có sao/lượt bán: 5 cột hẹp trên điện thoại,
  tiêu đề "Đánh giá", "Đã bán" bị bẻ vụn); số ô mỗi hàng bằng số cột tiêu đề.
- get_market_data (search_engine): mỗi khối (tiêu đề, bảng, ghi chú) cách nhau một dòng trống, nếu không marked nuốt dòng ghi chú
  vào bảng; khi không lấy được giá thì là một câu thường, không phải "hàng bảng" lơ lửng không có tiêu đề; ví dụ trong quy tắc vòng 2
  dùng đúng cấp tiêu đề mà tool sinh ra.
"""
import asyncio
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.tools import search_engine, shop_engine  # noqa: E402

_DELIM = re.compile(r"^\|\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|$")


def _cells(line: str) -> int:
    return len(line.strip().strip("|").split("|"))


def _tables(md: str) -> list[list[str]]:
    """Mọi khối dòng bắt đầu bằng "|"; mỗi khối phải là bảng GFM hợp lệ, đứng riêng (dòng trước/sau trống)."""
    lines = md.split("\n")
    blocks, i = [], 0
    while i < len(lines):
        if lines[i].lstrip().startswith("|"):
            j = i
            while j < len(lines) and lines[j].lstrip().startswith("|"):
                j += 1
            blocks.append((i, j, lines[i:j]))
            i = j
        else:
            i += 1
    for start, end, block in blocks:
        assert len(block) >= 3 and _DELIM.match(block[1].strip()), f"không phải bảng (thiếu tiêu đề/dòng ---): {block}"
        n = _cells(block[0])
        assert all(_cells(r) == n for r in block), f"số ô lệch số cột: {block}"
        assert start == 0 or not lines[start - 1].strip(), f"bảng dính dòng phía trên: {lines[start - 1]!r}"
        assert end == len(lines) or not lines[end].strip(), f"dòng sau bảng bị nuốt vào bảng: {lines[end]!r}"
    return [b for _, _, b in blocks]


def _row(name, price, rating="—", sold="—"):
    return {"name": name, "price": price, "rating": rating, "sold": sold, "source": "Bách Hóa Xanh", "url": f"https://bhx.vn/{name}"}


BHX = {"source": "Bách Hóa Xanh", "url": "https://bhx.vn/tim-kiem"}


def test_shop_table_drops_all_empty_columns():
    rows = [_row("Thịt bò xay PTV 200g (Khay)", "61.900₫"), _row("Nạm bò (200 g)", "49.000₫")]
    md = shop_engine._format_results("thịt bò", {}, [(BHX, rows)])
    [table] = _tables(md)
    assert table[0] == "| Sản phẩm | Giá niêm yết | Nguồn |"


def test_shop_table_keeps_only_columns_with_data():
    rows = [_row("Đùi bò (200 g)", "58.929₫", rating="5★ (3)"), _row("Bò viên tươi (Khay)", "45.900₫")]
    md = shop_engine._format_results("thịt bò", {}, [(BHX, rows)])
    [table] = _tables(md)
    assert table[0] == "| Sản phẩm | Giá niêm yết | Đánh giá | Nguồn |"
    assert "5★ (3)" in table[2]


def test_shop_table_full_columns_when_present():
    dmx = {"source": "Điện máy xanh", "url": "https://dmx.vn"}
    rows = [{**_row("Máy giặt LG 10kg", "8.990.000₫", rating="4.9★ (120)", sold="2.300"), "source": "Điện máy xanh"}]
    [table] = _tables(shop_engine._format_results("máy giặt", {"min_kg": 10}, [(dmx, rows)]))
    assert table[0] == "| Sản phẩm | Giá niêm yết | Đánh giá | Đã bán | Nguồn |"


def _market(monkeypatch, pages: dict[str, str], query: str) -> str:
    async def fake_visit(url, script):
        return next((text for key, text in pages.items() if key in url), "")
    monkeypatch.setattr(search_engine.browser, "visit_and_evaluate", fake_visit)
    return asyncio.run(search_engine.handle_market_query(query))


GAS_PAGE = "Bảng giá đổi bình gas tại Hà Nội\nPetrolimex van đứng 644.112 đ 580.000 đ\n"
ELEC_PAGE = "Giá bán (đồng/kWh)\n" + "".join(f"{i}\nCho kWh từ {i}\n{1900 + i * 100}\n" for i in range(1, 7)) + "Cơ chế điều chỉnh"


def test_market_blocks_are_separated_and_tables_valid(monkeypatch):
    md = _market(monkeypatch, {"pgaspetrolimex": GAS_PAGE, "luatvietnam": ELEC_PAGE}, "giá gas và giá điện")
    tables = _tables(md)
    assert len(tables) == 2
    assert "| Gas Petrolimex (bình 12kg) |" in tables[0][2]
    assert any(line.startswith("*Giá lấy trực tiếp") for line in md.split("\n"))


def test_market_failed_parse_is_plain_text_not_a_stray_row(monkeypatch):
    md = _market(monkeypatch, {}, "báo cáo giá tổng hợp")
    assert _tables(md) == []
    assert "đang cập nhật" in md


