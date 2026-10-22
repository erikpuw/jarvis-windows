import asyncio
import os
import base64
import logging
import re
import httpx
from typing import Optional

from engine.server.tts_engine import prepare_tts_text

log = logging.getLogger("jarvis.tts_manager")

TTS_STREAM_URL = os.getenv("TTS_STREAM_URL", "http://127.0.0.1:8082").rstrip("/") + "/tts/stream"

# Attempt 1 (port 8082) and attempt 2 (in-process edge-tts) both end up opening
# a websocket to Microsoft's edge-tts backend. Retrying instantly back-to-back
# looks like a burst to that server and both attempts can fail together. A
# short breather before the fallback gives it a moment to recover.
_TTS_RETRY_BACKOFF_SECONDS = max(0.0, float(os.getenv("TTS_RETRY_BACKOFF_SECONDS", "0.6")))

_tts_client: Optional[httpx.AsyncClient] = None
_tts_client_lock = asyncio.Lock()

async def get_tts_client() -> httpx.AsyncClient:
    global _tts_client
    if _tts_client is None:
        async with _tts_client_lock:
            if _tts_client is None:
                _tts_client = httpx.AsyncClient(timeout=httpx.Timeout(60.0, read=90.0))
    return _tts_client

_on_success_callback = None

def _env_enabled(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}

def _prepare(text: str, engine: str) -> str:
    """Điểm DUY NHẤT chuẩn bị văn bản cho TTS (markdown/URL/emoji/số/đơn vị → chữ đọc được)."""
    clean = prepare_tts_text(text, "vieneu" if engine == "vieneu" else "edge")
    log.info("[tts:%s] send raw=%r clean=%r", engine, text, clean)
    return clean


def _resolve_tts_engine() -> Optional[str]:
    vieneu_enabled = _env_enabled("VIENEU_TTS_ENABLED")
    edge_enabled = _env_enabled("EDGE_TTS_ENABLED", default=True)

    if vieneu_enabled and edge_enabled:
        log.error("Invalid TTS configuration: VIENEU_TTS_ENABLED and EDGE_TTS_ENABLED cannot both be true")
        return None
    if vieneu_enabled:
        return "vieneu"
    if edge_enabled:
        return "edge"
    return None

async def synthesize_speech(text: str, ws=None, voice: Optional[str] = None) -> Optional[bytes]:
    if ws and (getattr(ws, "tts_disabled", False) or getattr(ws, "cancel_requested", False)):
        log.debug("TTS skipped — tts_disabled or cancel_requested is True")
        return None

    if not text or not text.strip():
        log.debug("TTS skipped — empty text")
        return None

    engine = _resolve_tts_engine()
    if engine is None:
        engine = os.getenv("TTS_ENGINE", "edge").lower()

    text = _prepare(text, engine)
    if len(text) < 2:
        log.debug(f"TTS skipped — nothing speakable after cleanup: {text!r}")
        return None

    from engine.server.llm_server import check_stream_tts_server
    tts_online, tts_msg, _ = check_stream_tts_server()
    if engine == "vieneu" and not tts_online:
        return None

    for attempt in (1, 2):
        try:
            if engine == "vieneu":
                client = await get_tts_client()
                audio = b""
                async with client.stream("POST", TTS_STREAM_URL, json=_vieneu_payload(text, ws=ws, voice=voice)) as r:
                    if r.status_code == 200:
                        async for chunk in r.aiter_bytes():
                            if ws and (getattr(ws, "tts_disabled", False) or getattr(ws, "cancel_requested", False)):
                                log.debug("TTS skipped during stream download — tts_disabled or cancel_requested is True")
                                return None
                            audio += chunk
                    else:
                        raise RuntimeError(f"VieNeu TTS port 8082 returned status {r.status_code}")
            else:
                edge_mode = os.getenv("TTS_ENGINE", "stream").lower()
                if not tts_online and edge_mode == "stream":
                    edge_mode = "edge"
                elif attempt == 2 and edge_mode == "stream":
                    # Same fallback stream_synthesize_speech already has. The
                    # second try used to hit port 8082 again, so a greeting that
                    # failed there once went out with no audio at all.
                    edge_mode = "edge"
                    if _TTS_RETRY_BACKOFF_SECONDS:
                        await asyncio.sleep(_TTS_RETRY_BACKOFF_SECONDS)
                    log.info(f"Edge TTS via port 8082 failed on attempt 1, falling back to local edge generator: {text[:60]!r}")
                if edge_mode == "stream":
                    client = await get_tts_client()
                    audio = b""
                    edge_voice = _resolve_user_voice(ws=ws, explicit_voice=voice, engine="edge")
                    payload = {"text": text}
                    if edge_voice: payload["voice"] = edge_voice
                    async with client.stream("POST", TTS_STREAM_URL, json=payload) as r:
                        if r.status_code == 200:
                            async for chunk in r.aiter_bytes():
                                if ws and (getattr(ws, "tts_disabled", False) or getattr(ws, "cancel_requested", False)):
                                    log.debug("TTS skipped during stream download — tts_disabled or cancel_requested is True")
                                    return None
                                audio += chunk
                        else:
                            log.warning(f"Edge TTS port 8082 returned status {r.status_code}")
                else:
                    from engine.server.tts_server import generate_voice_bytes
                    edge_voice = _resolve_user_voice(ws=ws, explicit_voice=voice, engine="edge")
                    audio = await generate_voice_bytes(text, voice=edge_voice)

            if not audio:
                log.warning(f"TTS[{engine}] returned empty audio for: {text!r}")
                if attempt == 2:
                    return None
                continue

            if _on_success_callback:
                _on_success_callback()

            log.debug(f"TTS[{engine}] success: {len(audio)} bytes")
            return audio

        except Exception as e:
            if attempt == 2:
                log.warning(f"TTS[{engine}] error: {type(e).__name__}: {e}")
                return None
            log.debug(f"TTS[{engine}] retry after {type(e).__name__}: {e}")


