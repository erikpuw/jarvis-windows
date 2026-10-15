"""
engine/server/text_streamer.py — Shared text streaming utilities for smooth UI typewriter effects
========================================================================================
Supports smooth word-by-word streaming for static texts/agent results,
and direct streaming for real-time LLM chunks to prevent latency.
"""

import asyncio
import logging

log = logging.getLogger("jarvis.text_streamer")


def clean_latex_math(text: str) -> str:
    """Clean text for display — loại bỏ các ký hiệu LaTeX toán học/văn bản nhiễu từ mô hình."""
    if not text:
        return text
    import re

    # 1. Ánh xạ các ký tự mũi tên LaTeX sang Unicode tương ứng
    arrow_map = {
        r'\\rightarrow': '→',
        r'\\to': '→',
        r'\\leftarrow': '←',
        r'\\Rightarrow': '⇒',
        r'\\Leftarrow': '⇐',
        r'\\leftrightarrow': '↔',
        r'\\iff': '⇔',
    }
    for latex_arrow, unicode_arrow in arrow_map.items():
        # Khử cả dạng có dấu $ bọc ngoài, ví dụ: $\rightarrow$ hoặc \rightarrow
        text = re.sub(r'\$?' + latex_arrow + r'\$?', unicode_arrow, text)

    # 2. Khử dạng $\text{abc}$ hoặc \text{abc} -> abc
    text = re.sub(r'\$?\\text\{([^}]+)\}\$?', r'\1', text)

    # 3. Khử các ký tự $ bọc xung quanh từ đơn lẻ (ví dụ: $erikpuw$) -> erikpuw
    text = re.sub(r'\$([a-zA-Z0-9_\s\-\.]+)\$', r'\1', text)

    # 4. Khử các ký hiệu latex thông dụng khác như \dots, \quad, v.v.
    text = re.sub(r'\\(?:dots|quad|qquad|times|alpha|beta|gamma|lambda|omega)\b', '', text)
    
    # 5. Khử các dấu $ nhiễu còn sót lại quanh ký tự toán học hoặc gạch chéo ngược
    text = re.sub(r'\$([^$]+)\$', r'\1', text)

    # 6. Giải mã các chuỗi \uXXXX Unicode escape (nếu có từ LLM hoặc JSON) sang ký tự UTF-8 chuẩn
    if "\\u" in text:
        try:
            text = re.sub(r'\\u([0-9a-fA-F]{4})', lambda m: chr(int(m.group(1), 16)), text)
        except Exception:
            pass

    return text


class StreamLatexFilter:
    """
    Bộ lọc tích lũy token thời gian thực từ LLM để dọn sạch các ký tự LaTeX
    mà không bị xé vụn (vỡ cấu trúc tag LaTeX).
    """
    def __init__(self):
        self.buffer = ""
        self.in_latex = False

    def filter_chunk(self, chunk: str) -> str:
        if not chunk:
            return ""

        # Phát hiện bắt đầu khối LaTeX (bằng $ hoặc gạch chéo ngược \)
        if not self.in_latex:
            if "$" in chunk or "\\" in chunk:
                self.in_latex = True
                self.buffer = chunk
                return ""
            return chunk
        else:
            self.buffer += chunk
            
            # Kiểm tra xem khối LaTeX đã kết thúc chưa
            # - Có 2 dấu $ trong buffer (đóng cặp)
            # - Hoặc gặp khoảng trắng/xuống dòng ở cuối token hiện tại
            # - Hoặc buffer quá dài (> 60 ký tự)
            has_double_dollar = self.buffer.count("$") >= 2
            has_ends_space = chunk.endswith((" ", "\n", "\r", "\t", ".", ",", "!", "?", ":", ";"))
            
            if has_double_dollar or has_ends_space or len(self.buffer) > 60:
                cleaned = clean_latex_math(self.buffer)
                self.buffer = ""
                self.in_latex = False
                return cleaned
            return ""

    def flush(self) -> str:
        """Nếu kết thúc stream mà buffer vẫn còn dữ liệu, flush ra."""
        if self.buffer:
            cleaned = clean_latex_math(self.buffer)
            self.buffer = ""
            self.in_latex = False
            return cleaned
        return ""


