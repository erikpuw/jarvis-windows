"""Đọc dữ liệu thuốc và dược phẩm có cấu trúc từ các chuỗi nhà thuốc lớn tại Việt Nam:
Long Châu, An Khang và Pharmacity.

Chuẩn hóa về thẻ sản phẩm dict:
name: str (kèm quy cách đóng gói nếu có)
price_vnd: int (giá niêm yết hoặc giá sau chiết khấu)
rating: float | None
sold: int
url: str
"""
import json
import re
from urllib.parse import quote_plus

LONGCHAU_BASE = "https://nhathuoclongchau.com.vn"
ANKHANG_BASE = "https://www.nhathuocankhang.com"
PHARMACITY_BASE = "https://www.pharmacity.vn"

ANKHANG_API = "https://webapi.nhathuocankhang.com/gw/bus-ankhang-tmdt/api/Search/GetProductSearchV2"
PHARMACITY_API = "https://api-gateway.pharmacity.vn/pmc-ecm-product/api/v2/public/search/index"

ANKHANG_HEADERS = {
    "Origin": ANKHANG_BASE,
    "Referer": f"{ANKHANG_BASE}/",
    "Content-Type": "application/json",
}

PHARMACITY_HEADERS = {
    "Origin": PHARMACITY_BASE,
    "Referer": f"{PHARMACITY_BASE}/",
}


def parse_sold(text: str) -> int:
    """"20,5k" -> 20500, "Đã bán 276" -> 276, "10.942" -> 10942, rỗng/lạ -> 0."""
    if not text:
        return 0
    cleaned = str(text).strip().lower()
    m_k = re.search(r"(\d+(?:[.,]\d+)?)\s*k\b", cleaned)
    if m_k:
        num = float(m_k.group(1).replace(",", "."))
        return int(num * 1000)
    digits = re.sub(r"(?<=\d)[.,](?=\d{3}(?:\D|$))", "", cleaned)
    m_num = re.search(r"\d+", digits)
    return int(m_num.group(0)) if m_num else 0


def _card(name: str, price: int, url: str, *, rating: float | None = None, sold: int = 0) -> dict:
    return {
        "name": name,
        "price_vnd": price,
        "rating": rating,
        "sold": sold,
        "url": url,
    }


# ----------------------------------------------------------------------
# 1. Nhà thuốc Long Châu (Next.js Pages Router -> __NEXT_DATA__)
# ----------------------------------------------------------------------

def longchau_search_url(keyword: str) -> str:
    return f"{LONGCHAU_BASE}/tim-kiem?s={quote_plus(keyword.strip())}"


def parse_longchau(html: str) -> list[dict]:
    """Trích xuất danh sách sản phẩm từ script __NEXT_DATA__ trong HTML của Long Châu."""
    match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
    if not match:
        return []
    try:
        data = json.loads(match.group(1))
    except (json.JSONDecodeError, ValueError):
        return []

    products = (
        data.get("props", {})
        .get("pageProps", {})
        .get("initProducts", {})
        .get("products", [])
    )
    cards = []
    for p in products:
        p_price = p.get("price") or {}
        disc = p_price.get("discount") or {}
        price = disc.get("finalPrice") or p_price.get("price") or 0
        try:
            price_int = int(round(float(price)))
        except (ValueError, TypeError):
            continue
        if price_int <= 0:
            continue

        unit = (p_price.get("measureUnitName") or "").strip()
        name = " ".join((p.get("name") or "").split())
        if unit and unit.lower() not in name.lower():
            name = f"{name} ({unit})"

        slug = (p.get("slug") or "").lstrip("/")
        url = f"{LONGCHAU_BASE}/{slug}" if slug else longchau_search_url(name)
        rate = p.get("rating")
        try:
            rating = float(rate) if rate and float(rate) > 0 else None
        except (ValueError, TypeError):
            rating = None

        cards.append(_card(
            name,
            price_int,
            url,
            rating=rating,
            sold=int(p.get("sold") or 0),
        ))
    return cards


# ----------------------------------------------------------------------
# 2. Nhà thuốc An Khang (MWG REST API Gateway)
# ----------------------------------------------------------------------

