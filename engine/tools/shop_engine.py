"""Tra cứu giá sản phẩm từ các trang bán lẻ đã được người dùng phê duyệt."""

from __future__ import annotations

import asyncio
import logging
import re
import unicodedata
from urllib.parse import quote, quote_plus

from engine.tools import shop_sources as sources_mod
from engine.tools.browser import browser


log = logging.getLogger(__name__)

# Quy tắc định dạng cho LLM vòng 2 — bàn giao từ actions.py cho tool sở hữu
SUMMARY_RULES: dict[str, str] = {
    "search_products": (
        "QUY TẮC ĐỊNH DẠNG TRA GIÁ SẢN PHẨM BẮT BUỘC:\n"
        "- Giữ nguyên tên sản phẩm, giá niêm yết, nguồn và liên kết từ kết quả công cụ.\n"
        "- Không tự suy đoán hoặc bổ sung giá không có trong dữ liệu nguồn.\n"
        "- Nếu công cụ đang hỏi địa điểm AEON hoặc LOTTE, chỉ chuyển nguyên câu hỏi đó cho người dùng.\n"
        "- Khi bảng có cột Đánh giá/Đã bán: giữ nguyên bảng, nhận xét ngắn vì sao các mẫu đứng đầu hợp nhu cầu, "
        "chỉ dựa trên tên, giá, sao, lượt bán trong bảng. Tiêu chí người dùng mà bảng không có (kiểu cửa, loại động cơ…) "
        "phải nói rõ là chưa kiểm chứng, nên xem chi tiết ở liên kết."
    ),
}

_APPLIANCE_KW = (
    "máy giặt", "tủ lạnh", "tivi", "ti vi", "điều hòa", "máy lạnh", "nồi chiên", "nồi cơm",
    "lò vi sóng", "máy lọc", "máy hút bụi", "quạt", "bếp từ", "máy sấy", "máy rửa chén",
    "máy nước nóng", "robot hút bụi",
)
_TECH_KW = (
    "iphone", "ipad", "macbook", "laptop", "legion", "thinkpad", "ram",
    "ddr", "ssd", "cpu", "gpu", "điện thoại", "máy tính", "tai nghe",
    "sạc", "màn hình", "samsung", "xiaomi", "oppo", "vivo",
)
_GROCERY_KW = (
    "đi chợ", "thịt", "gà", "heo", "bò", "cá", "tôm", "rau", "củ",
    "trái cây", "kimchi", "kim chi", "sữa", "gạo", "mì", "nước",
    "gia vị", "thực phẩm", "bánh", "kẹo",
)
_PRICE_RE = re.compile(
    r"(?P<price>\d{1,3}(?:[.\s]\d{3})+|\d{4,})\s*(?:₫|đ|vnđ|vnd)(?!\w)",
    re.IGNORECASE,
)
_NOISE_RE = re.compile(
    r"^(?:đăng nhập|giỏ hàng|danh mục|xem thêm|mua ngay|so sánh|"
    r"trang chủ|khuyến mãi|sản phẩm|tìm kiếm|giảm|giam)$",
    re.IGNORECASE,
)
_NON_PRODUCT_PREFIXES = (
    "css_prices",
    "smember",
    "s-student",
    "tra gop",
    "them vao so sanh",
)
_QUERY_STOPWORDS = frozenset({
    "tim", "kiem", "tra", "cuu", "xem", "mua", "gia", "san", "pham",
})
# Phụ kiện/dịch vụ trôi vào kết quả "iphone 17 pro": bỏ trừ khi người dùng chính là tìm loại đó
_ACCESSORY_PREFIXES = ("op lung", "dan sticker", "mieng dan", "s-buyback", "kinh cuong luc", "bao da")
_PRODUCT_QUERY_PREFIX_RE = re.compile(
    r"^(?:(?:hãy|giúp|vui\s+lòng|làm\s+ơn)\s+)?"
    r"(?:tìm(?:\s+kiếm)?|tra(?:\s+cứu)?|xem)\s+"
    r"(?:(?:sản\s+ph(?:ẩm|ầm)|mặt\s+hàng|công\s+nghệ|bách\s+hóa|giá)\s+)?",
    re.IGNORECASE,
)

