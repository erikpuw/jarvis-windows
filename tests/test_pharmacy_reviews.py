"""Unit tests cho module tra cứu thuốc (pharmacy_sources & pharmacy_engine)."""

import pytest
from engine.tools import pharmacy_sources as sources
from engine.tools import pharmacy_engine as engine


def test_parse_sold():
    assert sources.parse_sold("20,5k") == 20500
    assert sources.parse_sold("Đã bán 276") == 276
    assert sources.parse_sold("10.942") == 10942
    assert sources.parse_sold("0") == 0
    assert sources.parse_sold(None) == 0
    assert sources.parse_sold("") == 0


def test_parse_longchau():
    sample_html = """
    <html>
    <head>
    <script id="__NEXT_DATA__" type="application/json">
    {
      "props": {
        "pageProps": {
          "initProducts": {
            "products": [
              {
                "name": "MEN VI SINH BIFINA BABY 30 GÓI",
                "slug": "thuc-pham-chuc-nang/bifina-baby.html",
                "rating": 4.8,
                "sold": 150,
                "price": {
                  "measureUnitName": "Hộp",
                  "price": 486000,
                  "discount": {
                    "finalPrice": 388800
                  }
                }
              },
              {
                "name": "Thuốc hết hàng hoặc giá 0",
                "slug": "sample.html",
                "price": {
                  "price": 0
                }
              }
            ]
          }
        }
      }
    }
    </script>
    </head>
    <body></body>
    </html>
    """
    cards = sources.parse_longchau(sample_html)
    assert len(cards) == 1
    c = cards[0]
    assert c["name"] == "MEN VI SINH BIFINA BABY 30 GÓI (Hộp)"
    assert c["price_vnd"] == 388800
    assert c["rating"] == 4.8
    assert c["sold"] == 150
    assert c["url"] == "https://nhathuoclongchau.com.vn/thuc-pham-chuc-nang/bifina-baby.html"


def test_parse_ankhang():
    sample_data = {
        "data": {
            "products": [
                {
                    "name": "Men vi sinh Bifina R",
                    "url": "men-uong-cac-loai/men-vi-sinh-bifina-r",
                    "variantName": "Hộp 20 gói",
                    "rate": 4.5,
                    "totalSold": "Đã bán 276",
                    "productPrices": [{"price": 386000.0}],
                },
                {
                    "name": "Sản phẩm không có giá",
                    "productPrices": [],
                }
            ]
        }
    }
    cards = sources.parse_ankhang(sample_data)
    assert len(cards) == 1
    c = cards[0]
    assert c["name"] == "Men vi sinh Bifina R (Hộp 20 gói)"
    assert c["price_vnd"] == 386000
    assert c["rating"] == 4.5
    assert c["sold"] == 276
    assert c["url"] == "https://www.nhathuocankhang.com/men-uong-cac-loai/men-vi-sinh-bifina-r"


def test_parse_pharmacity():
    sample_data = {
        "data": {
            "items": [
                {
                    "name": "Men vi sinh sống Biolac",
                    "slug": "thuoc-men-vi-sinh-song-biolac",
                    "variants": [
                        {
                            "unit_name": "Vỉ",
                            "price": 9600,
                            "is_sale_unit": True,
                        },
                        {
                            "unit_name": "Hộp",
                            "price": 96000,
                            "is_sale_unit": False,
                        }
                    ],
                    "sub_data": {
                        "score": 4.91,
                        "total_sold": 10942,
                    }
                }
            ]
        }
    }
    cards = sources.parse_pharmacity(sample_data)
    assert len(cards) == 1
    c = cards[0]
    assert c["name"] == "Men vi sinh sống Biolac (Vỉ)"
    assert c["price_vnd"] == 9600
    assert c["rating"] == 4.91
    assert c["sold"] == 10942
    assert c["url"] == "https://www.pharmacity.vn/thuoc-men-vi-sinh-song-biolac"


def test_normalize_and_site_keyword():
    assert engine.normalize_medicine_query("tìm thuốc men vi sinh") == "men vi sinh"
    assert engine.normalize_medicine_query("mua thực phẩm chức năng omega 3") == "omega 3"
    assert engine.site_medicine_keyword("men vi sinh long châu") == "men vi sinh"
    assert engine.site_medicine_keyword("panadol tại nhà thuốc an khang") == "panadol"
    assert engine.site_medicine_keyword("thuốc nhỏ mắt ở pharmacity") == "thuốc nhỏ mắt"


