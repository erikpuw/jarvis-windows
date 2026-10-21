"""
stream_tts.py — Streaming TTS Server (Port 8082)

Cổng phụ cung cấp true streaming TTS dùng edge-tts backend hoặc vieneu backend.
"""

import os
import sys
import time
import logging
import logging.handlers
import asyncio
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel

LOG_DIR = Path(__file__).resolve().parents[2] / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
STREAM_TTS_LOG_PATH = LOG_DIR / "stream_tts.log"


class _HealthFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return "/tts/health" not in record.getMessage()


def configure_stream_tts_logging():
    formatter = logging.Formatter("%(asctime)s [%(name)s] %(message)s")

    file_handler = logging.handlers.RotatingFileHandler(
        str(STREAM_TTS_LOG_PATH),
        encoding="utf-8",
        maxBytes=20 * 1024 * 1024,
        backupCount=3,
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.INFO)
    file_handler.addFilter(_HealthFilter())

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    stream_handler.setLevel(logging.INFO)

    target_loggers = [
        logging.getLogger("jarvis.stream_tts"),
        logging.getLogger("jarvis.vieneu_tts"),
        logging.getLogger("jarvis.tts_server"),
    ]
    for l in target_loggers:
        l.setLevel(logging.INFO)
        l.propagate = False
        if not any(
            isinstance(h, logging.handlers.RotatingFileHandler)
            and getattr(h, "baseFilename", None) == str(STREAM_TTS_LOG_PATH.resolve())
            for h in l.handlers
        ):
            l.addHandler(file_handler)
        if not any(
            isinstance(h, logging.StreamHandler)
            and not isinstance(h, logging.handlers.RotatingFileHandler)
            for h in l.handlers
        ):
            l.addHandler(stream_handler)

    access_logger = logging.getLogger("uvicorn.access")
    access_logger.disabled = False
    access_logger.setLevel(logging.INFO)
    if not any(
        isinstance(h, logging.handlers.RotatingFileHandler)
        and getattr(h, "baseFilename", None) == str(STREAM_TTS_LOG_PATH.resolve())
        for h in access_logger.handlers
    ):
        access_logger.addHandler(file_handler)


_log_cleared = False


def clear_stream_tts_log():
    """Xóa trắng stream_tts.log khi khởi động server, ghi lại tiêu đề phiên mới giống jarvis.log."""
    global _log_cleared
    if not _log_cleared:
        try:
            STREAM_TTS_LOG_PATH.write_text("", encoding="utf-8")
            _log_cleared = True
            l = logging.getLogger("jarvis.stream_tts")
            l.info("===== JARVIS Stream TTS Server Started =====")
        except Exception as e:
            logging.getLogger("jarvis.stream_tts").warning("Failed to clear stream_tts.log: %s", e)


configure_stream_tts_logging()
log = logging.getLogger("jarvis.stream_tts")
logging.getLogger("transformers.configuration_utils").setLevel(logging.ERROR)

from engine.server.tts_server import generate_voice_bytes, generate_voice_bytes_stream
from engine.server.tts_manager import _resolve_tts_engine
from engine.server.vieneu_tts import (
    default_voice_name,
    is_ready,
    list_voices,
    reload_clones,
    stream_vieneu_wav,
    synthesize_vieneu_wav,
    warm_up,
)

app = FastAPI(
    title="Jarvis Stream TTS",
    description="Streaming TTS server dùng edge-tts hoặc vieneu.",
    version="1.0.0",
)

# Trước đây server này KHÔNG có SecurityFirewallMiddleware và mở CORS "*" —
# nghĩa là bất kỳ thiết bị nào chạm được port 8082 (LAN/Tailscale) đều bỏ qua
# hoàn toàn allowlist IP mà server chính (server.py) đang áp dụng. Áp dụng
# đúng cùng 2 lớp bảo vệ ở đây để không có "cửa sau" nào.
from engine.security.policy import parse_cors_origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(parse_cors_origins(os.getenv("JARVIS_CORS_ORIGINS", ""))),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from engine.security.firewall import SecurityFirewallMiddleware
app.add_middleware(SecurityFirewallMiddleware)


class TTSRequest(BaseModel):
    text: str
    voice: Optional[str] = None


def _warm_up_safely():
    try:
        warm_up()
    except Exception as exc:
        log.warning("VieNeu warm-up failed (sẽ nạp lại ở request đầu tiên): %s", exc)


@app.on_event("startup")
async def _warm_up_vieneu():
    configure_stream_tts_logging()
    clear_stream_tts_log()
    if os.getenv("VIENEU_WARMUP", "1").strip().lower() in {"0", "false", "no", "off"}:
        log.info("[vieneu] Auto warm-up disabled via VIENEU_WARMUP=0 (lazy loading)")
        return
    # Không chặn khởi động: /tts/health vẫn trả lời ngay, request tới sớm sẽ chờ khóa nạp model.
    if _resolve_tts_engine() == "vieneu":
        app.state.warm_up_task = asyncio.create_task(asyncio.to_thread(_warm_up_safely))


