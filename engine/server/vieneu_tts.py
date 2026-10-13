import asyncio
import io
import logging
import os
import struct
import threading
import time
import wave
from array import array
from pathlib import Path
from typing import AsyncGenerator, Optional

import numpy as np

log = logging.getLogger("jarvis.vieneu_tts")

# Giọng preset mặc định của VieNeu-TTS v3 Turbo; ghi đè bằng VIENEU_VOICE_ID.
DEFAULT_VOICE = "Minh Quân"

# Mẫu giọng clone: thả file 3–8 giây (wav/mp3/flac...) vào đây, tên file = tên giọng.
CLONE_DIR = Path(__file__).resolve().parents[2] / "model" / "voices"
CLONE_EXTS = {".wav", ".mp3", ".flac", ".ogg", ".m4a"}


def float_audio_to_wav_bytes(audio, sample_rate: int = 48_000) -> bytes:
    pcm = array(
        "h",
        (
            int(max(-1.0, min(1.0, float(sample))) * 32767)
            for sample in audio
        ),
    )
    output = io.BytesIO()
    with wave.open(output, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm.tobytes())
    return output.getvalue()


def _pcm16_bytes(audio) -> bytes:
    return (np.clip(np.asarray(audio, dtype=np.float32), -1.0, 1.0) * 32767).astype("<i2").tobytes()


_engine = None
_engine_lock = threading.Lock()
_inference_lock = threading.Lock()
_clones: set = set()
_base_pauses: Optional[dict] = None


def _apply_pause_scale() -> None:
    """Nhân khoảng nghỉ của SDK (para 0.7s / câu 0.5s / phẩy 0.3s) cho đọc chậm rãi hơn."""
    global _base_pauses
    from vieneu_utils import core_utils

    table = core_utils.V3_GAP_SILENCE
    if _base_pauses is None:
        _base_pauses = dict(table)
    scale = float(os.getenv("VIENEU_PAUSE_SCALE", "1.6"))
    for kind, base in _base_pauses.items():
        table[kind] = round(base * scale, 3)


def _register_clones(engine) -> None:
    if not CLONE_DIR.is_dir():
        return
    for path in sorted(CLONE_DIR.iterdir()):
        if path.suffix.lower() in CLONE_EXTS and path.stem not in _clones:
            try:
                engine.add_voice(path.stem, path)
                _clones.add(path.stem)
            except Exception as exc:
                log.warning("Cannot enroll clone voice %s: %s", path.name, exc)


def _get_engine():
    global _engine
    with _engine_lock:
        if _engine is None:
            try:
                from vieneu import Vieneu
            except ImportError as exc:
                raise RuntimeError(
                    "VieNeu SDK is not installed; install requirements.txt first"
                ) from exc
            # Tự tải model từ HuggingFace lần đầu; CUDA thì tự dùng engine GPU.
            # Mặc định SDK là 16 luồng đồng thời; codec phải đệm đủ 16 khe nên chậm hơn.
            # Các câu ở đây chạy tuần tự (khóa inference) nên 2 luồng là đủ: đo trên máy
            # này RTF ~0.37 thay vì ~0.50, khoảng cách giữa các đoạn 130ms thay vì 240ms.
            _engine = Vieneu(max_streams=max(1, int(os.getenv("VIENEU_MAX_STREAMS", "2"))))
            _apply_pause_scale()
            _register_clones(_engine)
        return _engine


_warm = False


def is_ready() -> bool:
    return _warm


def warm_up() -> None:
    """Nạp model rồi sinh thử một câu ngắn để CUDA graph/xung GPU sẵn sàng trước câu đầu tiên.

    Trước đây engine chỉ nạp khi có request đầu tiên nên câu chào mở đầu phải chờ cả
    phút (import torch + nạp trọng số), các câu sau mới nhanh.
    """
    global _warm
    started = time.monotonic()
    engine = _get_engine()
    if _inference_lock.acquire(timeout=120):
        try:
            for _ in engine.infer_stream(text="Xin chào.", voice=DEFAULT_VOICE):
                pass
        finally:
            _inference_lock.release()
    _warm = True
    log.info("[vieneu] warm-up done in %.1fs", time.monotonic() - started)


def default_voice_name() -> str:
    """Tên giọng mặc định theo SDK đang cài (vd. 3.8 đổi "Minh Quân" thành "Minh Quân Pro")."""
    return _get_engine().resolve_voice_name(DEFAULT_VOICE) or DEFAULT_VOICE


def list_voices() -> list:
    engine = _get_engine()
    voices = [
        {"name": name, "label": label, "kind": "preset"}
        for label, name in engine.list_preset_voices()
        if name not in _clones
    ]
    voices += [{"name": n, "label": f"{n} (clone)", "kind": "clone"} for n in sorted(_clones)]
    return voices


