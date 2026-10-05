import hashlib
import logging
import re
import sqlite3
import time
from pathlib import Path
from urllib.parse import quote

from engine.tools.browser import browser

log = logging.getLogger("jarvis.legal_engine")

_CACHE_DIR = Path(__file__).parent.parent.parent / "data" / "cache"
_CACHE_DB = _CACHE_DIR / "legal_cache.db"
_CACHE_TTL = 7200

# Endpoint tra cứu VĂN BẢN pháp luật thật sự (không phải mục "hỏi đáp/tư vấn" chung
# chung) — trả kết quả là các luật/nghị định/thông tư có tiêu đề + link rõ ràng.
_TVPL_SEARCH = "https://thuvienphapluat.vn/page/tim-van-ban.aspx?keyword={kw}&match=True&area=0"
# Nguồn dự phòng khi TVPL không kết nối được hoặc không khớp kết quả nào —
# luatvietnam.vn không yêu cầu đăng nhập để đọc toàn văn điều luật.
_LVN_SEARCH = "https://luatvietnam.vn/van-ban/tim-kiem.html?Keywords={kw}"


def _is_lvn_url(url: str) -> bool:
    return "luatvietnam.vn" in url

# LƯU Ý VỀ KEYWORDS: cố tình KHÔNG dùng các từ đơn lẻ quá chung chung (vd "dân sự",
# "hình sự", "thuế", "giao thông", "doanh nghiệp", "quân sự"...) làm keyword riêng —
# pháp luật VN có rất nhiều văn bản khác nhau cùng nhắc tới các từ đó (vd "dân sự"
# còn xuất hiện trong Bộ luật TỐ TỤNG dân sự — 1 luật hoàn toàn khác). Nếu để những
# từ chung này khớp, tra "tố tụng dân sự" sẽ bị trả nhầm về Bộ luật Dân sự, tra "thuế
# thu nhập cá nhân" sẽ bị trả nhầm về Luật Quản lý thuế... Chỉ giữ cụm từ đủ đặc hiệu
# (tên đầy đủ/viết tắt chính thức/số hiệu) để tránh khớp sai sang văn bản khác.
CURATED_LAWS = [
    {
        "id": "bo-luat-lao-dong-2019",
        "title": "Bộ luật Lao động 2019",
        "url": "https://thuvienphapluat.vn/van-ban/Lao-dong-Tien-luong/Bo-Luat-lao-dong-2019-333670.aspx#tab1",
        "keywords": ["bộ luật lao động", "lao động 2019", "bllđ 2019", "labor code", "bllđ", "45/2019/qh14"],
    },
    {
        "id": "bo-luat-hinh-su-2015",
        "title": "Bộ luật Hình sự 2015 (sửa đổi 2017)",
        "url": "https://thuvienphapluat.vn/van-ban/Trach-nhiem-hinh-su/Bo-luat-hinh-su-2015-296661.aspx#tab1",
        "keywords": ["bộ luật hình sự", "hình sự 2015", "blhs", "penal code", "100/2015/qh13"],
    },
    {
        "id": "luat-xu-ly-vi-pham-hanh-chinh-2012",
        "title": "Luật Xử lý vi phạm hành chính 2012",
        "url": "https://thuvienphapluat.vn/van-ban/Vi-pham-hanh-chinh/Luat-xu-ly-vi-pham-hanh-chinh-2012-142766.aspx#tab1",
        "keywords": ["xử lý vi phạm hành chính", "vi phạm hành chính 2012", "xlvphc", "15/2012/qh13"],
    },
    {
        "id": "luat-doanh-nghiep-2020",
        "title": "Luật Doanh nghiệp 2020 (số 59/2020/QH14)",
        "url": "https://thuvienphapluat.vn/van-ban/Doanh-nghiep/Luat-Doanh-nghiep-so-59-2020-QH14-427301.aspx#tab1",
        "keywords": ["luật doanh nghiệp", "doanh nghiệp 2020", "59/2020/qh14"],
    },
    {
        "id": "bo-luat-dan-su-2015",
        "title": "Bộ luật Dân sự 2015",
        "url": "https://thuvienphapluat.vn/van-ban/Quyen-dan-su/Bo-luat-dan-su-2015-296215.aspx#tab1",
        "keywords": ["bộ luật dân sự", "dân sự 2015", "blds", "civil code", "91/2015/qh13"],
    },
    {
        # Luật Giao thông đường bộ 2008 đã hết hiệu lực, được thay thế bởi luật này
        # (URL cũ ở đây còn bị trỏ nhầm sang một Quyết định PCCC không liên quan).
        # Không dùng bare "giao thông" làm keyword vì Luật Đường bộ 2024 (35/2024/QH15,
        # về hạ tầng) là 1 luật khác cũng ban hành song song, dễ bị lẫn.
        "id": "luat-trat-tu-atgt-duong-bo-2024",
        "title": "Luật Trật tự, an toàn giao thông đường bộ 2024 (số 36/2024/QH15)",
        "url": "https://thuvienphapluat.vn/van-ban/Giao-thong-Van-tai/Luat-trat-tu-an-toan-giao-thong-duong-bo-2024-so-36-2024-QH15-444251.aspx#tab1",
        "keywords": ["luật giao thông", "giao thông đường bộ", "an toàn giao thông", "traffic law", "atgt", "36/2024/qh15"],
    },
    {
        "id": "nghi-dinh-168-2024-atgt",
        "title": "Nghị định 168/2024/NĐ-CP (mức phạt vi phạm giao thông đường bộ)",
        "url": "https://thuvienphapluat.vn/van-ban/Giao-thong-Van-tai/Nghi-dinh-168-2024-ND-CP-xu-phat-vi-pham-hanh-chinh-an-toan-giao-thong-duong-bo-619502.aspx#tab1",
        "keywords": ["nghị định 168", "nđ 168", "168/2024/nđ-cp", "mức phạt giao thông", "phạt vi phạm giao thông", "nđ168"],
    },
    {
        "id": "luat-dat-dai-2024",
        "title": "Luật Đất đai 2024 (số 31/2024/QH15)",
        "url": "https://thuvienphapluat.vn/van-ban/Bat-dong-san/Luat-Dat-dai-2024-31-2024-QH15-523642.aspx#tab1",
        "keywords": ["luật đất đai", "đất đai 2024", "land law", "31/2024/qh15"],
    },
    {
        "id": "luat-thu-thue-2019",
        "title": "Luật Quản lý thuế 2019 (số 38/2019/QH14)",
        "url": "https://thuvienphapluat.vn/van-ban/Thue-Phi-Le-Phi/Luat-quan-ly-thue-2019-387595.aspx#tab1",
        "keywords": ["luật quản lý thuế", "quản lý thuế 2019", "tax law", "38/2019/qh14"],
    },
    {
        "id": "luat-nghia-vu-quan-su-2015",
        "title": "Luật nghĩa vụ quân sự 2015",
        "url": "https://thuvienphapluat.vn/van-ban/Linh-vuc-khac/Luat-nghia-vu-quan-su-2015-282383.aspx#tab1",
        "keywords": ["luật nghĩa vụ quân sự", "nghĩa vụ quân sự 2015", "nvqs", "78/2015/qh13"],
    },
]


