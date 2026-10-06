import asyncio
import json
import logging
import os
import re
import time

from engine.tools.browser import browser
# Consolidated search engine for JARVIS

log = logging.getLogger("jarvis.search_engine")

# Quy tắc định dạng cho LLM vòng 2 — bàn giao từ actions.py cho tool sở hữu
SUMMARY_RULES: dict[str, str] = {
    "get_market_data": (
        "QUY TẮC ĐỊNH DẠNG BẢNG GIÁ THỊ TRƯỜNG BẮT BUỘC:\n"
        "1. COPY NGUYÊN VĂN từng bảng Markdown dạng `| Cột 1 | Cột 2 | Cột 3 |` đã có sẵn trong kết quả công cụ (giá vàng SJC/9999, giá xăng dầu RON95/E5, tỷ giá ngoại tệ USD/Vietcombank, giá gas, giá điện sinh hoạt EVN, giá nước sinh hoạt) — TUYỆT ĐỐI KHÔNG viết lại thành gạch đầu dòng (-) hay đoạn văn.\n"
        "2. Ví dụ mỗi mục phải giữ đúng cấu trúc:\n"
        "   ## 🟡 Giá Vàng SJC\n"
        "   | Sản phẩm | Mua | Bán |\n"
        "   | :---: | :---: | :---: |\n"
        "   | Vàng SJC (1L/10L/1KG) | ... VNĐ/lượng | ... VNĐ/lượng |\n"
        "3. Tuyệt đối không tự ý lược bỏ hàng, cột, hoặc thay đổi các con số giá trị.\n"
        "4. Không để dòng trống xen kẽ trong bảng Markdown."
    ),
    "search_news": (
        "QUY TẮC ĐỊNH DẠNG BÀI BÁO TIN TỨC BẮT BUỘC:\n"
        "- Tóm tắt ngắn gọn các bài báo/tin tức chính bằng các gạch đầu dòng súc tích.\n"
        "- Bọc các liên kết bằng cú pháp Markdown `[Xem chi tiết](url)`."
    ),
    "get_cgv_movies": (
        "QUY TẮC ĐỊNH DẠNG BẢNG CHIẾU PHIM BẮT BUỘC:\n"
        "- Định dạng lịch chiếu phim xếp theo bảng cột ngang đẹp mắt. Mỗi phim chiếm một cột theo cấu trúc:\n"
        "  | **Tên phim 1** | **Tên phim 2** | **Tên phim 3** | **Tên phim 4** |\n"
        "  | :---: | :---: | :---: | :---: |\n"
        "  | ![poster 1](url_poster_1) | ![poster 2](url_poster_2) | ![poster 3](url_poster_3) | ![poster 4](url_poster_4) |\n"
        "  | *Thể loại*: ... | *Thể loại*: ... | *Thể loại*: ... | *Thể loại*: ... |\n"
        "  | *Thời lượng*: ... | *Thời lượng*: ... | *Thời lượng*: ... | *Thời lượng*: ... |\n"
        "  | *Khởi chiếu*: ... | *Khởi chiếu*: ... | *Khởi chiếu*: ... | *Khởi chiếu*: ... |\n"
        "  | 🔗 [Xem chi tiết](url) | 🔗 [Xem chi tiết](url) | 🔗 [Xem chi tiết](url) | 🔗 [Xem chi tiết](url) |\n"
        "- Tuyệt đối không để dòng trống xen kẽ trong bảng.\n"
        "- Đặt liên kết tổng dẫn đến trang chủ CGV: 🔗 [Xem toàn bộ danh sách](url_tổng) ở bên dưới bảng."
    ),
    "get_epic_free_games": (
        "QUY TẮC ĐỊNH DẠNG BẢNG GAME MIỄN PHÍ EPIC BẮT BUỘC:\n"
        "- Giữ nguyên 100% cấu trúc 2 bảng Markdown riêng biệt: bảng 'ĐANG MIỄN PHÍ' và bảng 'SẮP MIỄN PHÍ'.\n"
        "- Mỗi bảng có 2 cột ngang, mỗi cột là 1 game với ảnh inline + tên + thời gian.\n"
        "- Tuyệt đối không xoá ảnh, không thay đổi cấu trúc bảng.\n"
        "- Không để dòng trống xen kẽ trong bảng.\n"
        "- Đặt liên kết tổng 🔗 [Xem tất cả game miễn phí](https://store.epicgames.com/vi/free-games) ở bên dưới."
    ),
}

_SEARCH_TTL_CACHE: dict = {}

# Dòng UI thường gặp khi scrape (share, social, CTA) — loại bỏ trước khi hiển thị/TTS
_NOISE_LINE_RE = re.compile(
    r"^(?:share|facebook|twitter|x|linkedin|pinterest|email|reddit|telegram|"
    r"whatsapp|zalo|copy\s*link|chia\s*s[eẻ]|đăng\s*ký|subscribe|follow\s*us|"
    r"read\s*more|related\s*posts|you\s*may\s*also\s*like|amazon|buy\s*now|"
    r"add\s*to\s*cart|bình\s*luận|comment|đọc\s*tiếp|xem\s*thêm)$",
    re.IGNORECASE,
)


def _clean_article_content(text: str) -> str:
    """Strip share buttons, social labels, and whitespace-only lines from scraped text."""
    if not text:
        return ""

    # Gỡ khối Share + tên mạng xã hội liên tiếp (một dòng hoặc nhiều dòng)
    text = re.sub(
        r"(?is)\bshare\b(?:\s*\n\s*)?(?:facebook|twitter|linkedin|pinterest|email|x|reddit|telegram|whatsapp|zalo)+\s*",
        "\n",
        text,
    )

    cleaned: list[str] = []
    for raw in text.splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if not line:
            continue
        if _NOISE_LINE_RE.match(line):
            continue
        # Bỏ dòng chỉ có ký tự đặc biệt / số đơn lẻ (menu, icon text)
        if len(line) < 4 and not re.search(r"[\w\u00C0-\u1EF9]", line, re.UNICODE):
            continue
        cleaned.append(line)

    body = "\n\n".join(cleaned)
    return re.sub(r"\n{3,}", "\n\n", body).strip()


def _build_news_speech(visited: list[dict], query: str) -> str:
    """Short spoken summary — UI still gets full article text."""
    if not visited:
        return "Không tìm thấy tin phù hợp, thưa ngài."
    parts = [f"Đã tìm được {len(visited)} bài về {query}."]
    for item in visited[:3]:
        title = (item.get("title") or "")[:100].strip()
        source = item.get("source") or "nguồn tin"
        if title:
            parts.append(f"Từ {source}: {title}.")
    return " ".join(parts)[:400].strip()


# Tên miền .com/net không .vn nhưng là báo/tổng hợp tin Việt Nam (không phải shop)
_VN_KNOWN_HOSTS = frozenset({
    "baomoi.com",
    "vnexpress.net",
    "vietnamnet.vn",
    "dantri.com.vn",
    "tuoitre.vn",
    "thanhnien.vn",
    "laodong.vn",
    "vtcnews.vn",
    "vtv.vn",
    "genk.vn",
    "tinhte.vn",
    "techz.vn",
    "vnreview.vn",
    "techrum.vn",
    "znews.vn",
    "nghenhinvietnam.vn",
    "ictnews.vn",
    "vietnamplus.vn",
    "plo.vn",
    "vneconomy.vn",
    "qdnd.vn",
    "cand.com.vn",
    "doisongphapluat.com",
    "game4v.com",
    "vietgame.asia",
    "gamek.vn",
    "soha.vn",
    "kenh14.vn",
    "cafef.vn",
    "cafebiz.vn"
})

# Shop / catalog — không dùng cho tra cứu tin tức
_VN_SHOP_HOSTS = frozenset({
    "hacom.vn",
    "thegioididong.com",
    "nhatminhlaptop.com",
    "cellphones.com.vn",
    "fptshop.com.vn",
    "phongvu.vn",
    "shopee.vn",
    "tiki.vn",
    "lazada.vn",
    "anphatpc.com.vn",
    "gearvn.com",
})

_SHOP_URL_PATH_RE = re.compile(
    r"/(?:danh-muc|category|collections?|shop|san-pham|products?|"
    r"tim-kiem|search|cart|checkout|gia-|bang-gia)(?:/|$)",
    re.IGNORECASE,
)