def reload_clones() -> list:
    """Đăng ký file mẫu mới thả vào CLONE_DIR mà không cần khởi động lại."""
    engine = _get_engine()
    if not _inference_lock.acquire(timeout=45):
        raise RuntimeError("VieNeu engine busy")
    try:
        _register_clones(engine)
    finally:
        _inference_lock.release()
    return list_voices()


def _synthesize_sync(text: str, voice_id: Optional[str]) -> bytes:
    text = (text or "").strip()  # đã được tts_manager chuẩn bị
    if not text:
        raise RuntimeError("VieNeu got empty text after cleanup")
    voice = voice_id or DEFAULT_VOICE
    log.info("[vieneu] batch synth text=%r voice=%s", text, voice)
    started = time.monotonic()
    engine = _get_engine()
    acquired = _inference_lock.acquire(timeout=45)
    if not acquired:
        raise RuntimeError("VieNeu inference lock timed out; engine busy")
    try:
        audio = engine.infer(text=text, voice=voice)
    finally:
        _inference_lock.release()
    if audio is None or len(audio) == 0:
        raise RuntimeError("VieNeu generated empty audio")
    dur = len(audio) / engine.sample_rate
    elapsed = (time.monotonic() - started) * 1000
    log.info("[vieneu] batch done audio=%.2fs total=%.0fms", dur, elapsed)
    return float_audio_to_wav_bytes(audio, sample_rate=engine.sample_rate)


def _wav_stream_header(sample_rate: int) -> bytes:
    # WAV mono 16-bit với độ dài chưa biết (0xFFFFFFFF): client nối header + các
    # chunk PCM lại vẫn ra một file WAV hợp lệ, decoder đọc tới hết dữ liệu.
    return (
        b"RIFF" + struct.pack("<I", 0xFFFFFFFF) + b"WAVEfmt "
        + struct.pack("<IHHIIHH", 16, 1, 1, sample_rate, sample_rate * 2, 2, 16)
        + b"data" + struct.pack("<I", 0xFFFFFFFF)
    )


async def stream_vieneu_wav(
    text: str, voice_id: Optional[str] = None
) -> AsyncGenerator[bytes, None]:
    """Yield header WAV rồi từng chunk PCM16 ngay khi engine.infer_stream sinh ra."""
    text = (text or "").strip()  # đã được tts_manager chuẩn bị
    if not text:
        raise RuntimeError("VieNeu got empty text after cleanup")
    voice = voice_id or os.getenv("VIENEU_VOICE_ID", "").strip() or DEFAULT_VOICE
    log.info("[vieneu] synth text=%r voice=%s", text, voice)
    engine = await asyncio.to_thread(_get_engine)
    loop = asyncio.get_running_loop()
    started = time.monotonic()
    stats = {"chunks": 0, "samples": 0, "first": None, "last": started, "max_gap": 0.0, "underruns": 0}
    queue: asyncio.Queue = asyncio.Queue()
    stop = threading.Event()

    def produce():
        try:
            if not _inference_lock.acquire(timeout=45):
                raise RuntimeError("VieNeu inference lock timed out; engine busy")
            try:
                for chunk in engine.infer_stream(text=text, voice=voice):
                    if stop.is_set():
                        break
                    if len(chunk):
                        loop.call_soon_threadsafe(queue.put_nowait, _pcm16_bytes(chunk))
            finally:
                _inference_lock.release()
        except Exception as exc:
            loop.call_soon_threadsafe(queue.put_nowait, exc)
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, None)

    producer = asyncio.create_task(asyncio.to_thread(produce))
    sent_header = False
    try:
        while True:
            item = await queue.get()
            if item is None:
                break
            if isinstance(item, Exception):
                raise item
            now = time.monotonic()
            if stats["first"] is None:
                stats["first"] = now - started
            else:
                stats["max_gap"] = max(stats["max_gap"], now - stats["last"])
                # Đoạn về trễ hơn lượng audio đã gửi → phía phát sẽ bị hụt (giật).
                if now - stats["first"] - started > stats["samples"] / engine.sample_rate:
                    stats["underruns"] += 1
            stats["last"] = now
            stats["chunks"] += 1
            stats["samples"] += len(item) // 2
            if not sent_header:
                yield _wav_stream_header(engine.sample_rate)
                sent_header = True
            yield item
        if not sent_header:
            raise RuntimeError("VieNeu generated empty audio")
    finally:
        stop.set()  # client ngắt kết nối → dừng sinh, nhả lock
        await producer
        log.info(
            "[vieneu] done chunks=%d audio=%.2fs first=%.0fms total=%.0fms max_gap=%.0fms underruns=%d",
            stats["chunks"], stats["samples"] / engine.sample_rate,
            (stats["first"] or 0) * 1000, (time.monotonic() - started) * 1000,
            stats["max_gap"] * 1000, stats["underruns"],
        )


async def synthesize_vieneu_wav(
    text: str, voice_id: Optional[str] = None
) -> bytes:
    selected_voice = voice_id or os.getenv("VIENEU_VOICE_ID", "").strip() or None
    return await asyncio.to_thread(_synthesize_sync, text, selected_voice)
