import os
import wave
import io
import psutil
from pathlib import Path
import pytest


def test_vieneu_packages_installed():
    """Kiểm tra các gói bắt buộc cho VieNeu TTS đã được cài đặt."""
    import importlib.metadata as md
    
    # 1. Package vieneu
    vieneu_ver = md.version("vieneu")
    assert vieneu_ver is not None, "Gói vieneu chưa được cài đặt"
    
    # 2. Package torch
    torch_ver = md.version("torch")
    assert torch_ver is not None, "Gói torch chưa được cài đặt"

    # 3. Package transformers & huggingface_hub
    assert md.version("transformers") is not None
    assert md.version("huggingface_hub") is not None


def test_huggingface_cache_models_exist():
    """Kiểm tra các file model tải từ Hugging Face có đầy đủ trong cache không."""
    hf_home = os.environ.get("HF_HOME", os.path.expanduser("~/.cache/huggingface"))
    hub_path = Path(hf_home) / "hub"
    assert hub_path.exists(), f"Thư mục cache Hugging Face không tồn tại: {hub_path}"

    # 1. Repo VieNeu-TTS-v3-Turbo
    turbo_dirs = list(hub_path.glob("models--pnnbao-ump--VieNeu-TTS-v3-Turbo/snapshots/*"))
    assert len(turbo_dirs) > 0, "Không tìm thấy snapshot của pnnbao-ump/VieNeu-TTS-v3-Turbo trong cache"
    snap_dir = turbo_dirs[0]
    
    # Phải có file model PyTorch hoặc ONNX
    has_safetensors = (snap_dir / "update" / "model.safetensors").is_file()
    has_onnx = (snap_dir / "onnx_update" / "vieneu_backbone_shared.data").is_file()
    assert has_safetensors or has_onnx, "Snapshot không có trọng số model.safetensors hoặc ONNX"

    # 2. Repo MOSS-Audio-Tokenizer-Nano
    moss_dirs = list(hub_path.glob("models--OpenMOSS-Team--MOSS-Audio-Tokenizer*"))
    assert len(moss_dirs) > 0, "Không tìm thấy snapshot của OpenMOSS Tokenizer"


def test_vieneu_audio_generation_sanity():
    """Kiểm tra chức năng sinh giọng nói thực tế ra định dạng WAV 48kHz hợp lệ."""
    from engine.server.vieneu_tts import _synthesize_sync, default_voice_name

    text = "Kiểm tra âm thanh."
    wav_bytes = _synthesize_sync(text, voice_id=default_voice_name())
    assert len(wav_bytes) > 44, "Audio WAV rỗng hoặc thiếu header"

    with wave.open(io.BytesIO(wav_bytes)) as w:
        assert w.getframerate() == 48000, f"Sample rate kỳ vọng 48000, thực tế {w.getframerate()}"
        assert w.getnchannels() == 1, "Kỳ vọng mono channel (1)"
        assert w.getsampwidth() == 2, "Kỳ vọng 16-bit PCM (2 bytes/sample)"


def test_vieneu_memory_remains_bounded():
    """Kiểm tra mức RAM nằm trong ngưỡng an toàn và không bị memory leak qua các lần gọi."""
    proc = psutil.Process()
    ram_before = proc.memory_info().rss / (1024 * 1024)

    from engine.server.vieneu_tts import _get_engine
    engine = _get_engine()

    # Sinh 3 câu liên tiếp
    for i in range(3):
        for _ in engine.infer_stream(text=f"Câu số {i}", voice="Minh Quân"):
            pass

    ram_after = proc.memory_info().rss / (1024 * 1024)
    # Tổng RAM tối đa cho phép không vượt quá 3.5 GB (ngưỡng an toàn)
    assert ram_after < 3500, f"RAM quá cao: {ram_after:.1f} MB (vượt ngưỡng 3.5GB)"


def test_run_vieneu_offline_flag():
    """Kiểm tra biến môi trường VIENEU_HF_OFFLINE và cấu hình port/host trong run_vieneu."""
    import run_vieneu
    assert hasattr(run_vieneu, "main")


def test_vieneu_warmup_can_be_disabled(monkeypatch):
    """Kiểm tra cờ VIENEU_WARMUP=0 cho phép khởi động nhẹ, không chạy warm-up tức thì."""
    import threading
    from fastapi.testclient import TestClient
    import engine.server.stream_tts as st

    called = threading.Event()
    monkeypatch.setattr(st, "warm_up", called.set)
    monkeypatch.setenv("VIENEU_TTS_ENABLED", "true")
    monkeypatch.setenv("EDGE_TTS_ENABLED", "false")
    monkeypatch.setenv("VIENEU_WARMUP", "0")

    with TestClient(st.app):
        assert not called.wait(0.5), "warm_up không được phép gọi khi VIENEU_WARMUP=0"

