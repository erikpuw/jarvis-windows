import re
import logging

log = logging.getLogger("jarvis.tts_engine")

# ---------------------------------------------------------------------------
# Emoji stripping (shared — dùng chung cho MỌI engine TTS, edge lẫn vieneu)
# ---------------------------------------------------------------------------

_EMOJI_RE = re.compile(
    "["
    "\U0001F1E6-\U0001F1FF"  # Regional indicator symbols (emoji cờ quốc gia)
    "\U0001F300-\U0001FAFF"  # Pictographs, emoticons, transport, supplemental symbols A/B, extended-A
    "\U00002600-\U000026FF"  # Miscellaneous Symbols
    "\U00002700-\U000027BF"  # Dingbats
    "\U00002B00-\U00002BFF"  # Miscellaneous Symbols and Arrows (★ ⭐ ...)
    "\U00002500-\U000025FF"  # Box drawing + Geometric Shapes (├── ▶ ■ trong cây thư mục)
    "\U0000FE0F"              # Variation Selector-16 (emoji presentation selector)
    "\U0000200D"              # Zero Width Joiner (nối emoji ghép)
    "\U000020E3"              # Combining Enclosing Keycap (1️⃣ 2️⃣ ...)
    "]+",
    flags=re.UNICODE,
)


# Cue phi ngôn ngữ của VieNeu v3 Turbo (thử nghiệm): [cười] [thở dài] [hắng giọng].
# vieneu giữ nguyên; edge-tts không diễn được nên bỏ hẳn (xem prepare_tts_text).
EMOTION_CUE_RE = re.compile(
    r"\[(?:cười|thở dài|hắng giọng|chuckle|sigh|clear throat)\]", re.IGNORECASE
)


def strip_emoji_for_tts(text: str) -> str:
    """Loại bỏ emoji khỏi text trước khi đưa vào bất kỳ TTS engine nào."""
    return _EMOJI_RE.sub("", text)

# ---------------------------------------------------------------------------
# Vietnamese Text Normalization for TTS
# ---------------------------------------------------------------------------

def num_to_vietnamese_words(num: int) -> str:
    """Chuyển số nguyên sang chữ tiếng Việt chuẩn."""
    if num == 0:
        return "không"
        
    units = ["không", "một", "hai", "ba", "bốn", "năm", "sáu", "bảy", "tám", "chín"]
    
    # Hàm đọc khối 3 chữ số
    def read_three_digits(n: int, show_hundreds: bool = True) -> str:
        h = n // 100
        t = (n % 100) // 10
        u = n % 10
        
        res = []
        if show_hundreds or h > 0:
            res.append(units[h] + " trăm")
            
        if t == 0:
            if u > 0:
                if show_hundreds or h > 0:
                    res.append("lẻ")
                res.append(units[u])
        elif t == 1:
            res.append("mười")
            if u == 5:
                res.append("lăm")
            elif u > 0:
                res.append(units[u])
        else:
            res.append(units[t] + " mươi")
            if u == 1:
                res.append("mốt")
            elif u == 5:
                res.append("lăm")
            elif u > 0:
                res.append(units[u])
                
        return " ".join(res)

    # Chia nhóm 3 chữ số từ phải qua trái (nghìn, triệu, tỷ)
    chunks = []
    temp = num
    while temp > 0:
        chunks.append(temp % 1000)
        temp //= 1000
        
    read_parts = []
    
    for i in range(len(chunks) - 1, -1, -1):
        val = chunks[i]
        if val == 0:
            continue
            
        show_hundreds = (i < len(chunks) - 1)
        chunk_str = read_three_digits(val, show_hundreds)
        
        read_parts.append(chunk_str)
        if i > 0:
            level_idx = i % 3
            if level_idx == 1:
                read_parts.append("nghìn")
            elif level_idx == 2:
                read_parts.append("triệu")
            elif level_idx == 0:
                billion_repeats = i // 3
                read_parts.append("tỷ" * billion_repeats)
                
    result = " ".join(read_parts).strip()
    result = re.sub(r"\s+", " ", result)
    return result


