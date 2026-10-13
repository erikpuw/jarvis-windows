"""
JARVIS Security Guardrails — Chốt chặn bảo mật cho đầu vào và đầu ra của LLM.
"""

import logging
import re
import unicodedata
from typing import Tuple

log = logging.getLogger("jarvis.guardrails")

# NOTE (giới hạn đã biết): các danh sách bên dưới là keyword/regex đơn giản,
# KHÔNG phải bộ phân loại ngữ nghĩa — dễ bị vượt qua bằng cách diễn đạt khác,
# viết bằng ngôn ngữ khác, hoặc chia nhỏ câu lệnh qua nhiều lượt. Đây chỉ là
# một lớp phòng thủ bề mặt (defense-in-depth), không phải chốt chặn chính.
# Một bộ phát hiện injection ngữ nghĩa thật sự (vd. LLM-based classifier) cần
# thiết kế riêng, không phải một patch nhỏ ở đây.

_ZERO_WIDTH_RE = re.compile("[\u200b‌‍⁠﻿]")


def _normalize_for_matching(text: str) -> str:
    """Chuẩn hoá Unicode (NFKC) và loại ký tự rộng-0 trước khi so khớp regex.

    Chặn kiểu né tránh rẻ tiền và phổ biến: chèn ký tự zero-width (U+200B...)
    vào giữa một từ khoá cấm để phá vỡ regex, hoặc dùng ký tự full-width
    tương đương (NFKC gộp về dạng chuẩn). Không giải quyết được homoglyph
    khác bảng chữ cái (vd. ký tự Cyrillic trông giống Latin) — vượt ngoài
    phạm vi một bộ lọc từ khoá.
    """
    normalized = unicodedata.normalize("NFKC", text)
    return _ZERO_WIDTH_RE.sub("", normalized)

# Danh sách đen từ khóa nguy hiểm ở đầu vào (Input Blacklist)
INPUT_DANGER_KEYWORDS = [
    r"\brm\s+-rf\b",
    r"\bformat\s+[c-zC-Z]:",
    r"\bdel\s+/s\b",
    r"\bshred\s+",
    r"\bmkfs\b",
    r"\bdd\s+if=",
    r"\bremove-item\b.*-recurse",
]

# Mẫu injection phải nhắm vào CHỈ THỊ của trợ lý (danh từ chỉ thị + "trước/ở trên/hệ thống/của bạn"),
# không phải mọi câu có "bỏ qua"/"quên" và "yêu cầu"/"hệ thống" — mẫu `.*` cũ chặn cả
# "bỏ qua cái đó, tôi có yêu cầu khác" (2026-09-26).
_VI_DIRECTIVE = r"(?:chỉ\s+thị|chỉ\s+dẫn|hướng\s+dẫn|quy\s+tắc|luật\s+lệ|prompt|lời\s+nhắc)"
_VI_TARGET = r"(?:trước|ở\s+trên|phía\s+trên|hệ\s+thống|ban\s+đầu|của\s+(?:bạn|mày|ngươi|jarvis))"

# Các mẫu câu tấn công Prompt Injection (Jailbreak) phổ biến
PROMPT_INJECTION_PATTERNS = [
    r"\bignore\s+(?:all\s+|any\s+)?(?:the\s+|your\s+)?(?:previous|prior|above|earlier)\s+(?:instructions|prompts?|rules)",
    r"\bdisregard\s+(?:all\s+)?(?:the\s+|your\s+)?(?:previous\s+|prior\s+|above\s+)?(?:instructions|prompts?|rules)",
    r"\bforget\s+(?:all\s+|everything\s+)?(?:the\s+|your\s+)?(?:previous\s+|system\s+)(?:instructions|prompts?|rules)",
    r"you\s+are\s+now\s+a\s+different\s+ai",
    rf"(?:bỏ\s+qua|phớt\s+lờ|lờ\s+đi|quên)\s+(?:\S+\s+){{0,3}}?{_VI_DIRECTIVE}(?:\s+\S+){{0,2}}?\s+{_VI_TARGET}\b",
]

# Ứng dụng cấm mở/đóng qua open_app/close_app để bảo vệ OS: shell và trình chạy script.
# So theo tên đã chuẩn hoá (bỏ ".exe", dấu nháy) VÀ theo lệnh mà desktop_automation sẽ thật sự chạy
# (_KNOWN_APPS: "command prompt"/"registry"/"power shell" → cmd/regedit/powershell).
BANNED_APPLICATIONS = [
    "cmd", "command prompt",
    "powershell", "power shell", "powershell_ise", "powershell ise", "pwsh",
    "terminal", "wt",
    "regedit", "registry",
    "bash", "wsl", "sh",
    "mshta", "rundll32", "wscript", "cscript", "regsvr32",
]

# Ký tự không bao giờ có trong tên ứng dụng nhưng mở được lệnh trong cmd/PowerShell
# ($( ) là subexpression của PowerShell trong chuỗi nháy kép; % ^ là của cmd), cùng
# dấu nháy và đường dẫn (open_app nhận tên, không nhận đường dẫn).
_APP_NAME_FORBIDDEN = set(";&|><`$()%^\"'\\/\r\n")

