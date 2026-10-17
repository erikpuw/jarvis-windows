"""Tra cứu giá thuốc và dược phẩm từ 3 chuỗi nhà thuốc lớn: Long Châu, An Khang, Pharmacity."""

from __future__ import annotations

import asyncio
import logging
import re
import unicodedata
from urllib.parse import quote_plus

from engine.tools import pharmacy_sources as sources_mod
from engine.tools.browser import browser

log = logging.getLogger(__name__)

_MEDICINE_PREFIX_RE = re.compile(
    r"^(?:(?:hãy|giúp|vui\s+lòng|làm\s+ơn)\s+)?"
    r"(?:tìm(?:\s+kiếm)?|tra(?:\s+cứu)?|xem|mua|hỏi)\s+"
    r"(?:(?:thuốc|dược\s+phẩm|thực\s+phẩm\s+chức\s+năng|tpcn|sản\s+phẩm|giá)\s+)?",
    re.IGNORECASE,
)

_STORE_CLEANUP_RE = re.compile(
    r"\b(?:ở|tại|trong|của)?\s*(?:nhà\s+thuốc\s+)?(?:long\s+châu|long\s+chau|an\s+khang|ankhang|pharmacity)\b",
    re.IGNORECASE,
)

_RANK_INTENT_RE = re.compile(r"\b(?:tốt\s+nhất|bán\s+chạy|rẻ\s+nhất|đánh\s+giá\s+cao|phổ\s+biến)\b", re.IGNORECASE)

_PRICE_CRITERIA_RE = re.compile(
    r"(?:dưới|tầm|khoảng|giá\s*<=?|tối\s+đa)\s*(\d+(?:[.,]\d+)?)\s*(k|nghìn|ngàn|tr|triệu|đ|vnd|vnđ)?\b",
    re.IGNORECASE,
)

_QUERY_STOPWORDS = frozenset({
    "tim", "kiem", "tra", "cuu", "xem", "mua", "gia", "thuoc", "san", "pham", "duoc",
})


def _plain(text: str) -> str:
    normalized = unicodedata.normalize("NFD", text.lower())
    return "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")


def _query_tokens(query: str) -> set[str]:
    return {
        token
        for token in re.findall(r"\w+", _plain(query))
        if len(token) >= 2 and token not in _QUERY_STOPWORDS
    }


def normalize_medicine_query(query: str) -> str:
    """Loại bỏ câu lệnh chào hỏi và tiền tố, chuẩn hóa từ khóa thuốc."""
    cleaned = _MEDICINE_PREFIX_RE.sub("", query.strip(), count=1).strip()
    return cleaned


def site_medicine_keyword(query: str) -> str:
    """Lọc bỏ tên nhà thuốc khỏi từ khóa để gửi tìm kiếm chính xác."""
    cleaned = _STORE_CLEANUP_RE.sub("", query).strip()
    return re.sub(r"\s+", " ", cleaned) or query.strip()


def parse_criteria(query: str) -> dict:
    criteria: dict = {}
    m = _PRICE_CRITERIA_RE.search(query)
    if m:
        num = float(m.group(1).replace(",", "."))
        unit = (m.group(2) or "").lower()
        if unit in ("k", "nghìn", "ngàn"):
            num *= 1000
        elif unit in ("tr", "triệu"):
            num *= 1_000_000
        criteria["max_price"] = int(num)
    return criteria


def _filter_and_rank_cards(
    cards: list[dict],
    query: str,
    criteria: dict,
    limit: int = 5,
) -> list[dict]:
    tokens = _query_tokens(query)
    filtered = []
    for c in cards:
        name_plain = _plain(c["name"])
        if tokens and not any(t in name_plain for t in tokens):
            continue
        if criteria.get("max_price") and c["price_vnd"] > criteria["max_price"]:
            continue
        filtered.append(c)

    # Ưu tiên: nếu người dùng tìm "rẻ nhất" -> xếp theo giá
    # Nếu "bán chạy" -> xếp theo lượt bán
    # Mặc định -> xếp sao đánh giá cao rồi lượt bán
    q_lower = query.lower()
    if "rẻ nhất" in q_lower or "re nhat" in q_lower or "giá thấp" in q_lower:
        filtered.sort(key=lambda x: x["price_vnd"])
    elif "bán chạy" in q_lower or "ban chay" in q_lower:
        filtered.sort(key=lambda x: x.get("sold") or 0, reverse=True)
    else:
        filtered.sort(key=lambda x: (x.get("rating") or 0, x.get("sold") or 0), reverse=True)

    return filtered[:limit]