def _ensure_cache():
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(_CACHE_DB)) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, data TEXT, created_at REAL)")
        conn.commit()


def _cache_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _cache_get(key: str) -> str | None:
    try:
        with sqlite3.connect(str(_CACHE_DB)) as conn:
            row = conn.execute("SELECT data, created_at FROM cache WHERE key = ?", (key,)).fetchone()
            if row and time.time() - row[1] < _CACHE_TTL:
                return row[0]
    except Exception:
        pass
    return None


def _cache_set(key: str, data: str):
    try:
        _ensure_cache()
        with sqlite3.connect(str(_CACHE_DB)) as conn:
            conn.execute("INSERT OR REPLACE INTO cache (key, data, created_at) VALUES (?, ?, ?)",
                         (key, data, time.time()))
            conn.commit()
    except Exception as e:
        log.warning(f"Cache write failed: {e}")


_NON_DIACRITIC_MAP = {
    "à": "a", "á": "a", "ả": "a", "ã": "a", "ạ": "a",
    "â": "a", "ầ": "a", "ấ": "a", "ẩ": "a", "ẫ": "a", "ậ": "a",
    "ă": "a", "ằ": "a", "ắ": "a", "ẳ": "a", "ẵ": "a", "ặ": "a",
    "è": "e", "é": "e", "ẻ": "e", "ẽ": "e", "ẹ": "e",
    "ê": "e", "ề": "e", "ế": "e", "ể": "e", "ễ": "e", "ệ": "e",
    "ì": "i", "í": "i", "ỉ": "i", "ĩ": "i", "ị": "i",
    "ò": "o", "ó": "o", "ỏ": "o", "õ": "o", "ọ": "o",
    "ô": "o", "ồ": "o", "ố": "o", "ổ": "o", "ỗ": "o", "ộ": "o",
    "ơ": "o", "ờ": "o", "ớ": "o", "ở": "o", "ỡ": "o", "ợ": "o",
    "ù": "u", "ú": "u", "ủ": "u", "ũ": "u", "ụ": "u",
    "ư": "u", "ừ": "u", "ứ": "u", "ử": "u", "ữ": "u", "ự": "u",
    "ỳ": "y", "ý": "y", "ỷ": "y", "ỹ": "y", "ỵ": "y",
    "đ": "d",
}

