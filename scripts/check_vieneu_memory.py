#!/usr/bin/env python3
"""
scripts/check_vieneu_memory.py — Bộ công cụ chẩn đoán RAM và kiểm tra model HuggingFace của VieNeu-TTS.

Sử dụng:
    rtk python scripts/check_vieneu_memory.py
"""

import os
import sys
import gc
import glob
import time
from pathlib import Path

# Đảm bảo root thư mục có trong sys.path
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import logging
logging.getLogger("transformers.configuration_utils").setLevel(logging.ERROR)

try:
    import psutil
except ImportError:
    print("Vui lòng cài psutil: pip install psutil")
    sys.exit(1)


def get_process_ram_mb() -> float:
    return psutil.Process().memory_info().rss / (1024 * 1024)


def inspect_packages():
    print("\n" + "=" * 60)
    print(" 1. KIỂM TRA CÁC GÓI THƯ VIỆN ĐÃ CÀI ĐẶT")
    print("=" * 60)

    import importlib.metadata as md

    pkgs = [
        "vieneu",
        "torch",
        "transformers",
        "huggingface_hub",
        "onnxruntime",
        "kaldi-native-fbank",
        "soundfile",
        "edge-tts",
        "psutil",
    ]

    for pkg in pkgs:
        try:
            ver = md.version(pkg)
            print(f"  - {pkg:<22}: v{ver}")
        except md.PackageNotFoundError:
            print(f"  - {pkg:<22}: [CHƯA CÀI]")

    try:
        import torch
        cuda_ok = torch.cuda.is_available()
        print(f"  - torch CUDA available  : {cuda_ok}")
        if cuda_ok:
            print(f"  - GPU Device            : {torch.cuda.get_device_name(0)}")
            print(f"  - VRAM Device Count     : {torch.cuda.device_count()}")
    except Exception as e:
        print(f"  - torch check error     : {e}")


def inspect_hf_cache():
    print("\n" + "=" * 60)
    print(" 2. KIỂM TRA MÔ HÌNH TẢI TỪ HUGGINGFACE")
    print("=" * 60)

    hf_home = os.environ.get("HF_HOME", os.path.expanduser("~/.cache/huggingface"))
    hub_path = Path(hf_home) / "hub"
    print(f"  - HF Hub Path: {hub_path}")

    if not hub_path.exists():
        print("  [!] Thư mục cache HF không tồn tại.")
        return

    model_dirs = sorted(hub_path.glob("models--*"))
    if not model_dirs:
        print("  [!] Không có model nào trong cache HF.")
        return

    total_cache_size = 0
    for mdir in model_dirs:
        size_bytes = sum(f.stat().st_size for f in mdir.rglob("*") if f.is_file())
        size_mb = size_bytes / (1024 * 1024)
        total_cache_size += size_bytes
        print(f"\n  📁 {mdir.name} ({size_mb:.1f} MB)")

        # Liệt kê các tệp trọng số chính
        for f in sorted(mdir.rglob("*")):
            if f.is_file() and f.suffix in {".safetensors", ".onnx", ".bin", ".data", ".npz", ".json"}:
                f_mb = f.stat().st_size / (1024 * 1024)
                if f_mb >= 0.5:
                    rel = f.relative_to(mdir)
                    print(f"     └── {str(rel):<45} {f_mb:>8.2f} MB")

    print(f"\n  -> Tổng dung lượng model cache: {total_cache_size / (1024*1024):.1f} MB")