_SHOP_CONTENT_MARKERS = (
    "bảo hành:",
    "thêm vào giỏ",
    "mua ngay",
    "danh sách ram",
    "chọn theo tiêu chí",
    "chi nhánh",
    "kho online",
    "bán hàng trực tuyến",
    "hotline hỗ trợ",
    "giỏ hàng",
    "tra cứu kiểm tra hàng",
    "giá tốt",
    "chính hãng, chất lượng",
)

_PRICE_VND_RE = re.compile(r"\d{1,3}(?:\.\d{3})+\s*VND", re.IGNORECASE)


def _host_from_url(url: str) -> str:
    from urllib.parse import urlparse

    return urlparse(url).netloc.lower().lstrip("www.")


def _is_product_category_path(path: str) -> bool:
    """Đường dẫn 1 cấp ngắn kiểu /ram-ddr5 — thường là trang danh mục, không phải bài."""
    segs = [s for s in (path or "").strip("/").split("/") if s]
    if len(segs) != 1:
        return False
    slug = segs[0].lower()
    if slug.endswith((".html", ".htm", ".epi")):
        return False
    # Slug bài báo thường dài, nhiều từ
    if len(slug) >= 40 and slug.count("-") >= 4:
        return False
    if slug.count("-") <= 3 and len(slug) <= 28:
        return True
    return False


def is_news_article_url(url: str, host_override: str = "") -> bool:
    """URL phải là bài báo/tin, không phải trang bán hàng hay danh mục sản phẩm."""
    if not is_vietnam_news_url(url, host_override=host_override):
        return False

    host = host_override.lower().lstrip("www.") if host_override else _host_from_url(url)
    if host in _VN_SHOP_HOSTS:
        return False
    for shop in _VN_SHOP_HOSTS:
        if host.endswith("." + shop):
            return False

    from urllib.parse import urlparse

    path = urlparse(url).path or ""
    
    # Loại bỏ các trang chủ (path rỗng hoặc cực kỳ ngắn)
    cleaned_path = path.strip("/")
    if not cleaned_path or len(cleaned_path) < 5:
        return False

    # Loại bỏ các trang tag, chủ đề, tìm kiếm, danh mục chung
    lower_path = path.lower()
    if any(k in lower_path for k in ["/tag/", "/tags/", "/chu-de/", "/topic/", "/search/", "/tim-kiem/", "/category/", "/danh-muc/"]):
        return False

    if _SHOP_URL_PATH_RE.search(path):
        return False
    if _is_product_category_path(path):
        return False

    # Lọc danh mục riêng của 24h.com.vn (ví dụ: bong-da-c48.html)
    # Bài viết thật của 24h thường có dạng c<chuyên mục>a<id bài viết>.html (vd: c46a1735303.html)
    if "24h.com.vn" in host:
        if re.search(r'-c\d+\.html$', lower_path) and not re.search(r'c\d+a\d+\.html$', lower_path):
            return False

    # Báo Mới: bài chuẩn thường có .epi
    if "baomoi.com" in host and not path.endswith(".epi"):
        if "/tag/" in path or "/chu-de/" in path or len(path.strip("/")) < 15:
            return False

    return True


def _looks_like_shop_or_nav_content(text: str) -> bool:
    """Phát hiện menu cửa hàng, danh sách giá, hotline — không phải nội dung báo."""
    if not text:
        return True

    lower = text.lower()
    if sum(1 for m in _SHOP_CONTENT_MARKERS if m in lower) >= 2:
        return True
    if len(_PRICE_VND_RE.findall(text)) >= 2:
        return True

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if len(lines) >= 8:
        short = sum(
            1
            for ln in lines[:35]
            if len(ln) < 40 and not ln.endswith((".", "!", "?", "…", "。"))
        )
        # Tăng ngưỡng tỷ lệ từ 0.6 lên 0.8 (với bài dài) và 0.7 (với bài ngắn) để không loại bỏ nhầm bài viết thật
        threshold = 0.8 if len(text) > 1500 else 0.7
        if short / min(len(lines), 35) >= threshold:
            return True

    return False


def _is_valid_news_content(text: str) -> bool:
    """Nội dung đủ dài và giống bài viết, không phải catalog/menu."""
    text = (text or "").strip()
    if not text or _looks_like_shop_or_nav_content(text):
        return False
    if len(text) < 150:
        return False
    sentences = re.findall(r"[^.!?…]+[.!?…]", text)
    return len(sentences) >= 2


def is_vietnam_news_url(url: str, host_override: str = "") -> bool:
    """Chỉ chấp nhận nguồn tin / bài viết trong nước (ưu tiên .vn và báo Việt).

    host_override: dùng khi url là link redirect (vd. Google News RSS luôn
    trỏ qua news.google.com) và host thật đã biết từ nơi khác (vd. <source
    url> của feed).
    """
    try:
        from urllib.parse import urlparse

        host = host_override.lower().lstrip("www.") if host_override else urlparse(url).netloc.lower().lstrip("www.")
        if not host:
            return False
        if host.endswith(".vn"):
            return True
        if host in _VN_KNOWN_HOSTS:
            return True
        # subdomain của host đã biết, vd shop.tiki.vn
        for known in _VN_KNOWN_HOSTS:
            if host.endswith("." + known):
                return True
        return False
    except Exception:
        return False


def get_source_label(url: str, host_override: str = "") -> str:
    """Extract a friendly label from any URL domain."""
    try:
        from urllib.parse import urlparse
        if host_override:
            domain = host_override.replace("www.", "").lower()
        else:
            netloc = urlparse(url).netloc
            domain = netloc.replace("www.", "").lower()
        
        domain_map = {
            "vietnamnet.vn": "VietnamNet",
            "tuoitre.vn": "Tuổi Trẻ",
            "vnexpress.net": "VnExpress",
            "baochinhphu.vn": "Báo Chính Phủ",
            "baomoi.com": "Báo Mới",
            "thanhnien.vn": "Thanh Niên",
            "cellphones.com.vn": "CellphoneS",
            "gearvn.com": "GearVN",
            "tinhte.vn": "Tinh Tế",
            "genk.vn": "GenK",
            "thegioididong.com": "Thế Giới Di Động",
            "fptshop.com.vn": "FPT Shop",
        }
        
        for d, label in domain_map.items():
            if d in domain:
                return label
        
        # Generic extraction: domain.com -> Domain
        return domain.split(".")[0].capitalize()
    except Exception as e:
        log.debug(f"Could not extract source label from {url}: {e}")
        return "Nguồn tin"


