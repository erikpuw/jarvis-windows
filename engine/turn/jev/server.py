"""
engine/turn/jev/server.py — Standalone Jev-Style Router Microservice (Port 8083)

Cung cấp REST API (CPU ~0.9s, GPU ~40ms) cho mô hình Jev-Style-0.8B Decision GGUF:
- GET  /health   : Kiểm tra trạng thái và thiết bị (CPU/GPU)
- POST /classify : Phân loại nhanh giữa chat thường và tool request
- POST /decide   : Phân loại theo tùy chọn tùy biến
"""

import os
import time
import logging
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from engine.turn.jev.jev_style_decision_gguf import JevStyleDecisionGGUF

log = logging.getLogger("jarvis.jev_server")

# ANSI Color codes đặc biệt cho log riêng của Jev
_RESET = "\033[0m"
_TAG_JEV = "\033[1;95m[⚡ JEV-ROUTER]\033[0m"
_CYAN = "\033[96m"
_GREEN = "\033[1;92m"
_YELLOW = "\033[1;93m"
_GRAY = "\033[90m"

RUN_MODEL_DIR = Path(os.environ.get("RUN_MODEL_DIR", r"E:\Run_Model"))
DEFAULT_MODEL_DIR = Path(__file__).parent

_OPTIONS = {
    "chat": "Trò chuyện, chào hỏi, tâm sự, hỏi về bản thân trợ lý (bạn là ai, ai tạo ra bạn), hỏi đáp kiến thức bách khoa, dịch thuật, thơ ca, giải thích khái niệm",
    "tool": "Yêu cầu hành động hoặc tra cứu dữ liệu thực tế: thời tiết, ngày âm lịch, giá thị trường, tin tức, tìm thuốc, mở app, kiểm tra CPU RAM máy tính, chụp màn hình, ghi chú, bật nhạc"
}

_ENGINE: Optional[JevStyleDecisionGGUF] = None
_DEVICE = "CPU"
_MODEL_NAME = "unknown"


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


def init_engine(use_cpu: bool = True) -> JevStyleDecisionGGUF:
    global _ENGINE, _DEVICE, _MODEL_NAME
    if _ENGINE is not None:
        return _ENGINE

    binary = find_jev_binary(use_cpu=use_cpu)
    gguf = find_jev_gguf()
    if not (binary and gguf and DEFAULT_MODEL_DIR.exists()):
        raise FileNotFoundError(f"Không tìm thấy model GGUF hoặc binary (binary={binary}, gguf={gguf})")

    n_gpu_layers = 0 if use_cpu else 999
    _DEVICE = "CPU" if use_cpu else "GPU"
    _MODEL_NAME = gguf.name
    log.info("[JEV_SERVER] Khởi động binary=%s, model=%s, device=%s", binary.name, gguf.name, _DEVICE)
    _ENGINE = JevStyleDecisionGGUF(
        model_dir=str(DEFAULT_MODEL_DIR),
        gguf=str(gguf),
        binary=str(binary),
        n_gpu_layers=n_gpu_layers,
    )
    return _ENGINE


def close_engine():
    global _ENGINE
    if _ENGINE is not None:
        try:
            _ENGINE.close()
        except Exception:
            pass
        _ENGINE = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    use_cpu = os.getenv("JEV_USE_CPU", "1").strip().lower() in ("1", "true", "yes")
    try:
        init_engine(use_cpu=use_cpu)
        print(f"{_TAG_JEV} {_GREEN}Khởi tạo thành công {_MODEL_NAME} trên {_DEVICE} (thường trực RAM/VRAM){_RESET}", flush=True)
    except Exception as exc:
        log.error("[JEV_SERVER] Khởi động thất bại: %s", exc)
        print(f"{_TAG_JEV} {_YELLOW}Lỗi khởi động: {exc}{_RESET}", flush=True)
    yield
    close_engine()


app = FastAPI(title="JARVIS Jev-Style Router Service", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ClassifyRequest(BaseModel):
    text: str
    min_confidence: float = 0.85


class DecideRequest(BaseModel):
    state: str
    question: str
    options: dict[str, str]


@app.get("/health")
def health():
    return {
        "status": "ok" if _ENGINE is not None else "error",
        "device": _DEVICE,
        "model": _MODEL_NAME,
    }


@app.post("/classify")
def classify(req: ClassifyRequest):
    global _ENGINE
    if _ENGINE is None:
        raise HTTPException(status_code=503, detail="Jev engine chưa sẵn sàng")

    clean = (req.text or "").strip()
    if not clean:
        return {"is_chat": False, "confidence": 0.0, "answer": "", "dt_ms": 0.0}

    t0 = time.perf_counter()
    res = _ENGINE.decide(
        state=f"Người dùng: {clean}",
        question="Xác định đây là trò chuyện hay yêu cầu dùng công cụ:",
        options=_OPTIONS,
    )
    dt_ms = (time.perf_counter() - t0) * 1000
    answer = res.get("answer", "")
    conf = float(res.get("top_probability", 0.0))
    is_chat = (answer == "chat" and conf >= req.min_confidence)

    if is_chat:
        print(f"{_TAG_JEV} {_CYAN}'{clean[:50]}'{_RESET} ➔ {_GREEN}CHAT BYPASS ({conf:.1%}) [{dt_ms:.1f}ms]{_RESET} {_GRAY}→ Bỏ qua vòng tool, trả lời ngay{_RESET}", flush=True)
    else:
        print(f"{_TAG_JEV} {_CYAN}'{clean[:50]}'{_RESET} ➔ {_YELLOW}TOOL REQUEST ({conf:.1%}) [{dt_ms:.1f}ms]{_RESET} {_GRAY}→ Chuyển sang router chọn tool{_RESET}", flush=True)

    return {
        "is_chat": is_chat,
        "confidence": conf,
        "answer": answer,
        "dt_ms": round(dt_ms, 2),
        "scores": res.get("probabilities", {}),
    }


@app.post("/decide")
def decide(req: DecideRequest):
    global _ENGINE
    if _ENGINE is None:
        raise HTTPException(status_code=503, detail="Jev engine chưa sẵn sàng")

    t0 = time.perf_counter()
    res = _ENGINE.decide(
        state=req.state,
        question=req.question,
        options=req.options,
    )
    dt_ms = (time.perf_counter() - t0) * 1000
    return {
        "result": res,
        "dt_ms": round(dt_ms, 2),
    }
