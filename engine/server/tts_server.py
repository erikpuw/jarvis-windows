import os
import re
import asyncio
import logging
from typing import Optional, AsyncGenerator

import edge_tts

log = logging.getLogger("jarvis.tts_server")

_DEFAULT_VOICE = "vi-VN-NamMinhNeural"

# One edge-tts websocket to Microsoft at a time per process. Firing several
# concurrently (e.g. overlapping sentences) reads as a burst to their server
# and gets connections reset; this makes later callers queue behind the one
# in flight instead of racing it.
# ponytail: process-local only, doesn't span the separate port-8082 process —
# raise to a shared cross-process lock (e.g. a lock file)
# if resets still show up with both processes hitting edge-tts at once.
_edge_tts_semaphore = asyncio.Semaphore(1)

def _get_voice() -> str:
    return os.getenv("TTS_LOCAL_MODEL") or _DEFAULT_VOICE

async def _iter_with_timeout(stream, timeout=30.0):
    """Wrap từng bước của async generator bằng timeout."""
    while True:
        try:
            chunk = await asyncio.wait_for(stream.__anext__(), timeout=timeout)
            yield chunk
        except StopAsyncIteration:
            return


async def generate_voice_bytes(text: str, voice: Optional[str] = None) -> Optional[bytes]:
    """Generate speech audio using edge-tts — gom toàn bộ (tương thích cũ)."""
    try:
        text = (text or "").strip()  # đã được tts_manager chuẩn bị
        if not text or len(text) < 2:
            return None
        # Kiểm tra xem chuỗi có chứa chữ hoặc số không, tránh gửi chuỗi chỉ có dấu câu
        if not re.search(r"[a-zA-Z0-9\u00C0-\u1EF9]", text):
            return None
            
        voice = voice or _get_voice()
        tts = edge_tts.Communicate(text, voice=voice)
        chunks = b""
        async with _edge_tts_semaphore:
            async for chunk in _iter_with_timeout(tts.stream(), timeout=30.0):
                if chunk["type"] == "audio":
                    chunks += chunk["data"]
        if not chunks:
            log.warning(f"edge-tts returned empty audio for: {text[:60]!r}")
            return None
        return chunks
    except asyncio.TimeoutError:
        log.warning("edge-tts timeout (30s)")
        return None
    except Exception as e:
        log.warning(f"edge-tts error: {type(e).__name__}: {e}")
        return None


async def generate_voice_bytes_stream(text: str, voice: Optional[str] = None) -> AsyncGenerator[bytes, None]:
    """
    True streaming: yield từng chunk audio ngay khi nhận từ edge-tts.
    Latency chunk đầu tiên ~150-300ms thay vì chờ toàn bộ.
    Dùng khi TTS_ENGINE=stream trong .env.
    """
    try:
        text = (text or "").strip()  # đã được tts_manager chuẩn bị
        if not text or len(text) < 2:
            return
        # Kiểm tra xem chuỗi có chứa chữ hoặc số không, tránh gửi chuỗi chỉ có dấu câu
        if not re.search(r"[a-zA-Z0-9\u00C0-\u1EF9]", text):
            return
            
        voice = voice or _get_voice()
        tts = edge_tts.Communicate(text, voice=voice)
        async with _edge_tts_semaphore:
            async for chunk in _iter_with_timeout(tts.stream(), timeout=30.0):
                if chunk["type"] == "audio":
                    yield chunk["data"]
    except asyncio.TimeoutError:
        log.warning("edge-tts stream timeout (30s)")
        return
    except Exception as e:
        log.warning(f"edge-tts stream error: {type(e).__name__}: {e}")
        return