LOTTE_STORES = {
    "nam sai gon": ("vi-nsg", "LOTTE Mart Nam Sài Gòn"),
    "nam sai gòn": ("vi-nsg", "LOTTE Mart Nam Sài Gòn"),
    "binh duong": ("vi-bdg", "LOTTE Mart Bình Dương"),
    "bình dương": ("vi-bdg", "LOTTE Mart Bình Dương"),
    "da nang": ("vi-dda", "LOTTE Mart Đà Nẵng"),
    "đà nẵng": ("vi-dda", "LOTTE Mart Đà Nẵng"),
    "ba dinh": ("vi-bdh", "LOTTE Mart Ba Đình"),
    "ba đình": ("vi-bdh", "LOTTE Mart Ba Đình"),
}


def _is_unwanted_accessory(plain_name: str, plain_query: str) -> bool:
    """Phụ kiện/dịch vụ trôi vào kết quả: bỏ trừ khi người dùng chính là tìm loại đó."""
    return plain_name.startswith(_ACCESSORY_PREFIXES) and not any(
        prefix in plain_query for prefix in _ACCESSORY_PREFIXES if plain_name.startswith(prefix)
    )


def _plain(text: str) -> str:
    normalized = unicodedata.normalize("NFD", text.lower())
    return "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")


def _query_tokens(query: str) -> set[str]:
    return {
        token
        for token in re.findall(r"\w+", _plain(query))
        if len(token) >= 3 and token not in _QUERY_STOPWORDS
    }


def _name_after_price(lines: list[str], index: int, query_tokens: set[str]) -> str:
    """FPT xếp giá trước tên (giá gốc, % giảm, giá sale, 'Giảm Xđ', hết giờ, rồi tên).
    Chỉ gọi cho dòng giá trần — nhìn về sau vài dòng để lấy tên thật của sản phẩm."""
    for look in range(index + 1, min(index + 7, len(lines))):
        candidate = lines[look].strip(" :-|")
        plain_candidate = _plain(candidate)
        if (
            len(candidate) < 4
            or _NOISE_RE.match(candidate)
            or plain_candidate.startswith(_NON_PRODUCT_PREFIXES)
        ):
            continue
        if query_tokens and not any(
            re.search(rf"\b{re.escape(token)}\b", plain_candidate)
            for token in query_tokens
        ):
            continue
        if _PRICE_RE.search(candidate):
            continue
        return candidate
    return ""


def normalize_product_query(query: str) -> str:
    """Bỏ tiền tố ra lệnh, chỉ giữ từ khóa sản phẩm cho website bán lẻ."""
    cleaned = _PRODUCT_QUERY_PREFIX_RE.sub("", query.strip(), count=1).strip()
    return cleaned or query.strip()


def _has_kw(text: str, keywords: tuple[str, ...]) -> bool:
    """Khớp nguyên từ: "cá" không dính "các", "ram" không dính "program"."""
    return any(re.search(rf"(?<!\w){re.escape(kw)}(?!\w)", text) for kw in keywords)


def classify_product_query(query: str) -> str:
    """Phân loại nguồn cần tra mà không đưa logic mua sắm vào search_engine."""
    text = query.lower()
    if _has_kw(text, _APPLIANCE_KW):
        return "appliance"
    if _has_kw(text, _TECH_KW):
        return "technology"
    if _has_kw(text, _GROCERY_KW):
        return "grocery"
    return "general"


_KG_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*kg", re.IGNORECASE)
_MIN_KG_RE = re.compile(
    r"(?:từ|trên|ít nhất)\s*(\d+(?:[.,]\d+)?)\s*kg|(\d+(?:[.,]\d+)?)\s*kg\s*(?:trở lên|trở đi)",
    re.IGNORECASE,
)
_BUDGET_RE = re.compile(
    r"(?:dưới|tối đa|không quá|ngân sách)\s*(\d+(?:[.,]\d+)?)\s*(triệu|tr|nghìn|k)\b",
    re.IGNORECASE,
)
_TOP_RE = re.compile(r"\btop\s*(\d+)", re.IGNORECASE)
_COMPARE_RE = re.compile(
    r"^\s*so sánh\s+(.+?)\s+(?:và|với|vs\.?|hay)\s+(.+?)\s*$", re.IGNORECASE
)
_RANK_INTENT_RE = re.compile(
    r"\btop\b|tốt nhất|nên mua|ưu tiên|lọc giúp|dưới\s*\d|từ\s*\d+(?:[.,]\d+)?\s*kg",
    re.IGNORECASE,
)