def _no_diacritics(text: str) -> str:
    return "".join(_NON_DIACRITIC_MAP.get(c, c) for c in text.lower())


def _match_curated(query: str) -> dict | None:
    ql = query.lower()
    qn = _no_diacritics(query)
    for law in CURATED_LAWS:
        for kw in law["keywords"]:
            if kw in ql or kw in qn:
                return law
    return None


def _document_link_response(url: str, title: str | None = None) -> str:
    heading = f"**{title}**\n" if title else ""
    return (
        f"{heading}🔗 {url}\n\n"
        "Văn bản này có nội dung dài. Hãy mở link để xem toàn văn; "
        "nếu cần, hãy hỏi điều hoặc khoản cụ thể để tra cứu."
    )


async def _fetch_page(url: str):
    page, used_stealth = await browser._fetch(url)
    return page


async def _search_tvpl(query: str) -> list[dict]:
    """Mỗi kết quả văn bản nằm trong khối <div class="nq"> chứa
    <p class="nqTitle"><a href=...>Tên văn bản</a></p> và <p class="nqContent">đoạn trích</p>."""
    url = _TVPL_SEARCH.format(kw=quote(query))
    log.info(f"Legal search (TVPL): {url}")
    page = await _fetch_page(url)

    articles = []
    items = page.css(".left-col .nq")
    if items and items.length:
        for item in items[:10]:
            a = item.css(".nqTitle a")
            href = (a.css("::attr(href)").get() or "").strip()
            title = " ".join(a.css("::text").getall() or []).strip()
            if not title or not href:
                continue
            # 2 bước như trên: TVPL bọc từ khoá khớp trong <em>, gọi "::text" gộp
            # chung trong 1 chuỗi selector sẽ làm mất đúng phần từ khoá đó.
            content = item.css(".nqContent")
            desc = " ".join(content.css("::text").getall() or [])
            desc = re.sub(r"\s+", " ", desc).strip()
            articles.append({
                "title": title,
                "url": href if href.startswith("http") else "https://thuvienphapluat.vn" + href,
                "description": desc[:300],
                "date": "",
            })

    if not articles:
        text = page.get_all_text() or ""
        lines = [l.strip() for l in text.split("\n") if len(l.strip()) > 60]
        seen = set()
        for line in lines[:30]:
            m = re.search(r'(https?://thuvienphapluat\.vn/[^\s"]+)', line)
            if m and m.group(1) not in seen:
                seen.add(m.group(1))
                articles.append({"title": line[:200], "url": m.group(1), "description": "", "date": ""})
    return articles