async def handle_market_query(query: str = None, **kwargs) -> str:
    """
    Intelligent market data dispatcher. 
    If query is specific (e.g. 'gold', 'gas'), it only fetches the relevant source.
    If query is 'báo cáo giá tổng hợp', it fetches everything.
    """
    
    q = (query or "").lower()
    user_text = kwargs.get("user_text", "").lower()
    combined_text = q + " " + user_text
    
    # Danh sách các từ khóa mặc định thuộc 6 nhóm
    core_keywords = ["vàng", "sjc", "gold", "9999", "xăng", "dầu", "oil", "fuel", "ron", "e5", "e10", "usd", "tỷ giá", "ngoại tệ", "vietcombank", "gas", "petrolimex", "giá điện", "tiền điện", "biểu giá điện", "evn", "giá nước", "tiền nước", "biểu giá nước", "nước sinh hoạt"]
    # Kiểm tra xem có yêu cầu báo cáo tổng hợp hay chứa từ khóa cốt lõi không
    is_core_request = any(k in combined_text for k in core_keywords)
    is_summary_request = not query or any(k in combined_text for k in ["tổng hợp", "thị trường", "market", "tất cả"])
    
    # Giới hạn get_market_data trong 6 nhóm dữ liệu thị trường được hỗ trợ.
    # Tra cứu sản phẩm được tách sang shop_engine thay vì tìm Google/snippet tại đây.
    if query and not is_core_request and not is_summary_request:
        return (
            "get_market_data không hỗ trợ tra cứu sản phẩm. "
            "Công cụ này chỉ hỗ trợ giá vàng, xăng dầu, tỷ giá USD, gas, giá điện sinh hoạt và giá nước sinh hoạt."
        )

    # Default script lấy toàn bộ text (fallback)
    default_script = "document.body.innerText"
    
    # Các script chuyên biệt để trích xuất dữ liệu chính xác
    extraction_scripts = {
        "gold": """
            (function() {
                const tables = document.querySelectorAll('table');
                for (let t of tables) {
                    const text = t.innerText || '';
                    if (text.includes('SJC') && (text.includes('9999') || text.includes('1L'))) {
                        return text.substring(0, 1500);
                    }
                }
                return document.body.innerText.substring(0, 2000);
            })()
        """,
        "oil": """
            (function() {
                const tables = document.querySelectorAll('table, .price-table, [class*="fuel"]');
                for (let t of tables) {
                    const text = t.innerText || '';
                    if (text.includes('RON') || text.includes('E10') || text.includes('E5') || text.includes('xăng')) {
                        return text.substring(0, 2000);
                    }
                }
                const bodyText = document.body.innerText;
                const lines = bodyText.split('\\n');
                const fuelLines = lines.filter(l => 
                    /E10\\sRON\\s*97-III|E10\\s*RON\\s*95-V|E10\\s*RON\\s*95-III|E5\\s*RON\\s*92-II/i.test(l)
                );
                return fuelLines.join('\\n').substring(0, 2000) || bodyText.substring(0, 2000);
            })()
        """,
        "currency": """
            (function() {
                const tables = document.querySelectorAll('table');
                for (let t of tables) {
                    const text = t.innerText || '';
                    if (text.includes('USD') && text.includes('VND')) {
                        return text.substring(0, 1500);
                    }
                }
                const bodyText = document.body.innerText;
                const usdMatch = bodyText.match(/USD[^\\n]{0,100}(?:Mua|Bán|Buy|Sell)[^\\n]{0,50}[\\d,.]+/i);
                return usdMatch ? usdMatch[0] : bodyText.substring(0, 1500);
            })()
        """,
"gas": """
            (function() {
                const bodyText = document.body.innerText;
                const idx = bodyText.indexOf('Bảng giá đổi bình gas tại Hà Nội');
                if (idx >= 0) {
                    return bodyText.substring(idx, idx + 1500);
                }
                return bodyText.substring(0, 1500);
            })()
        """,
        "electricity": """
            (function() {
                const tables = document.querySelectorAll('table');
                for (let t of tables) {
                    const text = t.innerText || '';
                    if (text.includes('kWh') && text.includes('701')) {
                        return text.substring(0, 2000);
                    }
                }
                return document.body.innerText.substring(0, 3000);
            })()
        """,
        "water": """
            (function() {
                const text = document.body.innerText;
                const start = text.indexOf('quy định giá nước sinh hoạt tại Hà Nội');
                const end = text.indexOf('Bật mí cách tính tiền nước');
                if (start >= 0 && end > start) {
                    return text.substring(start, end);
                }
                return text.substring(0, 6000);
            })()
        """
    }
    
    q = (query or "").lower()
    
    # Define source mapping
    sources = {
        "gold": {
            "url": "https://baomoi.com/tien-ich-gia-vang.epi",
            "keywords": ["vàng", "sjc", "gold", "9999"],
            "label": "Vàng SJC"
        },
        "oil": {
            "url": "https://baomoi.com/tien-ich-gia-xang-dau.epi",
            "keywords": ["xăng", "dầu", "oil", "fuel", "ron 95", "e5"],
            "label": "Xăng dầu"
        },
        "currency": {
            "url": "https://baomoi.com/tien-ich-ty-gia-ngoai-te-vietcombank.epi",
            "keywords": ["usd", "tỷ giá", "ngoại tệ", "vcb", "vietcombank", "đô la"],
            "label": "Tỷ giá Ngoại tệ"
        },
        "gas": {
            "url": "https://pgaspetrolimex.vn/gia-ban-le-gas-petrolimex-hom-nay-tai-ha-noi",
            "keywords": ["gas", "bình gas", "petrolimex"],
            "label": "Giá Gas"
        },
        "electricity": {
            "url": "https://luatvietnam.vn/linh-vuc-khac/bang-gia-dien-sinh-hoat-883-96993-article.html",
            "keywords": ["giá điện sinh hoạt", "giá điện", "tiền điện", "biểu giá điện", "evn"],
            "label": "Giá Điện Sinh Hoạt"
        },
        "water": {
            "url": "https://www.sonha.net.vn/gia-nuoc-sinh-hoat.html",
            "keywords": ["giá nước sinh hoạt", "giá nước sạch", "giá nước", "tiền nước", "biểu giá nước"],
            "label": "Giá Nước Sinh Hoạt"
        }
    }

    # Determine which sources to fetch based on specific keywords
    specific_targets = []
    for key, info in sources.items():
        if any(k in q for k in info["keywords"]):
            specific_targets.append(key)
    
    # "báo cáo giá tổng hợp" là câu trigger cho tất cả 4 loại
    is_comprehensive_report = "báo cáo giá tổng hợp" in q or "báo giá tổng hợp" in q
    # Hoặc tổng hợp chung nhưng KHÔNG có specific target cụ thể
    explicit_summary = any(k in q for k in ["thị trường", "market", "tất cả"]) and not specific_targets
    is_summary = not q or is_comprehensive_report or (not specific_targets and explicit_summary)
    
    if specific_targets:
        to_fetch = specific_targets
        is_summary = False # Explicitly not a summary if targets are found
    elif is_summary or explicit_summary:
        to_fetch = list(sources.keys())
        is_summary = True
    else:
        # Final fallback: if nothing else matches, but it's a market query, 
        # we check if it's a generic "giá xăng" vs "giá tổng hợp"
        if any(k in q for k in ["xăng", "vàng", "usd", "gas", "điện", "nước"]):
            to_fetch = specific_targets if specific_targets else [list(sources.keys())[0]]
            is_summary = False
        else:
            to_fetch = list(sources.keys())
            is_summary = True

    log.info(f"SEARCH_ENGINE: Fetching market sources: {to_fetch} for query: '{q}'")
    
    # Sequential fetching with specialized extraction scripts
    data_map = {}
    for key in to_fetch:
        try:
            log.info(f"SEARCH_ENGINE: Visiting {sources[key]['label']}...")
            # Dùng script chuyên biệt hoặc default
            script = extraction_scripts.get(key, default_script)
            val = await browser.visit_and_evaluate(sources[key]["url"], script)
            # Preserve newlines but collapse horizontal whitespace for cleaner regex matching
            data_map[key] = re.sub(r'[ \t\f\v]+', ' ', str(val)) if val else ""
        except Exception as e:
            log.warning(f"Failed to fetch {key}: {e}")
            data_map[key] = ""

    parts = []
    if is_summary:
        parts.append("📊 **BÁO CÁO THỊ TRƯỜNG TỔNG HỢP**")
    else:
        # Use a more forceful header for specific lookups
        target_label = sources[to_fetch[0]]['label'].upper() if len(to_fetch)==1 else 'THỊ TRƯỜNG'
        parts.append(f"📊 **KẾT QUẢ TRA CỨU: {target_label}**")

    # Extraction Logic
    # 1. Gold
    if "gold" in data_map:
        text = data_map["gold"]
        # Match SJC prices which are often in thousands (e.g., 82.250 means 82,250,000)
        m = re.search(r"SJC 1L, 10L, 1KG\s+([\d,.]+)\s+([\d,.]+)", text, re.I)
        if m:
            def _fmt_gold(s):
                s = s.replace(".", "").replace(",", "")
                if len(s) <= 5: s += "000"
                val = int(s)
                return f"{val:,}".replace(",", ".")
            
            p1, p2 = _fmt_gold(m.group(1)), _fmt_gold(m.group(2))
            parts.append("#### 🟡 Giá Vàng SJC")
            parts.append("| Sản phẩm | Mua | Bán |")
            parts.append("| :---: | :---: | :---: |")
            parts.append(f"| Vàng SJC (1L/10L/1KG) | {p1} VNĐ/lượng. | {p2} VNĐ/lượng. |")
        else:
            m = re.search(r"SJC - Bán Lẻ\s+([\d,.]+)\s+([\d,.]+)", text, re.I)
            if m:
                p1, p2 = m.group(1).replace(",", "."), m.group(2).replace(",", ".")
                parts.append("#### 🟡 Giá Vàng SJC")
                parts.append("| Sản phẩm | Mua | Bán |")
                parts.append("| :---: | :---: | :---: |")
                parts.append(f"| Vàng SJC (bán lẻ) | {p1} VNĐ/chỉ. | {p2} VNĐ/chỉ. |")
            else: 
                log.warning(f"SEARCH_ENGINE: Could not parse Gold price from text: {text[:200]}...")
                parts.append("Sản phẩm: Vàng SJC | Mua: đang cập nhật | Bán: đang cập nhật")

    # 2. Oil
    if "oil" in data_map:
        text = data_map["oil"]
        fuel_targets = [
            (r"E10 RON 95-III", "Xăng E10 RON 95-III"),
            (r"E10 RON 97-III", "Xăng E10 RON 97-III"),
            (r"E10 RON 95-V", "Xăng E10 RON 95-V"),
            (r"E5 RON 92-II", "Xăng E5 RON 92-II"),
        ]
        query_lower = query.lower()
        
        requested_targets = []
        for pattern, label in fuel_targets:
            if pattern.lower() in query_lower or " ".join(label.lower().split()[1:]) in query_lower:
                requested_targets.append((pattern, label))
        
        if not requested_targets and "e10 ron 95" in query_lower:
            requested_targets = [t for t in fuel_targets if "95" in t[1]]
        elif not requested_targets and "e10 ron 97" in query_lower:
            requested_targets = [t for t in fuel_targets if "97" in t[1]]
        elif not requested_targets and "e5 ron 92" in query_lower:
            requested_targets = [t for t in fuel_targets if "92" in t[1]]
        elif not requested_targets and "dầu" in query_lower:
            requested_targets = [t for t in fuel_targets if "Dầu" in t[1]]
            
        if not requested_targets:
            active_targets = fuel_targets
        else:
            active_targets = requested_targets

        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        oil_parsed_count = 0
        oil_table_started = False
        for pattern, label in active_targets:
            found = False
            for idx, line in enumerate(lines):
                clean_pat = pattern.replace(r"\s*", "").replace(r"\s", "").replace("-", "").lower()
                clean_line = line.replace(" ", "").replace("-", "").lower()
                
                if clean_pat in clean_line or (clean_pat.replace("e10", "") in clean_line):
                    if idx + 2 < len(lines):
                        val1 = lines[idx + 1].strip()
                        val2 = lines[idx + 2].strip()
                        if re.match(r"^\d{2}[\d,.]+$", val1) and re.match(r"^\d{2}[\d,.]+$", val2):
                            p1 = val1.replace(",", ".")
                            p2 = val2.replace(",", ".")
                            if not oil_table_started:
                                parts.append("#### ⛽ Giá Xăng Dầu (Petrolimex)")
                                parts.append("| Sản phẩm | Vùng 1 | Vùng 2 |")
                                parts.append("| :---: | :---: | :---: |")
                                oil_table_started = True
                            parts.append(f"| {label} | {p1} VNĐ. | {p2} VNĐ. |")
                            found = True
                            oil_parsed_count += 1
                            break
            
            if not found:
                regex = rf"(?:^|[\t\n])\s*(?:Xăng|Xng)?\s*{re.escape(pattern)}[\s\-\:]+([\d,.]+)\s+([\d,.]+)"
                m = re.search(regex, text, re.I | re.M)
                if not m:
                    m = re.search(rf"(?:^|[\t\n])\s*{re.escape(label)}[\s\-\:]+([\d,.]+)\s+([\d,.]+)", text, re.I | re.M)
                if m:
                    p1 = m.group(1).replace(",", ".")
                    p2 = m.group(2).replace(",", ".")
                    if not oil_table_started:
                        parts.append("#### ⛽ Giá Xăng Dầu (Petrolimex)")
                        parts.append("| Sản phẩm | Vùng 1 | Vùng 2 |")
                        parts.append("| :---: | :---: | :---: |")
                        oil_table_started = True
                    parts.append(f"| {label} | {p1} VNĐ. | {p2} VNĐ. |")
                    oil_parsed_count += 1
        
        if oil_parsed_count == 0:
            log.warning(f"SEARCH_ENGINE: Could not parse Oil prices from text: {text[:200]}...")
            parts.append("| Sản phẩm: Xăng dầu | Vùng 1: đang cập nhật | Vùng 2: đang cập nhật |")

    # 3. Currency
    if "currency" in data_map:
        text = data_map["currency"]
        m = re.search(r"USD[^\d]+([\d,.]+)\s+([\d,.]+)\s+([\d,.]+)", text)
        if m:
            def _fmt_curr(s):
                clean = s.split(',')[0].replace(".", "")
                val = int(clean)
                num_str = f"{val:,}".replace(",", ".")
                return f"{num_str} VNĐ"
            parts.append("#### 💵 Tỷ Giá Ngoại Tệ USD (Vietcombank)")
            parts.append("| Sản phẩm | Mua | Bán |")
            parts.append("| :---: | :---: | :---: |")
            parts.append(f"| Ngoại tệ USD | {_fmt_curr(m.group(1))}. | {_fmt_curr(m.group(3))}. |")
        else:
            log.warning(f"SEARCH_ENGINE: Could not parse Currency rates from text: {text[:200]}...")
            parts.append("| Sản phẩm: Ngoại tệ USD | Mua: đang cập nhật | Bán: đang cập nhật")

    # 4. Gas
    if "gas" in data_map:
        text = data_map["gas"]

        def _fmt_num(s):
            digits = re.sub(r"[.,]", "", s)
            try:
                return f"{int(digits):,}".replace(",", ".")
            except ValueError:
                return s

        m = re.search(r"Petrolimex van đứng\s+([\d][\d.,]*)\s*đ\s+([\d][\d.,]*)\s*đ", text, re.I)
        if not m:
            m = re.search(r"Petrolimex van ngang\s+([\d][\d.,]*)\s*đ\s+([\d][\d.,]*)\s*đ", text, re.I)
        if m:
            p_list, p_promo = _fmt_num(m.group(1)), _fmt_num(m.group(2))
            parts.append("#### 🔥 Giá Gas Petrolimex")
            parts.append("| Sản phẩm | Giá niêm yết | Giá ưu đãi |")
            parts.append("| :---: | :---: | :---: |")
            parts.append(f"| Gas Petrolimex (bình 12kg) | {p_list} VNĐ. | {p_promo} VNĐ. |")
        else:
            log.warning(f"SEARCH_ENGINE: Could not find Petrolimex 12kg Gas price in text: {text[:500]}...")
            parts.append("| Sản phẩm: Gas Petrolimex (bình 12kg) | Giá: đang cập nhật |")

    # 5. Electricity
    if "electricity" in data_map:
        text = data_map["electricity"]

        def _fmt_price(s):
            digits = re.sub(r"[.,]", "", s)
            try:
                return f"{int(digits):,}".replace(",", ".")
            except ValueError:
                return s

        rows = []
        block_m = re.search(
            r"Giá bán\s*\(đồng/kWh\)(.*?)(?:\*\s*Giá bán lẻ điện sinh hoạt dùng công tơ|Cơ chế điều chỉnh)",
            text, re.S | re.I,
        )
        if block_m:
            block_lines = [ln.strip() for ln in block_m.group(1).splitlines() if ln.strip()]
            i = 0
            while i + 2 < len(block_lines):
                bac, rng, price = block_lines[i], block_lines[i + 1], block_lines[i + 2]
                if re.fullmatch(r"\d+", bac) and "kwh" in rng.lower() and re.fullmatch(r"[\d.,]+", price):
                    rows.append((bac, rng, _fmt_price(price)))
                    i += 3
                else:
                    i += 1

        if len(rows) >= 5:
            parts.append("#### 💡 Giá Điện Sinh Hoạt (bậc thang)")
            parts.append("| Bậc | Mức sử dụng | Đơn giá (chưa VAT) |")
            parts.append("| :---: | :---: | :---: |")
            for idx, rng, price in rows:
                parts.append(f"| Bậc {idx} | {rng} | {price} VNĐ/kWh. |")
            parts.append("*Giá lấy trực tiếp mỗi lần tra cứu (biểu giá đang áp dụng phát hành hóa đơn theo Quyết định 1279/QĐ-BCT). Chưa gồm thuế GTGT (8%). Đối chiếu chính thức tại evn.com.vn.*")
        else:
            log.warning(f"SEARCH_ENGINE: Could not parse Electricity prices from text: {text[:300]}...")
            parts.append("| Sản phẩm: Giá điện sinh hoạt | Giá: đang cập nhật |")

    # 6. Water
    if "water" in data_map:
        text = data_map["water"]

        def _fmt_price(s):
            digits = re.sub(r"[.,]", "", s)
            try:
                return f"{int(digits):,}".replace(",", ".")
            except ValueError:
                return s

        # Hai cụm từ đặc trưng, không trùng nhau giữa 2 khu vực nên không cần
        # tách vùng văn bản trước — tìm trực tiếp trên toàn bộ text.
        # \s+ (không phải dấu cách literal) vì trang nguồn dùng \xa0 (non-breaking space).
        hn_prices = re.findall(r"giá\s+là\s+([\d][\d.,]*)\s*đồng", text, re.I)
        hcm_prices = re.findall(r"khối\s+nước\s+sẽ\s+là\s+([\d][\d.,]*)\s*đồng", text, re.I)

        hn_ranges = ["0 - 10 m³", "10 - 20 m³", "20 - 30 m³", "Trên 30 m³"]
        hcm_ranges = ["0 - 4 m³/người", "4 - 6 m³/người", "Trên 6 m³/người"]

        if len(hn_prices) >= 4 or len(hcm_prices) >= 3:
            parts.append("#### 🚰 Giá Nước Sinh Hoạt (bậc thang)")
            if len(hn_prices) >= 4:
                parts.append("**Hà Nội**")
                parts.append("| Mức sử dụng | Đơn giá (chưa VAT/phí BVMT) |")
                parts.append("| :---: | :---: |")
                for rng, p in zip(hn_ranges, hn_prices[:4]):
                    parts.append(f"| {rng} | {_fmt_price(p)} VNĐ/m³. |")
            if len(hcm_prices) >= 3:
                parts.append("**TP.HCM**")
                parts.append("| Mức sử dụng | Đơn giá (chưa VAT/phí BVMT) |")
                parts.append("| :---: | :---: |")
                for rng, p in zip(hcm_ranges, hcm_prices[:3]):
                    parts.append(f"| {rng} | {_fmt_price(p)} VNĐ/m³. |")
            parts.append("*Giá lấy trực tiếp mỗi lần tra cứu. Hà Nội theo Quyết định 3541/QĐ-UBND, TP.HCM theo biểu giá UBND TP.HCM. Chưa gồm thuế GTGT (5%) và phí bảo vệ môi trường (10%). Đối chiếu chính thức tại website công ty cấp nước địa phương.*")
        else:
            log.warning(f"SEARCH_ENGINE: Could not parse Water prices from text: {text[:300]}...")
            parts.append("| Sản phẩm: Giá nước sinh hoạt | Giá: đang cập nhật |")

    parts.append(f"Nguồn thông tin: {', '.join([sources[k]['label'] for k in to_fetch])}")
       
    res = "\n".join(parts)
    log.info(f"[TRACE] PROMPT_MUTATION_END: Market data context built ({len(res)} chars)")
    return res