def _num(text: str) -> float:
    return float(text.replace(",", "."))


def parse_criteria(query: str) -> dict:
    """Rút tiêu chí đo được từ câu nhu cầu: dung tích tối thiểu (kg), ngân sách, top N."""
    kg = _MIN_KG_RE.search(query)
    budget = _BUDGET_RE.search(query)
    top = _TOP_RE.search(query)
    unit = {"triệu": 1_000_000, "tr": 1_000_000, "nghìn": 1_000, "k": 1_000}
    return {
        "min_kg": _num(kg.group(1) or kg.group(2)) if kg else None,
        "max_price": int(_num(budget.group(1)) * unit[budget.group(2).lower()]) if budget else None,
        "top_n": int(top.group(1)) if top else 5,
    }


_FILLER_RE = re.compile(
    r"(?<!\w)(?:giá|hôm nay|hiện nay|hiện tại|bây giờ|mới nhất|bao nhiêu|tư vấn|giúp tôi|giúp|cho tôi|tôi muốn|muốn|mua|chọn)(?!\w)",
    re.IGNORECASE,
)


def site_keyword(query: str) -> str:
    """Từ khóa gõ vào ô tìm kiếm của shop: bỏ tiêu chí (đã có parse_criteria), từ đệm giá/thời gian ("giá … hôm nay"
    làm shop không ra sản phẩm); câu nhu cầu dài thì lấy loại hàng xuất hiện sớm nhất."""
    query = query.strip()
    if "\n" not in query and len(query.split()) <= 12:
        plain = " ".join(_BUDGET_RE.sub(" ", _MIN_KG_RE.sub(" ", _TOP_RE.sub(" ", query))).split())
        plain = " ".join(_FILLER_RE.sub(" ", re.sub(r"^đánh giá\s+", "", plain, flags=re.IGNORECASE)).split())
        return plain or query
    text = query.lower()
    hits = [
        (m.start(), kw)
        for kw in _APPLIANCE_KW + _TECH_KW + _GROCERY_KW
        if (m := re.search(rf"(?<!\w){re.escape(kw)}(?!\w)", text))
    ]
    return min(hits)[1] if hits else query.splitlines()[0][:60]


_DOOR_RE = re.compile(r"cửa (?:trên|ngang|trước)", re.IGNORECASE)


def extra_queries(term: str, query: str, criteria: dict) -> list[str]:
    """Truy vấn hẹp thêm cho shop từ tiêu chí đo được, để lọt các mẫu nằm ngoài ~20 kết quả đầu."""
    extras = []
    if criteria.get("min_kg"):
        extras.append(f"{term} {int(criteria['min_kg'])} kg")
    door = _DOOR_RE.search(query)
    if door:
        extras.append(f"{term} {door.group(0).lower()}")
    return extras


def split_compare(query: str) -> list[str]:
    """"so sánh A và B" -> [A, B]; câu khác -> []."""
    match = _COMPARE_RE.match(query)
    return [match.group(1), match.group(2)] if match else []


def _score(card: dict) -> float:
    """Sao trung bình có kéo về mức 4.5 khi ít lượt bán: 5★ với 57 lượt không vượt 4.9★ với 20 nghìn lượt.
    Nguồn không công bố sao (CellphoneS, FPT Shop) tính trung tính 4.5, không bị 0 điểm đẩy xuống cuối."""
    sold = card.get("sold") or 0
    return ((card.get("rating") or 4.5) * sold + 4.5 * 200) / (sold + 200)


def rank_cards(cards: list[dict], criteria: dict, *, sort: bool = True) -> list[dict]:
    """Lọc theo kg/ngân sách đọc được từ tên, rồi xếp theo sao đánh giá, lượt bán."""
    kept = []
    for card in cards:
        kg = _KG_RE.search(card["name"])
        if criteria.get("min_kg") and kg and _num(kg.group(1)) < criteria["min_kg"]:
            continue
        if criteria.get("max_price") and card["price_vnd"] > criteria["max_price"]:
            continue
        kept.append(card)
    if sort:
        kept.sort(key=_score, reverse=True)
    return kept[: criteria.get("top_n") or 5]