async def _search_luatvietnam(query: str) -> list[dict]:
    """Mỗi kết quả nằm trong <article class="art-search"> chứa
    <h2 class="doc-title"><a href=...>Tên văn bản</a></h2> và <div class="doc-summary">tóm tắt</div>."""
    url = _LVN_SEARCH.format(kw=quote(query))
    log.info(f"Legal search (LuatVietnam): {url}")
    page = await _fetch_page(url)

    articles = []
    for item in page.css("article.art-search")[:10]:
        a = item.css(".doc-title a")
        href = (a.css("::attr(href)").get() or "").strip()
        # QUAN TRỌNG: phải lấy text 2 bước — item.css(".x") rồi mới .css("::text") —
        # vì LuatVietnam bọc từ khoá khớp trong <mark>, và gọi "::text" trực tiếp
        # trong 1 chuỗi selector ("item.css('.x::text')") sẽ BỎ QUA toàn bộ nội dung
        # nằm trong <mark> (mất chữ/số thật, không chỉ lệch khoảng trắng).
        title = re.sub(r"\s+", " ", " ".join(a.css("::text").getall() or [])).strip()
        if not title or not href:
            continue
        summary = item.css(".doc-summary")
        desc = " ".join(summary.css("::text").getall() or [])
        desc = re.sub(r"\s+", " ", desc).strip()
        articles.append({
            "title": title,
            "url": href if href.startswith("http") else "https://luatvietnam.vn" + href,
            "description": desc[:300],
            "date": "",
        })
    return articles


async def search_law(query: str) -> str:
    if not query:
        return "Vui lòng nhập từ khoá cần tra cứu."

    curated = _match_curated(query)
    if curated:
        log.info(f"Matched curated law: {curated['title']}")
        return _document_link_response(curated["url"], curated["title"])

    ql = query.lower()
    qn = _no_diacritics(query)
    if any(w in ql or w in qn for w in ["luật", "bộ luật", "nghị định", "thông tư", "văn bản", "luat", "bo luat"]):
        curated_all = _match_curated(f"luật {query}")
        if not curated_all:
            for law in CURATED_LAWS:
                if any(kw in ql or kw in qn for kw in law["keywords"]):
                    return _document_link_response(law["url"], law["title"])

    key = _cache_key(f"search:{query}")
    cached = _cache_get(key)
    if cached:
        return cached

    # Ưu tiên TVPL; nếu lỗi kết nối (mạng chậm, chặn bot...) hoặc không khớp kết quả
    # nào thì tự động thử lại bằng luatvietnam.vn trước khi báo "không tìm thấy".
    articles = []
    try:
        articles = await _search_tvpl(query)
    except Exception as e:
        log.warning(f"TVPL search failed, fallback to LuatVietnam: {e}")

    if not articles:
        try:
            articles = await _search_luatvietnam(query)
        except Exception as e:
            log.warning(f"LuatVietnam search failed: {e}")
            if not articles:
                return f"Lỗi kết nối cả 2 nguồn tra cứu (thuvienphapluat.vn, luatvietnam.vn): {e}"

    if not articles:
        return (
            f"Không tìm thấy kết quả cho: {query}\n\n"
            "💡 Để tra chính xác hơn (pháp luật VN có rất nhiều văn bản trùng lĩnh vực), hãy cho biết:\n"
            "- Số hiệu văn bản nếu biết, vd \"168/2024/NĐ-CP\" hoặc \"45/2019/QH14\"\n"
            "- Hoặc tên đầy đủ kèm năm ban hành, vd \"Luật Bảo hiểm xã hội 2024\"\n"
            "- Nếu đã biết đúng văn bản, hỏi thẳng \"Điều mấy\" (và \"Khoản mấy\" nếu cần) để lấy đúng nội dung."
        )

    output = [f"📚 Kết quả tra cứu: **{query}**\n"]
    for i, a in enumerate(articles[:8], 1):
        output.append(f"**{i}. {a['title']}**")
        if a.get("description"):
            output.append(f"   {a['description'][:200]}")
        if a.get("date"):
            output.append(f"   📅 {a['date']}")
        output.append(f"   🔗 {a['url']}")
        output.append("")

    final = "\n".join(output)
    _cache_set(key, final)
    return final


