"""vn_admin_lookup (log 2026-10-17 21:21-21:26): hỏi đếm/liệt kê chỉ ra "mã 48"; ý hỏi đọc từ câu của ngài."""
import asyncio

import pytest

from engine.tools import registry as R
from engine.tools.search_engine import handle_vietnam_data_query as lookup


def ask(query, question=""):
    return asyncio.run(lookup(query, question=question))


@pytest.mark.parametrize("query,question", [
    ("Đà Nẵng", "Ở Đà Nẵng có bao nhiêu phường?"),   # model bỏ "bao nhiêu" khỏi query
    ("Đà Nẵng có mấy xã", ""),
])
def test_count_by_unit_type(query, question):
    text = ask(query, question)
    assert "Thành phố Đà Nẵng (mã 48) có 94 đơn vị cấp xã: 23 phường, 70 xã, 1 đặc khu" in text
    assert "Hải Châu" not in text                       # đếm thì không kèm danh sách


@pytest.mark.parametrize("query,question", [
    ("các phường thuộc Đà Nẵng", "Có liệt kê được phường ở Đà Nẵng không"),
    ("Đà Nẵng", "những phường nào ở Đà Nẵng"),
    ("danh sách xã Đà Nẵng", ""),
])
def test_list_grouped_by_type(query, question):
    text = ask(query, question)
    assert "23 phường, 70 xã, 1 đặc khu" in text
    assert "Phường (23): " in text and "Xã (70): " in text and "Đặc khu (1): " in text
    assert "Hải Châu" in text


def test_ward_says_type_province_and_province_size():
    text = ask("Phường Phú Định", "Phường Phú Định là ở đâu")
    assert "Phường Phú Định (mã 27427) là phường thuộc Thành phố Hồ Chí Minh" in text
    assert "168 đơn vị cấp xã: 113 phường, 54 xã, 1 đặc khu" in text
    assert "không có cấp quận/huyện" in text            # nói rõ giới hạn dữ liệu, model khỏi đoán quận cũ


def test_province_plain_keeps_code_and_size():
    text = ask("Đà Nẵng")
    assert "Thành phố Đà Nẵng (mã 48)" in text and "94 đơn vị cấp xã" in text


def test_tool_passes_user_sentence(monkeypatch):
    got = {}

    async def fake(query, question=""):
        got.update(q=query, s=question)
        return "ok"
    monkeypatch.setattr("engine.tools.search_engine.handle_vietnam_data_query", fake)
    ctx = R.ToolContext(user_text="Ở Đà Nẵng có bao nhiêu phường?")
    assert asyncio.run(R.run("vn_admin_lookup", {"query": "Đà Nẵng"}, ctx)).text == "ok"
    assert got == {"q": "Đà Nẵng", "s": "Ở Đà Nẵng có bao nhiêu phường?"}