def _resolve_user_voice(ws=None, explicit_voice: Optional[str] = None, engine: Optional[str] = None) -> Optional[str]:
    """Xác định giọng đọc (TTS voice) theo thứ tự ưu tiên:
    1. Giọng truyền trực tiếp (explicit_voice)
    2. Giọng mới nhất trong DB theo ws.user_id (không dùng bản cũ trên kết nối)
    3. Tra cứu tts_voice_id của get_current_user_id() trong DB
    4. Mặc định từ biến môi trường: VIENEU_VOICE_ID (vieneu) hoặc TTS_LOCAL_MODEL (edge)
    Giọng lưu của engine khác bị bỏ qua; explicit_voice luôn được ưu tiên.
    """
    if explicit_voice and explicit_voice.strip():
        return explicit_voice.strip()

    uid = None
    selected = ""
    if ws is not None:
        selected = str(getattr(ws, "tts_voice_id", "") or "").strip()
        uid = getattr(ws, "user_id", None)

    if not uid and not selected:
        try:
            from engine.core.session_context import get_current_user_id
            uid = get_current_user_id()
        except Exception:
            pass

    if uid:
        try:
            from engine.core.memory import _get_db
            with _get_db() as conn:
                row = conn.execute("SELECT tts_voice_id FROM users WHERE id = ?", (uid,)).fetchone()
                if row:
                    selected = (row["tts_voice_id"] or "").strip()
        except Exception:
            pass

    if selected:
        is_edge_voice = re.fullmatch(r"[a-z]{2,3}-[A-Z]{2}-.+Neural", selected) is not None
        if engine not in {"edge", "vieneu"} or is_edge_voice == (engine == "edge"):
            return selected

    if engine == "edge":
        return os.getenv("TTS_LOCAL_MODEL", "vi-VN-NamMinhNeural").strip()
    return os.getenv("VIENEU_VOICE_ID", "").strip()


def _vieneu_payload(text: str, ws=None, voice: Optional[str] = None) -> dict:
    selected = _resolve_user_voice(ws=ws, explicit_voice=voice, engine="vieneu")
    return {"text": text, "voice": selected} if selected else {"text": text}


async def stream_synthesize_pcm(text: str, ws=None, voice: Optional[str] = None):
    """VieNeu: yield (pcm16_base64, sample_rate) ngay khi từng đoạn audio về tới.

    Tách riêng khỏi stream_synthesize_speech (edge/mp3 gom cả câu rồi mới giải mã)
    để client vieneu phát được luôn từng đoạn PCM.
    """
    if ws and (getattr(ws, "tts_disabled", False) or getattr(ws, "cancel_requested", False)):
        return
    text = _prepare(text or "", "vieneu")
    if len(text) < 2:
        return

    from engine.server.llm_server import check_stream_tts_server
    tts_online, _, _ = check_stream_tts_server()
    if not tts_online:
        return

    for attempt in (1, 2):
        sent = 0
        try:
            client = await get_tts_client()
            header = b""
            rate = 48_000
            carry = b""
            async with client.stream("POST", TTS_STREAM_URL, json=_vieneu_payload(text, ws=ws, voice=voice)) as r:
                if r.status_code != 200:
                    raise RuntimeError(f"VieNeu TTS port 8082 returned status {r.status_code}")
                async for raw in r.aiter_bytes():
                    if ws and (getattr(ws, "tts_disabled", False) or getattr(ws, "cancel_requested", False)):
                        return
                    if len(header) < 44:  # header WAV 44 byte, sample rate ở offset 24
                        need = 44 - len(header)
                        header += raw[:need]
                        raw = raw[need:]
                        if len(header) == 44:
                            rate = int.from_bytes(header[24:28], "little")
                    data = carry + raw
                    keep = len(data) % 2  # PCM16: không cắt đôi mẫu
                    carry = data[len(data) - keep:] if keep else b""
                    data = data[:len(data) - keep]
                    if data:
                        sent += 1
                        yield base64.b64encode(data).decode(), rate
            if sent:
                return
            raise RuntimeError("Received empty audio stream from VieNeu")
        except Exception as e:
            if sent:
                log.warning(f"TTS[vieneu] pcm stream failed after {sent} chunks; not retrying: {type(e).__name__}: {e}")
                return
            if attempt == 2:
                log.warning(f"TTS[vieneu] pcm stream error for {text[:60]!r}: {type(e).__name__}: {e}")
                return
            log.debug(f"TTS[vieneu] pcm stream retry after {type(e).__name__}: {e}")