# ---------------------------------------------------------------------------
# Chuẩn bị văn bản cho TTS — MỘT nơi duy nhất, dùng cho cả edge lẫn vieneu
# ---------------------------------------------------------------------------
# TTS đọc đúng những gì nó nhận. Vì vậy ở đây: (1) bỏ mọi thứ TTS không đọc được
# (markdown, URL, emoji, ký hiệu); (2) viết ra thành chữ tiếng Việt mọi thứ dễ đọc sai
# (số, đơn vị, ngày giờ, tiền, phép tính). Không được làm mất chữ của người nói.
# Điểm gọi duy nhất: tts_manager (mọi yêu cầu TTS đều đi qua đó). Hàm idempotent.

_DIGIT_WORDS = ["không", "một", "hai", "ba", "bốn", "năm", "sáu", "bảy", "tám", "chín"]


def _digits_to_words(digits: str) -> str:
    return " ".join(_DIGIT_WORDS[int(c)] for c in digits if c.isdigit())


def _number_to_words(num_str: str) -> str:
    """'1.500' -> một nghìn năm trăm; '3,5' -> ba phẩy năm; '007' -> không không bảy."""
    if "." in num_str and "," in num_str:
        dec_sep = "." if num_str.rfind(".") > num_str.rfind(",") else ","
        integer_part, decimal_part = num_str.rsplit(dec_sep, 1)
        integer_part = integer_part.replace("," if dec_sep == "." else ".", "")
    else:
        sep = "." if "." in num_str else "," if "," in num_str else ""
        parts = num_str.split(sep) if sep else [num_str]
        thousands = (
            len(parts) > 1
            and all(len(p) == 3 for p in parts[1:])
            and 1 <= len(parts[0]) <= 3
            and parts[0] != "0"
        )
        if len(parts) == 1 or thousands:
            integer_part, decimal_part = "".join(parts), ""
        else:
            integer_part, decimal_part = parts[0], "".join(parts[1:])
    if not decimal_part and len(integer_part) > 1 and integer_part.startswith("0"):
        return _digits_to_words(integer_part)  # 007, mã số
    if len(integer_part) >= 11:  # số định danh dài: đọc từng nhóm 3 chữ số
        groups = [integer_part[i:i + 3] for i in range(0, len(integer_part), 3)]
        words = ", ".join(_digits_to_words(g) for g in groups)
    else:
        words = num_to_vietnamese_words(int(integer_part))
    if decimal_part:
        words += " phẩy " + _digits_to_words(decimal_part)
    return words


# Đơn vị đứng ngay sau chữ số. Nhiều chữ: không phân biệt hoa/thường; một chữ: có phân biệt
# ("V" vôn khác "v", "m" mét khác "M").
_UNIT_WORDS = {
    "km/h": "ki lô mét trên giờ", "kmh": "ki lô mét trên giờ", "m/s": "mét trên giây",
    "kwh": "ki lô oát giờ", "mwh": "mê ga oát giờ", "wh": "oát giờ",
    "kw": "ki lô oát", "mw": "mê ga oát", "gw": "gi ga oát", "kv": "ki lô vôn",
    "mah": "mi li am pe giờ",
    "khz": "ki lô héc", "mhz": "mê ga héc", "ghz": "gi ga héc", "hz": "héc",
    "kbps": "ki lô bít trên giây", "mbps": "mê ga bít trên giây", "gbps": "gi ga bít trên giây",
    "kb": "ki lô bai", "mb": "mê ga bai", "gb": "gi ga bai", "tb": "tê ra bai",
    "km2": "ki lô mét vuông", "m2": "mét vuông", "cm2": "xen ti mét vuông", "mm2": "mi li mét vuông",
    "m3": "mét khối", "cm3": "xen ti mét khối", "km": "ki lô mét", "cm": "xen ti mét",
    "mm": "mi li mét", "kg": "ki lô gam", "mg": "mi li gam", "ml": "mi li lít", "ha": "héc ta",
    "ms": "mi li giây", "px": "pích xen", "fps": "khung hình trên giây", "rpm": "vòng trên phút",
    "db": "đề xi ben", "kcal": "ki lô ca lo", "min": "phút",
}
_UNIT_LETTER = {"m": "mét", "g": "gam", "l": "lít", "L": "lít", "s": "giây", "h": "giờ", "V": "vôn", "W": "oát"}
_UNIT_ALT = "|".join(sorted((re.escape(k) for k in _UNIT_WORDS), key=len, reverse=True))
_UNIT_RE = re.compile(r"(?<=\d)\s?(" + _UNIT_ALT + r")(?!\w)", re.IGNORECASE)
_UNIT_LETTER_RE = re.compile(r"(?<=\d)\s?([mglLshVW])(?!\w)")