_LEAD_FILLER_RE = re.compile(
    r"^(?:(?:bạn|jarvis|anh|em|ơi|xin|vui\s+lòng|làm\s+ơn|giúp\s+(?:tôi|mình)|giúp|nhờ|hãy)[,\s]+)+",
    re.IGNORECASE,
)
_TRAIL_FILLER_RE = re.compile(
    r"(?:\s+(?:có\s+gì\s+(?:nổi\s+bật|mới|hot|đặc\s+biệt)|thế\s+nào|ra\s+sao|được\s+không"
    r"|giúp\s+(?:tôi|mình)|với|nhé|nha|đi|không))*\s*[?!.,…]*\s*$",
    re.IGNORECASE,
)


def strip_conversational_filler(text: str) -> str:
    """Drop spoken-language padding ("bạn", "giúp tôi", "... có gì nổi bật không?")
    so only the topic reaches the search engine. Falls back to the input if
    stripping would leave nothing."""
    original = (text or "").strip()
    cleaned = _LEAD_FILLER_RE.sub("", original)
    cleaned = _TRAIL_FILLER_RE.sub("", cleaned).strip()
    return cleaned or original


async def handle_news_search(query: str) -> str:
    """General web search for news and information."""
    global _SEARCH_TTL_CACHE
    
    def _norm_key(s: str) -> str:
        return re.sub(r"\s+", " ", (s or "").strip().lower())

    def _rewrite_search_query(s: str) -> str:
        import re as _re
        orig = s
        cleaned = strip_conversational_filler((s or "").strip())

        # Strip các prefix lệnh phổ biến để chỉ giữ phần nội dung cần tìm
        _PREFIXES = [
            r"^tin\s+t[uứ]c\s+v[eề]\s+",
            r"^tin\s+t[uứ]c\s+",
            r"^t[iì]m\s+ki[eế]m\s+tin\s+t[uứ]c\s+",
            r"^t[iì]m\s+ki[eế]m\s+",
            r"^t[iì]m\s+",
            r"^search\s+news\s+",
            r"^search\s+",
            r"^news\s+about\s+",
            r"^news\s+",
            r"^cho\s+t[oô]i\s+bi[eế]t\s+",
            r"^h[aã]y\s+t[iì]m\s+",
        ]
        for pat in _PREFIXES:
            cleaned = _re.sub(pat, "", cleaned, flags=_re.IGNORECASE).strip()
            if cleaned != (s or "").strip():
                break  # chỉ strip prefix đầu tiên khớp

        # Append năm hiện tại từ hệ thống để kết quả bám thời gian thực
        # Chỉ append năm nếu query rất ngắn hoặc mang tính thời sự chung chung
        import time as _time
        current_year = str(_time.localtime().tm_year)
        query_words = cleaned.lower().split()
        is_general_hot_news = any(k in cleaned.lower() for k in ["tin tức", "thời sự", "bão", "dịch bệnh", "thời tiết"]) or len(query_words) <= 2
        if is_general_hot_news and current_year not in cleaned:
            cleaned = f"{cleaned} {current_year}"

        # Ưu tiên kết quả trong nước + bài báo (tránh trang bán hàng / danh mục)
        if not re.search(r"\btin\s+tức\b", cleaned, re.IGNORECASE):
            cleaned = f"tin tức {cleaned}"

        final_query = cleaned.strip()

        log.info(f"[SEARCH_TRACE] ORIGINAL_USER_TEXT: '{orig}'")
        log.info(f"[SEARCH_TRACE] FINAL_SEARCH_QUERY: '{final_query}'")

        return final_query

    cache_key = _norm_key(query)
    now = time.time()
    if cache_key in _SEARCH_TTL_CACHE:
        cached = _SEARCH_TTL_CACHE[cache_key]
        if now - cached["ts"] < 900: # 15 min
            log.info(f"[SEARCH_ENGINE] Cache hit for query: '{query}'")
            return {
                "display": cached["value"],
                "speech": cached.get("summary") or cached["value"][:300],
            }

    rewritten = _rewrite_search_query(query)
    log.info(f"SEARCH_ENGINE: Executing News Search for '{rewritten}'...")
    
    # Memory recall removed to ensure deterministic web search

    try:
        results = await browser.search_news(rewritten, vietnam_only=True)
        if not results:
            return {
                "display": "Không tìm thấy kết quả phù hợp.",
                "speech": "Không tìm thấy tin phù hợp, thưa ngài.",
            }

        vn_results = [
            r for r in results
            if r.url and is_vietnam_news_url(r.url, host_override=getattr(r, "source_host", ""))
        ]
        article_candidates = [
            r for r in vn_results
            if is_news_article_url(r.url, host_override=getattr(r, "source_host", ""))
        ]
        log.info(
            f"[SEARCH_ENGINE] VN: {len(vn_results)}/{len(results)}, "
            f"news URLs: {len(article_candidates)} (skipped shops/catalogs)"
        )
        if not article_candidates:
            return {
                "display": (
                    f"🔍 **Kết quả tìm kiếm:** {rewritten}\n\n"
                    "Không có bài báo nguồn Việt Nam trong kết quả. "
                    "Thưa ngài thử từ khóa cụ thể hơn (vd: tin RAM, thị trường RAM)."
                ),
                "speech": "Không tìm thấy tin trong nước phù hợp, thưa ngài.",
            }

        news_target = 5
        # Ghé nhiều bài cùng lúc (thay vì tuần tự) thay vì chờ hết cái này
        # tới cái khác — nhưng giới hạn số lượng chạy song song: nếu bắn hết
        # 8 cái cùng lúc, những cái cần StealthyFetcher (mở trình duyệt) giành
        # CPU lẫn nhau và timeout oan (đã đo thực tế). Giới hạn 3 cái cùng lúc
        # để vẫn nhanh hơn tuần tự nhiều lần mà không đánh rớt bài tốt.
        candidates_to_try = [r for r in article_candidates if r.url][:8]
        _visit_sem = asyncio.Semaphore(3)

        async def _visit_one(r):
            async with _visit_sem:
                try:
                    log.info(f"[SEARCH_ENGINE] Visiting article: {r.url[:70]}")
                    return r, await browser.visit_article(r.url, timeout_ms=12_000), None
                except Exception as ve:
                    return r, None, ve

        visit_results = await asyncio.gather(*[_visit_one(r) for r in candidates_to_try])

        visited = []
        for r, page_data, ve in visit_results:
            if len(visited) >= news_target:
                break

            snippet = _clean_article_content((r.snippet or "").strip())
            title = (r.title or "Untitled").strip()
            content = snippet

            if ve is not None:
                log.warning(f"[SEARCH_ENGINE] Visit failed for {r.url}: {ve}, using snippet")
            elif page_data and page_data.text_content and len(page_data.text_content) > 80:
                content = _clean_article_content(page_data.text_content[:5000])
                if page_data.title and page_data.title.strip():
                    title = page_data.title.strip()
                log.info(f"[SEARCH_ENGINE] Got {len(content)} chars from article")
            else:
                log.info(
                    f"[SEARCH_ENGINE] Article visit returned little content, "
                    f"using snippet ({len(snippet)} chars)"
                )

            if not _is_valid_news_content(content):
                log.info(
                    f"[SEARCH_ENGINE] Skip non-article content (shop/menu): {r.url[:70]}"
                )
                continue

            visited.append({
                "title": title,
                "source": get_source_label(r.url, host_override=getattr(r, "source_host", "")),
                "url": r.url,
                "content": content,
            })

        if not visited:
            return {
                "display": (
                    f"🔍 **Kết quả tìm kiếm:** {rewritten}\n\n"
                    "Có kết quả Việt Nam nhưng không trích được bài báo "
                    "(toàn trang bán hàng hoặc menu). Thưa ngài thử lại sau."
                ),
                "speech": "Không lấy được bài báo phù hợp, thưa ngài.",
            }

        # Build full result for UI — 5 bài, nội dung đã lọc
        output_parts = [f"🔍 **Kết quả tìm kiếm:** {rewritten}\n"]
        for item in visited:
            output_parts.append(
                f"📰 **{item['title']}**\n"
                f"🏷️ Nguồn: {item['source']}\n"
                f"🔗 {item['url']}\n"
                f"📄 {item['content']}\n"
            )

        full_result = "\n".join(output_parts)
        log.info(f"[TRACE] PROMPT_MUTATION_END: News search context built ({len(full_result)} chars)")

        speech = _build_news_speech(visited, rewritten)

        # Store full result in cache
        _SEARCH_TTL_CACHE[cache_key] = {"ts": now, "value": full_result, "summary": speech}

        return {"display": full_result, "speech": speech}
    except Exception as e:
        log.warning(f"News Search failed: {e}")
        return f"Xin lỗi, tôi gặp sự cố khi tra cứu tin tức cho '{rewritten}'."