def ankhang_search_body(keyword: str, page_size: int = 20, province_id: int = 1027) -> dict:
    """Body gửi lên Gateway của An Khang (mặc định tỉnh 1027: TP.HCM)."""
    return {
        "provinceId": province_id,
        "pageSize": page_size,
        "pageIndex": 0,
        "filters": [],
        "keyWord": keyword.strip(),
        "sellerId": 0,
    }


def parse_ankhang(data: dict) -> list[dict]:
    """JSON từ webapi.nhathuocankhang.com/gw/bus-ankhang-tmdt/api/Search/GetProductSearchV2."""
    products = (data.get("data") or {}).get("products") or []
    cards = []
    for p in products:
        prices = p.get("productPrices") or []
        if not prices:
            continue
        try:
            price_int = int(round(float(prices[0].get("price") or 0)))
        except (ValueError, TypeError):
            continue
        if price_int <= 0:
            continue

        package = (p.get("variantName") or p.get("packageValue") or "").strip()
        raw_name = p.get("name") or p.get("akProductName") or ""
        name = " ".join(raw_name.split())
        if package and package.lower() not in name.lower():
            name = f"{name} ({package})"

        url_path = (p.get("url") or "").lstrip("/")
        url = f"{ANKHANG_BASE}/{url_path}" if url_path else ANKHANG_BASE

        rate = p.get("rate")
        try:
            rating = float(rate) if rate and float(rate) > 0 else None
        except (ValueError, TypeError):
            rating = None

        sold = parse_sold(p.get("totalSold"))
        cards.append(_card(name, price_int, url, rating=rating, sold=sold))
    return cards


# ----------------------------------------------------------------------
# 3. Pharmacity (Public REST API Gateway)
# ----------------------------------------------------------------------

def pharmacity_search_url(keyword: str, limit: int = 20) -> str:
    return (
        f"{PHARMACITY_API}?platform=1&index=1&limit={limit}&total=0"
        f"&refresh=true&keyword={quote_plus(keyword.strip())}"
    )


def parse_pharmacity(data: dict) -> list[dict]:
    """JSON từ api-gateway.pharmacity.vn/pmc-ecm-product/api/v2/public/search/index."""
    items = (data.get("data") or {}).get("items") or []
    cards = []
    for p in items:
        variants = p.get("variants") or []
        # Ưu tiên đơn vị bán lẻ (is_sale_unit=True) có giá
        variant = next(
            (v for v in variants if v.get("is_sale_unit") and v.get("price")),
            variants[0] if variants else {},
        )
        try:
            price_int = int(round(float(variant.get("price") or 0)))
        except (ValueError, TypeError):
            continue
        if price_int <= 0:
            continue

        unit = (variant.get("unit_name") or "").strip()
        name = " ".join((p.get("name") or "").split())
        if unit and unit.lower() not in name.lower():
            name = f"{name} ({unit})"

        slug = (p.get("slug") or "").lstrip("/")
        url = f"{PHARMACITY_BASE}/{slug}" if slug else f"{PHARMACITY_BASE}/search?keyword={quote_plus(name)}"

        sub = p.get("sub_data") or {}
        score = sub.get("score")
        try:
            rating = float(score) if score and float(score) > 0 else None
        except (ValueError, TypeError):
            rating = None

        try:
            sold = int(sub.get("total_sold") or 0)
        except (ValueError, TypeError):
            sold = 0

        cards.append(_card(name, price_int, url, rating=rating, sold=sold))
    return cards


# ----------------------------------------------------------------------
# Danh sách nguồn nhà thuốc
# ----------------------------------------------------------------------

def build_pharmacy_sources(keyword: str) -> list[dict]:
    kw = keyword.strip()
    return [
        {
            "source": "Nhà thuốc Long Châu",
            "type": "longchau",
            "url": longchau_search_url(kw),
            "web_url": longchau_search_url(kw),
        },
        {
            "source": "Nhà thuốc An Khang",
            "type": "ankhang",
            "url": ANKHANG_API,
            "body": ankhang_search_body(kw),
            "headers": ANKHANG_HEADERS,
            "web_url": f"{ANKHANG_BASE}/tim-kiem?keyword={quote_plus(kw)}&source=112",
        },
        {
            "source": "Pharmacity",
            "type": "pharmacity",
            "url": pharmacity_search_url(kw),
            "headers": PHARMACITY_HEADERS,
            "web_url": f"{PHARMACITY_BASE}/search?keyword={quote_plus(kw)}&order=desc&order_by=de-xuat",
        },
    ]
