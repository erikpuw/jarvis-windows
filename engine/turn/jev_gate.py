"""Fast-Path Gate sử dụng mô hình Jev-Style-0.8B-Decision-v3 (GGUF).

Phân loại nhanh (CPU ~0.9s, GPU ~40ms) giữa Chat thông thường và Yêu cầu Tool.
Nếu là Chat thông thường với độ tin cậy cao (>= 0.85), bỏ qua vòng lặp chọn tool
nặng nề của Big LLM (~3.5s) để nhảy thẳng vào vòng sinh câu trả lời.

Hỗ trợ 2 chế độ:
1. Standalone Microservice (khuyến nghị): kết nối tới http://127.0.0.1:8083 (chạy bởi run_jev.py).
   Không phụ thuộc vào server.py, khởi động tức thì, model thường trực trong RAM/VRAM.
2. In-Process Fallback: tự động nạp local nếu run_jev.py không bật.
"""
import logging
import os
import threading
import time
from pathlib import Path
from typing import Optional

import httpx

from engine.turn.jev.jev_style_decision_gguf import JevStyleDecisionGGUF

log = logging.getLogger("jarvis.turn.jev_gate")

RUN_MODEL_DIR = Path(os.environ.get("RUN_MODEL_DIR", r"E:\Run_Model"))
DEFAULT_MODEL_DIR = Path(__file__).parent / "jev"

JEV_SERVER_URL = os.getenv("JEV_SERVER_URL", "http://127.0.0.1:8083").rstrip("/")

_ENGINE = None
_LOCK = threading.Lock()
_REMOTE_AVAILABLE = None  # None = chưa check, True = online, False = offline
_REMOTE_REACHABLE = False  # run_jev.py có chạy (kể cả đang lỗi/chậm): khi đó không nạp model thứ hai
_LAST_REMOTE_CHECK = 0.0
_LAST_LOCAL_FAILURE = float("-inf")
_RETRY_SECONDS = 5.0

# ANSI Color codes đặc biệt cho log riêng của Jev
_RESET = "\033[0m"
_TAG_JEV = "\033[1;95m[⚡ JEV-ROUTER]\033[0m"
_CYAN = "\033[96m"
_GREEN = "\033[1;92m"
_YELLOW = "\033[1;93m"
_BLUE = "\033[1;94m"
_WHITE = "\033[1;97m"
_GRAY = "\033[90m"


def print_decision(source: str, text: str, answer: str, conf: float, dt_ms: float, min_confidence: float):
    """Một dòng console cho mỗi quyết định: Jev chọn gì, chắc bao nhiêu, lượt đi đường nào."""
    if answer == "chat":
        label = f"{_GREEN}CHAT{_RESET}"
        if conf >= min_confidence:
            route = f"{_GREEN}⚡ BYPASS → trả lời ngay{_RESET}"
        else:
            route = f"{_BLUE}→ router thường{_RESET} {_GRAY}(chưa đủ {min_confidence:.0%}){_RESET}"
    else:
        label = f"{_YELLOW}TOOL{_RESET}"
        route = f"{_YELLOW}→ router chọn tool{_RESET}"
    print(f"{_TAG_JEV}{_GRAY}[{source}]{_RESET} {_CYAN}'{text[:50]}'{_RESET} ➔ {label} {_WHITE}{conf:.1%}{_RESET} "
          f"{route} {_GRAY}[{dt_ms:.0f}ms]{_RESET}", flush=True)

_OPTIONS = {
    "chat": "Trò chuyện, chào hỏi, tâm sự, hỏi về bản thân trợ lý (bạn là ai, ai tạo ra bạn), hỏi đáp kiến thức bách khoa, dịch thuật, thơ ca, giải thích khái niệm",
    "tool": "Yêu cầu hành động hoặc tra cứu dữ liệu thực tế: thời tiết, ngày âm lịch, giá thị trường, tin tức, tìm thuốc, mở app, kiểm tra CPU RAM máy tính, chụp màn hình, ghi chú, bật nhạc"
}