class SentenceSplitter:
    """Cắt luồng token LLM thành câu để đưa cho TTS.

    Dấu "." ngay sau một chữ/số có thể là hết câu HOẶC nằm trong tên file/URL
    ("context_manager" + ".py"): token kế tiếp chưa tới nên chưa biết. Ở đây hoãn
    quyết định tới token sau — nếu nó dính liền bằng chữ/số thì đó là phần mở rộng,
    không cắt (trước đây "py" bị tách thành câu riêng và đọc rất lạ).
    """

    _MAX_LEN = 150

    def __init__(self, raw: bool = False):
        # raw=True: trả nguyên đoạn (giữ khoảng trắng đầu/cuối) cho nơi cần ghép lại để hiển thị.
        self.raw = raw
        self.buffer = ""
        self.dot_pending = False

    def push(self, delta: str) -> list:
        out = []
        if self.dot_pending:
            self.dot_pending = False
            head = delta[:1]
            if not (head.isalnum() or head == "_"):
                out.extend(self._emit())
        self.buffer += delta
        stripped = self.buffer.rstrip()
        last = stripped[-1:]
        prev = stripped[-2:-1]
        trigger = False
        if last in ".!?":
            if last == "." and prev.isdigit():
                pass  # số thập phân / đánh số
            elif last == "." and (prev.isalnum() or prev == "_"):
                if len(self.buffer) == len(stripped):
                    self.dot_pending = True  # "." nằm sát cuối: chờ token sau mới biết
                else:
                    trigger = True  # đã có khoảng trắng theo sau "." → hết câu
            else:
                trigger = True
        elif last in ",;":
            if not (last == "," and prev.isdigit()) and len(stripped) >= self._MAX_LEN:
                trigger = True
        elif len(stripped) >= self._MAX_LEN and delta.endswith(" "):
            trigger = True
        if trigger:
            out.extend(self._emit())
        return out

    def flush(self) -> list:
        self.dot_pending = False
        return self._emit()

    def _emit(self) -> list:
        segment, self.buffer = self.buffer, ""
        if not segment.strip():
            return []
        return [segment if self.raw else segment.strip()]


def split_for_tts(text: str) -> list:
    """Cắt một khối văn bản dài thành câu (cùng quy tắc luồng LLM). Ngắt dòng cũng là ngắt câu
    (mục danh sách, tiêu đề); khối mã không được đọc nên bỏ luôn."""
    import re

    out = []
    for line in re.sub(r"```[\s\S]*?```", "\n", text).splitlines():
        splitter = SentenceSplitter()
        for token in re.findall(r"\S+\s*", line):
            out.extend(splitter.push(token))
        out.extend(splitter.flush())
    return out


_CUE_WITH_SPACE_RE = None


def strip_voice_cues(text: str) -> str:
    """Bỏ cue cảm xúc của VieNeu ([cười]...) khỏi chữ hiển thị/lưu trữ."""
    global _CUE_WITH_SPACE_RE
    if not text or "[" not in text:
        return text
    if _CUE_WITH_SPACE_RE is None:
        import re
        from engine.server.tts_engine import EMOTION_CUE_RE
        _CUE_WITH_SPACE_RE = re.compile(r"\s*" + EMOTION_CUE_RE.pattern, re.IGNORECASE)
    return _CUE_WITH_SPACE_RE.sub("", text)


class StreamCueFilter:
    """Ẩn cue cảm xúc khỏi luồng chữ hiển thị. Cue có thể bị token xé ("[", "cười", "]")
    nên phần bắt đầu bằng "[" chưa đóng được giữ lại chờ token sau."""

    _MAX_CUE_LEN = 16  # "[clear throat]" dài 14

    def __init__(self):
        self.pending = ""

    def filter_chunk(self, chunk: str) -> str:
        text = strip_voice_cues(self.pending + chunk)
        i = text.rfind("[")
        cut = i if i != -1 and "]" not in text[i:] and len(text) - i <= self._MAX_CUE_LEN else len(text)
        head = text[:cut]
        body = head.rstrip()
        # Giữ khoảng trắng cuối: nếu token sau là cue thì nó nuốt luôn khoảng trắng này,
        # tránh "đó ." khi cue nằm giữa chữ và dấu câu.
        self.pending = head[len(body):] + text[cut:]
        return body

    def flush(self) -> str:
        rest, self.pending = self.pending, ""
        return rest


async def stream_text_smoothly(ws, safe_ws_send_json, text: str, word_delay: float = 0.04, **kwargs):
    if not ws or not text:
        return
    # 1. Làm sạch LaTeX trên toàn bộ văn bản trước để tránh bị cắt đứt tag LaTeX
    cleaned_text = clean_latex_math(text)
    
    # 2. Tách thành các từ để stream mượt mà (word-by-word)
    words = cleaned_text.split(" ")
    for idx, word in enumerate(words):
        # Thêm khoảng trắng giữa các từ (trừ từ cuối cùng)
        chunk = word + (" " if idx < len(words) - 1 else "")
        if chunk:
            await safe_ws_send_json(ws, {"type": "text_chunk", "text": chunk})
        if word_delay > 0:
            await asyncio.sleep(word_delay)