# Nhận diện người dùng hỏi đích danh "Điều N" (có hoặc không dấu) để tra thẳng
# vào đúng điều luật thay vì trả cả văn bản dài.
_ARTICLE_QUERY_RE = re.compile(r"đi[eềêể]u\s*(\d+)", re.IGNORECASE)
# Mỗi mốc lớn trong văn bản TVPL (Điều/Chương/Mục) có 1 thẻ <a name="dieu_N">
# (không lẫn với diem_/khoan_ là các mục con bên trong 1 Điều).
_SECTION_ANCHOR_RE = re.compile(r"^(dieu|chuong|muc)_(\d+)$")
_THUOCTINH_LABELS = [
    "Số hiệu", "Loại văn bản", "Nơi ban hành", "Người ký", "Ngày ban hành",
    "Ngày hiệu lực", "Ngày công báo", "Số công báo", "Tình trạng",
]


def _extract_article_number(query: str) -> int | None:
    m = _ARTICLE_QUERY_RE.search(query)
    if not m:
        m = re.search(r"\bdieu\s*(\d+)\b", _no_diacritics(query), re.IGNORECASE)
    return int(m.group(1)) if m else None


# Nhận diện "Khoản M" (chỉ có ý nghĩa khi đi kèm 1 "Điều N" cụ thể) để tra sâu hơn
# nữa vào bên trong 1 Điều — vd "khoản 2 điều 25 bộ luật lao động".
_CLAUSE_QUERY_RE = re.compile(r"khoản\s*(\d+)", re.IGNORECASE)
# Mỗi khoản trong 1 Điều luôn là 1 đoạn văn riêng, mở đầu bằng "N. " (số + dấu chấm).
_CLAUSE_START_RE = re.compile(r"^\s*(\d+)\.\s")


def _extract_clause_number(query: str) -> int | None:
    m = _CLAUSE_QUERY_RE.search(query)
    if not m:
        m = re.search(r"\bkhoan\s*(\d+)\b", _no_diacritics(query), re.IGNORECASE)
    return int(m.group(1)) if m else None


def _slice_clause(article_paragraphs: list[str], clause_no: int) -> list[str] | None:
    """article_paragraphs: các đoạn văn của 1 Điều đã trích được (đoạn đầu tiên là
    dòng tiêu đề 'Điều N. ...'). Trả về [tiêu đề, (các) đoạn thuộc Khoản N] nếu có."""
    if not article_paragraphs:
        return None
    heading = article_paragraphs[0]
    out, collecting = [], False
    for text in article_paragraphs[1:]:
        m = _CLAUSE_START_RE.match(text)
        if m:
            if int(m.group(1)) == clause_no:
                collecting = True
            elif collecting:
                break
        if collecting:
            out.append(text)
    if not out:
        return None
    return [heading] + out


def _p_section_anchor(p):
    """Trả về ('dieu'|'chuong'|'muc', N) nếu đoạn <p> này mở đầu 1 mục lớn."""
    for a in p.css("a[name]"):
        m = _SECTION_ANCHOR_RE.match(a.attrib.get("name", ""))
        if m:
            return m.group(1), int(m.group(2))
    return None


def _parse_metadata(page) -> list[str]:
    """#divThuocTinh gộp nhiều cặp 'Nhãn: Giá trị' liền nhau trong text thô —
    tách theo danh sách nhãn cố định của TVPL cho dễ đọc thay vì để nguyên khối."""
    box = page.css("#divThuocTinh")
    if not box or not box.length:
        return []
    raw = re.sub(r"\s+", " ", box[0].get_all_text() or "").strip()
    pattern = "|".join(re.escape(l) for l in _THUOCTINH_LABELS)
    parts = re.split(f"({pattern}):", raw)
    out = []
    for i in range(1, len(parts) - 1, 2):
        label, value = parts[i].strip(), parts[i + 1].strip(" .|")
        if value:
            out.append(f"**{label}:** {value}")
    return out