def test_parse_criteria():
    assert engine.parse_criteria("men vi sinh dưới 200k") == {"max_price": 200000}
    assert engine.parse_criteria("thuốc bổ mắt tối đa 500 nghìn") == {"max_price": 500000}
    assert engine.parse_criteria("panadol") == {}


def test_filter_and_rank():
    cards = [
        {"name": "Men vi sinh loại A", "price_vnd": 300000, "rating": 4.5, "sold": 100},
        {"name": "Men vi sinh loại B", "price_vnd": 100000, "rating": 4.8, "sold": 500},
        {"name": "Thuốc đau đầu C", "price_vnd": 50000, "rating": 5.0, "sold": 10},
    ]
    # Filter by token 'vi sinh'
    res = engine._filter_and_rank_cards(cards, "men vi sinh", {})
    assert len(res) == 2
    # B has higher rating than A
    assert res[0]["name"] == "Men vi sinh loại B"

    # Filter with max_price <= 200000
    res_price = engine._filter_and_rank_cards(cards, "men vi sinh", {"max_price": 200000})
    assert len(res_price) == 1
    assert res_price[0]["name"] == "Men vi sinh loại B"

    # Sort 'rẻ nhất'
    res_cheap = engine._filter_and_rank_cards(cards, "men vi sinh rẻ nhất", {})
    assert res_cheap[0]["price_vnd"] == 100000


def test_format_pharmacy_results():
    results = [
        (
            {"source": "Nhà thuốc Long Châu", "web_url": "https://nhathuoclongchau.com.vn"},
            [{"name": "Men vi sinh A (Hộp)", "price_vnd": 200000, "rating": 4.5, "sold": 50, "url": "https://lc.vn/a"}]
        ),
        (
            {"source": "Pharmacity", "web_url": "https://www.pharmacity.vn"},
            [{"name": "Men vi sinh B (Vỉ)", "price_vnd": 50000, "rating": 4.8, "sold": 1200, "url": "https://pmc.vn/b"}]
        )
    ]
    formatted = engine._format_pharmacy_results("men vi sinh", {}, results)
    assert "| Sản phẩm | Giá niêm yết | Đánh giá | Đã bán | Nguồn |" in formatted
    assert "Men vi sinh A (Hộp)" in formatted
    assert "200.000₫" in formatted
    assert "⭐ 4.5" in formatted
    assert "1.200" in formatted
    assert "[Nhà thuốc Long Châu](https://lc.vn/a)" in formatted
    assert "[Pharmacity](https://pmc.vn/b)" in formatted
    assert "không bán thuốc và không thay thế tư vấn y khoa" in formatted


@pytest.mark.asyncio
async def test_search_medicine_e2e(monkeypatch):
    """Test e2e search_medicine with mocked browser."""
    from engine.tools.browser import browser

    async def mock_fetch_listing_html(url):
        return """
        <script id="__NEXT_DATA__" type="application/json">
        {"props":{"pageProps":{"initProducts":{"products":[{"name":"Men A","slug":"a","rating":4.5,"sold":10,"price":{"measureUnitName":"Hộp","price":100000}}]}}}}
        </script>
        """

    async def mock_post_json(url, body, headers=None):
        return {
            "data": {
                "products": [
                    {"name": "Men B", "url": "b", "variantName": "Gói", "rate": 4.8, "totalSold": "100", "productPrices": [{"price": 120000}]}
                ]
            }
        }

    async def mock_get_json(url, headers=None):
        return {
            "data": {
                "items": [
                    {"name": "Men C", "slug": "c", "variants": [{"unit_name": "Ống", "price": 150000, "is_sale_unit": True}], "sub_data": {"score": 4.9, "total_sold": 500}}
                ]
            }
        }

    monkeypatch.setattr(browser, "fetch_listing_html", mock_fetch_listing_html)
    monkeypatch.setattr(browser, "post_json", mock_post_json)
    monkeypatch.setattr(browser, "get_json", mock_get_json)

    res = await engine.search_medicine("men vi sinh")
    assert "Kết quả tra giá thuốc cho **men vi sinh**:" in res
    assert "Men A (Hộp)" in res
    assert "Men B (Gói)" in res
    assert "Men C (Ống)" in res
    assert "100.000₫" in res
    assert "120.000₫" in res
    assert "150.000₫" in res
