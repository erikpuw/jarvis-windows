"""
JARVIS Server — Voice AI + Development Orchestration

Handles:
1. WebSocket voice interface (browser audio <-> LLM <-> TTS)
2.  Code task manager (spawn/manage  -p subprocesses)
3. Project awareness (scan Desktop for git repos)
4. REST API for task management
"""
import os
import sys
from pathlib import Path

# Load .env file immediately to set system configuration like HF_HUB_OFFLINE
_env_path = Path(__file__).parent / ".env"
if _env_path.exists():
    for _line in _env_path.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ[_k.strip()] = _v.strip().strip('"').strip("'")

import asyncio
import base64
import json
import logging
import logging.handlers
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

from openai import AsyncOpenAI, OpenAI
import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Reconnected core and tools modules
from engine.core.memory import (
    SemanticMemoryEngine,
)
from engine.main.greeting_engine import send_greeting
from engine.core.session_context import set_session
from engine.server.ws_sessions import ActiveSessions

LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
# RotatingFileHandler thay vì FileHandler thường — trước đây jarvis.log không
# có giới hạn kích thước, phình to vô hạn suốt vòng đời cài đặt.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(message)s",
    handlers=[
        logging.handlers.RotatingFileHandler(
            str(LOG_DIR / "jarvis.log"), encoding="utf-8-sig",
            maxBytes=20 * 1024 * 1024, backupCount=5,
        ),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("jarvis")
logging.getLogger("asyncio").setLevel(logging.CRITICAL)  # suppress benign Windows ProactorEventLoop noise

# Background task registry — keeps fire-and-forget tasks alive
_background_tasks: set[asyncio.Task] = set()
_telegram_bot = None
_telegram_bot_task: Optional[asyncio.Task] = None
_mcp_connect_task: Optional[asyncio.Task] = None
_reflection_lock = asyncio.Lock()
_uvicorn_server = None


def request_restart() -> bool:
    """Request a graceful worker restart through the existing supervisor."""
    if _uvicorn_server is None:
        log.warning("Restart requested before the Uvicorn server was initialized")
        return False
    os.environ["JARVIS_RESTART_REQUESTED"] = "1"
    _uvicorn_server.should_exit = True
    log.info("Graceful JARVIS restart requested")
    return True


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

LOCAL_API_KEY = os.getenv("LOCAL_API_KEY")
TTS_LOCAL_KEY = os.getenv("TTS_LOCAL_KEY")
TTS_LOCAL_MODEL = os.getenv("TTS_LOCAL_MODEL")
LOCAL_URL     = os.getenv("LOCAL_URL")
TTS_LOCAL_URL = os.getenv("TTS_LOCAL_URL")
LOCAL_MODEL   = os.getenv("LOCAL_MODEL")
VISION_MODEL  = os.getenv("VISION_MODEL")
USER_NAME = os.getenv("USER_NAME")
HONORIFIC = os.getenv("HONORIFIC")
# ---------------------------------------------------------------------------
# Speech-to-Text Corrections
# ---------------------------------------------------------------------------

STT_CORRECTIONS = {
    r"\bcloud code\b": " Code",
    r"\bclock code\b": " Code",
    r"\bquad code\b": " Code",
    r"\bclawed code\b": " Code",
    r"\bclod code\b": " Code",
    r"\bcloud\b": "",
    r"\bquad\b": "",
    r"\btravis\b": "JARVIS",
    r"\bjarves\b": "JARVIS",
}


def apply_speech_corrections(text: str) -> str:
    """Fix common speech-to-text errors before processing."""
    import re as _stt_re
    result = text
    for pattern, replacement in STT_CORRECTIONS.items():
        result = _stt_re.sub(pattern, replacement, result, flags=_stt_re.IGNORECASE)
    return result


# ---------------------------------------------------------------------------
# WebSocket Safe Send Helper
# ---------------------------------------------------------------------------

async def safe_ws_send_json(ws: WebSocket, data: dict) -> bool:
    """Safely send JSON to WebSocket with error handling.
    
    Returns True if successful, False if connection is broken.
    """
    if not ws:
        return False
    from engine.prompts.honorific import personalize_payload
    data = personalize_payload(data)
    dispatcher = getattr(ws, "_event_dispatcher", None)
    if dispatcher is not None:
        return await dispatcher.enqueue(data)
    try:
        await ws.send_json(data)
        return True
    except (RuntimeError, ConnectionError, ValueError) as e:
        log.debug(f"WebSocket send failed (likely disconnected): {type(e).__name__}")
        return False
    except Exception as e:
        log.warning(f"Unexpected WebSocket error: {e}")
        return False


# ---------------------------------------------------------------------------
# TTS (edge-tts — hỗ trợ chuyển đổi engine qua TTS_ENGINE env)
# ---------------------------------------------------------------------------

async def synthesize_speech(text: str, ws=None) -> Optional[bytes]:
    """Delegate to centralized tts_manager."""
    from engine.server.tts_manager import synthesize_speech as _synth
    audio = await _synth(text, ws=ws)
    if audio:
        _session_tokens["tts_calls"] += 1
        await asyncio.to_thread(_append_usage_entry, 0, 0, "tts")
    return audio


# ---------------------------------------------------------------------------
# LLM Response
# ---------------------------------------------------------------------------

async def generate_response_stream(
    text: str,
    client: AsyncOpenAI,
    ws: WebSocket,
    last_response: str = "",
    conversation_history: list[dict] | None = None,
    flow_tracker=None,
    flow_agents=None,
    attachment_context=None,
) -> str:
    """Một lượt hội thoại: router quyết định rồi xử lý (engine/router)."""
    from engine.router import TurnContext, handle_turn
    ctx = TurnContext(
        ws=ws, send_json=safe_ws_send_json, client=client,
        conversation_history=conversation_history or [],
        flow_tracker=flow_tracker, flow_agents=flow_agents,
        attachment_context=attachment_context, background_tasks=_background_tasks,
    )
    return await handle_turn(text, ctx)


# ---------------------------------------------------------------------------
# FastAPI App
# ---------------------------------------------------------------------------

# Shared state
openai_client: Optional[AsyncOpenAI] = None
embed_client: Optional[OpenAI] = None
_stream_tts_proc: Optional[asyncio.subprocess.Process] = None
_stream_tts_log = None


def _stream_tts_env() -> dict:
    """Môi trường cho tiến trình stream_tts. VIENEU_HF_OFFLINE=1 (mặc định) → chỉ nạp model từ
    cache, không gọi Hugging Face lúc khởi động; đặt 0 khi cần cập nhật model/SDK.
    Chỉ áp dụng cho stream_tts để không ảnh hưởng các thư viện HF khác của server chính."""
    env = dict(os.environ)
    if os.getenv("VIENEU_HF_OFFLINE", "1").strip().lower() in {"1", "true", "yes", "on"}:
        env["HF_HUB_OFFLINE"] = "1"
    return env


def _sync_tts_gate(ws) -> None:
    """TTS tắt khi nút TTS đang tắt HOẶC media đang phát. Tắt media chỉ mở lại TTS nếu nút đang bật;
    bật nút lúc media đang phát vẫn giữ TTS tắt cho tới khi media dừng."""
    blocked = getattr(ws, "user_tts_disabled", False) or getattr(ws, "media_active", False)
    ws.tts_disabled = blocked
    ws.cancel_requested = blocked


def _apply_tts_gate_now(ws, msg: dict) -> None:
    """Nút TTS và trình phát media có tác dụng ngay, kể cả giữa một lượt trả lời.

    Gọi từ ws_reader (task chạy song song, như "cancel"), vì vòng lặp chính đang await generate_response_stream nên không đọc message_queue
    cho tới khi lượt cũ xong: toggle_tts xếp hàng ở đó thì luồng TTS vẫn chạy tiếp hết lượt. Chỉ đặt ws.tts_disabled (voice_streamer và
    tts_manager poll cờ này) và KHÔNG đặt cancel_requested: tắt tiếng không được giết luôn phần chữ đang stream. Vòng lặp chính vẫn xử lý
    tin như cũ khi rảnh (huỷ greeting, _sync_tts_gate).
    """
    kind = msg.get("type")
    if kind == "toggle_tts":
        ws.user_tts_disabled = not msg.get("enabled", True)
    elif kind == "media_state":
        ws.media_active = bool(msg.get("active", False))
    else:
        return
    ws.tts_disabled = getattr(ws, "user_tts_disabled", False) or getattr(ws, "media_active", False)


async def _watch_vieneu_warmup(started: float, timeout: float = 240.0) -> None:
    """Theo dõi /tts/health của stream_tts và ghi vào jarvis.log khi VieNeu warm-up xong."""
    announced = False
    while time.monotonic() - started < timeout:
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                data = (await client.get("http://127.0.0.1:8082/tts/health")).json()
            if data.get("engine") != "vieneu":
                return
            if not announced:
                log.info("[vieneu] warm-up started: model đang nạp ở nền (stream_tts, port 8082)")
                announced = True
            if data.get("ready"):
                log.info("[vieneu] warm-up done: TTS sẵn sàng sau %.1fs kể từ khi khởi động stream_tts",
                         time.monotonic() - started)
                return
        except Exception:
            pass
        await asyncio.sleep(1.0)
    log.warning("[vieneu] warm-up chưa xong sau %.0fs; xem logs/stream_tts.log", timeout)


async def _free_stale_stream_tts_port(port: int) -> None:
    """Force-kill whatever is already LISTENING on `port`, if anything.

    Guards against the known orphaned-process issue: a prior crash can leave
    an old stream_tts still bound to this port, so the freshly spawned one
    fails to bind in silence while the stale instance keeps serving traffic.
    Since this port has exactly one intended owner (our own stream_tts),
    killing whatever holds it is safe.
    """
    import subprocess as _subprocess

    try:
        result = await asyncio.to_thread(
            _subprocess.run,
            ["netstat", "-ano"],
            capture_output=True, text=True, timeout=5,
        )
    except Exception as e:
        log.debug(f"Could not inspect port {port} occupancy: {e}")
        return

    stale_pids = set()
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[0].upper() == "TCP" and parts[-1].upper() == "LISTENING":
            local_addr = parts[1]
            if local_addr.endswith(f":{port}"):
                try:
                    stale_pids.add(int(parts[-2]))
                except ValueError:
                    continue

    if not stale_pids:
        return

    log.warning(
        "Port %s already held by PID(s) %s (likely an orphaned process from a previous crash) — "
        "force-killing before starting a fresh stream_tts instance",
        port, sorted(stale_pids),
    )
    from engine.core.process_tree import force_kill_pids
    force_kill_pids(stale_pids)
    await asyncio.sleep(0.5)

# Webcam synchronization globals
_latest_webcam_image: Optional[str] = None
_webcam_image_event: Optional[asyncio.Event] = None
_active_ws_session: Optional[WebSocket] = None
_ws_sessions = ActiveSessions()

# Usage tracking — logs every call with timestamp, persists to disk
_USAGE_FILE = Path(__file__).parent / "data" / "usage_log.jsonl"
_session_start = time.time()
_session_tokens = {"input": 0, "output": 0, "api_calls": 0, "tts_calls": 0}
_active_voice_connections = 0


def _append_usage_entry(input_tokens: int, output_tokens: int, call_type: str = "api", cached_tokens: int = 0):
    """Append a usage entry with timestamp to the log file."""
    try:
        _USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
        import json as _json
        entry = {
            "ts": time.time(),
            "date": datetime.now().strftime("%Y-%m-%d"),
            "type": call_type,
            "input_tokens": input_tokens,
            "cached_tokens": cached_tokens,
            "output_tokens": output_tokens,
        }
        with open(_USAGE_FILE, "a") as f:
            f.write(_json.dumps(entry) + "\n")
        _rotate_usage_log_if_needed()
    except Exception:
        pass


_USAGE_MAX_BYTES = 5 * 1024 * 1024
_USAGE_KEEP_LINES = 20000


def _rotate_usage_log_if_needed() -> None:
    """Keep the usage log bounded.

    It was append-only with no cap, and /api/usage re-reads and re-parses the
    whole file four times per request, so answering it got slower forever.
    """
    try:
        if _USAGE_FILE.stat().st_size <= _USAGE_MAX_BYTES:
            return
        lines = _USAGE_FILE.read_text(encoding="utf-8").splitlines()
        if len(lines) <= _USAGE_KEEP_LINES:
            return
        kept = lines[-_USAGE_KEEP_LINES:]
        tmp = _USAGE_FILE.with_name(_USAGE_FILE.name + ".tmp")
        tmp.write_text("\n".join(kept) + "\n", encoding="utf-8")
        os.replace(tmp, _USAGE_FILE)
        log.info("Usage log trimmed from %d to %d entries", len(lines), len(kept))
    except Exception:
        pass

def _get_usage_for_period(seconds: float | None = None) -> dict:
    """Sum usage from the log file for a time period. None = all time."""
    import json as _json
    totals = {"input_tokens": 0, "output_tokens": 0, "api_calls": 0, "tts_calls": 0}
    cutoff = (time.time() - seconds) if seconds else 0
    try:
        if _USAGE_FILE.exists():
            for line in _USAGE_FILE.read_text().strip().split("\n"):
                if not line:
                    continue
                entry = _json.loads(line)
                if entry["ts"] >= cutoff:
                    totals["input_tokens"] += entry.get("input_tokens", 0)
                    totals["output_tokens"] += entry.get("output_tokens", 0)
                    if entry.get("type") == "tts":
                        totals["tts_calls"] += 1
                    else:
                        totals["api_calls"] += 1
    except Exception:
        pass
    return totals

def _update_session_tokens_from_log():
    """Update _session_tokens from the usage log file for the current session."""
    try:
        session_totals = _get_usage_for_period(time.time() - _session_start)
        _session_tokens["input"] = session_totals["input_tokens"]
        _session_tokens["output"] = session_totals["output_tokens"]
        _session_tokens["api_calls"] = session_totals["api_calls"]
        _session_tokens["tts_calls"] = session_totals["tts_calls"]
    except Exception:
        pass


def _cost_from_tokens(input_t: int, output_t: int) -> float:
    return (input_t / 1_000_000) * 0.80 + (output_t / 1_000_000) * 4.00


@asynccontextmanager
async def lifespan(application: FastAPI):
    global _telegram_bot, _telegram_bot_task, _mcp_connect_task
    global openai_client, embed_client, _stream_tts_proc, _stream_tts_log
    
    # Load .env into os.environ for modules that use os.getenv
    try:
        _, env_dict = _read_env()
        for k, v in env_dict.items():
            if v and k not in os.environ:
                os.environ[k] = v
    except Exception as e:
        log.warning(f"Failed to load .env into environment: {e}")

    # Clear log on startup
    log_file = LOG_DIR / "jarvis.log"
    try:
        log_file.write_text("")  # Clear the log file
        log.info("===== JARVIS Server Started =====")
    except Exception as e:
        log.warning(f"Failed to clear log: {e}")
    
    if LOCAL_API_KEY:
        from engine.server.llm_server import get_llm_client
        openai_client = get_llm_client()
    else:
        log.warning("LOCAL_API_KEY not set — LLM features disabled")

    # Initialize local embedding client pointing to LOCAL_EMBED_URL
    local_embed_api = os.getenv("LOCAL_EMBED_API")
    local_embed_url = os.getenv("LOCAL_EMBED_URL")
    if local_embed_api and local_embed_url:
        try:
            embed_client = OpenAI(api_key=local_embed_api, base_url=local_embed_url)
            log.info(f"Initialized local embedding client pointing to {local_embed_url}")
        except Exception as embed_ex:
            log.warning(f"Failed to initialize embed_client: {embed_ex}")
    else:
        log.warning("LOCAL_EMBED_API or LOCAL_EMBED_URL not set — local embedding features disabled")

 
    # Initialize modules
    try:
        from engine.tools.skill_manager import get_skill_manager
        skill_mgr = get_skill_manager()
        skill_mgr.scan_skills()
        skill_mgr.scan_commands()
        log.info(f"Skills: {len(skill_mgr.skills)}, Commands: {len(skill_mgr.commands)}")

        # RAG is initialized lazily by agent_rag when an attachment needs it.
        if embed_client is not None:
            SemanticMemoryEngine.get_instance().set_embed_client(embed_client)
            # Chủ động khởi tạo semantic memory cache sau khi có embed client
            try:
                await asyncio.to_thread(SemanticMemoryEngine.get_instance().initialize_cache)
            except Exception as sem_ex:
                log.warning(f"Failed to initialize semantic cache at startup: {sem_ex}")

        # Không nạp vector định tuyến lúc khởi động vì đã dùng Fast Keyword Router
        pass
            
    except Exception as e:
        log.warning(f"Skill manager init failed: {e}")

    try:
        from engine.tools.load_plugin import PluginLoader
        PluginLoader.get_instance().load_all()
    except Exception as e:
        log.warning(f"Plugin loader init failed: {e}")

    try:
        from engine.tools.load_hook import HookLoader, HookRegistry
        HookLoader.get_instance().load_all()
        await HookRegistry.get_instance().fire_async("on_startup")
    except Exception as e:
        log.warning(f"Hook loader init failed: {e}")

    try:
        from engine.server.mcp_server import get_mcp_hub
        hub = get_mcp_hub()
        log.info(f"MCP server ready: {hub.get_stats()['total_servers']} servers loaded")
        # Kết nối MCP servers (agentmemory, browser, gitnexus...)
        _mcp_connect_task = asyncio.create_task(hub.connect_all(), name="mcp-connect-all")
    except Exception as e:
        log.warning(f"MCP server init failed: {e}")

    try:
        from engine.server.redis_server import connect_redis, worker_loop
        if await connect_redis():
            redis_worker_task = asyncio.create_task(worker_loop())
            _background_tasks.add(redis_worker_task)
            redis_worker_task.add_done_callback(_background_tasks.discard)
            log.info("Redis worker loop started")
    except Exception as e:
        log.warning(f"Redis init failed: {e}")

    # Tự động khởi chạy cổng phụ stream_tts trên port 8082
    try:
        python_exe = sys.executable or "python"
        await _free_stale_stream_tts_port(8082)
        log.info("Starting stream_tts port 8082 process...")
        # Its output went to DEVNULL, so every failure on port 8082 (the empty
        # streams behind the constant "falling back" lines) was invisible.
        # Truncated on each start so it stays bounded.
        _stream_tts_log_path = Path(__file__).parent / "logs" / "stream_tts.log"
        _stream_tts_log_path.parent.mkdir(parents=True, exist_ok=True)
        _stream_tts_log = open(_stream_tts_log_path, "wb")
        _stream_tts_started = time.monotonic()
        _stream_tts_proc = await asyncio.create_subprocess_exec(
            python_exe, "-m", "engine.server.stream_tts",
            env=_stream_tts_env(),
            stdout=_stream_tts_log,
            stderr=asyncio.subprocess.STDOUT,
        )
        log.info(f"stream_tts process started with PID {_stream_tts_proc.pid}")

        # Trước đây server chỉ log "đã khởi động" ngay sau khi spawn — nếu port
        # 8082 vẫn còn bị 1 tiến trình mồ côi cũ chiếm giữ, tiến trình mới có
        # thể bind lỗi trong im lặng trong khi bản cũ (có thể chạy code cũ) vẫn
        # âm thầm phục vụ toàn bộ traffic TTS. Xác nhận thật sự bằng health-check.
        healthy = False
        for _ in range(10):
            await asyncio.sleep(0.5)
            try:
                async with httpx.AsyncClient(timeout=1.0) as client:
                    resp = await client.get("http://127.0.0.1:8082/tts/health")
                    if resp.status_code == 200:
                        healthy = True
                        break
            except Exception:
                continue
        if healthy:
            log.info("stream_tts health check OK on port 8082")
            warm_task = asyncio.create_task(_watch_vieneu_warmup(_stream_tts_started))
            _background_tasks.add(warm_task)
            warm_task.add_done_callback(_background_tasks.discard)
        else:
            log.warning(
                "stream_tts process spawned (PID %s) but /tts/health did not respond within 5s — "
                "port 8082 may still be occupied by a stale process; TTS requests may hit a wrong/stale instance.",
                _stream_tts_proc.pid,
            )
    except Exception as tts_ex:
        log.warning(f"Failed to auto-start stream_tts on port 8082: {tts_ex}")

    # Khởi chạy Security Connection Monitor ngầm để theo dõi các IP lạ kết nối vào socket
    try:
        from engine.security.monitor import start_security_monitor
        configured_port = int(os.getenv("JARVIS_SERVER_PORT", "8340"))
        runtime_server = getattr(application.state, "uvicorn_server", None)
        security_port = int(getattr(getattr(runtime_server, "config", None), "port", configured_port))
        sec_task = start_security_monitor(lambda: _active_ws_session, server_port=security_port)
        _background_tasks.add(sec_task)
        sec_task.add_done_callback(_background_tasks.discard)
        log.info("Security Connection Monitor daemon scheduled")
    except Exception as sec_err:
        log.warning(f"Failed to start security monitor loop: {sec_err}")

    # Khởi chạy Self-Healing background watcher ngầm
    try:
        from engine.core.self_healing import start_self_healing_watcher
        start_self_healing_watcher()
        log.info("🛡️ Self-Healing background watcher scheduled (60-s interval)")
    except Exception as sh_err:
        log.warning(f"Failed to start self-healing watcher loop: {sh_err}")

    # Khởi chạy Dream Cycle background watcher — tự động tóm tắt/dọn dẹp hội thoại,
    # agent_outcomes và Obsidian Wiki cũ khi hệ thống idle vào khung giờ yên tĩnh
    try:
        from engine.core.dream import start_dream_watcher
        start_dream_watcher()
        log.info("💤 Dream Cycle background watcher scheduled")
    except Exception as dream_err:
        log.warning(f"Failed to start dream watcher loop: {dream_err}")

    log.info("JARVIS server starting")

    telegram_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if telegram_token:
        from engine.server.telegram_bot import TelegramBot, parse_allowed_chat_ids

        allowed_telegram_chat_ids = parse_allowed_chat_ids(
            os.getenv("TELEGRAM_ALLOWED_CHAT_IDS", "")
        )
        if allowed_telegram_chat_ids:
            _telegram_bot = TelegramBot(
                telegram_token, allowed_telegram_chat_ids, sys.modules[__name__]
            )
            try:
                if await _telegram_bot.send_pending_restart_notice():
                    log.info("Telegram restart completion notice sent")
            except Exception:
                log.warning("Telegram restart completion notice failed", exc_info=True)
            _telegram_bot_task = asyncio.create_task(
                _telegram_bot.run(), name="telegram-bot"
            )
            _background_tasks.add(_telegram_bot_task)
            _telegram_bot_task.add_done_callback(_background_tasks.discard)
            log.info(
                "Telegram long polling enabled for %d allowed chat(s)",
                len(allowed_telegram_chat_ids),
            )
        else:
            log.warning(
                "Telegram is disabled because TELEGRAM_ALLOWED_CHAT_IDS is empty or invalid"
            )

    # Tìm việc mỗi sáng (engine/jobs, spec 2026-09-27-job-search mục 11)
    try:
        from engine.jobs import scheduler as jobs_scheduler

        async def _jobs_notify(text: str) -> None:
            if _active_ws_session is not None:
                await safe_ws_send_json(_active_ws_session, {"type": "text_chunk", "text": text})
                await safe_ws_send_json(_active_ws_session, {"type": "stream_end"})
            if _telegram_bot is not None:
                await _telegram_bot.broadcast(text)

        jobs_task = jobs_scheduler.start(_jobs_notify)
        _background_tasks.add(jobs_task)
        jobs_task.add_done_callback(_background_tasks.discard)
        log.info("💼 Jobs scheduler started")
    except Exception as jobs_err:
        log.warning(f"Failed to start jobs scheduler: {jobs_err}")

    # RAG tự index tệp thả vào thư mục theo dõi (RAG_WATCH_FOLDER, mặc định data/documents)
    try:
        from engine.core.rag_engine import get_rag_engine
        from engine.core.rag_watcher import get_rag_watcher
        from engine.server.llm_server import get_embed_client

        _rag_embed = get_embed_client()
        if _rag_embed is not None:
            get_rag_engine().set_embed_client(_rag_embed)
            _watch_dir = Path(os.getenv("RAG_WATCH_FOLDER") or "data/documents")
            if not _watch_dir.is_absolute():
                _watch_dir = Path(__file__).parent / _watch_dir
            _rag_watcher = get_rag_watcher(str(_watch_dir))
            _rag_watcher.start(asyncio.get_running_loop())
            for _rag_coro in (_rag_watcher.process_queue(), _rag_watcher.scan_existing()):
                _rag_task = asyncio.create_task(_rag_coro)
                _background_tasks.add(_rag_task)
                _rag_task.add_done_callback(_background_tasks.discard)
            log.info(f"📚 RAG watcher started: {_watch_dir}")
        else:
            log.warning("RAG watcher not started: embedding client is not configured")
    except Exception as rag_watch_err:
        log.warning(f"Failed to start RAG watcher: {rag_watch_err}")

    yield

    async def _shutdown_sequence():
        global _telegram_bot, _telegram_bot_task, _mcp_connect_task, openai_client, _stream_tts_log

        if _telegram_bot is not None:
            await _telegram_bot.stop()
        if _telegram_bot_task is not None:
            _telegram_bot_task.cancel()
            await asyncio.wait_for(
                asyncio.gather(_telegram_bot_task, return_exceptions=True),
                timeout=5.0,
            )
        _telegram_bot = None
        _telegram_bot_task = None

        try:
            from engine.core.rag_watcher import get_rag_watcher
            _rag_watcher = get_rag_watcher()
            if _rag_watcher is not None:
                _rag_watcher.stop()
        except Exception as e:
            log.warning(f"RAG watcher shutdown failed: {e}")

        # Cancel tất cả background tasks (security monitor, voice streamer, WS reader...)
        if _background_tasks:
            for t in list(_background_tasks):
                t.cancel()
            await asyncio.wait_for(
                asyncio.gather(*_background_tasks, return_exceptions=True),
                timeout=5.0,
            )
            _background_tasks.clear()

        try:
            from engine.server.llm_server import close_llm_client
            await close_llm_client()
        except Exception as e:
            log.warning(f"LLM client shutdown failed: {e}")
        finally:
            openai_client = None

        if _stream_tts_proc is not None:
            try:
                log.info("Stopping stream_tts process...")
                _stream_tts_proc.terminate()
                await asyncio.wait_for(_stream_tts_proc.wait(), timeout=2.0)
                log.info("stream_tts process stopped successfully")
            except asyncio.TimeoutError:
                log.warning("stream_tts did not exit in 2s; force-killing it")
                try:
                    _stream_tts_proc.kill()
                    await asyncio.wait_for(_stream_tts_proc.wait(), timeout=1.0)
                except asyncio.TimeoutError:
                    log.warning("stream_tts still alive after kill (cleaned by descendant sweep)")
            except Exception as ex:
                log.warning(f"Error terminating stream_tts: {ex}")
        if _stream_tts_log is not None:
            try:
                _stream_tts_log.close()
            except Exception:
                pass
            _stream_tts_log = None

        if _mcp_connect_task is not None and not _mcp_connect_task.done():
            _mcp_connect_task.cancel()
            await asyncio.wait_for(
                asyncio.gather(_mcp_connect_task, return_exceptions=True),
                timeout=5.0,
            )

        try:
            from engine.server.mcp_server import get_mcp_hub
            await asyncio.wait_for(get_mcp_hub().shutdown(), timeout=5.0)
        except asyncio.TimeoutError:
            log.warning("MCP hub shutdown timed out")
        except Exception as e:
            log.warning(f"MCP shutdown failed: {e}")

        try:
            from engine.tools.load_hook import HookRegistry
            await HookRegistry.get_instance().fire_async("on_shutdown")
        except Exception as e:
            log.warning(f"Hook shutdown failed: {e}")

        try:
            from engine.tools.load_plugin import PluginLoader
            PluginLoader.get_instance().unload_all()
        except Exception as e:
            log.warning(f"Plugin unload failed: {e}")

        try:
            from engine.server.redis_server import close_redis
            await asyncio.wait_for(close_redis(), timeout=5.0)
        except asyncio.TimeoutError:
            log.warning("Redis close timed out")
        except Exception as e:
            log.warning(f"Redis close failed: {e}")

        try:
            from engine.core.learning import get_learning_engine
            await asyncio.wait_for(
                get_learning_engine().shutdown_learning_scheduler(), timeout=3.0
            )
        except asyncio.TimeoutError:
            log.warning("Learning scheduler shutdown timed out")
        except Exception as e:
            log.warning(f"Learning scheduler shutdown failed: {e}")

        try:
            from engine.core.dream import shutdown_dream_watcher
            await asyncio.wait_for(shutdown_dream_watcher(), timeout=3.0)
        except asyncio.TimeoutError:
            log.warning("Dream watcher shutdown timed out")
        except Exception as e:
            log.warning(f"Dream watcher shutdown failed: {e}")

        log.info("===== JARVIS Server Shutdown =====")

    try:
        await asyncio.wait_for(_shutdown_sequence(), timeout=10.0)
    except asyncio.TimeoutError:
        log.warning("Overall lifespan shutdown timed out after 10s")
    finally:
        # Catch-all: force-kill every descendant server.py spawned (stream_tts,
        # redis if self-started, MCP stdio subprocesses, tool helpers) so nothing
        # is orphaned holding ports 8082/8340/6379. llama-server and headroom
        # live outside this process tree and are untouched.
        try:
            from engine.core.process_tree import kill_descendants
            killed = await asyncio.to_thread(kill_descendants, os.getpid())
            if killed:
                log.info("Force-killed %d leftover descendant process(es)", killed)
        except Exception as e:
            log.warning(f"Descendant cleanup failed: {e}")


app = FastAPI(title="JARVIS Server", version="0.1.0", lifespan=lifespan)

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


# -- Include Modularized REST Endpoints ----------------------------------------
from engine.UIUX.ui_engine import router as ui_router
app.include_router(ui_router)


# -- WebSocket Voice Handler -----------------------------------------------

@app.websocket("/ws/voice")
async def voice_handler(ws: WebSocket):
    global _active_voice_connections, _active_ws_session
    """
    WebSocket protocol:

    Client -> Server:
        {"type": "transcript", "text": "...", "isFinal": true}

    Server -> Client:
        {"type": "audio", "data": "<base64 mp3>", "text": "spoken text"}
        {"type": "status", "state": "thinking"|"speaking"|"idle"|"working"}
    """
    client_host = ws.client.host if ws.client else None
    device_type = ws.query_params.get("device", "desktop")
    ws.device_type = device_type
    from engine.security.firewall import is_ip_allowed, is_request_origin_allowed
    if not is_ip_allowed(client_host):
        log.warning(f"Blocked unauthorized WebSocket connection attempt from IP: {client_host}")
        await ws.close(code=1008) # Policy Violation
        return
    if not is_request_origin_allowed(ws.headers):
        log.warning(f"Blocked cross-origin WebSocket from Origin: {ws.headers.get('origin')}")
        await ws.close(code=1008)
        return

    await ws.accept()
    from engine.server.ws_dispatcher import WebSocketEventDispatcher
    dispatcher = WebSocketEventDispatcher(ws)
    await dispatcher.start()
    ws._event_dispatcher = dispatcher
    # Mỗi kết nối là một phiên chat riêng: tab khác không bị đóng, hội thoại không trộn.
    ws.session_id = f"web-{uuid.uuid4().hex[:8]}"
    set_session(ws.session_id)
    _ws_sessions.add(ws)
    _active_ws_session = ws

    _active_voice_connections += 1
    history: list[dict] = []

    from engine.main.flow_tracker import FlowTracker
    from engine.main.flow_agents import FlowAgents
    ft = FlowTracker(ws, safe_ws_send_json)
    fa = FlowAgents(ws, safe_ws_send_json)

    # Audio collision prevention — track when user last spoke
    voice_state = {"last_user_time": 0.0}

    # Self-awareness — track last spoken response to avoid repetition
    last_jarvis_response = ""

    log.info(f"Voice WebSocket connected ({device_type}) from {client_host} session={ws.session_id}")

    try:
        ws.cancel_requested = False
        message_queue = asyncio.Queue()
        ws.message_queue = message_queue

        async def ws_reader():
            try:
                while True:
                    raw = await ws.receive_text()
                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if msg.get("type") == "ping":
                        # Answered here so it never reaches message_queue, where
                        # ask_user_* pollers would churn re-queueing it for the
                        # whole 300s an approval card is open.
                        await safe_ws_send_json(ws, {"type": "pong"})
                        continue
                    if msg.get("type") == "cancel":
                        # Đặt cờ ngay tại đây (task này chạy song song, không
                        # bị chặn bởi generate_response_stream) thay vì chỉ
                        # đẩy vào message_queue — vòng lặp chính đang await
                        # generate_response_stream nên không thể đọc queue
                        # cho tới khi lượt cũ sinh xong, khiến cancel tới trễ
                        # vô nghĩa. Các checkpoint trong LLM stream/TTS đã
                        # sẵn poll cờ này thường xuyên nên chỉ cần đặt sớm.
                        ws.cancel_requested = True
                        log.info("Cancel requested by client (barge-in)")
                    # Nút TTS / media: đặt cờ ngay (luồng TTS đang chạy dừng ở lượt poll tiếp theo), không chờ vòng lặp chính rảnh.
                    _apply_tts_gate_now(ws, msg)
                    await message_queue.put(msg)
            except WebSocketDisconnect:
                log.info("Voice WebSocket disconnected")
                # Nếu client đã rời đi giữa lúc đang generate/TTS, generation
                # trước đây vẫn tiếp tục chạy hết cho tới khi xong (chỉ dừng
                # khi được yêu cầu tường minh qua tin nhắn) — tốn compute/TTS
                # vô ích cho 1 kết nối đã chết. Đặt cancel_requested ngay lập
                # tức để bất kỳ vòng lặp generation nào đang kiểm tra cờ này
                # dừng lại ở lượt kiểm tra tiếp theo, không cần chờ tới khi
                # main loop rảnh mới đọc được sentinel None trong queue.
                ws.cancel_requested = True
                await message_queue.put(None)
            except Exception as e:
                log.error(f"WS Reader Exception: {e}")
                ws.cancel_requested = True
                await message_queue.put(None)

        reader_task = asyncio.create_task(ws_reader())
        _background_tasks.add(reader_task)
        reader_task.add_done_callback(_background_tasks.discard)

        # Chạy greeting ở background, hủy nếu user nói trước
        greeting_task: Optional[asyncio.Task] = None

        async def _run_greeting():
            try:
                await send_greeting(ws, history, safe_ws_send_json)
            except asyncio.CancelledError:
                pass

        # Không await — greeting chạy background, message loop chạy ngay
        greeting_task = asyncio.create_task(_run_greeting())
        ws.greeting_task = greeting_task

        async def _cancel_greeting_audio() -> None:
            """Dừng audio greeting độc lập trước khi đổi sang trạng thái/phiên mới."""
            greeting_tts_task = getattr(ws, "greeting_tts_task", None)
            if greeting_tts_task and not greeting_tts_task.done():
                greeting_tts_task.cancel()
                await asyncio.gather(greeting_tts_task, return_exceptions=True)
            if getattr(ws, "greeting_tts_task", None) is greeting_tts_task:
                ws.greeting_tts_task = None

        while True:
            msg = await message_queue.get()
            if msg is None:  # Connection closed
                break
            # Anything an agent records after this belongs to this turn.
            turn_started_at = time.time()

            if msg.get("type") == "toggle_tts":
                enabled = msg.get("enabled", True)
                ws.user_tts_disabled = not enabled
                _sync_tts_gate(ws)
                log.info(f"TTS toggled to: {enabled}")
                if not enabled:
                    await _cancel_greeting_audio()
                continue

            if msg.get("type") == "media_state":
                ws.media_active = msg.get("active", False)
                log.info(f"Media state changed to active={ws.media_active}")
                _sync_tts_gate(ws)
                continue

            if msg.get("type") == "webcam_capture_response":
                img_data = msg.get("image", "")
                log.info("Received webcam_capture_response from client")
                global _latest_webcam_image, _webcam_image_event
                _latest_webcam_image = img_data
                if _webcam_image_event:
                    _webcam_image_event.set()
                continue

            if msg.get("type") == "save_pin":
                label = msg.get("label", "Ghi chú")
                lat = float(msg.get("lat", 0))
                lng = float(msg.get("lng", 0))
                from engine.core.memory import save_pin_to_db, get_pins_from_db
                await asyncio.to_thread(save_pin_to_db, label, lat, lng)
                # Phát lại danh sách pin mới cho client
                current_pins = await asyncio.to_thread(get_pins_from_db)
                await safe_ws_send_json(ws, {"type": "pins", "pins": current_pins})
                continue

            if msg.get("type") == "delete_pin":
                lat = float(msg.get("lat", 0))
                lng = float(msg.get("lng", 0))
                from engine.core.memory import delete_pin_from_db, get_pins_from_db
                await asyncio.to_thread(delete_pin_from_db, lat, lng)
                # Phát lại danh sách pin mới
                current_pins = await asyncio.to_thread(get_pins_from_db)
                await safe_ws_send_json(ws, {"type": "pins", "pins": current_pins})
                continue

            if msg.get("type") == "get_pins":
                from engine.core.memory import get_pins_from_db
                current_pins = await asyncio.to_thread(get_pins_from_db)
                await safe_ws_send_json(ws, {"type": "pins", "pins": current_pins})
                continue

            if msg.get("type") == "geolocation":
                lat = msg.get("lat")
                lng = msg.get("lng")
                log.info(f"Client reported geolocation: {lat}, {lng}")
                continue

            if msg.get("type") == "interactive_response":
                card_id = msg.get("cardId", "")
                action = msg.get("action", "")
                val = msg.get("value")
                log.info(f"Received interactive_response: card_id={card_id}, action={action}, value={val}")
                
                # Kiểm tra xem card_id này có nằm trong các yêu cầu đang chờ xác thực hay không
                from engine.main.ask_verifi import (
                    pending_input_cards,
                    pending_selection_cards,
                    pending_verifications,
                )
                if card_id in pending_input_cards:
                    fut = pending_input_cards[card_id]
                    if not fut.done():
                        fut.set_result(val if action == "submit" and isinstance(val, str) else None)
                elif card_id in pending_selection_cards:
                    fut = pending_selection_cards[card_id]
                    if not fut.done():
                        selected = val[0] if action == "submit" and isinstance(val, list) and val else None
                        fut.set_result(selected if isinstance(selected, str) else None)
                elif card_id in pending_verifications:
                    fut = pending_verifications[card_id]
                    if not fut.done():
                        if action == "approve":
                            fut.set_result(True)
                        elif action == "reject":
                            fut.set_result(False)
                        else:
                            fut.set_result(False)

                # Auto-play video Youtube khi nhận được phản hồi chọn video từ Frontend
                if "youtube_select_" in card_id and action == "submit" and val:
                    selected_embed_url = val[0] if isinstance(val, list) and val else val
                    log.info(f"Auto-playing selected Youtube video URL: {selected_embed_url}")
                    await safe_ws_send_json(ws, {
                        "type": "media_open",
                        "query": "Youtube Video",
                        "embed_url": selected_embed_url,
                        "title": "Youtube Stream",
                        "source": "youtube"
                     })

                try:
                    from engine.core.memory import save_message
                    # Lưu lại phản hồi tương tác như một đoạn chat của user
                    feedback_text = f"[Phản hồi tương tác] {action.upper()}"
                    if val:
                        feedback_text += f": {json.dumps(val, ensure_ascii=False)}"
                    await asyncio.to_thread(save_message, "user", feedback_text)
                except Exception as db_err:
                    log.warning(f"Failed to save interactive response message: {db_err}")
                continue


            if msg.get("type") != "transcript" or not msg.get("isFinal"):
                continue

            user_text = apply_speech_corrections(msg.get("text", "").strip())
            attachment_id = msg.get("attachmentId")
            if not user_text and not attachment_id:
                continue

            # Slash-command interception (mirrors the Telegram command flow):
            # resolve "/cmd arg" deterministically so arguments reach the pipeline.
            from engine.server import slash_commands as sc
            user_text = await sc.handle_slash_message(
                ws,
                user_text,
                lambda payload: safe_ws_send_json(ws, payload),
            )
            if user_text is None:
                continue

            attachment_context = None
            if attachment_id:
                from engine.core.attachment_store import resolve_attachment
                attachment_context = await asyncio.to_thread(resolve_attachment, str(attachment_id))
                if attachment_context is None:
                    await safe_ws_send_json(ws, {"type": "stream_start"})
                    await safe_ws_send_json(ws, {
                        "type": "text_chunk",
                        "text": "Tệp đính kèm đã hết hạn hoặc không còn tồn tại. Vui lòng tải lại tệp.",
                    })
                    await safe_ws_send_json(ws, {"type": "stream_end"})
                    continue

            # Nếu greeting còn chạy, hủy ngay để xử lý tin nhắn user
            if greeting_task and not greeting_task.done():
                ws.cancel_requested = True
                greeting_task.cancel()
                greeting_task = None
            await _cancel_greeting_audio()

            ws.cancel_requested = False

            voice_state["last_user_time"] = time.time()
            log.info(f"User: {user_text}")

            # Reset flow tracker cho phiên mới + báo frontend clear steps
            ft.reset()
            fa.reset()
            await safe_ws_send_json(ws, {"type": "stream_start"})
            await ft.track(f"Nhận: {user_text[:24]}{'...' if len(user_text) > 24 else ''}", "completed")

            # Chốt chặn bảo mật Input Guardrail
            is_safe = True
            reason = ""
            try:
                async with ft.step("Kiểm tra Input Guardrail"):
                    from engine.core.guardrails import verify_input
                    is_safe, reason = verify_input(user_text)
                    if not is_safe:
                        raise ValueError(reason)
            except Exception as e:
                if not is_safe:
                    response_text = f"Cảnh báo bảo mật: {reason}"
                    log.warning(f"Input Guardrail blocked user message: {user_text}")
                    await safe_ws_send_json(ws, {"type": "text_chunk", "text": response_text})
                    audio = await synthesize_speech(response_text)
                    if audio:
                        await safe_ws_send_json(ws, {"type": "audio", "data": base64.b64encode(audio).decode()})
                    await safe_ws_send_json(ws, {"type": "stream_end"})
                    
                    history.append({"role": "user", "content": user_text})
                    history.append({"role": "assistant", "content": response_text})
                    
                    try:
                        from engine.core.memory import save_message
                        await asyncio.to_thread(save_message, "user", user_text)
                        await asyncio.to_thread(save_message, "assistant", response_text)
                    except Exception as db_err:
                        log.warning(f"Failed to save blocked messages: {db_err}")
                    continue
                else:
                    log.error(f"Failed to run Input Guardrail: {e}")

            # Lưu tin nhắn User ngay lập tức vào database trước khi gọi LLM
            try:
                from engine.core.memory import save_message
                await asyncio.to_thread(save_message, "user", user_text)
            except Exception as db_err:
                log.warning(f"Failed to save user message: {db_err}")

            await safe_ws_send_json(ws, {"type": "status", "state": "thinking"})

            try:
                if not openai_client:
                    # This branch replies without running handle_turn, so it never
                    # resets ws.pending_ask_user (normally done in dispatch/chat_stream) —
                    # left alone, a stale value from an earlier turn would ride along
                    # into the assistant save below (M4).
                    ws.pending_ask_user = ""
                    ws.pending_action_run = ""
                    response_text = "API key not configured."
                else:
                    from engine.core.learning import get_learning_engine
                    learning_engine = get_learning_engine()

                    try:
                        learning_engine.begin_interactive_chat()
                        # Tags this task (and everything it spawns) as a live
                        # turn so call_llm prioritises it over background work.
                        from engine.core.activity_gate import mark_interactive_turn
                        mark_interactive_turn()
                        try:
                            response_text = await generate_response_stream(
                                user_text, openai_client,
                                ws=ws,
                                last_response=last_jarvis_response,
                                conversation_history=history,
                                flow_tracker=ft,
                                flow_agents=fa,
                                attachment_context=attachment_context,
                            )
                        finally:
                            learning_engine.end_interactive_chat()
                    finally:
                        if attachment_id:
                            from engine.core.attachment_store import discard_attachment
                            discard_attachment(str(attachment_id))

                if ws.cancel_requested:
                    log.info("Discarding database/history updates because response was cancelled")
                    await ft.fail_all_active()
                    await fa.fail_all_active()
                    continue

                # Update history (giữ nguyên user_text gốc để không làm bẩn hiển thị của người dùng)
                history.append({"role": "user", "content": user_text})
                history.append({"role": "assistant", "content": response_text})

                # Lưu tin nhắn Assistant đồng bộ trực tiếp vào database
                try:
                    from engine.core.memory import save_message
                    persistence_started = time.monotonic()
                    await asyncio.to_thread(
                        save_message, "assistant", response_text, "", getattr(ws, "pending_ask_user", ""), getattr(ws, "pending_action_run", "")
                    )
                    log.info(
                        "Web response persistence: assistant_message elapsed=%.3fs",
                        time.monotonic() - persistence_started,
                    )
                except Exception as db_err:
                    log.warning(f"Failed to save assistant message: {db_err}")

                # Only an outcome recorded during THIS turn counts. The session
                # keeps its last outcome forever, which made every later turn
                # re-validate an old workflow and skip conversation learning.
                from engine.core.learning import outcome_for_turn
                turn_outcome_id, turn_outcome_status = outcome_for_turn(ws, turn_started_at)

                # Lưu nhật ký hoạt động hàng ngày vào Obsidian Wiki
                try:
                    from engine.core.memory_tree import save_daily_digest
                    persistence_started = time.monotonic()
                    await asyncio.to_thread(
                        save_daily_digest,
                        user_text,
                        response_text,
                        outcome_id=turn_outcome_id,
                    )
                    log.info(
                        "Web response persistence: daily_digest elapsed=%.3fs",
                        time.monotonic() - persistence_started,
                    )
                except Exception as ex:
                    log.warning(f"Failed to save daily digest to wiki: {ex}")

                # Xếp learning + semantic memory vào hàng đợi ưu tiên thấp sau khi phản hồi đã được lưu.
                try:
                    from engine.core.learning import get_learning_engine
                    get_learning_engine().schedule_conversation_learning(
                        user_text,
                        response_text,
                        outcome_id=turn_outcome_id,
                        outcome_status=turn_outcome_status,
                    )
                    log.info("Conversation learning queued for idle processing session=%s", ws.session_id)
                except Exception as le_task_err:
                    log.warning(f"Failed to queue conversation learning: {le_task_err}")

                await ft.track("Hoàn thành", "completed")
                await fa.complete_all_active()
                # Tell client to go idle after audio finishes
                await safe_ws_send_json(ws, {"type": "status", "state": "idle"})
                
                log.info(f"JARVIS: {response_text or ''}")
                last_jarvis_response = response_text

            except Exception as e:
                log.error(f"Error: {e}", exc_info=True)
                await ft.fail_all_active()
                await fa.fail_all_active()
                await ft.track(f"Lỗi: {e}", "failed")
                fallback = "Something went wrong, sir."

                # Lưu fallback assistant message vào database khi xảy ra lỗi
                try:
                    await asyncio.to_thread(save_message, "assistant", fallback)
                except Exception as db_err:
                    log.warning(f"Failed to save assistant fallback message: {db_err}")

                # Luôn đọc/gửi fallback cho client, bất kể lưu DB có thành công hay không
                try:
                    audio = await synthesize_speech(fallback)
                    if audio:
                        await safe_ws_send_json(ws, {"type": "audio", "data": base64.b64encode(audio).decode(), "text": fallback})
                    else:
                        await safe_ws_send_json(ws, {"type": "text", "text": fallback})
                    # Let client's audioPlayer.onFinished handle idle transition
                except Exception as send_err:
                    log.warning(f"Fallback audio send failed: {send_err}")

    except WebSocketDisconnect:
        log.info("Voice WebSocket disconnected")
    except Exception as e:
        log.error(f"WebSocket error: {e}", exc_info=True)
    finally:
        greeting_task = getattr(ws, "greeting_task", None)
        if greeting_task is not None and not greeting_task.done():
            greeting_task.cancel()
            await asyncio.gather(greeting_task, return_exceptions=True)
        ws.greeting_task = None
        await dispatcher.close()
        ws._event_dispatcher = None
        _ws_sessions.remove(ws)
        _active_ws_session = _ws_sessions.latest
        _active_voice_connections = max(0, _active_voice_connections - 1)




# ---------------------------------------------------------------------------
# Settings / Configuration endpoints
# ---------------------------------------------------------------------------

def _env_file_path() -> Path:
    return Path(__file__).parent / ".env"

def _env_example_path() -> Path:
    return Path(__file__).parent / ".env.example"

def _read_env() -> tuple[list[str], dict[str, str]]:
    """Read .env file. Returns (raw_lines, parsed_dict). Creates from .env.example if missing."""
    path = _env_file_path()
    if not path.exists():
        example = _env_example_path()
        if example.exists():
            import shutil as _shutil
            _shutil.copy2(str(example), str(path))
        else:
            path.write_text("")
    lines = path.read_text(encoding="utf-8").splitlines()
    parsed: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            k, _, v = stripped.partition("=")
            parsed[k.strip()] = v.strip().strip('"').strip("'")
    return lines, parsed

def _write_env_key(key: str, value: str) -> None:
    """Update a single key in .env, preserving comments and order."""
    lines, _ = _read_env()
    found = False
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            k, _, _ = stripped.partition("=")
            if k.strip() == key:
                new_lines.append(f"{key}={value}")
                found = True
                continue
        new_lines.append(line)
    if not found:
        new_lines.append(f"{key}={value}")
    _env_file_path().write_text("\n".join(new_lines) + "\n", encoding="utf-8")

class KeyUpdate(BaseModel):
    key_name: str
    key_value: str

class KeyTest(BaseModel):
    key_value: str | None = None

class PreferencesUpdate(BaseModel):
    user_name: str = ""
    honorific: str = "sir"
    calendar_accounts: str = "auto"

# ---------------------------------------------------------------------------
# Media Hub API
# ---------------------------------------------------------------------------

MEDIA_LOCAL_DIR = Path(__file__).parent / "media"
MEDIA_LOCAL_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Static file serving (frontend)
# ---------------------------------------------------------------------------

from engine.UIUX.ui_engine import mount_frontend_dist

FRONTEND_DIST = Path(__file__).parent / "frontend" / "dist"
mount_frontend_dist(app, FRONTEND_DIST)


# ---------------------------------------------------------------------------
# APP API change in folder engine/UIUX/ui_engine connect frontend
# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def signal_handler(signum, frame):
    """Route Ctrl+C to the running Uvicorn worker for graceful cleanup."""
    if _uvicorn_server is not None:
        log.info("Ctrl+C received; requesting graceful Uvicorn shutdown")
        _uvicorn_server.should_exit = True
        return
    raise KeyboardInterrupt


if __name__ == "__main__":
    import argparse
    import signal
    import uvicorn

    signal.signal(signal.SIGINT, signal_handler)

    parser = argparse.ArgumentParser(description="JARVIS Server 3.0")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host")
    parser.add_argument("--port", type=int, default=8340, help="Bind port")
    parser.add_argument("--reload", action="store_true", help="Auto-reload on changes")
    parser.add_argument("--ssl", action="store_true", help="Enable HTTPS with key.pem/cert.pem")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    if not args.worker:
        import subprocess
        worker_command = [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:], "--worker"]
        while True:
            worker = subprocess.Popen(worker_command)
            try:
                worker_exit = worker.wait()
            except KeyboardInterrupt:
                log.info("Terminal Ctrl+C received; waiting for JARVIS worker cleanup")
                try:
                    worker.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    log.warning("Worker did not exit after Ctrl+C; force-killing its process tree")
                    try:
                        subprocess.run(
                            ["taskkill", "/F", "/T", "/PID", str(worker.pid)],
                            capture_output=True,
                            timeout=10,
                        )
                        worker.wait(timeout=5)
                    except Exception as e:
                        log.warning(f"Force-kill failed: {e}; falling back to terminate()")
                        worker.terminate()
                        worker.wait(timeout=5)
                raise SystemExit(0)
            if worker_exit != 75:
                raise SystemExit(worker_exit)
            log.info("Worker requested restart; starting a clean worker")

    # Auto-detect SSL certs
    cert_file = Path(__file__).parent / "cert.pem"
    key_file = Path(__file__).parent / "key.pem"
    use_ssl = args.ssl or (cert_file.exists() and key_file.exists())

    ssl_kwargs = {}
    if use_ssl:
        ssl_kwargs["ssl_keyfile"] = str(key_file)
        ssl_kwargs["ssl_certfile"] = str(cert_file)

    # Import asyncio at function level for shutdown handling
    import asyncio
    
    exit_code = 0
    try:
        # Configure uvicorn with timeout for graceful shutdown
        config = uvicorn.Config(
            app,
            host=args.host,
            port=args.port,
            reload=args.reload,
            log_level="warning",
            access_log=False,
            timeout_graceful_shutdown=3,  # 3 second timeout for graceful shutdown
            **ssl_kwargs,
        )
        server = uvicorn.Server(config)
        _uvicorn_server = server
        app.state.uvicorn_server = server
        asyncio.run(server.serve())
    except (KeyboardInterrupt, SystemExit):
        log.info("Server interrupted")
    finally:
        log.info("Server stopped")
        restart_requested = os.environ.pop("JARVIS_RESTART_REQUESTED", "") == "1"
        try:
            import os as _os
            import sys as _sys
            _sys.stderr = open(_os.devnull, 'w')
        except Exception:
            pass
        if restart_requested:
            log.info("Cleanup complete; returning restart code to terminal supervisor")
            exit_code = 75
        sys.exit(exit_code)
