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


def test_appliance_cards_keep_only_requested_type(monkeypatch):
    """2026-10-12: Điện máy xanh tìm "máy giặt 11kg" trả tủ lạnh Toshiba lên đầu bảng."""
    import asyncio
    from engine.tools import shop_engine as S
    cards = [{"name": "Tủ lạnh Toshiba Inverter 461 lít", "price_vnd": 12840000, "url": "u1", "rating": 5, "sold": 45},
             {"name": "Máy giặt LG AI DD Inverter 11 kg", "price_vnd": 11990000, "url": "u2", "rating": 4.9, "sold": 22700}]

    async def fake_load(item, url):
        return cards
    monkeypatch.setattr(S, "_load_cards", fake_load)
    item = {"source": "Điện máy xanh", "url": "x"}
    _, rows = asyncio.run(S._fetch_cards(item, "máy giặt 11kg", {}, sort=False, per_term=None))
    assert [r["name"] for r in rows] == ["Máy giặt LG AI DD Inverter 11 kg"]


def test_general_queries_also_search_tiki_when_shopee_blocks():
    """log 2026-10-15 18:51: Shopee trả trang chặn bot (verify/traffic) → "không trích xuất được giá" mãi. Nhóm general
    tra thêm Tiki (API công khai) song song; tai nghe/airpods là công nghệ, giá đỗ/trứng là thực phẩm."""
    assert [u["source"] for u in shop.build_source_urls("bút bi", "general")] == ["Shopee", "Tiki"]
    assert shop.classify_product_query("airpods pro 3") == "technology"
    assert shop.classify_product_query("mac mini m4") == "technology"
    assert shop.classify_product_query("giá đỗ") == "grocery"
    assert shop.classify_product_query("trứng gà") == "grocery"
    data = {"data": [{"name": "Tai nghe Apple AirPods Pro 3", "price": 6250000, "url_path": "tai-nghe-p1.html",
                      "rating_average": 4.8, "review_count": 12, "quantity_sold": {"value": 100}},
                     {"name": "Hết giá", "price": 0, "url_path": "x.html"}]}
    cards = shop.sources_mod.parse_tiki(data)
    assert cards == [{"name": "Tai nghe Apple AirPods Pro 3", "price_vnd": 6250000, "rating": 4.8, "sold": 100,
                      "url": "https://tiki.vn/tai-nghe-p1.html", "image": None, "reviews": 12}]


def test_tiki_and_technology_sources_include_tiki():
    assert "Tiki" in [u["source"] for u in shop.build_source_urls("airpods pro 3", "technology")]


def test_case_and_eartip_accessories_are_dropped():
    """probe 2026-10-15: "Airpods Pro 3" ra toàn hộp đựng/ốp của CellphoneS, không có chính sản phẩm."""
    p = shop._plain
    for name in ("Hộp đựng tai nghe Apple Airpods Pro 3 ESR", "Ốp Airpods Pro 3 silicone", "Vỏ ốp cho AirPods Pro 3",
                 "Nút Tai Nghe Thay Thế cho AirPods Pro 3", "Dây đeo Apple Watch"):
        assert shop._is_unwanted_accessory(p(name), p("airpods pro 3")), name
    assert not shop._is_unwanted_accessory(p("Tai nghe Bluetooth Apple AirPods Pro 3"), p("airpods pro 3"))
    assert not shop._is_unwanted_accessory(p("Ốp lưng iPhone 17"), p("ốp lưng iphone 17"))


def test_cards_must_match_most_query_words():
    """probe 2026-10-15: "Airpods Pro 3" ở CellphoneS lẫn "iPhone 18 Pro" (chỉ khớp chữ "pro")."""
    cards = [{"name": "Tai nghe Apple AirPods Pro 3 Chính hãng", "price_vnd": 5890000, "url": "a"},
             {"name": "iPhone 18 Pro 256GB", "price_vnd": 38690000, "url": "b"}]
    assert [c["url"] for c in shop._relevant_cards(cards, "airpods pro 3")] == ["a"]
    only_off = [{"name": "iPhone 18 Pro 256GB", "price_vnd": 1, "url": "b"}]
    assert shop._relevant_cards(only_off, "airpods pro 3") == only_off  # không còn gì thì giữ nguyên, để báo gần nhất


def test_grocery_sources_include_coop_and_winmart():
    sources = shop.build_source_urls("trứng gà", "grocery")
    names = [s["source"] for s in sources]
    assert "Bách Hóa Xanh" in names
    assert "Co.op Online" in names
    assert "WinMart" in names
    coop = next(s for s in sources if s["source"] == "Co.op Online")
    assert "cooponline.vn/search?router=productListing&query=" in coop["url"]
    winmart = next(s for s in sources if s["source"] == "WinMart")
    assert "winmart.vn/search/" in winmart["url"]


def test_parse_coop():
    data = {
        "result": {
            "products": [
                {
                    "productInfo": {
                        "name": "Trứng gà Ba Huân",
                        "uomName": "Hộp 10 quả",
                        "canonical": "trung-ga-ba-huan-hop-10-qua-p123",
                    },
                    "prices": [{"latestPrice": 32000}],
                    "averageRating": 4.8,
                },
                {
                    "productInfo": {"name": "Hết hàng"},
                    "prices": [],
                },
            ]
        }
    }
    cards = shop.sources_mod.parse_coop(data)
    assert len(cards) == 1
    assert cards[0]["name"] == "Trứng gà Ba Huân (Hộp 10 quả)"
    assert cards[0]["price_vnd"] == 32000
    assert cards[0]["url"] == "https://cooponline.vn/trung-ga-ba-huan-hop-10-qua-p123"
    assert cards[0]["rating"] == 4.8


