import logging
import os
import tempfile
import asyncio

log = logging.getLogger("jarvis.whisper_server")

_model = None
_lock = asyncio.Lock()

def get_whisper_model():
    global _model
    if _model is not None:
        return _model
        
    try:
        from faster_whisper import WhisperModel
        model_size = os.getenv("WHISPER_MODEL_SIZE", "base")
        log.info(f"Loading Whisper model '{model_size}' on CPU (int8)...")
        # CPU + int8 là cấu hình an toàn, nhẹ nhàng và tương thích cao nhất
        _model = WhisperModel(model_size, device="cpu", compute_type="int8")
        log.info("Whisper model loaded successfully")
        return _model
    except Exception as e:
        log.error(f"Failed to load Whisper model: {e}", exc_info=True)
        return None

async def transcribe_audio(audio_bytes: bytes) -> str:
    """Ghi bytes âm thanh ra file tạm và thực hiện nhận diện STT tiếng Việt."""
    model = get_whisper_model()
    if not model:
        return "ERROR: Whisper model not loaded"

    try:
        await asyncio.wait_for(_lock.acquire(), timeout=45)
    except asyncio.TimeoutError:
        log.error("Whisper transcription lock timed out after 45s")
        return "ERROR: Whisper busy, timed out waiting for lock"

    try:
        temp_path = None
        try:
            # Tạo file tạm để ghi audio bytes
            with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as temp_file:
                temp_file.write(audio_bytes)
                temp_path = temp_file.name

            # Chạy nhận diện trong thread pool để tránh block event loop
            def _transcribe():
                segments, info = model.transcribe(temp_path, beam_size=5, language="vi")
                text = "".join([segment.text for segment in segments]).strip()
                return text

            text = await asyncio.to_thread(_transcribe)

            log.info(f"Whisper STT Transcribed: '{text}'")
            return text

        except Exception as e:
            log.error(f"Whisper transcription failed: {e}", exc_info=True)
            return f"ERROR: {e}"
        finally:
            # Xóa file tạm dù nhận diện thành công hay thất bại
            if temp_path and os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except Exception as clean_ex:
                    log.warning(f"Failed to delete temp file {temp_path}: {clean_ex}")
    finally:
        _lock.release()