# ---------------------------------------------------------------------------
# Zodiac and Perpetual Calendar Utilities
# ---------------------------------------------------------------------------

ZODIAC_SIGNS = {
    "bạch dương": ["bạch dương", "aries"],
    "kim ngưu": ["kim ngưu", "taurus"],
    "song tử": ["song tử", "gemini"],
    "cự giải": ["cự giải", "cancer"],
    "sư tử": ["sư tử", "leo"],
    "xử nữ": ["xử nữ", "virgo"],
    "thiên bình": ["thiên bình", "libra"],
    "hổ cáp": ["hổ cáp", "thiên yết", "thần nông", "bọ cạp", "scorpio"],
    "nhân mã": ["nhân mã", "sagittarius"],
    "ma kết": ["ma kết", "capricorn"],
    "bảo bình": ["bảo bình", "aquarius"],
    "song ngư": ["song ngư", "pisces"]
}

ZODIAC_RANGES = [
    {"name": "Ma Kết", "english": "Capricorn", "start": (12, 22), "end": (1, 19), "range_str": "22/12 - 19/01"},
    {"name": "Bảo Bình", "english": "Aquarius", "start": (1, 20), "end": (2, 18), "range_str": "20/01 - 18/02"},
    {"name": "Song Ngư", "english": "Pisces", "start": (2, 19), "end": (3, 20), "range_str": "19/02 - 20/03"},
    {"name": "Bạch Dương", "english": "Aries", "start": (3, 21), "end": (4, 19), "range_str": "21/03 - 19/04"},
    {"name": "Kim Ngưu", "english": "Taurus", "start": (4, 20), "end": (5, 20), "range_str": "20/04 - 20/05"},
    {"name": "Song Tử", "english": "Gemini", "start": (5, 21), "end": (6, 20), "range_str": "21/05 - 20/06"},
    {"name": "Cự Giải", "english": "Cancer", "start": (6, 21), "end": (7, 22), "range_str": "21/06 - 22/07"},
    {"name": "Sư Tử", "english": "Leo", "start": (7, 23), "end": (8, 22), "range_str": "23/07 - 22/08"},
    {"name": "Xử Nữ", "english": "Virgo", "start": (8, 23), "end": (9, 22), "range_str": "23/08 - 22/09"},
    {"name": "Thiên Bình", "english": "Libra", "start": (9, 23), "end": (10, 22), "range_str": "23/09 - 22/10"},
    {"name": "Hổ Cáp", "english": "Scorpio", "start": (10, 23), "end": (11, 21), "range_str": "23/10 - 21/11"},
    {"name": "Nhân Mã", "english": "Sagittarius", "start": (11, 22), "end": (12, 21), "range_str": "22/11 - 21/12"},
]