@app.get("/tts/health")
async def health():
    engine = _resolve_tts_engine() or "edge"
    return JSONResponse({
        "status": "ok",
        "engine": engine,
        "voice": (
            os.getenv("VIENEU_VOICE_ID", "")
            if engine == "vieneu"
            else os.getenv("TTS_LOCAL_MODEL", "vi-VN-NamMinhNeural")
        ),
        "ready": is_ready() if engine == "vieneu" else True,
        "port": 8082,
    })


def _require_vieneu():
    if _resolve_tts_engine() != "vieneu":
        raise HTTPException(status_code=409, detail="VieNeu engine is not active")


@app.get("/tts/voices")
async def tts_voices():
    """Danh sách giọng preset + clone (chỉ cho VieNeu)."""
    _require_vieneu()
    voices = await asyncio.to_thread(list_voices)
    return {"engine": "vieneu", "default": await asyncio.to_thread(default_voice_name), "voices": voices}


@app.post("/tts/voices/reload")
async def tts_voices_reload():
    """Đăng ký mẫu clone vừa thêm vào model/voices/."""
    _require_vieneu()
    voices = await asyncio.to_thread(reload_clones)
    return {"engine": "vieneu", "default": await asyncio.to_thread(default_voice_name), "voices": voices}


async def _stream_vieneu(req: TTSRequest) -> StreamingResponse:
    """VieNeu v3: WAV stream (header + PCM16) từ infer_stream."""
    gen = stream_vieneu_wav(req.text, voice_id=req.voice)
    try:
        # Lấy chunk đầu trước khi trả response để lỗi sớm vẫn ra 503 (client retry).
        first = await gen.__anext__()
    except Exception as exc:
        log.warning("VieNeu synthesis failed: %s", exc)
        raise HTTPException(
            status_code=503,
            detail=f"VieNeu synthesis failed: {exc}",
        ) from exc

    async def _body():
        try:
            yield first
            async for chunk in gen:
                yield chunk
        finally:
            await gen.aclose()

    return StreamingResponse(
        _body(),
        media_type="audio/wav",
        headers={
            "X-TTS-Engine": "vieneu",
            # Header HTTP chỉ nhận latin-1; tên giọng tiếng Việt ("Minh Triết") phải mã hóa.
            "X-TTS-Voice": quote(req.voice or os.getenv("VIENEU_VOICE_ID", "")),
        },
    )


async def _stream_edge(req: TTSRequest) -> StreamingResponse:
    """edge-tts: MP3 stream."""
    async def _gen():
        chunks = 0
        started = time.monotonic()
        first_ms = None
        log.info("[edge-tts] synth text=%r voice=%s", req.text, req.voice)
        try:
            async for chunk in generate_voice_bytes_stream(req.text, voice=req.voice):
                if first_ms is None:
                    first_ms = (time.monotonic() - started) * 1000
                chunks += 1
                yield chunk
        finally:
            log.info(
                "[edge-tts] done chunks=%d first=%.0fms total=%.0fms",
                chunks, first_ms or 0, (time.monotonic() - started) * 1000,
            )

    return StreamingResponse(
        _gen(),
        media_type="audio/mpeg",
        headers={
            "Transfer-Encoding": "chunked",
            "X-TTS-Engine": "edge-tts",
            "X-TTS-Voice": req.voice or os.getenv("TTS_LOCAL_MODEL", "vi-VN-NamMinhNeural"),
        }
    )


@app.post("/tts/stream")
async def tts_stream(req: TTSRequest):
    if not req.text or not req.text.strip():
        raise HTTPException(status_code=400, detail="text field is required")

    engine = _resolve_tts_engine() or "edge"
    if engine == "vieneu":
        return await _stream_vieneu(req)
    return await _stream_edge(req)


@app.post("/tts/bytes")
async def tts_bytes(req: TTSRequest):
    if not req.text or not req.text.strip():
        raise HTTPException(status_code=400, detail="text field is required")

    engine = _resolve_tts_engine() or "edge"
    if engine == "vieneu":
        audio = await synthesize_vieneu_wav(req.text, voice_id=req.voice)
        media_type = "audio/wav"
    else:
        audio = await generate_voice_bytes(req.text, voice=req.voice)
        media_type = "audio/mpeg"

    if not audio:
        raise HTTPException(status_code=500, detail="TTS generation failed")

    return StreamingResponse(
        iter([audio]),
        media_type=media_type,
        headers={"Content-Length": str(len(audio))},
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8082, log_level="info")
