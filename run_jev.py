#!/usr/bin/env python3
"""
run_jev.py — Standalone Jev-Style Fast-Path Router Server (Port 8083)

Chạy độc lập để giữ mô hình Jev-Style-0.8B luôn thường trực (ấm) trong RAM/VRAM.
Khi chạy riêng bằng lệnh này, server.py chính sẽ tự động kết nối và tái sử dụng qua REST API,
không phải khởi động lại hay nạp lại mô hình mỗi lần bật/tắt hoặc reload server.py.

Cách dùng:
    python run_jev.py             # Mặc định chạy CPU (VRAM 0MB, trễ ~0.9s); JEV_USE_CPU=0 để chạy GPU (~505MB VRAM, ~40ms)
    python run_jev.py --cpu       # Ép chạy CPU kể cả khi JEV_USE_CPU=0
    python run_jev.py --port 8083 # Chỉ định port tùy chọn
"""

import argparse
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

from engine.core.process_tree import free_port


def main():
    parser = argparse.ArgumentParser(description="Standalone Jev Router Server")
    parser.add_argument("--port", type=int, default=int(os.getenv("JEV_PORT", "8083")), help="Cổng chạy server (mặc định 8083)")
    parser.add_argument("--host", type=str, default=os.getenv("JEV_HOST", "127.0.0.1"), help="Host chạy server (mặc định 127.0.0.1)")
    parser.add_argument("--cpu", action="store_true", help="Bắt buộc chạy Jev trên CPU 100% (giải phóng toàn bộ VRAM GPU)")
    args = parser.parse_args()

    port = args.port
    host = args.host
    if args.cpu:
        os.environ["JEV_USE_CPU"] = "1"

    use_cpu = os.getenv("JEV_USE_CPU", "1").strip().lower() in ("1", "true", "yes")
    device_str = "CPU 100% (Tiết kiệm VRAM)" if use_cpu else "GPU / CUDA (~505MB VRAM)"

    # Dọn dẹp tiến trình kẹt (nếu có) trên port trước khi bind
    stale_pids = free_port(port)
    if stale_pids:
        print(f"[Jev-Router] Đã giải phóng port {port} từ tiến trình cũ: {stale_pids}")

    print("=" * 66)
    print("  ⚡ JARVIS Jev-Style Fast-Path Router Standalone Server")
    print(f"  - Host / Port:     http://{host}:{port}")
    print(f"  - Health check:    http://{host}:{port}/health")
    print(f"  - Classify API:    http://{host}:{port}/classify")
    print(f"  - Device:          {device_str}")
    print("  - Mode:            Chạy độc lập (thường trực RAM/VRAM)")
    print("  - Gợi ý:           Mở server.py ở console khác để tái sử dụng ngay")
    print("=" * 66, flush=True)

    import uvicorn
    uvicorn.run(
        "engine.turn.jev.server:app",
        host=host,
        port=port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
