#!/usr/bin/env python3
"""
run_vieneu.py — Standalone VieNeu Streaming TTS Server (Port 8082)

Chạy độc lập để giữ mô hình VieNeu-TTS luôn thường trực (ấm) trong RAM/VRAM.
Khi chạy riêng bằng lệnh này, server.py chính sẽ tự động kết nối và tái sử dụng,
không phải khởi động lại hay nạp lại mô hình mỗi lần bật/tắt server.py.
"""

import os
import sys
from pathlib import Path

# Đảm bảo root thư mục có trong sys.path
ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# Nạp file .env từ thư mục gốc
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT_DIR / ".env")
except ImportError:
    pass

# Đảm bảo môi trường chạy chuyên biệt cho VieNeu-TTS
if os.getenv("VIENEU_HF_OFFLINE", "1").strip().lower() in {"1", "true", "yes", "on"}:
    os.environ["HF_HUB_OFFLINE"] = "1"

os.environ["VIENEU_TTS_ENABLED"] = "true"
os.environ["EDGE_TTS_ENABLED"] = "false"

from engine.core.process_tree import free_port


def main():
    port = int(os.getenv("STREAM_TTS_PORT", "8082"))
    host = os.getenv("STREAM_TTS_HOST", "127.0.0.1")

    # Dọn dẹp tiến trình kẹt (nếu có) trên port 8082 trước khi bind
    stale_pids = free_port(port)
    if stale_pids:
        print(f"[VieNeu-TTS] Đã giải phóng port {port} từ tiến trình mồ côi cũ: {stale_pids}")

    print("=" * 64)
    print("  🚀 JARVIS VieNeu-TTS Standalone Server")
    print(f"  - Host / Port:     http://{host}:{port}")
    print(f"  - Health check:    http://{host}:{port}/tts/health")
    print(f"  - Stream endpoint: http://{host}:{port}/tts/stream")
    print("  - Mode:            Chạy độc lập (thường trực RAM/VRAM)")
    print("  - Gợi ý:           Mở server.py ở console khác để tái sử dụng ngay")
    print("=" * 64)

    import uvicorn
    uvicorn.run(
        "engine.server.stream_tts:app",
        host=host,
        port=port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