# Từ đứng trước "/" khiến "/" nghĩa là "trên" (đồng/lượng, kWh/ngày, người/ngày...).
_PER_LEFT = r"(?:đồng|gam|lít|mét|giờ|giây|phút|oát|vôn|Mỹ|người|lần|cái|chiếc|bít|bai)"
_FILE_EXT = (
    r"py|js|ts|tsx|jsx|md|json|txt|html|htm|css|yml|yaml|toml|cfg|ini|env|sh|bat|exe|dll|log|csv|"
    r"pdf|png|jpg|jpeg|gif|svg|zip|docx|xlsx|pptx|mp3|mp4|wav|com|vn|net|org|io|edu|gov|dev|app"
)
_CUE_NAMES = r"cười|thở dài|hắng giọng|chuckle|sigh|clear throat"
_LEADING_JUNK_RE = re.compile(
    r"^(?:\[(?:" + _CUE_NAMES + r")\]\s*)*", re.IGNORECASE
)


def _strip_markup(text: str) -> str:
    """Bỏ markdown, HTML, URL, LaTeX; đổi ngắt dòng thành ngắt câu. Không đụng tới số."""
    t = re.sub(r"(\d)\s*\*\s*(\d)", r"\1 × \2", text)  # phép nhân, trước khi xóa "*" của markdown
    t = re.sub(r"```[\s\S]*?```", "\n", t)  # khối mã
    t = re.sub(r"</?[A-Za-z][^>\n]*>", " ", t)  # thẻ HTML
    t = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", t)  # ảnh markdown

    def _link(m):
        label = m.group(1).strip()
        if label.startswith(("http://", "https://", "www.")) or re.search(r"\.(?:com|vn|net|org)\b", label):
            return "xem chi tiết"
        return label

    t = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", _link, t)

    def _url(m):
        url = m.group(0)
        tail = ""
        while url and url[-1] in ".,!?;:":
            tail = url[-1] + tail
            url = url[:-1]
        seen = m.string[max(0, m.start() - 5):m.start()].lower()
        return ("chi tiết" if seen.endswith("xem ") else "xem chi tiết") + tail  # tránh "xem xem chi tiết"

    t = re.sub(r"(?:https?://|www\.)[^\s<>\"')\]]+", _url, t)
    t = re.sub(  # email đọc từng phần, không bỏ
        r"([\w.+-]+)@([\w-]+(?:\.[\w-]+)+)",
        lambda m: f"{m.group(1)} còng {m.group(2).replace('.', ' chấm ')}",
        t,
    )
    # Ký hiệu LaTeX / mũi tên → lời (tránh TTS đọc "backslash rightarrow")
    for old, new in (("→", " sang "), ("⇒", " thì "), ("↔", " hoặc "), ("←", " từ "),
                     (r"$\rightarrow$", " sang "), (r"$\to$", " sang "), (r"\rightarrow", " sang "),
                     (r"\to", " sang "), (r"$\Rightarrow$", " thì "), (r"\Rightarrow", " thì "),
                     (r"$\dots$", " "), (r"\dots", " ")):
        t = t.replace(old, new)
    t = t.replace("`", "").replace("**", "").replace("*", "")
    lines = []
    for line in t.splitlines():
        line = re.sub(r"^\s*(?:#{1,6}\s*|>\s*|[-*+•]\s+|\d+[.)]\s+)", "", line).strip()
        if not line or re.fullmatch(r"[\s|:\-_=]*", line):  # dòng trống, kẻ bảng, đường kẻ ngang
            continue
        line = line.replace("|", ", ").strip(" ,")
        lines.append(line)
    # Ngắt dòng = ngắt câu (mục danh sách, tiêu đề), trừ dòng cuối để không chèn dấu chấm giả.
    out = []
    for i, line in enumerate(lines):
        if i < len(lines) - 1 and line[-1] not in ".!?…:;,":
            line += "."
        out.append(line)
    t = " ".join(out)
    # Cụm cấm (tiếng Anh sáo rỗng) — giữ hành vi cũ
    banned = ["my apologies", "i apologize", "absolutely", "great question", "i'd be happy to",
              "of course", "how can i help", "is there anything else", "i should clarify",
              "let me know if", "feel free to"]
    low = t.lower()
    for phrase in banned:
        idx = low.find(phrase)
        while idx != -1:
            end = idx + len(phrase)
            if end < len(t) and t[end] in " ,—-":
                end += 1
            t = t[:idx] + t[end:]
            low = t.lower()
            idx = low.find(phrase)
    return t