async def _fetch_single_source(
    src: dict,
    term: str,
    criteria: dict,
    limit_per_source: int = 5,
) -> tuple[dict, list[dict]]:
    stype = src["type"]
    try:
        if stype == "longchau":
            html = await browser.fetch_listing_html(src["url"])
            raw_cards = sources_mod.parse_longchau(html)
        elif stype == "ankhang":
            data = await browser.post_json(src["url"], src["body"], headers=src["headers"])
            raw_cards = sources_mod.parse_ankhang(data)
        elif stype == "pharmacity":
            data = await browser.get_json(src["url"], headers=src["headers"])
            raw_cards = sources_mod.parse_pharmacity(data)
        else:
            raw_cards = []

        processed = _filter_and_rank_cards(raw_cards, term, criteria, limit=limit_per_source)
        return src, processed
    except Exception as exc:
        log.warning("Lỗi tra cứu thuốc từ %s: %s", src["source"], exc)
        return src, []


def _format_pharmacy_results(
    query: str,
    criteria: dict,
    results: list[tuple[dict, list[dict]]],
) -> str:
    all_cards = [(src, card) for src, cards in results for card in cards]
    if not all_cards:
        lines = [
            f"Chưa tìm thấy thuốc phù hợp cho **{query}**.",
            "",
            "Bạn có thể xem trực tiếp tại các nhà thuốc:",
        ]
        for src, _ in results:
            lines.append(f"- [{src['source']}]({src['web_url']})")
        return "\n".join(lines)

    has_rating = any(c.get("rating") is not None for _, c in all_cards)
    has_sold = any((c.get("sold") or 0) > 0 for _, c in all_cards)

    # Cột động: Đánh giá / Đã bán
    headers = ["Sản phẩm", "Giá niêm yết"]
    aligns = [":---", "---:"]
    if has_rating:
        headers.append("Đánh giá")
        aligns.append(":---:")
    if has_sold:
        headers.append("Đã bán")
        aligns.append("---:")
    headers.append("Nguồn")
    aligns.append(":---")

    lines = [
        f"Kết quả tra giá thuốc cho **{query}**:",
        "",
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(aligns) + " |",
    ]

    for src, card in all_cards:
        price_str = f"{card['price_vnd']:,}".replace(",", ".") + "₫"
        cols = [card["name"], price_str]
        if has_rating:
            rate_str = f"⭐ {card['rating']:.1f}" if card.get("rating") else "—"
            cols.append(rate_str)
        if has_sold:
            sold_count = card.get("sold") or 0
            sold_str = f"{sold_count:,}".replace(",", ".") if sold_count > 0 else "—"
            cols.append(sold_str)
        cols.append(f"[{src['source']}]({card['url']})")
        lines.append("| " + " | ".join(cols) + " |")

    if criteria.get("max_price"):
        lines.extend(["", f"Đã lọc theo: giá ≤ {criteria['max_price']:,}".replace(",", ".") + "₫."])

    lines.extend([
        "",
        "Lưu ý: Giá và tình trạng hàng có thể thay đổi tùy khu vực. Jarvis chỉ tra cứu giá tham khảo, không bán thuốc và không thay thế tư vấn y khoa của bác sĩ/dược sĩ.",
    ])
    return "\n".join(lines)


async def search_medicine(query: str, ws=None) -> str:
    """Tra cứu giá và thông tin thuốc từ Long Châu, An Khang và Pharmacity."""
    raw_query = normalize_medicine_query(query)
    if not raw_query:
        return "Vui lòng cho biết tên thuốc hoặc dược phẩm cần tra cứu."

    target_term = site_medicine_keyword(raw_query)
    criteria = parse_criteria(raw_query)
    all_sources = sources_mod.build_pharmacy_sources(target_term)

    # Lọc nhà thuốc nếu người dùng chỉ định cụ thể
    q_lower = raw_query.lower()
    if "long châu" in q_lower or "long chau" in q_lower:
        sources = [s for s in all_sources if s["type"] == "longchau"]
    elif "an khang" in q_lower or "ankhang" in q_lower:
        sources = [s for s in all_sources if s["type"] == "ankhang"]
    elif "pharmacity" in q_lower:
        sources = [s for s in all_sources if s["type"] == "pharmacity"]
    else:
        sources = all_sources

    jobs = [
        _fetch_single_source(src, target_term, criteria, limit_per_source=4 if len(sources) > 1 else 10)
        for src in sources
    ]
    results = await asyncio.gather(*jobs)
    return _format_pharmacy_results(target_term, criteria, list(results))