async def stream_synthesize_speech(text: str, ws=None, voice: Optional[str] = None):
    if ws and (getattr(ws, "tts_disabled", False) or getattr(ws, "cancel_requested", False)):
        log.debug("TTS stream skipped — tts_disabled or cancel_requested is True")
        return

    if not text or not text.strip():
        return

    engine = _resolve_tts_engine()
    if engine is None:
        engine = os.getenv("TTS_ENGINE", "edge").lower()

    text = _prepare(text, engine)
    if len(text) < 2:
        return

    from engine.server.llm_server import check_stream_tts_server
    tts_online, _, _ = check_stream_tts_server()
    if engine == "vieneu" and not tts_online:
        return

    for attempt in (1, 2):
        try:
            chunk_count = 0
            
            if engine == "vieneu":
                client = await get_tts_client()
                async with client.stream("POST", TTS_STREAM_URL, json=_vieneu_payload(text, ws=ws, voice=voice)) as r:
                    if r.status_code != 200:
                        raise RuntimeError(f"VieNeu TTS port 8082 returned status {r.status_code}")
                    async for chunk in r.aiter_bytes():
                        if ws and (getattr(ws, "tts_disabled", False) or getattr(ws, "cancel_requested", False)):
                            log.debug("TTS stream skipped during download — tts_disabled or cancel_requested is True")
                            return
                        if chunk:
                            yield base64.b64encode(chunk).decode()
                            chunk_count += 1
            else:
                edge_mode = os.getenv("TTS_ENGINE", "stream").lower()
                if not tts_online and edge_mode == "stream":
                    edge_mode = "edge"
                elif attempt == 2 and edge_mode == "stream":
                    edge_mode = "edge"
                    if _TTS_RETRY_BACKOFF_SECONDS:
                        await asyncio.sleep(_TTS_RETRY_BACKOFF_SECONDS)
                    log.info(f"Edge stream TTS failed on attempt 1, falling back to local edge generator: {text[:60]!r}")

                if edge_mode == "stream":
                    client = await get_tts_client()
                    edge_voice = _resolve_user_voice(ws=ws, explicit_voice=voice, engine="edge")
                    payload = {"text": text}
                    if edge_voice: payload["voice"] = edge_voice
                    async with client.stream("POST", TTS_STREAM_URL, json=payload) as r:
                        if r.status_code != 200:
                            raise RuntimeError(f"Edge stream TTS port 8082 returned status {r.status_code}")
                        async for chunk in r.aiter_bytes():
                            if ws and (getattr(ws, "tts_disabled", False) or getattr(ws, "cancel_requested", False)):
                                log.debug("TTS stream skipped during download — tts_disabled or cancel_requested is True")
                                return
                            if chunk:
                                yield base64.b64encode(chunk).decode()
                                chunk_count += 1
                else:
                    from engine.server.tts_server import generate_voice_bytes_stream
                    edge_voice = _resolve_user_voice(ws=ws, explicit_voice=voice, engine="edge")
                    async for chunk in generate_voice_bytes_stream(text, voice=edge_voice):
                        if ws and (getattr(ws, "tts_disabled", False) or getattr(ws, "cancel_requested", False)):
                            log.debug("TTS stream skipped during local generator — tts_disabled or cancel_requested is True")
                            return
                        if chunk:
                            yield base64.b64encode(chunk).decode()
                            chunk_count += 1

            if chunk_count > 0:
                log.info(f"TTS[{engine}] stream success")
                return
            raise Exception("Received empty audio stream from TTS backend")
        except Exception as e:
            if chunk_count > 0:
                # Audio for this sentence is already playing. Retrying would
                # re-synthesize it from the start and the listener would hear
                # the first half of the sentence twice.
                log.warning(
                    f"TTS[{engine}] stream failed after {chunk_count} chunks; "
                    f"not retrying to avoid replaying audio: {type(e).__name__}: {e}"
                )
                return
            if attempt == 2:
                # Name the sentence: without it there was no way to tell whether
                # failures follow the text or are just the service refusing.
                log.warning(f"TTS[{engine}] stream error for {text[:60]!r}: {type(e).__name__}: {e}")
                return
            log.debug(f"TTS[{engine}] stream retry after {type(e).__name__}: {e}")