def _date_prefix(m) -> str:
    return "" if m.string[max(0, m.start() - 5):m.start()].lower().endswith("ngày ") else "ngày "


def _normalize_reading(text: str) -> str:
    """Viết số, đơn vị, ngày giờ, tiền, phép tính thành chữ tiếng Việt để TTS đọc đúng."""
    t = text.replace("²", "2").replace("³", "3")
    t = re.sub(r"(?<=[A-Za-z])\^([23])(?!\d)", r"\1", t)  # m^2 -> m2

    # --- Tiền tệ (giữ chữ số, chỉ đưa từ chỉ tiền ra sau số) ---
    t = re.sub(
        r"\$\s*(\d+(?:[.,]\d+)*)(?:\s*(tỷ|triệu|nghìn|ngàn))?(?:\s*(?:đô\s*la|đô|usd)\b)?",
        lambda m: f"{m.group(1)}{' ' + m.group(2) if m.group(2) else ''} đô la",
        t, flags=re.IGNORECASE,
    )
    t = re.sub(r"\bUSD\s*(\d+(?:[.,]\d+)*)", r"\1 đô la Mỹ", t)
    t = re.sub(r"\bUSD\b", "đô la Mỹ", t)
    t = re.sub(r"€\s*(\d+(?:[.,]\d+)*)|(\d+(?:[.,]\d+)*)\s*(?:€|EUR\b)",
               lambda m: f"{m.group(1) or m.group(2)} ơ rô", t)
    t = re.sub(r"\b(\d+(?:[.,]\d+)*)\s*(?:VNĐ|VND|₫|đồng|đ)(?!\w)", r"\1 đồng", t, flags=re.IGNORECASE)

    # --- Giờ ---
    t = re.sub(r"(?<![\d.,:])((?:[01]?\d|2[0-3]):[0-5]\d)\s*[-–]\s*((?:[01]?\d|2[0-3]):[0-5]\d)\b", r"\1 đến \2", t)
    t = re.sub(
        r"(?<![\d.,:])([01]?\d|2[0-3]):([0-5]\d):([0-5]\d)\b",
        lambda m: f"{int(m.group(1))} giờ {int(m.group(2))} phút {int(m.group(3))} giây", t,
    )
    t = re.sub(
        r"(?<![\d.,:])([01]?\d|2[0-3])\s*(?::|h)\s*([0-5]\d)\b",
        lambda m: f"{int(m.group(1))} giờ" + (f" {int(m.group(2))} phút" if int(m.group(2)) else ""), t,
        flags=re.IGNORECASE,
    )
    t = re.sub(r"(?<![\d.,:])([01]?\d|2[0-3])\s+giờ\s+([0-5]?\d)(?!\d)(?:\s*phút)?", r"\1 giờ \2 phút", t)
    t = re.sub(r"(?<![\d.,:])([01]?\d|2[0-3])h\b", r"\1 giờ", t)

    # --- Ngày tháng ---
    t = re.sub(  # 2026-09-21
        r"(?<![\d])((?:19|20)\d{2})-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])(?!\d)",
        lambda m: f"{_date_prefix(m)}{int(m.group(3))} tháng {int(m.group(2))} năm {m.group(1)}", t,
    )
    t = re.sub(  # 21/09/2026, 21.09.2026
        r"(?<![\d/.\-])(0?[1-9]|[12]\d|3[01])\s*[/.\-]\s*(0?[1-9]|1[0-2])\s*[/.\-]\s*((?:19|20)\d{2})(?!\d)",
        lambda m: f"{_date_prefix(m)}{int(m.group(1))} tháng {int(m.group(2))} năm {m.group(3)}", t,
    )
    t = re.sub(  # 09/2026
        r"(?<![\d/])(0?[1-9]|1[0-2])/((?:19|20)\d{2})(?!\d)",
        lambda m: f"{'' if m.string[max(0, m.start() - 6):m.start()].lower().endswith('tháng ') else 'tháng '}"
                  f"{int(m.group(1))} năm {m.group(2)}", t,
    )

    def _day_month(m):  # 21/09: ngày nếu có "ngày" đứng trước hoặc ngày > 12, ngược lại là phân số
        day, month = int(m.group(1)), int(m.group(2))
        has_ngay = m.string[max(0, m.start() - 5):m.start()].lower().endswith("ngày ")
        if (day, month) == (24, 7) and not has_ngay:
            return "24 trên 7"  # 24/7: cả ngày cả tuần, không phải ngày 24 tháng 7
        if day > 12 or m.string[max(0, m.start() - 5):m.start()].lower().endswith("ngày "):
            return f"{_date_prefix(m)}{day} tháng {month}"
        return f"{day} phần {month}"

    t = re.sub(r"(?<![\d/])(0?[1-9]|[12]\d|3[01])/(0?[1-9]|1[0-2])(?![\d/])", _day_month, t)
    t = re.sub(r"(?<=\d)\s+/\s+(?=\d)", " chia ", t)  # 10 / 2
    t = re.sub(r"(?<![\d/])(\d+)\s*/\s*(\d+)(?![\d/])", r"\1 phần \2", t)  # phân số 3/4
    t = re.sub(r"(?<=\d):(?=\d)", " trên ", t)  # tỷ lệ 16:9 (giờ đã đổi ở trên)

    # --- Số điện thoại: đọc từng chữ số, nhóm 4-3-3 ---
    def _phone(m):
        digits = re.sub(r"\D", "", m.group(0))
        prefix = ""
        if m.group(0).startswith("+84"):
            prefix, digits = "cộng tám bốn, ", "0" + digits[2:]
        groups = [digits[:4]] + [digits[i:i + 3] for i in range(4, len(digits), 3)]
        return prefix + ", ".join(_digits_to_words(g) for g in groups if g)

    t = re.sub(r"(?<![\d.,])(?:\+84|0)(?:[\s.\-]?\d){8,10}(?![\d])", _phone, t)

    # --- Phiên bản 3.7.1 (khác 1.234.567 là số có phân nhóm nghìn) ---
    t = re.sub(r"\b([vV])(?=\d+(?:\.\d+)+\b)", "vê ", t)

    def _version(m):
        s = m.group(0)
        if re.fullmatch(r"\d{1,3}(?:\.\d{3})+", s):
            return s
        return " chấm ".join(s.split("."))

    t = re.sub(r"(?<![\d.])\d+(?:\.\d+){2,}(?![\d])", _version, t)

    # --- Nhiệt độ, phần trăm, đơn vị ---
    t = re.sub(r"°\s*([CFK])?", lambda m: " độ" + {"C": " xê", "F": " ép", "K": " ca"}.get(m.group(1), "") + " ", t)
    t = re.sub(r"\s*%", " phần trăm ", t)
    t = _UNIT_RE.sub(lambda m: " " + _UNIT_WORDS[m.group(1).lower()] + " ", t)
    t = _UNIT_LETTER_RE.sub(lambda m: " " + _UNIT_LETTER[m.group(1)] + " ", t)
    t = re.sub(r"\.(" + _FILE_EXT + r")\b", r" chấm \1", t, flags=re.IGNORECASE)  # tên tệp, tên miền
    t = re.sub(r"\b([A-Za-z])\+\+", r"\1 cộng cộng", t)
    t = re.sub(r"\b([CF])#", r"\1 thăng", t)
    t = re.sub(r"~\s*(?=\d)", "khoảng ", t)

    # --- Phép tính, khoảng, số âm ---
    t = t.replace("->", " sang ").replace("=>", " thì ")
    for old, new in (("≥", " lớn hơn hoặc bằng "), (">=", " lớn hơn hoặc bằng "),
                     ("≤", " nhỏ hơn hoặc bằng "), ("<=", " nhỏ hơn hoặc bằng "),
                     ("≠", " khác "), ("!=", " khác "), ("==", " bằng "),
                     ("≈", " xấp xỉ "), ("±", " cộng trừ "), ("√", " căn "), ("π", " pi "),
                     ("÷", " chia "), ("×", " nhân ")):
        t = t.replace(old, new)
    t = re.sub(r"(?<=\d)\s*x\s*(?=\d)", " nhân ", t)
    t = re.sub(r"(?<=\d)\s*\^\s*(?=\d)|(?<=\w)\^(?=\w)", " mũ ", t)
    t = re.sub(r"(?<=[\w)])\s+\+\s+(?=[\w(])|(?<=\d)\+(?=\d)", " cộng ", t)
    t = re.sub(r"(?<![\w)])\+(?=\d)", "", t)  # +26 -> 26
    t = re.sub(r"(\d)\s*[-–−]\s*(?=\d[\d.,\s+\-*/]*=)", r"\1 trừ ", t)  # 8 - 3 = 5
    t = re.sub(r"(\d)\s*[-–−]\s*(?=\d)", r"\1 đến ", t)  # 10-20
    t = re.sub(r"(?<![\w)\]])[-−](?=\d)", "âm ", t)  # -3
    t = re.sub(r"\s*=\s*", " bằng ", t)
    t = re.sub(r"(?<=[\w)])\s*>\s*(?=[\w(])", " lớn hơn ", t)
    t = re.sub(r"(?<=[\w)])\s*<\s*(?=[\w(])", " nhỏ hơn ", t)
    t = re.sub(r"(?<=\w)\s*&\s*(?=\w)", " và ", t)
    t = re.sub(r"#(?=\d)", "số ", t)

    # "/" : trên (đồng/lượng, kWh/ngày) hoặc khoảng trắng (đường dẫn, và/hoặc)
    t = re.sub(  # đồng/m3, đồng/kWh, đồng/kg: đơn vị sau "/" không có chữ số đứng trước nên phải đổi ở đây
        r"\b(" + _PER_LEFT + r")\s*/\s*(" + _UNIT_ALT + r")(?!\w)",
        lambda m: f"{m.group(1)} trên {_UNIT_WORDS[m.group(2).lower()]} ",
        t, flags=re.IGNORECASE,
    )
    t = re.sub(r"\b(" + _PER_LEFT + r")\s*/\s*(?=\w)", r"\1 trên ", t)
    t = re.sub(r"\s*/\s*", " ", t)

    # --- Số còn lại thành chữ (cả khi dính chữ cái: A4, 3D, H2O) ---
    t = re.sub(r"(?<![\d.,])\d+(?:[.,]\d+)*(?!\d)", lambda m: f" {_number_to_words(m.group(0))} ", t)
    return t


