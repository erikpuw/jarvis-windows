import asyncio
from engine.tools.legal_engine import (
    _match_curated,
    _normalize_legal_query,
    CURATED_LAWS,
)


def test_normalize_legal_query():
    assert "nồng độ cồn" in _normalize_legal_query("mức phạt khi nhậu say tham gia giao thông là bao nhiêu")
    assert "vượt đèn đỏ" in _normalize_legal_query("vượt đèn đỏ bị phạt bao nhiêu tiền")
    assert "chạy quá tốc độ" in _normalize_legal_query("bắn tốc độ 20km/h")
    assert "mũ bảo hiểm" in _normalize_legal_query("không đội nón bảo hiểm")
    assert "giấy phép lái xe" in _normalize_legal_query("quên mang bằng lái xe")
    assert "nghĩa vụ quân sự" in _normalize_legal_query("trốn đi lính")


def test_match_curated_priority():
    # Nghị định phải được ưu tiên khi hỏi về nghị định/mức phạt giao thông
    match_decree = _match_curated("Nghị định 168 về giao thông đường bộ")
    assert match_decree is not None
    assert match_decree["id"] == "nghi-dinh-168-2024-atgt"

    # Luật phải được khớp khi hỏi về luật
    match_law = _match_curated("Luật giao thông đường bộ 2024")
    assert match_law is not None
    assert match_law["id"] == "luat-trat-tu-atgt-duong-bo-2024"

    # Bộ luật Lao động
    match_bllđ = _match_curated("Bộ luật Lao động 2019")
    assert match_bllđ is not None
    assert match_bllđ["id"] == "bo-luat-lao-dong-2019"
