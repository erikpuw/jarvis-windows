"""
JARVIS Execution Trace Logger — Lưu vết chi tiết thực thi của các tool/action dưới dạng JSON.
"""

import json
import logging
import time
from pathlib import Path
from typing import Dict, Any

log = logging.getLogger("jarvis.trace_logger")

PROJECT_ROOT = Path(__file__).parent.parent.parent
TRACE_DIR = PROJECT_ROOT / "data" / "traces"
TRACE_DIR.mkdir(parents=True, exist_ok=True)

_trace_count = 0
_TRACE_CLEANUP_INTERVAL = 20

class TraceLogger:
    @staticmethod
    def log_trace(action_name: str, args: Dict[str, Any], outcome: str, 
                  output: Any = None, duration: float = 0.0, error_message: str = "") -> Path:
        """Ghi vết một phiên thực thi tool/command thành tệp JSON."""
        timestamp = int(time.time() * 1000)
        trace_data = {
            "timestamp": timestamp,
            "action_name": action_name,
            "args": args,
            "outcome": outcome,
            "output": str(output) if output is not None else None,
            "duration_ms": int(duration * 1000),
            "error_message": error_message
        }
        
        trace_file = TRACE_DIR / f"trace_{timestamp}_{action_name}.json"
        try:
            trace_file.write_text(json.dumps(trace_data, indent=2, ensure_ascii=False), encoding="utf-8")
            log.debug(f"Execution trace saved to {trace_file}")

            # Tự động dọn dẹp các vết quá cũ nếu vượt quá 100 vết. Trước đây
            # spawn 1 thread OS mới cho mỗi lần gọi log_trace — chỉ chạy kiểm
            # tra dọn dẹp mỗi _TRACE_CLEANUP_INTERVAL lần gọi để tránh tạo
            # thread liên tục cho một thao tác đếm/xoá file rẻ tiền.
            global _trace_count
            _trace_count += 1
            if _trace_count % _TRACE_CLEANUP_INTERVAL == 0:
                import threading
                threading.Thread(target=TraceLogger._cleanup_old_traces, daemon=True).start()

            return trace_file
        except Exception as e:
            log.error(f"Failed to save execution trace: {e}")
            return trace_file

    @staticmethod
    def _cleanup_old_traces(max_files: int = 100):
        try:
            files = sorted(TRACE_DIR.glob("trace_*.json"), key=lambda f: f.stat().st_mtime)
            if len(files) > max_files:
                for f in files[:-max_files]:
                    f.unlink()
                    log.debug(f"Deleted old execution trace: {f.name}")
        except Exception as e:
            log.warning(f"Error during trace cleanup: {e}")

    @staticmethod
    def get_recent_traces(limit: int = 10) -> list[dict]:
        """Lấy danh sách vết thực thi gần đây để phục vụ tự học hỏi."""
        traces = []
        try:
            files = sorted(TRACE_DIR.glob("trace_*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
            for f in files[:limit]:
                try:
                    traces.append(json.loads(f.read_text(encoding="utf-8")))
                except Exception:
                    pass
        except Exception as e:
            log.warning(f"Error reading recent traces: {e}")
        return traces