def get_zodiac_by_date(day: int, month: int) -> dict:
    """Xác định cung hoàng đạo dựa trên ngày và tháng."""
    for z in ZODIAC_RANGES:
        start_month, start_day = z["start"]
        end_month, end_day = z["end"]
        
        # Trường hợp cung vắt qua năm mới (Ma Kết: 22/12 - 19/01)
        if start_month > end_month:
            if (month == start_month and day >= start_day) or (month == end_month and day <= end_day):
                return z
        else:
            if (month == start_month and day >= start_day) or (month == end_month and day <= end_day):
                return z
    return None

def extract_zodiac_info(text: str, requested_sign: str = None) -> str:
    """Bóc tách thông tin cung hoàng đạo cụ thể từ innerText."""
    signs_order = [
        "Bạch Dương", "Bảo Bình", "Cự Giải", "Hổ Cáp", "Kim Ngưu", 
        "Ma Kết", "Nhân Mã", "Song Ngư", "Song Tử", "Sư Tử", "Thiên Bình", "Xử Nữ"
    ]
    
    if requested_sign:
        std_sign = None
        for s in signs_order:
            if s.lower() == requested_sign:
                std_sign = s
                break
        
        if std_sign:
            # Tìm mốc bắt đầu
            pattern = re.compile(rf"{re.escape(std_sign)}\s*\(\d+/\d+\s*-\s*\d+/\d+\)", re.IGNORECASE)
            match = pattern.search(text)
            if not match:
                pattern = re.compile(rf"Cung\s*{re.escape(std_sign)}", re.IGNORECASE)
                match = pattern.search(text)
            if not match:
                pattern = re.compile(rf"\b{re.escape(std_sign)}\b", re.IGNORECASE)
                match = pattern.search(text)
                
            if match:
                start_pos = match.start()
                # Điểm kết thúc là mốc bắt đầu của cung khác tiếp theo
                end_pos = len(text)
                for other_s in signs_order:
                    if other_s != std_sign:
                        other_match = re.search(rf"\b{re.escape(other_s)}\b", text[start_pos + 10:], re.IGNORECASE)
                        if other_match:
                            pos = start_pos + 10 + other_match.start()
                            if pos < end_pos:
                                end_pos = pos
                
                section_text = text[start_pos:end_pos].strip()
                # Làm sạch dòng trống thừa
                section_text = re.sub(r'\n{3,}', '\n\n', section_text)
                return f"🔮 **Tử vi {std_sign}:**\n{section_text}"
            
    return "🔮 **Cung hoàng đạo hôm nay:** Vui lòng chỉ định rõ cung hoàng đạo bạn muốn xem (Ví dụ: 'Xem cung Bạch Dương', 'Xem Song Ngư hôm nay')."


