"""Đọc sản phẩm có cấu trúc từ từng nguồn bán lẻ: một nơi duy nhất biết markup/JSON/API của từng trang.
Text thô của trang không dùng được (popup, banner, phụ kiện lẫn vào, tên và giá ghép nhầm dòng); mỗi nguồn
đọc đúng chỗ chứa dữ liệu: DOM thẻ sản phẩm, JSON nhúng của Next.js, hoặc API công khai của chính trang.

Thẻ sản phẩm (dict): name, price_vnd, rating (float|None), sold (int), url; BHX thêm reviews."""
import re
from urllib.parse import urljoin, urlparse

from scrapling.parser import Selector

BHX_SEARCH_API = "https://api.bachhoaxanh.com/gw/search/v2/DataSearch"
BHX_BASE = "https://www.bachhoaxanh.com"
# Cửa hàng mặc định của chính trang web (trình duyệt chưa chọn gì cũng dùng cặp này): TP.HCM.
BHX_PROVINCE_ID, BHX_STORE_ID = 1027, 2546


def parse_sold(text: str) -> int:
    """"20,5k" -> 20500, "473" -> 473, rỗng/lạ -> 0."""
    match = re.fullmatch(r"(\d+(?:[.,]\d+)?)(k?)", (text or "").strip().lower())
    if not match:
        return 0
    return int(float(match.group(1).replace(",", ".")) * (1000 if match.group(2) else 1))


def _vnd(text: str) -> int:
    digits = re.sub(r"\D", "", text or "")
    return int(digits) if digits else 0


def _card(name: str, price: int, url: str, *, rating=None, sold: int = 0) -> dict:
    return {"name": name, "price_vnd": price, "rating": rating, "sold": sold, "url": url}


def parse_dmx(html: str, base_url: str) -> list[dict]:
    """Điện máy Xanh và Thế Giới Di Động chung markup: li.item > a.main-contain[data-name, data-price]."""
    cards = []
    for link in Selector(html).css("li.item a.main-contain"):
        name = (link.attrib.get("data-name") or "").strip()
        try:
            price = int(float(link.attrib.get("data-price") or 0))
        except ValueError:
            price = 0
        if not name or not price:
            continue
        li = link.parent
        rating = (li.css(".vote-txt b::text").get() or "").strip()
        meta = " ".join(li.css(".rating_Compare span::text").getall())
        sold = re.search(r"Đã bán\s*([\d.,]+k?)", meta)
        cards.append(_card(
            name, price, urljoin(base_url, link.attrib.get("href", "")),
            rating=float(rating) if re.fullmatch(r"\d(?:\.\d)?", rating) else None,
            sold=parse_sold(sold.group(1)) if sold else 0,
        ))
    return cards


def parse_cellphones(html: str, base_url: str) -> list[dict]:
    """CellphoneS: .product-info-container, tên ở .product__name h3, giá bán ở .product__price--show."""
    cards = []
    for box in Selector(html).css(".product-info-container"):
        name = " ".join((box.css(".product__name h3::text").get() or "").split())
        price = _vnd(box.css(".product__price--show::text").get())
        href = box.css("a.product__link::attr(href)").get()
        if name and price and href:
            cards.append(_card(name, price, urljoin(base_url, href)))
    return cards


# FPT Shop (Next.js): danh sách nằm trong JSON nhúng dạng chuỗi đã escape; mỗi sku có
# displayName, sku, slug, ... currentPrice. Ràng buộc 1200 ký tự để không nhảy sang sku khác.
_FPT_SKU = re.compile(
    r'\\"displayName\\":\\"(?P<name>[^"\\]+)\\",\\"sku\\":\\"(?P<sku>\w+)\\".{0,1200}?'
    r'\\"slug\\":\\"(?P<slug>[^"\\]+)\\".{0,1200}?\\"currentPrice\\":(?P<price>\d+)',
    re.DOTALL,
)


def parse_fpt(html: str, base_url: str) -> list[dict]:
    cards: dict[str, dict] = {}
    for m in _FPT_SKU.finditer(html):
        price = int(m.group("price"))
        if price and m.group("sku") not in cards:
            cards[m.group("sku")] = _card(m.group("name"), price, urljoin(base_url, "/" + m.group("slug")))
    return list(cards.values())


_LISTING_PARSERS = {
    "dienmayxanh.com": parse_dmx,
    "thegioididong.com": parse_dmx,
    "cellphones.com.vn": parse_cellphones,
    "fptshop.com.vn": parse_fpt,
}


def parse_listing(url: str, html: str) -> list[dict]:
    """Chọn bộ đọc theo tên miền của URL; miền lạ -> []."""
    host = (urlparse(url).hostname or "").removeprefix("www.")
    parser = _LISTING_PARSERS.get(host)
    return parser(html, url) if parser else []


def bhx_search_body(keyword: str, page: int = 0, size: int = 20) -> dict:
    return {"keywords": keyword, "provinceId": BHX_PROVINCE_ID, "storeId": BHX_STORE_ID,
            "pageIndex": page, "pageSize": size, "brandIds": "", "categoryIds": "", "sortStr": ""}


def parse_bhx(data: dict) -> list[dict]:
    """JSON của api.bachhoaxanh.com/gw/search/v2/DataSearch. Giá mặc định là gói nhỏ nhất; hàng bán theo
    cân (netUnitValue = số kg của gói) ghi cỡ gói vào tên để so giá khỏi nhầm."""
    products = ((data or {}).get("data") or {}).get("products") or []
    cards = []
    for item in products:
        prices = item.get("productPrices") or []
        if not prices or not prices[0].get("price"):
            continue
        pack = prices[0].get("netUnitValue") or 0
        suffix = f"{int(round(pack * 1000))} g" if pack and str(item.get("unit", "")).lower() == "kg" else item.get("unit", "")
        card = _card(
            f"{item['name']} ({suffix})" if suffix else item["name"],
            int(round(prices[0]["price"])),
            urljoin(BHX_BASE, item.get("url", "")),
            rating=float(item["rateStar"]) if item.get("rateStar") else None,
            sold=int(item.get("totalUserBuy") or 0),
        )
        card["reviews"] = int(item.get("totalReview") or 0)
        cards.append(card)
    return cards