def find_jev_binary(use_cpu: bool = False) -> Optional[Path]:
    """Tự động tìm kiếm binary jev-score theo thứ tự ưu tiên."""
    if use_cpu:
        candidates = [
            RUN_MODEL_DIR / "jev-run_cpu" / "jev-score.exe",
            RUN_MODEL_DIR / "jev_build" / "build_cpu" / "Release" / "jev-score.exe",
            RUN_MODEL_DIR / "jev-run" / "jev-score.exe",
            RUN_MODEL_DIR / "jev-run_gpu" / "jev-score.exe",
        ]
    else:
        candidates = [
            RUN_MODEL_DIR / "jev-run_gpu" / "jev-score.exe",
            RUN_MODEL_DIR / "jev_build" / "build_cuda" / "Release" / "jev-score.exe",
            RUN_MODEL_DIR / "jev-run" / "jev-score.exe",
            RUN_MODEL_DIR / "jev-run_cpu" / "jev-score.exe",
        ]
    for c in candidates:
        if c.exists():
            return c
    return None


def find_jev_gguf() -> Optional[Path]:
    """Tự động tìm file weights model GGUF."""
    candidates = [
        RUN_MODEL_DIR / "model" / "Jev-Style-0.8B-Decision-v3-Q4_K_M.gguf",
        RUN_MODEL_DIR / "models" / "Jev-Style-0.8B-Decision-v3-Q4_K_M.gguf",
        DEFAULT_MODEL_DIR / "models" / "Jev-Style-0.8B-Decision-v3-Q4_K_M.gguf",
        DEFAULT_MODEL_DIR / "Jev-Style-0.8B-Decision-v3-Q4_K_M.gguf",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def _check_remote_server() -> bool:
    """Kiểm tra xem standalone Jev server có đang online hay không (kết quả giữ 5 giây)."""
    global _REMOTE_AVAILABLE, _REMOTE_REACHABLE, _LAST_REMOTE_CHECK
    now = time.monotonic()
    if _REMOTE_AVAILABLE is not None and (now - _LAST_REMOTE_CHECK < _RETRY_SECONDS):
        return _REMOTE_AVAILABLE

    _LAST_REMOTE_CHECK = now
    _REMOTE_AVAILABLE = False
    try:
        with httpx.Client(timeout=0.3) as client:
            resp = client.get(f"{JEV_SERVER_URL}/health")
        _REMOTE_REACHABLE = True
        _REMOTE_AVAILABLE = resp.status_code == 200 and resp.json().get("status") == "ok"
    except httpx.ConnectTimeout:
        _REMOTE_REACHABLE = False  # Windows: cổng không ai nghe thường hết giờ thay vì bị từ chối
    except httpx.TimeoutException:
        _REMOTE_REACHABLE = True  # đã kết nối nhưng trả lời chậm: service bận/đang nạp model
    except httpx.TransportError:
        _REMOTE_REACHABLE = False  # run_jev.py không chạy: dùng model trong tiến trình
    except ValueError:
        _REMOTE_REACHABLE = True  # trả về không phải JSON
    return _REMOTE_AVAILABLE


def is_available() -> bool:
    """Kiểm tra xem có Jev standalone server HOẶC có file binary + model local."""
    if _check_remote_server():
        return True
    return not _REMOTE_REACHABLE and bool(find_jev_binary() and find_jev_gguf() and DEFAULT_MODEL_DIR.exists())


def _get_engine():
    """Engine trong tiến trình; jev-score chết thì nạp lại (thử lại sau 5 giây nếu nạp lỗi)."""
    global _ENGINE, _LAST_LOCAL_FAILURE
    engine = _ENGINE
    if engine is not None and engine.is_alive():
        return engine
    with _LOCK:
        if _ENGINE is not None and _ENGINE.is_alive():
            return _ENGINE
        if _ENGINE is not None:
            log.warning("[JEV_GATE] jev-score đã dừng, nạp lại")
            try:
                _ENGINE.close()
            except Exception as exc:
                log.debug("[JEV_GATE] Đóng engine cũ lỗi: %s", exc)
            _ENGINE = None
        if time.monotonic() - _LAST_LOCAL_FAILURE < _RETRY_SECONDS:
            return None
        use_cpu = os.getenv("JEV_USE_CPU", "1").strip().lower() in ("1", "true", "yes")
        binary = find_jev_binary(use_cpu=use_cpu)
        gguf = find_jev_gguf()
        if not (binary and gguf and DEFAULT_MODEL_DIR.exists()):
            return None
        try:
            n_gpu_layers = 0 if use_cpu else 999
            device_str = "CPU" if use_cpu else "GPU"

            log.info("[JEV_GATE] Khởi động local Jev engine trên %s (binary=%s): %s", device_str, binary.name, gguf.name)
            _ENGINE = JevStyleDecisionGGUF(
                model_dir=str(DEFAULT_MODEL_DIR),
                gguf=str(gguf),
                binary=str(binary),
                n_gpu_layers=n_gpu_layers,
            )
            print(f"{_TAG_JEV} {_GREEN}Khởi tạo thành công model {gguf.name} trên {device_str} (in-process fallback){_RESET}", flush=True)
            return _ENGINE
        except Exception as exc:
            _LAST_LOCAL_FAILURE = time.monotonic()
            log.warning("[JEV_GATE] Không khởi động được local Jev engine: %s", exc)
            return None


def _classify_via_remote(clean: str, min_confidence: float) -> tuple[bool, float] | None:
    """Gửi yêu cầu phân loại tới standalone server (run_jev.py)."""
    global _REMOTE_AVAILABLE
    try:
        t0 = time.perf_counter()
        with httpx.Client(timeout=httpx.Timeout(connect=0.3, read=2.0, write=0.5, pool=2.0)) as client:
            resp = client.post(
                f"{JEV_SERVER_URL}/classify",
                json={"text": clean, "min_confidence": min_confidence},
            )
            if resp.status_code == 200:
                data = resp.json()
                dt_ms = (time.perf_counter() - t0) * 1000
                is_chat = bool(data.get("is_chat"))
                conf = float(data.get("confidence", 0.0))
                answer = data.get("answer", "")

                print_decision("remote", clean, answer, conf, dt_ms, min_confidence)
                log.info("[JEV_GATE] Remote '%s' -> %s (conf=%.1f%%, dt=%.1fms, bypass=%s)",
                         clean[:50], answer, conf * 100, dt_ms, is_chat)
                return is_chat, conf
    except Exception as exc:
        log.debug("[JEV_GATE] Remote server không phản hồi (%s), dùng router thường", exc)
    _REMOTE_AVAILABLE = False  # kiểm tra lại health sau 5 giây
    return None


def classify_chat(text: str, min_confidence: float = 0.85) -> tuple[bool, float]:
    """Phân loại xem câu hỏi có phải là chat thông thường hay không.

    Ưu tiên 1: Gọi Standalone Server http://127.0.0.1:8083 (nếu run_jev.py đang chạy).
    Ưu tiên 2: Fallback in-process engine chỉ khi run_jev.py không chạy; service có mặt nhưng lỗi
    thì lượt này đi router thường (không nạp model thứ hai tranh CPU/RAM).

    Returns:
        (is_chat, confidence): True nếu là Chat và độ tin cậy >= min_confidence.
    """
    clean = (text or "").strip()
    if not clean:
        return False, 0.0

    # 1. Thử gọi Standalone Server trước
    if _check_remote_server():
        return _classify_via_remote(clean, min_confidence) or (False, 0.0)
    if _REMOTE_REACHABLE:
        return False, 0.0

    # 2. Fallback sang local in-process engine
    engine = _get_engine()
    if engine is None:
        return False, 0.0

    try:
        t0 = time.perf_counter()
        res = engine.decide(
            state=f"Người dùng: {clean}",
            question="Xác định đây là trò chuyện hay yêu cầu dùng công cụ:",
            options=_OPTIONS,
        )
        dt_ms = (time.perf_counter() - t0) * 1000
        answer = res.get("answer", "")
        conf = float(res.get("top_probability", 0.0))
        is_chat = (answer == "chat" and conf >= min_confidence)

        print_decision("local", clean, answer, conf, dt_ms, min_confidence)
        log.info("[JEV_GATE] Local '%s' -> %s (conf=%.1f%%, dt=%.1fms, bypass=%s)",
                 clean[:50], answer, conf * 100, dt_ms, is_chat)
        return is_chat, conf
    except Exception as exc:
        log.warning("[JEV_GATE] Lỗi khi phân loại local: %s", exc)
        return False, 0.0


def close():
    """Dọn dẹp tiến trình khi tắt server."""
    global _ENGINE, _REMOTE_AVAILABLE, _REMOTE_REACHABLE, _LAST_REMOTE_CHECK, _LAST_LOCAL_FAILURE
    with _LOCK:
        if _ENGINE is not None:
            try:
                _ENGINE.close()
            except Exception:
                pass
            _ENGINE = None
    _REMOTE_AVAILABLE, _REMOTE_REACHABLE, _LAST_REMOTE_CHECK = None, False, 0.0
    _LAST_LOCAL_FAILURE = float("-inf")