def _vn_line(text: str, label: str) -> str:
    """Dòng ngay sau một nhãn đứng riêng một dòng ("Giờ hoàng đạo\nMậu Dần (3h-5h), ..."). Nhãn phải nằm đầu dòng và
    phân biệt hoa thường: khớp tự do thì dính tiêu đề trang ("... ngày giờ hoàng đạo\nTiện ích")."""
    m = re.search(rf"^ ?{re.escape(label)}[ ]*\n ?([^\n]+)", text, re.M)
    return m.group(1).strip() if m else ""


def extract_vannien_info(text: str) -> str:
    """Bóc tách thông tin lịch vạn niên từ innerText của trang BaoMoi."""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    info = ["📅 **LỊCH VẠN NIÊN HÔM NAY:**"]

    # 1. Dương lịch
    date_match = re.search(r"Thứ\s+\w+,\s+Ngày\s+\d+\s+Tháng\s+\d+\s+Năm\s+\d+", text, re.I)
    if date_match:
        info.append(f"  • Dương lịch: {date_match.group(0)}")
    else:
        dp_match = re.search(r"Tháng\s+\d+\s+Năm\s+\d+", text, re.I)
        if dp_match:
            info.append(f"  • Dương lịch: {dp_match.group(0)}")

    # 2. Âm lịch: ngày/tháng/năm âm kèm can chi, để biết rõ đây là lịch âm (ngày dương không bao giờ ghi nhãn này)
    lunar = re.search(r"\(Ngày\s+(\d+)\s+Tháng\s+(\d+)\s+Năm\s+(\d+)\s*-\s*Âm\s+lịch\)", text, re.I)
    if lunar:
        can_chi = re.search(r"ngày\s+([^,\n]+),\s*tháng\s+([^,\n]+),\s*năm\s+([^,\n]+)", text, re.I)
        detail = (f" (ngày {can_chi.group(1).title()}, tháng {can_chi.group(2).strip().title()}, "
                  f"năm {can_chi.group(3).strip().title()})") if can_chi else ""
        info.append(f"  • Âm lịch: ngày {lunar.group(1)} tháng {lunar.group(2)} năm {lunar.group(3)}{detail}")

    # 3. Loại ngày, tiết khí, trực
    day_kind = re.search(r"^ ?Ngày (Hoàng đạo|Hắc đạo|Bình thường)\s*$", text, re.M)
    if day_kind:
        info.append(f"  • Loại ngày: {day_kind.group(1)}")
    if tiet_khi := _vn_line(text, "Tiết khí"):
        info.append(f"  • Tiết khí: {tiet_khi}")
    truc = re.search(r"^ ?Trực[ ]*\n ?([^\n]+)\n ?([^\n]+)", text, re.M)
    if truc:
        info.append(f"  • Trực {truc.group(1).strip()}: {truc.group(2).strip()}")

    # 4. Giờ hoàng đạo, mệnh ngày, tuổi xung
    if hours := _vn_line(text, "Giờ hoàng đạo"):
        info.append(f"  • Giờ hoàng đạo: {hours}")
    if menh := _vn_line(text, "Mệnh ngày"):
        info.append(f"  • Mệnh ngày: {menh}")
    if xung := _vn_line(text, "Tuổi xung"):
        info.append(f"  • Tuổi xung khắc: {xung}")

    # 5. Hướng xuất hành
    gods = [f"{god}: {direction}" for god in ("Hỷ thần", "Tài thần", "Kê thần") if (direction := _vn_line(text, god))]
    if gods:
        info.append(f"  • Hướng tốt: {', '.join(gods)}")

    # Dự phòng nếu bóc tách lỗi
    if len(info) <= 1:
        snippet = ""
        for line in lines[:30]:
            if any(k in line.lower() for k in ["lịch âm", "hoàng đạo", "ngày", "tháng", "năm", "mệnh", "tuổi xung"]):
                snippet += f"  • {line}\n"
        if snippet:
            return f"📅 **Lịch vạn niên hôm nay:**\n{snippet}"
        return "📅 **Lịch vạn niên hôm nay:** Đang cập nhật dữ liệu..."

    return "\n".join(info)


async def handle_zodiac_query(query: str = None) -> str:
    """Tra cứu tử vi cung hoàng đạo từ BaoMoi."""
    url = "https://baomoi.com/tien-ich-tu-vi-cung-hoang-dao.epi"
    try:
        q_lower = (query or "").lower()
        
        # 1. Trích xuất ngày tháng từ query
        day, month = None, None
        
        # Thử tìm dạng "ngày X tháng Y" hoặc "mùng X tháng Y"
        match_date_text = re.search(r'(?:ngày|mùng)?\s*(\d+)\s+tháng\s+(\d+)', q_lower)
        if match_date_text:
            day = int(match_date_text.group(1))
            month = int(match_date_text.group(2))
        else:
            # Thử tìm dạng "X/Y" hoặc "X-Y"
            match_date_slash = re.search(r'\b(\d{1,2})[-/](\d{1,2})\b', q_lower)
            if match_date_slash:
                day = int(match_date_slash.group(1))
                month = int(match_date_slash.group(2))
                
        matched_sign = None
        date_prefix = ""
        
        if day is not None and month is not None:
            # Validate ngày tháng hợp lệ sơ bộ
            days_in_month = {1:31, 2:29, 3:31, 4:30, 5:31, 6:30, 7:31, 8:31, 9:30, 10:31, 11:30, 12:31}
            if 1 <= month <= 12 and 1 <= day <= days_in_month.get(month, 31):
                zodiac_info = get_zodiac_by_date(day, month)
                if zodiac_info:
                    matched_sign = zodiac_info["name"].lower()
                    date_prefix = f"🔮 Ngày {day} tháng {month} thuộc cung **{zodiac_info['name']}** ({zodiac_info['range_str']}).\n\n"
        
        val = await browser.visit_and_evaluate(url, "document.body.innerText")
        text = re.sub(r'[ \t\f\v]+', ' ', str(val)) if val else ""
        if not text:
            if date_prefix:
                return date_prefix + "🔮 Không thể tải dữ liệu tử vi từ BaoMoi."
            return "🔮 Không thể tải dữ liệu tử vi từ BaoMoi."
        
        if not matched_sign:
            for sign, keywords in ZODIAC_SIGNS.items():
                if any(k in q_lower for k in keywords):
                    matched_sign = sign
                    break
                    
        zodiac_detail = extract_zodiac_info(text, matched_sign)
        if date_prefix:
            # Tránh lặp lại tiêu đề tử vi nếu extract_zodiac_info trả về chuỗi rỗng/mặc định
            if zodiac_detail.startswith("🔮 **Tử vi hôm nay:**"):
                # Nếu không khớp cung nào trong Báo Mới, hoặc chỉ báo mặc định, chỉ hiển thị kết quả ngày tháng
                return date_prefix
            return date_prefix + zodiac_detail
        return zodiac_detail
    except Exception as e:
        log.error(f"Error fetching zodiac: {e}")
        return f"🔮 Có lỗi xảy ra khi lấy thông tin tử vi: {str(e)}"


async def handle_vannien_query(query: str = None) -> str:
    """Tra cứu lịch vạn niên từ BaoMoi."""
    url = "https://baomoi.com/tien-ich-lich-van-nien.epi"
    try:
        val = await browser.visit_and_evaluate(url, "document.body.innerText")
        text = re.sub(r'[ \t\f\v]+', ' ', str(val)) if val else ""
        if not text:
            return "📅 Không thể tải dữ liệu lịch vạn niên từ BaoMoi."
            
        return extract_vannien_info(text)
    except Exception as e:
        log.error(f"Error fetching calendar: {e}")
        return f"📅 Có lỗi xảy ra khi lấy thông tin lịch vạn niên: {str(e)}"