def _parse_lvn_metadata(page) -> list[str]:
    """Bảng thuộc tính trên luatvietnam.vn là 1 <table> với các cặp ô
    <td><strong>Nhãn:</strong></td><td>Giá trị</td> liền kề nhau trong cùng <tr>.
    Một số giá trị (Tình trạng hiệu lực, Ngày công báo...) bị khoá sau đăng nhập —
    những ô đó luôn kèm chữ "Đăng nhập" nên bỏ qua để không hiện rác."""
    out = []
    for strong in page.css("td strong"):
        raw_label = (strong.get_all_text() or "").strip()
        m = re.match(r"^([^:]+:)", raw_label)
        label = m.group(1) if m else raw_label
        if not label:
            continue
        td = strong.parent
        row_cells = list(td.parent.css("td"))
        try:
            idx = row_cells.index(td)
        except ValueError:
            continue
        if idx + 1 >= len(row_cells):
            continue
        value = re.sub(r"\s+", " ", row_cells[idx + 1].get_all_text() or "").strip()
        if not value or "Đăng nhập" in value or value == "Đang cập nhật":
            continue
        out.append(f"**{label}** {value}")
    return out


def _lvn_block_heading(block):
    """Nếu khối <div class="mab2"> này mở đầu bằng dòng tiêu đề in đậm
    'Điều N. ...' hoặc 'Chương/Phần/Mục ...' thì trả về ('dieu', N) / ('chuong', None)."""
    b = block.css("p > b")
    if not b:
        return None
    txt = (b[0].get_all_text() or "").strip()
    m = re.match(r"^Điều\s+(\d+)\.", txt)
    if m:
        return "dieu", int(m.group(1))
    if re.match(r"^(Chương|Phần|Mục)\b", txt, re.IGNORECASE):
        return "chuong", None
    return None


def _lvn_extract_article(blocks, article_no: int) -> list[str]:
    out, collecting = [], False
    for block in blocks:
        heading = _lvn_block_heading(block)
        if heading and heading[0] == "dieu":
            if heading[1] == article_no:
                collecting = True
            elif collecting:
                break
        elif heading and heading[0] == "chuong" and collecting:
            break
        if collecting:
            text = (block.get_all_text() or "").strip()
            if text:
                out.append(text)
    return out