def test_parse_winmart():
    data = {
        "data": [
            {
                "description": "Trứng gà tươi sạch MEATDeli",
                "uomName": "Vỉ 10 quả",
                "seoName": "trung-ga-tuoi-sach-meatdeli-vi-10-qua",
                "price": {"salePrice": 29500, "originPrice": 32000},
            },
            {
                "description": "Sản phẩm không giá",
                "price": {"salePrice": 0},
            },
        ]
    }
    cards = shop.sources_mod.parse_winmart(data)
    assert len(cards) == 1
    assert cards[0]["name"] == "Trứng gà tươi sạch MEATDeli (Vỉ 10 quả)"
    assert cards[0]["price_vnd"] == 29500
    assert cards[0]["url"] == "https://winmart.vn/products/trung-ga-tuoi-sach-meatdeli-vi-10-qua"


def test_grocery_sources_include_lotte_mart_default_vi_nsg():
    sources = shop.build_source_urls("trứng gà", "grocery")
    names = [s["source"] for s in sources]
    assert "LOTTE Mart" in names
    lotte = next(s for s in sources if s["source"] == "LOTTE Mart")
    assert lotte["store"] == "vi-nsg"
    assert "lottemart.vn/vi-nsg/category?q=" in lotte["url"]


def test_parse_lotte():
    data = {
        "data": {
            "items": [
                {
                    "name": "Trứng Gà Tươi 365 Fresh Size 60G Hộp 6 Trứng",
                    "price": {
                        "VND": {
                            "default": 19800,
                            "special_price": 0,
                            "price": 19800,
                        }
                    },
                    "url_key": "cl-trung-ga-tuoi-size-60g-hop-6-8938511817430",
                    "rating_summary": 90,
                },
                {
                    "name": "Hết hàng",
                    "price": {"VND": {"price": 0}},
                },
            ]
        }
    }
    cards = shop.sources_mod.parse_lotte(data, store="vi-nsg")
    assert len(cards) == 1
    assert cards[0]["name"] == "Trứng Gà Tươi 365 Fresh Size 60G Hộp 6 Trứng"
    assert cards[0]["price_vnd"] == 19800
    assert cards[0]["url"] == "https://www.lottemart.vn/vi-nsg/product/cl-trung-ga-tuoi-size-60g-hop-6-8938511817430"
    assert cards[0]["rating"] == 90.0


def test_grocery_filters_out_lekima_and_sandwiches_for_egg_query():
    cards = [
        {"name": "Quả Lêkima (Trứng gà) (Kg)", "price_vnd": 59900, "url": "u1"},
        {"name": "ATABLE-Sandwich Trứng mayo+Gà Terryaki (Cái)", "price_vnd": 25000, "url": "u2"},
        {"name": "Bánh trứng tươi sợi thịt gà Fasty túi 6gói", "price_vnd": 30000, "url": "u3"},
        {"name": "Trứng gà tươi Dabaco hộp 10 quả", "price_vnd": 32000, "url": "u4"},
    ]
    p = shop._plain
    filtered = [c for c in cards if not shop._is_unwanted_grocery(p(c["name"]), p("trứng gà"))]
    kept = shop._relevant_cards(filtered, "trứng gà")
    assert [c["name"] for c in kept] == ["Trứng gà tươi Dabaco hộp 10 quả"]


def test_tech_query_filters_out_books_and_homonyms_for_macmini():
    cards = [
        {"name": "Mac Mini 2024 - Chip M4 - 16GB/ 256GB", "price_vnd": 23990000, "url": "u1"},
        {"name": "Sách - Mini Fashion - Migo", "price_vnd": 24000, "url": "u2"},
        {"name": "Két heo NAGA - Đỏ cam - Két Gấu ấm áp", "price_vnd": 986000, "url": "u3"},
        {"name": "Thiên Thần Nhỏ - Số 493", "price_vnd": 20000, "url": "u4"},
        {"name": "François Mauriac - Sa mạc tình yêu", "price_vnd": 90250, "url": "u5"},
        {"name": "Bàn phím không dây Logitech MX Keys Mini - Có bản cho Mac", "price_vnd": 2699000, "url": "u6"},
    ]
    p = shop._plain
    clean_query = shop.normalize_product_query("giá macmini")
    assert clean_query == "mac mini"
    filtered = [c for c in cards if not shop._is_unwanted_accessory(p(c["name"]), p(clean_query))]
    kept = shop._relevant_cards(filtered, clean_query)
    assert [c["name"] for c in kept] == ["Mac Mini 2024 - Chip M4 - 16GB/ 256GB"]


def test_egg_sort_prioritizes_shell_eggs_over_egg_organs(monkeypatch):
    import asyncio
    cards = [
        {"name": "Tràng trứng gà (trứng non) THÀNH ĐẠT (Kg)", "price_vnd": 90000, "url": "u1", "rating": 5, "sold": 10},
        {"name": "Trứng gà tươi Dabaco hộp 10 quả", "price_vnd": 32000, "url": "u2", "rating": 5, "sold": 100},
    ]

    async def fake_load(item, url):
        return cards

    monkeypatch.setattr(shop, "_load_cards", fake_load)
    item = {"source": "WinMart", "url": "x"}
    _, rows = asyncio.run(shop._fetch_cards(item, "trứng gà", {}, sort=False, per_term=None))
    assert rows[0]["name"].startswith("Trứng gà tươi Dabaco")
    assert rows[1]["name"].startswith("Tràng trứng gà")



