"""Thẻ sản phẩm cho nút 👁 trong bảng giá (ngài 2026-10-19).

Bảng giá (shop_engine, pharmacy_engine) ghi lại thẻ theo link lúc tìm: ảnh và giá đã có sẵn từ JSON/HTML của nguồn,
không tải lại từng trang dù nhiều mặt hàng. Thẻ thiếu ảnh (TGDĐ/FPT, nhà thuốc) hoặc link không còn trong bộ nhớ
(JARVIS khởi động lại, mở lại lịch sử) mới tải trang lấy og:image và tiêu đề."""
from collections import OrderedDict

_CARDS: OrderedDict[str, dict] = OrderedDict()
_MAX = 500  # ponytail: chỉ trong RAM, mất khi khởi động lại → nhánh tải trang; lưu DB nếu cần giá sau khởi động lại


def remember(card: dict, source: str) -> None:
    url = card.get("url")
    if not url:
        return
    _CARDS[url] = {
        "name": card.get("name", ""),
        "price": f"{card['price_vnd']:,}".replace(",", ".") + "₫" if card.get("price_vnd") else "",
        "rating": card.get("rating"),
        "sold": card.get("sold") or 0,
        "source": source,
        "url": url,
        "image": card.get("image"),
    }
    _CARDS.move_to_end(url)
    while len(_CARDS) > _MAX:
        _CARDS.popitem(last=False)


async def load(url: str) -> dict | None:
    card = _CARDS.get(url)
    if card and card["image"]:
        return dict(card)
    from engine.tools.browser import browser
    page = await browser.visit(url)
    if not page and not card:
        return None
    if not card:
        from engine.tools.search_engine import get_source_label
        card = {"name": "", "price": "", "rating": None, "sold": 0, "source": get_source_label(url), "url": url,
                "image": None}
    card = dict(card)
    if page:
        card["image"] = card["image"] or page.image_url
        card["name"] = card["name"] or (page.title or "").strip()
    return card if card["name"] or card["image"] else None