async def get_document_detail(
    url: str,
    article_no: int | None = None,
    clause_no: int | None = None,
    title: str | None = None,
) -> str:
    key = _cache_key(f"detail:{url}:{article_no or ''}:{clause_no or ''}")
    cached = _cache_get(key)
    if cached:
        return cached

    log.info(f"Fetching document detail: {url} (article_no={article_no}, clause_no={clause_no})")
    try:
        page = await _fetch_page(url)
    except Exception as e:
        return f"Lỗi tải văn bản: {e}"

    is_lvn = _is_lvn_url(url)
    metadata = []
    try:
        if is_lvn:
            # luatvietnam.vn: mỗi Điều/Chương nằm trong 1 <div class="mab2">, không
            # dùng thẻ <a name="dieu_N"> như TVPL nên phải nhận diện qua tiêu đề in đậm.
            paragraphs = page.css(".mab2")
            metadata = _parse_lvn_metadata(page)
        else:
            # .cldivContentDocVn là bản Tiếng Việt (trang luôn kèm 1 bản .cldivContentDocEn
            # song song — nếu không chỉ định đúng khối này sẽ dễ lẫn nội dung tiếng Anh).
            paragraphs = page.css(".cldivContentDocVn .content1 p")
            metadata = _parse_metadata(page)
    except Exception as e:
        log.warning(f"Metadata parse failed: {e}")
        paragraphs = page.css(".mab2") if is_lvn else page.css(".cldivContentDocVn .content1 p")

    if not paragraphs or not paragraphs.length:
        # Trang không đúng cấu trúc chuẩn TVPL -> fallback lấy text thô
        all_text = page.get_all_text() or ""
        lines = [l.strip() for l in all_text.split("\n") if len(l.strip()) > 40]
        sections, started = [], False
        for line in lines:
            if any(kw in line.lower() for kw in ["điều", "chương", "mục", "khoản"]):
                started = True
            if started:
                sections.append(line)
            if len(sections) >= 80:
                break
        if not sections:
            return "Không thể trích xuất nội dung văn bản."
        body = "\n".join(sections[:80])
        if len(body) > 6000:
            body = body[:6000] + "\n\n...(nội dung tiếp theo đã được cắt bớt)"
        _cache_set(key, body)
        return body

    output = []
    if title:
        output.append(f"**{title}**")
    if metadata:
        output.append("**Thông tin văn bản:**")
        output.extend(f"   {m}" for m in metadata)
        output.append("")

    if article_no is not None:
        if is_lvn:
            found = _lvn_extract_article(paragraphs, article_no)
        else:
            found, collecting = [], False
            for p in paragraphs:
                anchor = _p_section_anchor(p)
                if anchor and anchor[0] == "dieu":
                    if anchor[1] == article_no:
                        collecting = True
                    elif collecting:
                        break
                elif anchor and collecting:
                    break  # sang Chương/Mục khác -> hết phạm vi Điều đang lấy
                if collecting:
                    text = (p.get_all_text() or "").strip()
                    if text:
                        found.append(text)
        if not found:
            output.append(f"Không tìm thấy Điều {article_no} trong văn bản này.")
            output.append(f"🔗 {url}")
        elif clause_no is not None:
            clause_found = _slice_clause(found, clause_no)
            if clause_found is None:
                # Điều này có tồn tại nhưng không chia khoản theo số đã hỏi (vd Điều
                # chỉ có 1 đoạn duy nhất không đánh số) -> trả cả Điều để không mất thông tin.
                output.append(f"Không tìm thấy Khoản {clause_no} trong Điều {article_no} — trả về cả Điều:\n")
                output.append("\n".join(found))
            else:
                output.append("\n".join(clause_found))
            output.append(f"\n🔗 Toàn văn: {url}")
        else:
            output.append("\n".join(found))
            output.append(f"\n🔗 Toàn văn: {url}")
    else:
        body_lines = [(p.get_all_text() or "").strip() for p in paragraphs[:120]]
        body = "\n".join(l for l in body_lines if l)
        if len(body) > 6000:
            body = body[:6000] + (
                "\n\n...(nội dung tiếp theo đã được cắt bớt — "
                "hỏi rõ 'Điều bao nhiêu' để xem trọn vẹn điều đó)"
            )
        output.append(body)

    result = "\n".join(output)
    _cache_set(key, result)
    return result


async def legal_lookup(query: str, **kwargs) -> str:
    article_no = _extract_article_number(query)
    # "Khoản" chỉ có nghĩa khi đi kèm 1 Điều cụ thể (khoản luôn nằm trong 1 điều).
    clause_no = _extract_clause_number(query) if article_no is not None else None

    url_pattern = re.search(r'(https?://(?:thuvienphapluat|luatvietnam)\.vn[^\s)]+)', query)
    if url_pattern:
        if article_no is not None:
            return await get_document_detail(url_pattern.group(1), article_no=article_no, clause_no=clause_no)
        return _document_link_response(url_pattern.group(1))

    if "trợ giúp" in query.lower() or "help" in query.lower():
        output = ["**Các văn bản pháp luật có sẵn:**\n"]
        for law in CURATED_LAWS:
            output.append(f"- **{law['title']}**")
            output.append(f"  🔗 {law['url']}")
        output.append("\nHoặc gõ từ khoá bất kỳ để tìm kiếm trên thuvienphapluat.vn.")
        return "\n".join(output)

    # Hỏi đích danh 1 Điều trong 1 luật đã biết -> tra thẳng nội dung Điều đó,
    # thay vì chỉ trả link rồi bắt người dùng tự mở ra tìm.
    curated = _match_curated(query)
    if curated and article_no is not None:
        return await get_document_detail(
            curated["url"], article_no=article_no, clause_no=clause_no, title=curated["title"]
        )

    return await search_law(query)
