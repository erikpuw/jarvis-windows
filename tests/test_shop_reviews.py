"""Tests cho tra giá / đánh giá / so sánh sản phẩm. Run: python tests/test_shop_reviews.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.tools import shop_engine as shop

NEED = (
    "Tôi đang tìm mua máy giặt\nTôi chỉ mua ở Điện máy xanh\n"
    "Nhu cầu sử dụng cho 7 người lớn, Ưu tiên loại từ 11kg trở lên\n"
    "Có động cơ truyền động trực tiếp (quan trọng)\nMáy giặt cửa trên\n"
    "Ưu tiên độ bền và giá dưới 10tr\n"
    "Hãy chọn và lọc giúp tôi top 5 máy giặt thực tế hợp với nhu cầu của tôi nhất"
)


def test_appliance_category_and_dmx_source():
    assert shop.classify_product_query("máy giặt panasonic") == "appliance"
    assert shop.classify_product_query("tủ lạnh samsung") == "appliance"  # không bị _TECH_KW "samsung" cướp
    urls = shop.build_source_urls("máy giặt", "appliance")
    assert [u["source"] for u in urls] == ["Điện máy xanh"], urls
    assert "dienmayxanh.com/tim-kiem?key=m%C3%A1y+gi%E1%BA%B7t" in urls[0]["url"]


def test_keywords_match_whole_words_only():
    assert shop.classify_product_query("kết quả các loại bảo hiểm") == "general"  # "quả", "cá" trong từ khác
    assert shop.classify_product_query("giá thịt bò") == "grocery"


def test_parse_criteria_from_real_log_text():
    c = shop.parse_criteria(NEED)
    assert c == {"min_kg": 11.0, "max_price": 10_000_000, "top_n": 5}, c
    assert shop.parse_criteria("iphone 17 pro") == {"min_kg": None, "max_price": None, "top_n": 5}
    assert shop.parse_criteria("laptop dưới 25 triệu")["max_price"] == 25_000_000
    assert shop.parse_criteria("top 3 tivi")["top_n"] == 3


def test_site_keyword_shortens_long_need_text():
    assert shop.site_keyword(NEED) == "máy giặt"
    assert shop.site_keyword("Máy giặt Panasonic Inverter 11.5 kg NA-FJ115X1BV") == \
        "Máy giặt Panasonic Inverter 11.5 kg NA-FJ115X1BV"


def test_accessories_dropped_unless_asked_for():
    text = "Ốp lưng iPhone 17 Pro Max Pitaka 1.400.000đ\niPhone 17 Pro 256GB 31.990.000đ"
    rows = shop._extract_rows(text, "FPT", "u", query="iphone 17 pro")
    assert [r["name"] for r in rows] == ["iPhone 17 Pro 256GB"], rows
    rows = shop._extract_rows(text, "FPT", "u", query="ốp lưng iphone 17 pro")
    assert any(r["name"].startswith("Ốp lưng") for r in rows), rows


def test_site_keyword_strips_criteria_from_short_queries_too():
    # smoke 2026-10-03: "top 5 máy giặt từ 11kg dưới 10tr" gõ nguyên vào ô tìm kiếm của shop -> không ra thẻ nào
    assert shop.site_keyword("top 5 máy giặt từ 11kg dưới 10tr") == "máy giặt"
    assert shop.site_keyword("đánh giá máy giặt LG dưới 12 triệu") == "máy giặt LG"
    assert shop.site_keyword("laptop văn phòng dưới 15 triệu") == "laptop văn phòng"


def test_split_compare():
    assert shop.split_compare("so sánh iphone 16 và galaxy s25") == ["iphone 16", "galaxy s25"]
    assert shop.split_compare("so sánh LG FX1411N5W với Electrolux EWF1143P5SC") == \
        ["LG FX1411N5W", "Electrolux EWF1143P5SC"]
    assert shop.split_compare("máy giặt lg") == []


def _card(name, price, rating, sold):
    return {"name": name, "price_vnd": price, "rating": rating, "sold": sold, "url": "u", "source": "s"}


def test_rank_filters_kg_budget_and_orders_by_rating_then_sold():
    cards = [
        _card("Máy giặt Aqua 8 kg A", 4_000_000, 4.9, 20000),          # dưới 11kg → loại
        _card("Máy giặt LG 11 kg B", 10_990_000, 4.9, 5700),           # quá ngân sách → loại
        _card("Máy giặt Sharp 12 kg C", 6_290_000, 5.0, 57),
        _card("Máy giặt Panasonic 11.5 kg D", 9_790_000, 5.0, 1600),
        _card("Máy giặt Samsung 11 kg E", 9_000_000, 4.9, 3000),
    ]
    got = shop.rank_cards(cards, {"min_kg": 11.0, "max_price": 10_000_000, "top_n": 2})
    assert [c["name"][-1] for c in got] == ["D", "E"], got  # 4.9★/3000 lượt hơn 5★/57 lượt


def test_rank_prefers_many_ratings_over_few_perfect_ones():
    cards = [_card("few", 1, 5.0, 57), _card("many", 1, 4.9, 20000)]
    assert [c["name"] for c in shop.rank_cards(cards, {"top_n": 5})] == ["many", "few"]


def test_rank_without_criteria_keeps_all_up_to_top_n():
    cards = [_card(f"sp {i}", 1_000_000, 4.0, i) for i in range(8)]
    assert len(shop.rank_cards(cards, {"min_kg": None, "max_price": None, "top_n": 5})) == 5


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