async def handle_cgv_movies_query(query: str = None, **kwargs) -> str:
    """Cào thông tin phim đang chiếu và sắp chiếu từ CGV sử dụng StealthyFetcher."""
    now_showing_url = "https://www.cgv.vn/default/movies/now-showing.html"
    coming_soon_url = "https://www.cgv.vn/default/movies/coming-soon-1.html"
    
    q_lower = (query or "").lower()
    user_text = kwargs.get("user_text", "").lower()
    combined_text = q_lower + " " + user_text
    
    show_now = True
    show_coming = True
    
    is_coming_query = any(k in combined_text for k in ["sắp", "sap", "coming", "chuẩn bị"])
    is_now_query = any(k in combined_text for k in ["đang", "dang", "now", "chiếu rạp", "hôm nay", "lich chieu", "lịch chiếu"])
    
    if is_coming_query and not is_now_query:
        show_now = False
    elif is_now_query and not is_coming_query:
        show_coming = False
        
    def fetch_cgv(url):
        from scrapling.fetchers import StealthyFetcher
        from engine.tools.browser import stealth_fetch_kwargs
        try:
            log.info(f"StealthyFetcher fetching CGV URL: {url}")
            page = StealthyFetcher.fetch(url, headless=True, solve_cloudflare=True, **stealth_fetch_kwargs())
            items = page.css(".products-grid li.item, li.item")
            movies = []
            for i in range(min(4, items.length)):
                item = items[i]
                
                # title
                title = item.css(".product-name a::text").get()
                if not title:
                    title = item.css("h2.product-name a::text").get()
                if not title:
                    title = item.css("a::text").get()
                title = title.strip() if title else "Không rõ tên"
                
                # cgv-movie-info fields
                genre = "Đang cập nhật"
                duration = "Đang cập nhật"
                release = "Đang cập nhật"
                
                info_blocks = item.css(".cgv-movie-info")
                for block in info_blocks:
                    bold_text = block.css(".cgv-info-bold::text").get()
                    normal_text = block.css(".cgv-info-normal::text").get()
                    if bold_text and normal_text:
                        bold_clean = bold_text.strip().lower()
                        normal_clean = normal_text.strip()
                        if "thể loại" in bold_clean or "genre" in bold_clean:
                            genre = normal_clean
                        elif "thời lượng" in bold_clean or "duration" in bold_clean:
                            duration = normal_clean
                        elif "khởi chiếu" in bold_clean or "release" in bold_clean:
                            release = normal_clean
                
                # img
                img = item.css("img::attr(src)").get()
                
                # link
                link = item.css(".product-name a::attr(href)").get()
                if not link:
                    link = item.css("a::attr(href)").get()
                
                movies.append({
                    "title": title,
                    "img": img or "",
                    "link": link or "",
                    "genre": genre,
                    "duration": duration,
                    "release": release
                })
            return movies
        except Exception as e:
            log.error(f"Error fetching CGV movies from {url}: {e}")
            return []

    loop = asyncio.get_event_loop()
    
    tasks = []
    if show_now:
        tasks.append(loop.run_in_executor(None, fetch_cgv, now_showing_url))
    else:
        async def dummy(): return []
        tasks.append(dummy())
        
    if show_coming:
        tasks.append(loop.run_in_executor(None, fetch_cgv, coming_soon_url))
    else:
        async def dummy(): return []
        tasks.append(dummy())
        
    res_now, res_coming = await asyncio.gather(*tasks)
    
    now_showing = res_now if show_now else []
    coming_soon = res_coming if show_coming else []
    
    output = []
    
    if show_now:
        output.append("=== PHIM ĐANG CHIẾU TẠI CGV ===")
        if now_showing:
            for idx, m in enumerate(now_showing):
                output.append(f"Phim {idx+1}:")
                output.append(f"Tên phim: {m['title']}")
                output.append(f"Poster: {m['img']}")
                output.append(f"Thể loại: {m['genre']}")
                output.append(f"Thời lượng: {m['duration']}")
                output.append(f"Khởi chiếu: {m['release']}")
                output.append(f"Chi tiết: {m['link']}")
                output.append("")
            output.append(f"Xem thêm tại: {now_showing_url}\n")
        else:
            output.append("Không thể tải danh sách phim đang chiếu hoặc danh sách trống.\n")
            
    if show_coming:
        output.append("=== PHIM SẮP CHIẾU TẠI CGV ===")
        if coming_soon:
            for idx, m in enumerate(coming_soon):
                output.append(f"Phim {idx+1}:")
                output.append(f"Tên phim: {m['title']}")
                output.append(f"Poster: {m['img']}")
                output.append(f"Thể loại: {m['genre']}")
                output.append(f"Thời lượng: {m['duration']}")
                output.append(f"Khởi chiếu: {m['release']}")
                output.append(f"Chi tiết: {m['link']}")
                output.append("")
            output.append(f"Xem thêm tại: {coming_soon_url}\n")
        else:
            output.append("Không thể tải danh sách phim sắp chiếu hoặc danh sách trống.\n")
        
    return "\n".join(output)


CACHE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "config", "epic.json")


async def handle_epic_free_games_query(query: str = None, **kwargs) -> str:
    """Lấy danh sách game miễn phí tuần này từ Epic Games Store."""
    api_url = "https://store-site-backend-static.ak.epicgames.com/freeGamesPromotions"
    locale = "vi-VN"
    url = f"{api_url}?locale={locale}&country=VN"

    data = None
    from_cache = False
    try:
        import httpx
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
            with open(CACHE_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
    except Exception as e:
        log.warning(f"Epic API request failed: {e}")
        if os.path.exists(CACHE_PATH):
            try:
                with open(CACHE_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                from_cache = True
            except Exception:
                pass
        if not data:
            return "Không thể kết nối đến Epic Games Store. Vui lòng thử lại sau."

    elements = data.get("data", {}).get("Catalog", {}).get("searchStore", {}).get("elements", [])
    if not elements:
        return "Không tìm thấy thông tin game miễn phí từ Epic Games."

    current_free = []
    upcoming_free = []

    for e in elements:
        promos = e.get("promotions")
        if not promos:
            continue
        title = e.get("title", "Không rõ tên")
        key_images = e.get("keyImages", [])
        thumb = ""
        for img in key_images:
            if img.get("type") in ("Thumbnail", "DieselGameBoxTall", "OfferImageTall"):
                thumb = img.get("url", "")
                break
        if not thumb and key_images:
            thumb = key_images[0].get("url", "")

        # Current promotional offers (free = discountPercentage == 0)
        for offer_group in promos.get("promotionalOffers", []):
            for offer in offer_group.get("promotionalOffers", []):
                ds = offer.get("discountSetting", {})
                if ds.get("discountPercentage", -1) != 0:
                    continue
                start = (offer.get("startDate") or "")[:10]
                end = (offer.get("endDate") or "")[:10]
                current_free.append({"title": title, "thumb": thumb, "start": start, "end": end})

        # Upcoming (free = discountPercentage == 0)
        for offer_group in promos.get("upcomingPromotionalOffers", []):
            for offer in offer_group.get("promotionalOffers", []):
                ds = offer.get("discountSetting", {})
                if ds.get("discountPercentage", -1) != 0:
                    continue
                start = (offer.get("startDate") or "")[:10]
                end = (offer.get("endDate") or "")[:10]
                upcoming_free.append({"title": title, "thumb": thumb, "start": start, "end": end})

    # Deduplicate by title, sort by startDate
    current_dedup = {}
    for g in current_free:
        if g["title"] not in current_dedup:
            current_dedup[g["title"]] = g
    current_list = sorted(current_dedup.values(), key=lambda x: x["start"])[:2]

    upcoming_dedup = {}
    for g in upcoming_free:
        if g["title"] not in upcoming_dedup:
            upcoming_dedup[g["title"]] = g
    upcoming_list = sorted(upcoming_dedup.values(), key=lambda x: x["start"])[:2]

    output = []
    if from_cache:
        output.append("⚠️ Dữ liệu từ bộ nhớ đệm (API không phản hồi).\n")
    output.append("=== GAME MIỄN PHÍ TUẦN NÀY TRÊN EPIC GAMES ===")
    output.append("Nguồn: https://store.epicgames.com/vi/free-games\n")

    if current_list:
        output.append("**🎮 ĐANG MIỄN PHÍ**")
        output.append("| " + " | ".join(f"![{game['title']}]({game['thumb']})" for game in current_list) + " |")
        output.append("|" + "|".join(":---:" for _ in current_list) + "|")
        output.append("| " + " | ".join(f"**{game['title']}** ⏳ đến {game['end']}" for game in current_list) + " |")
        output.append("")

    if upcoming_list:
        output.append("**⏰ SẮP MIỄN PHÍ**")
        output.append("| " + " | ".join(f"![{game['title']}]({game['thumb']})" for game in upcoming_list) + " |")
        output.append("|" + "|".join(":---:" for _ in upcoming_list) + "|")
        output.append("| " + " | ".join(f"**{game['title']}** từ {game['start']} đến {game['end']}" for game in upcoming_list) + " |")
        output.append("")
    output.append("Xem thêm tại: https://store.epicgames.com/vi/free-games")
    return "\n".join(output)
