"""Đọc sản phẩm từ từng nguồn (DOM / JSON nhúng / API) và luồng search_products không cần mạng.
Run: python -m pytest tests/test_shop_sources.py"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.tools import shop_engine as shop
from engine.tools import shop_sources as src

DMX = """<ul class="listsearch"><li class="item"><a href="/may-giat/lg-11" class="main-contain" data-name="Máy giặt LG 11 kg FX1411N5W"
 data-price="10990000.0" data-brand="LG"><p class="product-title">x</p><strong class="price">10.990.000₫</strong></a>
 <div class="rating_Compare has_quantity"><div class="vote-txt"><i></i><b>4.9</b></div><span>• Đã bán 5,7k</span></div></li>
 <li class="item"><a href="/may-giat/no-price" class="main-contain" data-name="Hết hàng" data-price="0"></a></li></ul>"""

CELLPHONES = """<div class="product-info-container product-item"><div class="product-info"><a href="https://cellphones.com.vn/iphone-17-pro.html" class="product__link">
 <div class="product__name"><h3>iPhone 17 Pro 256GB | Chính hãng</h3></div><div class="box-info__box-price">
 <p class="product__price--show"> 31.990.000đ </p><p class="product__price--through"> 34.990.000đ </p></div></a></div></div>
 <div class="product-info-container product-item"><div class="product-info"><a href="/op-lung.html" class="product__link">
 <div class="product__name"><h3>Ốp lưng iPhone 17 Pro</h3></div><p class="product__price--show"> 388.000đ </p></a></div></div>"""

FPT = ('<script>self.__next_f.push([1,"{\\"skus\\":[{\\"name\\":\\"iPhone 17 Pro 256GB\\",\\"displayName\\":\\"iPhone 17 Pro 256GB\\",'
       '\\"sku\\":\\"00921739\\",\\"type\\":\\"Normal\\",\\"slug\\":\\"dien-thoai/iphone-17-pro-256gb?sku=00921739\\",\\"x\\":{\\"a\\":1},'
       '\\"originalPrice\\":34990000,\\"currentPrice\\":31990000,\\"promotions\\":[]},{\\"name\\":\\"iPhone 17 Pro 256GB\\",'
       '\\"displayName\\":\\"iPhone 17 Pro 256GB\\",\\"sku\\":\\"00921739\\",\\"type\\":\\"Normal\\",\\"slug\\":\\"dien-thoai/iphone-17-pro-256gb?sku=00921739\\",'
       '\\"originalPrice\\":34990000,\\"currentPrice\\":31990000}]}"])</script>')

BHX = {"code": 0, "data": {"products": [
    {"name": "Nạm bò", "url": "/thit-bo/nam-bo", "unit": "Kg", "rateStar": 0, "totalReview": 0, "totalUserBuy": 0,
     "productPrices": [{"price": 49000, "netUnitValue": 0.2}, {"price": 73500, "netUnitValue": 0.3}]},
    {"name": "Bò viên tươi", "url": "/thit-bo/bo-vien", "unit": "Khay", "rateStar": 4.0, "totalReview": 8, "totalUserBuy": 120,
     "productPrices": [{"price": 45900.0, "netUnitValue": 0}]},
    {"name": "Không giá", "url": "/x", "unit": "Gói", "productPrices": []},
]}}


def test_dmx_markup_gives_name_price_rating_and_sold_and_skips_unpriced():
    cards = src.parse_listing("https://www.dienmayxanh.com/tim-kiem?key=a", DMX)
    assert cards == [{"name": "Máy giặt LG 11 kg FX1411N5W", "price_vnd": 10_990_000, "rating": 4.9, "sold": 5700,
                      "url": "https://www.dienmayxanh.com/may-giat/lg-11"}]


def test_cellphones_dom_reads_name_and_price_from_the_same_card():
    cards = src.parse_listing("https://cellphones.com.vn/catalogsearch/result?q=iphone", CELLPHONES)
    assert [(c["name"], c["price_vnd"]) for c in cards] == [
        ("iPhone 17 Pro 256GB | Chính hãng", 31_990_000), ("Ốp lưng iPhone 17 Pro", 388_000)]
    assert cards[0]["url"] == "https://cellphones.com.vn/iphone-17-pro.html"
    assert cards[1]["url"] == "https://cellphones.com.vn/op-lung.html"


def test_fpt_embedded_json_is_parsed_and_deduplicated_by_sku():
    cards = src.parse_listing("https://fptshop.com.vn/tim-kiem?s=iphone", FPT)
    assert cards == [{"name": "iPhone 17 Pro 256GB", "price_vnd": 31_990_000, "rating": None, "sold": 0,
                      "url": "https://fptshop.com.vn/dien-thoai/iphone-17-pro-256gb?sku=00921739"}]


def test_unknown_host_gives_no_cards():
    assert src.parse_listing("https://example.com/x", DMX) == []


def test_bhx_api_json_becomes_cards_with_pack_size_in_the_name():
    cards = src.parse_bhx(BHX)
    assert cards[0] == {"name": "Nạm bò (200 g)", "price_vnd": 49000, "rating": None, "sold": 0,
                        "reviews": 0, "url": "https://www.bachhoaxanh.com/thit-bo/nam-bo"}
    assert cards[1]["name"] == "Bò viên tươi (Khay)" and cards[1]["rating"] == 4.0 and cards[1]["reviews"] == 8
    assert cards[1]["sold"] == 120 and cards[1]["price_vnd"] == 45900
    assert len(cards) == 2   # sản phẩm không có giá bị bỏ


def test_parse_sold_handles_thousands_suffix():
    assert [src.parse_sold(t) for t in ("473", "2,2k", "20,5k", "", "abc")] == [473, 2200, 20500, 0, 0]


def test_site_keyword_drops_price_and_time_filler():
    assert shop.site_keyword("giá thịt bò hôm nay") == "thịt bò"
    assert shop.site_keyword("giá iphone 18 pro hôm nay") == "iphone 18 pro"
    assert shop.site_keyword("mua sữa tươi vinamilk") == "sữa tươi vinamilk"
    assert shop.site_keyword("thịt gà bao nhiêu một ký") == "thịt gà một ký"
    assert shop.site_keyword("Máy giặt Panasonic Inverter 11.5 kg NA-FJ115X1BV") == "Máy giặt Panasonic Inverter 11.5 kg NA-FJ115X1BV"


def test_card_row_keeps_markdown_table_intact_when_name_has_a_pipe():
    row = shop._card_row({"name": "iPhone 17 Pro 256GB | Chính hãng", "price_vnd": 31_990_000, "url": "u"}, "CellphoneS")
    assert "|" not in row["name"] and row["name"].startswith("iPhone 17 Pro 256GB")


def test_same_product_and_price_from_color_variants_is_listed_once(monkeypatch):
    html = FPT.replace("00921739", "00921739", 1)
    two = html + html.replace("00921739", "00921741")   # cùng tên, cùng giá, sku khác (màu khác)
    _patch_network(monkeypatch, {"fptshop.com.vn": two})
    out = asyncio.run(shop.search_products("iphone 17 pro"))
    assert out.count("| iPhone 17 Pro 256GB |") == 1


def test_bhx_asks_the_next_page_when_the_first_has_few_exact_matches(monkeypatch):
    seen = _patch_network(monkeypatch, bhx={"code": 0, "data": {"products": BHX["data"]["products"][:1]}})
    asyncio.run(shop.search_products("kimchi"))
    assert [b["pageIndex"] for b in seen["post"]] == [0, 1]


def test_unrated_cards_are_not_ranked_below_rated_low_sellers():
    rated_low = {"name": "a", "price_vnd": 1, "rating": 5.0, "sold": 3}
    unrated = {"name": "b", "price_vnd": 1, "rating": None, "sold": 0}
    assert shop._score(unrated) == 4.5     # trung tính, không bị 0 điểm đẩy xuống cuối
    assert shop._score(rated_low) > 4.5 > shop._score({"rating": 3.0, "sold": 500})


def _patch_network(monkeypatch, html_by_host=None, bhx=None):
    seen = {"post": [], "html": []}

    async def fake_html(url):
        seen["html"].append(url)
        return (html_by_host or {}).get(next((h for h in (html_by_host or {}) if h in url), ""), "")

    async def fake_post(url, body, headers=None):
        seen["post"].append(body)
        return bhx or {"code": 30000}
    async def fake_text_page(url):  # đường dự phòng đọc text khi nguồn không có thẻ: không ra mạng thật
        return type("Page", (), {"text_content": ""})()
    monkeypatch.setattr(shop.browser, "visit_product_listing", fake_text_page)
    monkeypatch.setattr(shop.browser, "fetch_listing_html", fake_html)
    monkeypatch.setattr(shop.browser, "post_json", fake_post)
    return seen


def test_grocery_query_uses_the_cleaned_keyword_and_bhx_api(monkeypatch):
    seen = _patch_network(monkeypatch, bhx=BHX)
    out = asyncio.run(shop.search_products("giá thịt bò hôm nay"))
    assert seen["post"][0]["keywords"] == "thịt bò"
    assert "| Nạm bò (200 g) |" in out and "[Bách Hóa Xanh](https://www.bachhoaxanh.com/thit-bo/nam-bo)" in out


def test_phone_query_reads_cellphones_cards_not_text_and_drops_accessories(monkeypatch):
    _patch_network(monkeypatch, {"cellphones.com.vn": CELLPHONES})
    out = asyncio.run(shop.search_products("giá iphone 17 pro hôm nay"))
    assert "| iPhone 17 Pro 256GB - Chính hãng | 31.990.000₫ |" in out
    assert "Ốp lưng" not in out and "388.000" not in out


def test_missing_model_number_is_reported_instead_of_silently_showing_other_models(monkeypatch):
    _patch_network(monkeypatch, {"cellphones.com.vn": CELLPHONES})
    out = asyncio.run(shop.search_products("giá iphone 18 pro hôm nay"))
    assert "18" in out.split("Lưu ý")[1] and "iPhone 17 Pro 256GB" in out