def build_source_urls(
    query: str,
    category: str,
    *,
    lotte_store: str | None = None,
) -> list[dict[str, str]]:
    """Tạo URL tìm kiếm theo đúng thanh tìm kiếm của từng nguồn."""
    encoded = quote_plus(query.strip())
    if category == "appliance":
        return [{
            "source": "Điện máy xanh",
            "url": f"https://www.dienmayxanh.com/tim-kiem?key={encoded}",
        }]
    if category == "technology":
        return [
            {
                "source": "Thế giới di động",
                "url": f"https://www.thegioididong.com/tim-kiem?key={encoded}",
            },
            {
                "source": "CellphoneS",
                "url": f"https://cellphones.com.vn/catalogsearch/result?q={encoded}",
            },
            {
                "source": "FPT Shop",
                "url": f"https://fptshop.com.vn/tim-kiem?s={encoded}",
            },
        ]
    if category == "general":
        return [{
            "source": "Shopee",
            "url": f"https://shopee.vn/search?keyword={encoded}",
        }]

    sources = [
        {
            "source": "Bách Hóa Xanh",
            "keyword": query.strip(),
            "url": f"https://www.bachhoaxanh.com/tim-kiem?key={encoded}",
        },
        {
            "source": "AEONESHOP",
            "url": f"https://aeoneshop.com/products/search/{quote(query.strip())}",
        },
    ]
    if lotte_store:
        sources.append({
            "source": "LOTTE Mart",
            "store": lotte_store,
            "url": f"https://www.lottemart.vn/{lotte_store}/category?q={encoded}",
        })
    return sources


def _lotte_choice(text: str) -> tuple[str, str] | None:
    plain = _plain(text)
    if re.fullmatch(r"vi-[a-z]{3}", plain.strip()):
        return plain.strip(), plain.strip()
    for label, value in LOTTE_STORES.items():
        if _plain(label) in plain:
            return value
    return None


def _extract_rows(
    text: str,
    source: str,
    url: str,
    limit: int = 5,
    *,
    query: str = "",
) -> list[dict[str, str]]:
    query_tokens = _query_tokens(query)
    lines = [" ".join(line.split()) for line in text.splitlines()]
    lines = [
        line for line in lines
        if line and not _plain(line).startswith("css_prices:")
    ]
    rows_by_name: dict[str, dict[str, str]] = {}
    seen: set[tuple[str, str]] = set()
    for index, line in enumerate(lines):
        match = _PRICE_RE.search(line)
        if not match:
            continue
        label = line[:match.start()].strip(" :-|")
        if label:
            if not (
                len(label) >= 4
                and not _NOISE_RE.match(label)
                and not _plain(label).startswith(_NON_PRODUCT_PREFIXES)
            ):
                continue
            name = label
        else:
            prev_name = ""
            if index:
                prev = lines[index - 1].strip(" :-|")
                if (
                    len(prev) >= 4
                    and not _NOISE_RE.match(prev)
                    and not _plain(prev).startswith(_NON_PRODUCT_PREFIXES)
                    and not _PRICE_RE.search(prev)
                ):
                    prev_name = prev
            name = prev_name
            if not name:
                name = _name_after_price(lines, index, query_tokens)
                if not name:
                    continue
        plain_name = _plain(name)
        if _is_unwanted_accessory(plain_name, _plain(query)):
            continue
        if query_tokens and not any(
            re.search(rf"\b{re.escape(token)}\b", plain_name)
            for token in query_tokens
        ):
            continue
        price = match.group(0).replace(" ", "")
        key = (name.casefold(), price.casefold())
        if key in seen:
            continue
        seen.add(key)
        rows_by_name[name.casefold()] = {
            "name": name[:140],
            "price": price,
            "source": source,
            "url": url,
        }
        if len(rows_by_name) >= limit:
            break
    return list(rows_by_name.values())


_CARD_SOURCES = frozenset({"Điện máy xanh", "Thế giới di động", "CellphoneS", "FPT Shop", "Bách Hóa Xanh"})


