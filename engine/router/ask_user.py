"""Thẻ <ask_user>: Jarvis xin phép làm MỘT việc; "ừ" ở lượt sau chạy đúng việc đó (spec §2, §4, §6, §11).
Một chỗ duy nhất cho mọi quy tắc về thẻ."""
import re

from engine.prompts.catalog import offerable_tools

# Chịu lỗi định dạng: model nhỏ đóng bằng "<ask_user>" (thiếu "/") hoặc không đóng (spec §6).
ASK_RE = re.compile(r"<ask_user>\s*(.*?)\s*(?:</ask_user>|<ask_user>|<action_run>|$)", re.S)
ACTION_RE = re.compile(r"<action_run>\s*(.*?)\s*(?:</action_run>|<action_run>|$)", re.S)
_ACTION_BLOCK_RE = re.compile(r"<action_run>.*?(?:</action_run>|$)", re.S)
# Task 19 M5: strip stray </action_run> tag with </?ask_user>|</action_run>
_MARKER_RE = re.compile(r"</?ask_user>|</action_run>")
_MARKERS = ("<ask_user>", "</ask_user>", "<action_run>", "</action_run>")
_ACTION_OPEN, _ACTION_CLOSE = "<action_run>", "</action_run>"

_YESNO_END = re.compile(r"(không|nhé|chứ|nha|được không|ạ)\s*\?\s*$", re.I)
_TRAILING_JUNK = re.compile(r"[^\w?.!)\"'\s]+$")  # emoji/cue sau dấu "?"

_WRAP = re.compile(
    r"^(?:thưa ngài,?\s*)?(?:ngài\s+)?(?:có\s+)?(?:muốn|cần|cho phép|đồng ý (?:cho|để)|để)\s+tôi\s+"
    r"|^(?:tôi\s+)?(?:có\s+)?(?:nên|được phép|có thể)\s+|^cho\s+(?:tôi\s+)?phép\s+(?:tôi\s+)?|^để\s+tôi\s+", re.I)
_TAIL = re.compile(r"(?:\s+(?:cho ngài|giúp ngài|ngay bây giờ|ngay lúc này|bây giờ|ngay|lần nữa|luôn))*"
                   r"\s*(?:không|nhé|chứ|nha|được không)?\s*(?:ạ|thưa ngài)?\s*\?\s*$", re.I)

AFFIRM = frozenset({
    "có", "co", "ừ", "ừm", "ừ ừ", "uh", "uhm", "ok", "oke", "okay", "yes", "vâng", "dạ", "dạ có", "được", "được đó",
    "đồng ý", "làm đi", "chạy đi", "mở đi", "làm luôn", "ok làm đi", "ừ làm đi", "có làm đi", "ok luôn", "ừ đúng rồi",
    "ừ đi", "ok đi", "oke đi", "dạ vâng", "được rồi", "có đi",
    "thử lại", "thử lại đi", "thử lại coi", "thử lại xem", "làm lại", "làm lại đi", "chạy lại", "mở lại", "mở lại đi",
})
DENY = frozenset({
    "không", "ko", "khong", "no", "thôi", "thoi", "thôi khỏi", "khỏi", "không cần", "không cần đâu", "để sau",
    "khoan", "khoan đã", "thôi không", "không đâu",
})
_LEAD = {"jarvis"}
_TAIL_WORDS = {"nhé", "nha", "nhá", "ạ", "à"}

# Từ đệm/động từ chung được phép đi sau một từ đồng ý ("ừ mở đi"); có đối tượng mới thì không tính.
# Task 19 M2b: thêm "rồi" để "được rồi mở đi" → affirm
_FILLER = {"mở", "làm", "chạy", "đi", "luôn", "cho", "tôi", "giúp", "nhé", "nha", "nhá", "ngay", "với", "lên", "ạ", "đó", "rồi",
           "lại", "lần", "nữa", "thử", "giùm", "dùm", "hộ"}
_AFFIRM_HEADS = (("đồng", "ý"), ("ừ",), ("ừm",), ("uh",), ("ok",), ("oke",), ("okay",), ("có",), ("vâng",), ("dạ",), ("được",), ("yes",))


def _drop_trailing_partial_marker(text: str) -> str:
    """Cắt bỏ đuôi là marker dở dang (model bị cắt ngang giữa thẻ, vd "<ask_us")."""
    i = text.rfind("<")
    if i != -1 and any(m.startswith(text[i:]) for m in _MARKERS) and text[i:] not in _MARKERS:
        return text[:i]
    return text


_TEMPLATE_BRACKETS = re.compile(r"(<ask_user>\s*)\[([^\[\]]*)\]")  # khuôn ghi "[việc]", model chép luôn cả ngoặc


def extract(text: str) -> tuple[str, str]:
    """(văn bản bỏ marker + bỏ cả khối <action_run>, câu hỏi trong <ask_user> hoặc "")."""
    text = _TEMPLATE_BRACKETS.sub(lambda m: m.group(1) + m.group(2), text or "")
    m = ASK_RE.search(text)
    ask = " ".join(m.group(1).split()) if m else ""
    clean = _drop_trailing_partial_marker(_MARKER_RE.sub("", _ACTION_BLOCK_RE.sub("", text)))
    return clean.strip(), ask


def extract_action(text: str) -> str:
    """Tên tool trong <action_run>, chỉ khi có trong offerable_tools(); còn lại ""."""
    m = ACTION_RE.search(text or "")
    name = m.group(1).strip().strip("`'\" ") if m else ""
    return name if name in offerable_tools() else ""