def verify_input(text: str) -> Tuple[bool, str]:
    """Kiểm tra đầu vào của người dùng trước khi gửi cho LLM.
    
    Returns:
        (is_safe, reason): Trả về True nếu an toàn, ngược lại trả về False kèm lý do chặn.
    """
    if not text:
        return True, ""

    text_lower = _normalize_for_matching(text).lower()

    # 1. Kiểm tra từ khóa lệnh phá hoại hệ thống
    for pattern in INPUT_DANGER_KEYWORDS:
        if re.search(pattern, text_lower):
            log.warning(f"Input Guardrail: Phát hiện từ khóa nguy hiểm khớp với pattern: {pattern}")
            return False, "Yêu cầu chứa câu lệnh hệ thống có mức độ nguy hiểm cao bị cấm."

    # 2. Kiểm tra Prompt Injection / Jailbreak
    for pattern in PROMPT_INJECTION_PATTERNS:
        if re.search(pattern, text_lower):
            log.warning(f"Input Guardrail: Phát hiện dấu hiệu Prompt Injection khớp với pattern: {pattern}")
            return False, "Yêu cầu thay đổi hành vi hệ thống hoặc bỏ qua chỉ thị bảo mật bị từ chối."

    return True, ""


def looks_like_injection(text: str) -> bool:
    """Chỉ bộ PROMPT_INJECTION_PATTERNS (không gồm lệnh nguy hiểm), cho nội dung KHÔNG tin cậy
    như trang web, lịch sử trò chuyện (engine/plans/untrusted.py, spec 2026-09-26 mục 7)."""
    if not text:
        return False
    t = _normalize_for_matching(text).lower()
    return any(re.search(p, t) for p in PROMPT_INJECTION_PATTERNS)


_INJECTION_REMOVED = "[đã lọc 1 dòng nghi prompt injection]"


def scrub_untrusted(text: str) -> str:
    """Nội dung từ tool/agent (web, MCP, file...) — bỏ từng DÒNG khớp PROMPT_INJECTION_PATTERNS
    (so trên _normalize_for_matching(line).lower()), thay bằng _INJECTION_REMOVED, log warning.
    Không chặn cả kết quả: một dòng xấu không được làm hỏng cả lượt."""
    if not isinstance(text, str):
        return text

    lines = text.split("\n")
    out = []
    changed = False
    for line in lines:
        line_norm = _normalize_for_matching(line).lower()
        if any(re.search(p, line_norm) for p in PROMPT_INJECTION_PATTERNS):
            log.warning("scrub_untrusted: đã lọc 1 dòng nghi prompt injection: %r", line[:200])
            out.append(_INJECTION_REMOVED)
            changed = True
        else:
            out.append(line)
    return "\n".join(out) if changed else text


def _verify_app_access(app_name: str) -> Tuple[bool, str]:
    """Kiểm duyệt tham số app_name chống CLI injection và ứng dụng cấm."""
    if not app_name or not isinstance(app_name, str):
        return False, "Thiếu tham số 'app_name' cho lệnh mở/đóng ứng dụng."

    app_name_lower = _normalize_for_matching(app_name).strip().lower()

    # Chặn Command Injection qua ký tự điều khiển CLI/PowerShell, dấu nháy và đường dẫn
    if any(char in _APP_NAME_FORBIDDEN for char in app_name_lower):
        log.warning(f"Output Guardrail: Phát hiện ký tự điều khiển CLI nguy hiểm trong app_name: {app_name}")
        return False, "Tên ứng dụng chứa các ký tự điều khiển dòng lệnh không hợp lệ."

    # Chặn gọi ứng dụng trong danh sách cấm: theo tên, theo từng từ, và theo lệnh sẽ thật sự chạy
    from engine.tools.desktop_automation import _KNOWN_APPS
    name = " ".join(w.removesuffix(".exe") for w in app_name_lower.split())
    words = set(name.split())
    launched = _KNOWN_APPS.get(name, ("",))[0].lower()
    if any(banned == name or banned in words or banned == launched or (" " in banned and banned in name)
           for banned in BANNED_APPLICATIONS):
        log.warning(f"Output Guardrail: Chặn truy cập ứng dụng nhạy cảm: {app_name}")
        return False, f"Không được phép mở hoặc can thiệp trực tiếp vào ứng dụng dòng lệnh/hệ thống '{app_name}' thông qua trợ lý ảo."

    return True, ""





def verify_output(tool_name: str, arguments: dict) -> Tuple[bool, str]:
    """Kiểm tra và xác thực đầu ra gọi tool từ LLM trước khi thực thi thực tế."""
    if not isinstance(arguments, dict):
        return False, "Tham số gọi công cụ không hợp lệ."

    # 1. Định tuyến kiểm duyệt trực tiếp
    if tool_name in ["open_app", "close_app"]:
        app_name = arguments.get("app_name", "")
        return _verify_app_access(app_name)

    return True, ""