def _card_row(card: dict, source: str) -> dict[str, str]:
    return {
        "name": card["name"][:140].replace("|", "-"),   # "| Chính hãng" làm vỡ bảng markdown
        "price": f"{card['price_vnd']:,}".replace(",", ".") + "₫",
        "rating": (f"{card['rating']:g}★" + (f" ({card['reviews']})" if card.get("reviews") else "")) if card.get("rating") else "—",
        "sold": f"{card['sold']:,}".replace(",", ".") if card.get("sold") else "—",
        "source": source,
        "url": card["url"],
    }


async def _load_cards(item: dict[str, str], url: str) -> list[dict]:
    if item["source"] == "Bách Hóa Xanh":  # API công khai của chính trang: trang HTML không có sản phẩm khi chưa chọn cửa hàng
        headers = {"Origin": sources_mod.BHX_BASE, "Referer": f"{sources_mod.BHX_BASE}/tim-kiem"}
        data = await browser.post_json(sources_mod.BHX_SEARCH_API, sources_mod.bhx_search_body(item["keyword"]), headers=headers)
        cards = sources_mod.parse_bhx(data)
        if len(cards) < 5:  # ít khớp đúng thì trang kế là các từ gần nghĩa ("kimchi" -> "kim chi")
            more = await browser.post_json(sources_mod.BHX_SEARCH_API, sources_mod.bhx_search_body(item["keyword"], page=1), headers=headers)
            cards += sources_mod.parse_bhx(more)
        return cards
    return sources_mod.parse_listing(url, await browser.fetch_listing_html(url))


def _missing_model_tokens(term: str, cards: list[dict]) -> list[str]:
    """Số/mã máy trong từ khóa mà không thẻ nào có ("iphone 18" khi shop chỉ có 17): shop trả mẫu gần nhất,
    không báo thì người dùng tưởng đó là mẫu mình hỏi."""
    names = " ".join(_plain(card["name"]) for card in cards)
    tokens = [t for t in re.findall(r"\w+", _plain(term)) if len(t) >= 2 and any(ch.isdigit() for ch in t)]
    return [t for t in dict.fromkeys(tokens) if not re.search(rf"(?<!\w){re.escape(t)}(?!\w)", names)]


async def _fetch_cards(
    item: dict[str, str],
    term: str,
    criteria: dict,
    *,
    sort: bool,
    per_term: int | None,
) -> tuple[dict[str, str], list[dict[str, str]]]:
    # Mỗi trang tìm kiếm chỉ trả ~20 mẫu nên gộp thêm truy vấn hẹp ("máy giặt 11 kg", "cửa trên")
    pages = await asyncio.gather(
        *(_load_cards(item, url) for url in [item["url"], *item.get("alt_urls", ())]),
        return_exceptions=True,
    )
    if isinstance(pages[0], Exception):
        raise pages[0]
    cards = list({c["url"]: c for page in pages if not isinstance(page, Exception) for c in page}.values())
    cards = [c for c in cards if not _is_unwanted_accessory(_plain(c["name"]), _plain(term))]
    cards = list({(c["name"].casefold(), c["price_vnd"]): c for c in reversed(cards)}.values())[::-1]  # màu/sku khác, cùng tên cùng giá
    # so sánh: lấy mẫu khớp nhất của từng sản phẩm, không lọc theo nhu cầu
    kept = cards[:per_term] if per_term else rank_cards(cards, criteria, sort=sort)
    if cards and not kept:
        item = {**item, "note": f"có {len(cards)} sản phẩm nhưng không mẫu nào đạt tiêu chí"}
    elif kept and (missing := _missing_model_tokens(term, cards)):
        item = {**item, "warn": f"{item['source']} không có sản phẩm khớp «{', '.join(missing)}», đây là kết quả gần nhất"}
    return item, [_card_row(card, item["source"]) for card in kept]


async def _fetch_source(
    item: dict[str, str],
    query: str,
    criteria: dict | None = None,
    *,
    sort: bool = False,
    per_term: int | None = None,
) -> tuple[dict[str, str], list[dict[str, str]]]:
    try:
        if item["source"] in _CARD_SOURCES:
            result = await _fetch_cards(item, query, criteria or {}, sort=sort, per_term=per_term)
            if result[1] or result[0].get("note") or item["source"] == "Bách Hóa Xanh":
                return result
            # trang không có thẻ (vd Thế Giới Di Động chuyển thẳng sang trang chi tiết): đọc text như nguồn khác
        page = await browser.visit_product_listing(item["url"])
        return item, _extract_rows(
            page.text_content,
            item["source"],
            item["url"],
            query=query,
        )
    except Exception as exc:
        log.warning("Không thể tra giá từ %s: %s", item["source"], exc)
        return item, []