def profile_memory():
    print("\n" + "=" * 60)
    print(" 3. BENCHMARK TIÊU THỤ RAM & VRAM THEO TỪNG GIAI ĐOẠN")
    print("=" * 60)

    ram_base = get_process_ram_mb()
    print(f"  [Giai đoạn 0] Python Khởi điểm       : {ram_base:>8.1f} MB RAM")

    t0 = time.time()
    import torch
    ram_torch = get_process_ram_mb()
    print(f"  [Giai đoạn 1] Import torch + CUDA DLL: {ram_torch:>8.1f} MB RAM (+{ram_torch - ram_base:.1f} MB in {time.time()-t0:.2f}s)")

    t0 = time.time()
    from vieneu import Vieneu
    ram_import_vn = get_process_ram_mb()
    print(f"  [Giai đoạn 2] Import vieneu          : {ram_import_vn:>8.1f} MB RAM (+{ram_import_vn - ram_torch:.1f} MB)")

    max_streams = int(os.getenv("VIENEU_MAX_STREAMS", "2"))
    print(f"\n  Khởi tạo Vieneu(max_streams={max_streams})...")
    t0 = time.time()
    engine = Vieneu(max_streams=max_streams)
    ram_loaded = get_process_ram_mb()
    vram_alloc = torch.cuda.memory_allocated() / (1024*1024) if torch.cuda.is_available() else 0
    vram_res = torch.cuda.memory_reserved() / (1024*1024) if torch.cuda.is_available() else 0
    print(f"  [Giai đoạn 3] Sau khi nạp model      : {ram_loaded:>8.1f} MB RAM (+{ram_loaded - ram_import_vn:.1f} MB in {time.time()-t0:.2f}s)")
    if torch.cuda.is_available():
        print(f"                VRAM Allocated         : {vram_alloc:>8.1f} MB")
        print(f"                VRAM Reserved          : {vram_res:>8.1f} MB")

    print("\n  Chạy câu test 1 (warm_up infer_stream kích hoạt CUDA graph)...")
    t0 = time.time()
    for _ in engine.infer_stream(text="Xin chào, tôi là trợ lý ảo Jarvis.", voice="Minh Quân"):
        pass
    ram_infer1 = get_process_ram_mb()
    vram_alloc1 = torch.cuda.memory_allocated() / (1024*1024) if torch.cuda.is_available() else 0
    vram_res1 = torch.cuda.memory_reserved() / (1024*1024) if torch.cuda.is_available() else 0
    print(f"  [Giai đoạn 4] Sau câu đầu tiên       : {ram_infer1:>8.1f} MB RAM (+{ram_infer1 - ram_loaded:.1f} MB in {time.time()-t0:.2f}s)")
    if torch.cuda.is_available():
        print(f"                VRAM Allocated         : {vram_alloc1:>8.1f} MB")
        print(f"                VRAM Reserved          : {vram_res1:>8.1f} MB")

    print("\n  Chạy thêm 5 câu tiếp theo để kiểm tra rò rỉ RAM (leak test)...")
    t0 = time.time()
    for i in range(1, 6):
        for _ in engine.infer_stream(text=f"Kiểm tra đoạn văn bản số {i}.", voice="Minh Quân"):
            pass
    ram_infer5 = get_process_ram_mb()
    print(f"  [Giai đoạn 5] Sau 5 câu tiếp theo    : {ram_infer5:>8.1f} MB RAM (Độ lệch: {ram_infer5 - ram_infer1:+.1f} MB in {time.time()-t0:.2f}s)")

    print("\n" + "-" * 60)
    print(" KẾT LUẬN VỀ TIÊU THỤ BỘ NHỚ:")
    print(f"  • Tổng RAM tiêu thụ thực tế (RSS)   : {ram_infer5:.1f} MB (~{ram_infer5/1024:.2f} GB)")
    if torch.cuda.is_available():
        print(f"  • Tổng VRAM GPU sử dụng (Reserved)  : {vram_res1:.1f} MB (~{vram_res1/1024:.2f} GB)")
    print(f"  • Rò rỉ RAM qua các lần suy luận     : {'KHÔNG' if abs(ram_infer5 - ram_infer1) < 50 else 'CÓ'}")
    print("-" * 60)


def main():
    print("=" * 60)
    print("  JARVIS VIENEU-TTS DIAGNOSTIC & BENCHMARK TOOL")
    print("=" * 60)
    inspect_packages()
    inspect_hf_cache()
    profile_memory()


if __name__ == "__main__":
    main()