_MARKER_SPLIT = re.compile(r"(</?ask_user>|</?action_run>)")


def _tool_label(name: str) -> str:
    """Công cụ model gắn cho lời đề nghị, hiện cho ngài thấy (cả tên bịa — log 2026-09-27: check_project_code)."""
    name = name.strip().strip("`'\" ")
    if not name:
        return ""
    if name in offerable_tools():
        return f"(công cụ: `{name}`)"
    return f"(công cụ: `{name}` — không tồn tại, sẽ không chạy)"


class StreamTagFilter:
    """Chữ hiển thị (không phải TTS): <ask_user>ý định</ask_user> → `ý định`, <action_run>tool</action_run> →
    "(công cụ: `tool`)" — để ngài thấy model định làm gì (user 2026-09-27). Thẻ không bao giờ lộ ra; marker có
    thể bị token xé ("<act", "ion_run>"); model nhỏ đóng sai bằng <ask_user> thứ hai hoặc không đóng."""

    def __init__(self):
        self.pending = ""
        self.in_ask = False    # đã mở dấu ` cho ý định
        self.suppress = False  # đang gom tên tool trong khối <action_run>
        self.tool = ""
        self.last = ""         # ký tự cuối đã phát ra (để chèn dấu cách trước nhãn công cụ)

    def _emit(self, out: str, piece: str) -> str:
        if piece:
            self.last = piece[-1]
        return out + piece

    def _label(self) -> str:
        label, self.tool, self.suppress = _tool_label(self.tool), "", False
        if label and self.last and not self.last.isspace():
            label = " " + label
        return label

    def _close_ask(self) -> str:
        self.in_ask = False
        return "`"

    def filter_chunk(self, chunk: str) -> str:
        text, self.pending, out = self.pending + chunk, "", ""
        i = text.rfind("<")
        if i != -1 and ">" not in text[i:] and any(m.startswith(text[i:]) for m in _MARKERS):
            text, self.pending = text[:i], text[i:]  # marker có thể còn dở: chờ chunk sau
        for part in _MARKER_SPLIT.split(text):
            if part == _ACTION_OPEN:
                if self.in_ask:
                    out = self._emit(out, self._close_ask())
                self.suppress, self.tool = True, ""
            elif part == _ACTION_CLOSE:
                if self.suppress:
                    out = self._emit(out, self._label())
            elif part in ("<ask_user>", "</ask_user>"):
                if self.suppress:
                    out = self._emit(out, self._label())
                if self.in_ask:
                    out = self._emit(out, self._close_ask())
                elif part == "<ask_user>":
                    self.in_ask = True
                    out = self._emit(out, "`")
            elif self.suppress:
                self.tool += part
            else:
                out = self._emit(out, part.replace("[", "").replace("]", "") if self.in_ask else part)
        return out

    def flush(self) -> str:
        """Hết stream: marker dở dang bị bỏ; khối <action_run> chưa đóng vẫn hiện nhãn; ý định chưa đóng thì đóng `."""
        self.pending, out = "", ""
        if self.suppress:
            out = self._emit(out, self._label())
        if self.in_ask:
            out = self._emit(out, self._close_ask())
        return out


def is_actionable(ask: str) -> bool:
    """Một câu hỏi có/không cho MỘT việc. Câu hai lựa chọn/câu hỏi mở bị loại → "ừ" đi qua gate như thường.
    ponytail: heuristic từ khoá; câu hợp lệ lạ ("Mở Notepad?") bị loại oan — hậu quả chỉ là không chạy."""
    ask = _TRAILING_JUNK.sub("", (ask or "").strip()).strip()
    a = " " + ask.lower() + " "
    if " hay " in a or " hoặc " in a:
        return False
    if "?" not in ask:  # dạng mới (user 2026-09-25): thẻ chỉ bọc phần việc bên trong câu hỏi
        return 2 <= len(ask.split()) <= 12
    return ask.count("?") == 1 and len(ask) <= 200 and bool(_YESNO_END.search(ask))


def ask_to_command(ask: str) -> str:
    """'Ngài có muốn tôi xem hộp thư không ạ?' -> 'xem hộp thư'. Classifier nhận câu lệnh (10/10) chứ không nhận câu hỏi (4/10)."""
    ask = _TRAILING_JUNK.sub("", (ask or "").strip()).strip()
    return _TAIL.sub("", _WRAP.sub("", ask)).strip(" ,.")


def reply_kind(text: str) -> str:
    """'affirm' | 'deny' | '' — không dùng LLM (spec §4, §11.4)."""
    words = re.findall(r"\w+", (text or "").casefold())
    while words and words[0] in _LEAD:
        words.pop(0)
    changed = True
    while changed:  # "thưa ngài" và từ đuôi đứng theo mọi thứ tự ("vâng thưa ngài ạ", "ok nhé thưa ngài")
        changed = False
        if words[-2:] == ["thưa", "ngài"]:
            words, changed = words[:-2], True
        while words and words[-1] in _TAIL_WORDS:
            words.pop()
            changed = True
    t = " ".join(words)
    if t in AFFIRM:
        return "affirm"
    if t in DENY:
        return "deny"
    for head in _AFFIRM_HEADS:
        n = len(head)
        if tuple(words[:n]) == head and len(words) > n:
            # Task 19 M2a: affirm-head followed by "tôi" + verb means user will do it themselves
            if n < len(words) and words[n] == "tôi":
                return ""  # user will do it themselves: "ok tôi mở"
            if all(w in _FILLER for w in words[n:]):
                return "affirm"
    return ""