def _criteria_note(criteria: dict) -> str:
    parts = []
    if criteria.get("min_kg"):
        parts.append(f"từ {criteria['min_kg']:g} kg")
    if criteria.get("max_price"):
        parts.append("giá ≤ " + f"{criteria['max_price']:,}".replace(",", ".") + "₫")
    return f"Đã lọc theo: {', '.join(parts)}; xếp theo sao đánh giá rồi lượt bán." if parts else ""


def _format_results(
    query: str,
    criteria: dict,
    fetched: list[tuple[dict[str, str], list[dict[str, str]]]],
) -> str:
    rated = any("rating" in row for _, rows in fetched for row in rows)
    lines = [
        f"Kết quả tra giá cho **{query}**:",
        "",
        "| Sản phẩm | Giá niêm yết | Đánh giá | Đã bán | Nguồn |" if rated
        else "| Sản phẩm | Giá niêm yết | Nguồn |",
        "| :--- | ---: | :---: | ---: | :--- |" if rated else "| :--- | ---: | :--- |",
    ]
    found = False
    for source, rows in fetched:
        for row in rows:
            found = True
            extra = f" {row.get('rating', '—')} | {row.get('sold', '—')} |" if rated else ""
            lines.append(
                f"| {row['name']} | {row['price']} |{extra} "
                f"[{source['source']}]({row['url']}) |"
            )
    if not found:
        notes = [item["note"] for item, _ in fetched if item.get("note")]
        lines = [
            f"Không có kết quả phù hợp cho **{query}**: {'; '.join(notes)}. Thử nới tiêu chí."
            if notes else
            f"Chưa trích xuất được giá có cấu trúc cho **{query}**. "
            "Có thể website đang yêu cầu JavaScript, cookie hoặc xác minh truy cập.",
            "",
            "Bạn có thể xem trực tiếp:",
        ]
        lines.extend(f"- [{item['source']}]({item['url']})" for item, _ in fetched)
    if found and rated and (note := _criteria_note(criteria)):
        lines.extend(["", note])
    lines.extend(f"\nLưu ý: {item['warn']}." for item, _ in fetched if item.get("warn"))
    lines.extend([
        "",
        "Giá và tình trạng hàng có thể thay đổi; Jarvis chỉ tra cứu, không đặt hàng.",
    ])
    return "\n".join(lines)


async def search_products(query: str, ws=None) -> str:
    """Tra giá sản phẩm từ từ khóa hiện tại, không giữ trạng thái mua sắm riêng."""
    original_query = normalize_product_query(query)
    if not original_query:
        return "Vui lòng cho biết tên sản phẩm cần tra giá."

    category = classify_product_query(original_query)
    text = original_query.lower()
    lotte_choice = _lotte_choice(original_query) if category == "grocery" else None
    lotte_store = lotte_choice[0] if lotte_choice else None

    criteria = parse_criteria(original_query)
    compare = split_compare(original_query)
    sort = bool(_RANK_INTENT_RE.search(original_query))
    jobs = []
    for term in compare or [site_keyword(original_query)]:
        sources = build_source_urls(term, category, lotte_store=lotte_store)
        extras = [] if compare else [
            build_source_urls(extra, category) for extra in extra_queries(term, original_query, criteria)
        ]
        for item in sources:
            if item["source"] in _CARD_SOURCES:
                item["alt_urls"] = [u["url"] for alt in extras for u in alt if u["source"] == item["source"]]
        if category == "grocery":
            if "aeon" in text:
                sources = [item for item in sources if item["source"] == "AEONESHOP"]
            elif "lotte" in text and lotte_store:
                sources = [item for item in sources if item["source"] == "LOTTE Mart"]
            elif "bách hóa xanh" in text or "bach hoa xanh" in text:
                sources = [item for item in sources if item["source"] == "Bách Hóa Xanh"]
        jobs += [
            _fetch_source(item, term, criteria, sort=sort, per_term=2 if compare else None)
            for item in sources
        ]
    fetched = await asyncio.gather(*jobs)
    return _format_results(" / ".join(compare or [site_keyword(original_query)]), criteria, list(fetched))
