# engine/turn/say.py
"""Tách dần chuỗi "say" từ JSON đang stream để hiện chữ + đọc TTS ngay khi model viết (spec mục 3.1).
"say" là câu báo ngắn trước khi tool chạy: chỉ lấy dòng đầu (log 2026-10-20 02:19: model viết thêm cả đoạn "đã tạo skill
thành công…" trong "say" trước khi tool chạy, vòng trả lời lại báo lần nữa)."""
import json
import re

_OPEN = re.compile(r'"say"\s*:\s*"')  # "say" đứng sau "tool"
_ESC = {'"': '"', "\\": "\\", "/": "/", "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t"}


class SayReader:
    def __init__(self):
        self.buf, self.pos, self.done = "", None, False

    def feed(self, delta: str) -> str:
        self.buf += delta
        if self.done:
            return ""
        if self.pos is None:
            m = _OPEN.search(self.buf)
            if not m:
                return ""
            self.pos = m.end()
        b, i, out = self.buf, self.pos, []
        while i < len(b):
            ch = b[i]
            if ch == '"':
                self.done = True
                i += 1
                break
            if ch != "\\":
                out.append(ch)
                i += 1
                continue
            if b[i + 1:i + 2] == "n":  # xuống dòng: hết câu báo, bỏ phần còn lại
                self.done = True
                i += 2
                break
            if i + 1 >= len(b):
                break  # chờ ký tự sau dấu \
            e = b[i + 1]
            if e != "u":
                out.append(_ESC.get(e, e))
                i += 2
                continue
            if i + 6 > len(b):
                break  # chờ đủ \uXXXX
            code = int(b[i + 2:i + 6], 16)
            if 0xD800 <= code < 0xDC00:  # nửa đầu cặp surrogate (emoji): chờ nửa sau
                if i + 12 > len(b):
                    break
                low = int(b[i + 8:i + 12], 16)
                out.append(chr(0x10000 + ((code - 0xD800) << 10) + (low - 0xDC00)))
                i += 12
                continue
            out.append(chr(code))
            i += 6
        self.pos = i
        return "".join(out)


def parse_turn(raw: str) -> dict:
    """{"say","tool","args"}; JSON hỏng (bị cắt, lỗi server) → coi như trả lời bằng chữ đã nhận."""
    try:
        d = json.loads(raw)
    except ValueError:
        d = None
    if not isinstance(d, dict):
        return {"say": SayReader().feed(raw) or raw.strip(), "tool": "none", "args": {}}
    args = d.get("args")
    return {"say": str(d.get("say") or "").split("\n", 1)[0].strip(), "tool": str(d.get("tool") or "none"),
            "args": args if isinstance(args, dict) else {}}
