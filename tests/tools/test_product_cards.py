"""Nút 👁 xem sản phẩm (ngài 2026-10-19): ảnh lấy ngay lúc tìm từ JSON/HTML của nguồn; thẻ giữ theo link để
/api/product trả lại không cần tải trang; thiếu ảnh hoặc chưa có thẻ (khởi động lại) thì lấy og:image của trang."""
import asyncio
from unittest.mock import AsyncMock, patch

from engine.tools import product_cards as P
from engine.tools import shop_sources as S
from engine.UIUX.ui_engine import product_card_api


def test_json_sources_keep_image():
    tiki = S.parse_tiki({"data": [{"name": "Sữa chua", "price": 30000, "url_path": "sua.html",
                                   "thumbnail_url": "https://salt.tikicdn.com/a.png"}]})
    bhx = S.parse_bhx({"data": {"products": [{"name": "Nutimilk", "url": "/sua", "avatar": "https://cdn.tgdd.vn/b.jpg",
                                              "productPrices": [{"price": 27500}]}]}})
    coop = S.parse_coop({"result": {"products": [{"productInfo": {"name": "Vinamilk", "canonical": "vm",
                                                                  "imageUrl": "https://lh3.googleusercontent.com/c"},
                                                  "prices": [{"latestPrice": 28000}]}]}})
    winmart = S.parse_winmart({"data": [{"description": "TH", "seoName": "th", "image": "https://s3.vn/d.png",
                                         "price": {"salePrice": 26000}}]})
    lotte = S.parse_lotte({"data": {"items": [{"name": "Dalat", "url_key": "dl", "image_url": "https://lotte.vn/e.webp",
                                               "price": {"VND": {"price": 25000}}}]}})
    assert [c[0]["image"] for c in (tiki, bhx, coop, winmart, lotte)] == [
        "https://salt.tikicdn.com/a.png", "https://cdn.tgdd.vn/b.jpg", "https://lh3.googleusercontent.com/c",
        "https://s3.vn/d.png", "https://lotte.vn/e.webp"]


def test_html_sources_keep_image():
    cps = S.parse_cellphones('<div class="product-info-container"><a class="product__link" href="/hp.html">'
                             '<img class="product__img" src="https://cdn2.cellphones.com.vn/hp.png"></a>'
                             '<div class="product__name"><h3>Laptop HP</h3></div>'
                             '<p class="product__price--show">15.990.000đ</p></div>', "https://cellphones.com.vn")
    emart = S.parse_emart('<div class="product-block"><div class="image"><img class="img-responsive lazy-load" '
                          'src="https://emartmall.com.vn/image/t.jpg"></div><div class="product-meta">'
                          '<h3 class="name"><a href="/t">Thạch sữa chua</a></h3><div class="price">45.000đ</div></div></div>')
    assert cps[0]["image"] == "https://cdn2.cellphones.com.vn/hp.png"
    assert emart[0]["image"] == "https://emartmall.com.vn/image/t.jpg"


def test_pharmacy_sources_keep_image():
    from engine.tools import pharmacy_sources as PS
    html = ('<script id="__NEXT_DATA__" type="application/json">{"props": {"pageProps": {"initProducts": {"products": '
            '[{"name": "Panadol", "slug": "panadol.htm", "image": "https://cdn.longchau.vn/p.jpg", "price": {"price": 60000}}]'
            '}}}}</script>')
    lc = PS.parse_longchau(html)
    ak = PS.parse_ankhang({"data": {"products": [{"name": "Panadol", "url": "/p", "avatar": "https://cdnv2.tgdd.vn/a.jpg",
                                                  "productPrices": [{"price": 61000}]}]}})
    pc = PS.parse_pharmacity({"data": {"items": [{"name": "Panadol", "slug": "p", "variants": [{"price": 62000}],
                                                  "thumbnail": {"image_url": "https://pharmacity.io/c.jpg"}}]}})
    assert [c[0]["image"] for c in (lc, ak, pc)] == [
        "https://cdn.longchau.vn/p.jpg", "https://cdnv2.tgdd.vn/a.jpg", "https://pharmacity.io/c.jpg"]


def test_remembered_card_needs_no_fetch():
    P.remember({"name": "Nutimilk", "price_vnd": 27500, "rating": 5.0, "sold": 77, "url": "https://bhx.vn/sua",
                "image": "https://cdn.tgdd.vn/b.jpg"}, "Bách Hóa Xanh")
    with patch("engine.tools.browser.browser.visit", AsyncMock(side_effect=AssertionError("không được tải trang"))):
        card = asyncio.run(P.load("https://bhx.vn/sua"))
    assert card == {"name": "Nutimilk", "price": "27.500₫", "rating": 5.0, "sold": 77, "source": "Bách Hóa Xanh",
                    "url": "https://bhx.vn/sua", "image": "https://cdn.tgdd.vn/b.jpg"}


def test_missing_image_falls_back_to_page():
    P.remember({"name": "Laptop", "price_vnd": 15990000, "rating": None, "sold": 0, "url": "https://fptshop.com.vn/l"},
               "FPT Shop")
    page = type("Page", (), {"title": "Laptop FPT", "image_url": "https://cdn2.fptshop.com.vn/l.png"})()
    with patch("engine.tools.browser.browser.visit", AsyncMock(return_value=page)):
        card = asyncio.run(P.load("https://fptshop.com.vn/l"))
    assert card["image"] == "https://cdn2.fptshop.com.vn/l.png" and card["price"] == "15.990.000₫"


def test_unknown_url_uses_page_only():
    page = type("Page", (), {"title": "Kamagra-100", "image_url": "https://pharmacity.vn/k.png"})()
    with patch("engine.tools.browser.browser.visit", AsyncMock(return_value=page)):
        card = asyncio.run(P.load("https://www.pharmacity.vn/kamagra"))
    assert card["name"] == "Kamagra-100" and card["image"] == "https://pharmacity.vn/k.png" and card["price"] == ""


def test_api_rejects_bad_url_and_404s_on_nothing():
    assert asyncio.run(product_card_api("javascript:alert(1)")).status_code == 400
    with patch("engine.tools.browser.browser.visit", AsyncMock(return_value=None)):
        assert asyncio.run(product_card_api("https://example.com/none")).status_code == 404