def prepare_tts_text(text: str, engine: str = "edge") -> str:
    """Văn bản chuẩn cho TTS. engine: "vieneu" (giữ cue [cười]...) hoặc "edge" (bỏ cue)."""
    if not text:
        return ""
    from engine.prompts.honorific import personalize
    text = personalize(text)
    text = re.sub(r"<action_run>.*?(?:</action_run>|$)", " ", text, flags=re.S)
    cues = []

    def _stash(m):
        cues.append(m.group(0).lower())
        return chr(0xE100 + len(cues) - 1)  # 1 ký tự PUA: các bước dưới không đụng tới

    t = EMOTION_CUE_RE.sub(_stash if engine == "vieneu" else " ", text)
    t = strip_emoji_for_tts(t)
    t = re.sub(r"\bjarvis\b", "Gia vích", t, flags=re.IGNORECASE)  # cách đọc tên riêng
    t = _strip_markup(t)
    t = _normalize_reading(t)

    # --- Dọn ký tự và dấu câu còn sót ---
    t = t.replace("…", ".")
    t = re.sub(r"[\"“”„«»]", "", t)  # dấu nháy kép không đọc; nháy đơn trong từ (don't) giữ
    t = re.sub(r"(?<!\w)'|'(?!\w)", "", t)
    t = re.sub(r"\s+[—–-]\s+", ", ", t)
    t = re.sub(r"[#*`~_\[\](){}<>\\|^@+=&/–—−-]", " ", t)
    t = re.sub(r"[:;]", ",", t)
    t = re.sub(r"([.!?,])(?:\s*[.!?,])+", r"\1", t)
    t = re.sub(r"\s+([.,!?])", r"\1", t)
    # Từ viết HOA ≥5 chữ (RESOURCES) là từ thường, không phải viết tắt: hạ xuống để không bị đánh vần.
    t = re.sub(r"\b[A-Z]{5,}\b", lambda m: m.group(0) if m.group(0) == "HTTPS" else m.group(0).lower(), t)
    t = re.sub(r"\s+", " ", t).strip()
    for i, cue in enumerate(cues):
        t = t.replace(chr(0xE100 + i), cue)
    lead = _LEADING_JUNK_RE.match(t).group(0).strip()
    body = re.sub(r"^[\W_]+", "", t[len(_LEADING_JUNK_RE.match(t).group(0)):])
    t = f"{lead} {body}".strip()
    if not re.search(r"\w", t):
        return ""
    return t[:2000]
