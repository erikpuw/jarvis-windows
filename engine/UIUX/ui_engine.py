import os
import time
import asyncio
import logging
import base64
import json
import re
from pathlib import Path
from typing import Any, Literal
from fastapi import APIRouter, Depends, UploadFile, File, Form, Request
from fastapi.responses import JSONResponse, FileResponse
from engine.security.policy import UploadTooLarge, read_limited, resolve_file_under
from pydantic import BaseModel
from engine.UIUX.memory_lock import lock_router, memory_gate


def mount_frontend_dist(app, dist: Path) -> None:
    """Serve the Vite build: index at "/", plus every top-level dist folder
    (assets/ and whatever frontend/public/ copies in, e.g. mascots/)."""
    if not dist.exists():
        return
    from starlette.staticfiles import StaticFiles

    @app.get("/")
    async def serve_index():
        return FileResponse(str(dist / "index.html"))

    for sub in sorted(p for p in dist.iterdir() if p.is_dir()):
        app.mount(f"/{sub.name}", StaticFiles(directory=str(sub)), name=f"dist-{sub.name}")

log = logging.getLogger("jarvis.ui_engine")

# Memory Control, lịch sử chat, nhật ký (xem memory_lock.PROTECTED_PREFIXES) đòi token mở khóa bằng MEMORY_PASSWORD
router = APIRouter(dependencies=[Depends(memory_gate)])
router.include_router(lock_router)
_pending_tasks: set[asyncio.Task] = set()

# ---------------------------------------------------------------------------
# Pydantic Models
# ---------------------------------------------------------------------------
class KeyUpdate(BaseModel):
    key_name: str
    key_value: str

class KeyTest(BaseModel):
    key_value: str | None = None

class PreferencesUpdate(BaseModel):
    user_name: str = ""
    honorific: str = "sir"
    calendar_accounts: str = "auto"

class PromptSave(BaseModel):
    id: str
    content: str

PROMPT_DIR = Path(__file__).parent.parent.parent / "prompt"
_PROMPT_ID_RE = re.compile(r"^[A-Za-z0-9_\-]+$")
_PROMPT_MAX_BYTES = 256 * 1024


# ---------------------------------------------------------------------------
# REST Endpoints
# ---------------------------------------------------------------------------

# Số phiên bản: một nguồn duy nhất là file VERSION ở gốc repo (README ghi cùng số).
_VERSION = (Path(__file__).resolve().parents[2] / "VERSION").read_text(encoding="utf-8").strip()


@router.get("/api/health")
async def health():
    return {"status": "online", "name": "JARVIS", "version": _VERSION}


@router.get("/api/health/detailed")
async def health_detailed():
    """Chi tiết trạng thái của toàn bộ hệ thống (LLM, Redis, UI-TARS, RAG, DB)."""
    import os
    import time
    import httpx
    
    # 1. LLM (llama.cpp) Status
    llm_url = os.getenv("LOCAL_URL", "").strip()
    llm_key = os.getenv("LOCAL_API_KEY", "").strip()
    llm_status = "offline"
    llm_response_time = None
    if llm_url:
        try:
            start_time = time.perf_counter()
            async with httpx.AsyncClient(timeout=2.0) as client:
                headers = {}
                if llm_key:
                    headers["Authorization"] = f"Bearer {llm_key}"
                resp = await client.get(f"{llm_url}/models", headers=headers)
                if resp.status_code == 200:
                    llm_status = "online"
                else:
                    llm_status = f"error_http_{resp.status_code}"
            llm_response_time = round((time.perf_counter() - start_time) * 1000, 2)
        except Exception as e:
            llm_status = f"offline ({type(e).__name__})"
    else:
        llm_status = "not_configured"

    # 2. Redis Status
    redis_status = "offline"
    try:
        from engine.server.redis_server import redis_client
        if redis_client:
            await asyncio.wait_for(redis_client.ping(), timeout=2.0)
            redis_status = "online"
        else:
            redis_status = "not_initialized"
    except Exception as e:
        redis_status = f"offline ({type(e).__name__})"

    # 4. RAG Status
    rag_enabled = False
    rag_chunks = 0
    rag_files_count = 0
    try:
        from engine.core.rag_engine import get_rag_engine
        rag = get_rag_engine()
        try:
            from engine.server.llm_server import get_embed_client
            await rag.try_self_heal(get_embed_client())
        except Exception as heal_err:
            log.warning(f"RAG self-heal check failed: {heal_err}")
        rag_enabled = rag.enabled
        rag_chunks = len(rag.chunks)
        rag_files_count = len(rag.get_indexed_files())
    except Exception:
        pass

    # 5. DB Stats (Memory DB)
    db_size_kb = 0
    db_ok = False
    try:
        from engine.core.memory import DB_PATH, _get_db
        if DB_PATH.exists():
            db_size_kb = round(os.path.getsize(DB_PATH) / 1024, 2)
        conn = _get_db()
        conn.execute("SELECT 1").fetchone()
        conn.close()
        db_ok = True
    except Exception:
        db_ok = False

    return {
        "status": "online",
        "llm": {
            "status": llm_status,
            "url": llm_url,
            "response_time_ms": llm_response_time
        },
        "redis": {
            "status": redis_status
        },

        "rag": {
            "enabled": rag_enabled,
            "total_chunks": rag_chunks,
            "files_count": rag_files_count
        },
        "database": {
            "ok": db_ok,
            "size_kb": db_size_kb
        },
        "timestamp": time.time()
    }


# ---------------------------------------------------------------------------
# Conversation Quality Metrics (Feature 4)
# ---------------------------------------------------------------------------

class FeedbackBody(BaseModel):
    messageId: str = ""
    rating: int  # 1 = thumbs up, -1 = thumbs down
    comment: str = ""


@router.post("/api/feedback")
async def api_save_feedback(body: FeedbackBody):
    """Lưu feedback thumbs up/down của người dùng về câu trả lời."""
    try:
        from engine.core.memory import save_feedback
        fb_id = await asyncio.to_thread(save_feedback, body.messageId, body.rating, body.comment)
        return {"success": True, "id": fb_id}
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@router.get("/api/feedback/stats")
async def api_feedback_stats(days: int = 30):
    """Thống kê satisfaction rate trong N ngày."""
    try:
        from engine.core.memory import get_feedback_stats
        stats = await asyncio.to_thread(get_feedback_stats, days)
        return stats
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ---------------------------------------------------------------------------
# RAG Document Intelligence Status (Feature 11)
# ---------------------------------------------------------------------------

@router.get("/api/rag/status")
async def api_rag_status():
    """Trạng thái RAG engine: danh sách file đã index, chunk count, watch folder."""
    try:
        from engine.core.rag_engine import get_rag_engine
        from engine.core.rag_watcher import get_watch_stats
        import os
        from pathlib import Path

        rag = get_rag_engine()
        try:
            from engine.server.llm_server import get_embed_client
            await rag.try_self_heal(get_embed_client())
        except Exception as heal_err:
            log.warning(f"RAG self-heal check failed: {heal_err}")
        indexed_files = rag.get_indexed_files()
        watch_stats = get_watch_stats()

        _default_watch = str(Path(__file__).parent.parent.parent / "data" / "documents")
        watch_folder = os.getenv("RAG_WATCH_FOLDER", _default_watch)

        return {
            "enabled": rag.enabled,
            "total_chunks": len(rag.chunks),
            "indexed_files": indexed_files,
            "watch_folder": watch_folder,
            "watch_db": watch_stats,
        }
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.delete("/api/rag/document")
async def api_rag_remove_document(
    file_path: str | None = None,
    document_id: str | None = None,
):
    """Xóa tài liệu khỏi RAG index theo đường dẫn (file trong thư mục watcher)
    hoặc theo document_id (tài liệu lưu qua chat, không có file_path thân
    thiện với người dùng)."""
    if not file_path and not document_id:
        return JSONResponse(
            {"success": False, "error": "Cần truyền file_path hoặc document_id."},
            status_code=400,
        )
    try:
        from engine.core.rag_engine import get_rag_engine
        rag = get_rag_engine()
        if document_id:
            # Tài liệu lưu qua chat không được rag_watch.db theo dõi, nên
            # không cần (và không thể) đồng bộ mark_removed() ở đây.
            removed = await rag.remove_by_document_id(document_id)
        else:
            from engine.core.rag_watcher import mark_removed
            removed = await rag.remove_document(file_path)
            # Keep rag_watch.db in sync with the index - otherwise _is_indexed()
            # keeps believing this file is already indexed and a later
            # scan_existing() (e.g. after a fixed re-upload) never re-indexes it.
            mark_removed(str(Path(file_path).resolve()))
        return {"success": True, "chunks_removed": removed}
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@router.get("/api/tts-test")
async def tts_test():
    """Generate a test audio clip for debugging."""
    import server
    audio = await server.synthesize_speech("Testing audio, sir.")
    if audio:
        return {"audio": base64.b64encode(audio).decode()}
    return {"audio": None, "error": "TTS failed"}


@router.get("/api/usage")
async def api_usage():
    import server
    await asyncio.to_thread(server._update_session_tokens_from_log)
    uptime = int(time.time() - server._session_start)
    today = await asyncio.to_thread(server._get_usage_for_period, 86400)
    week = await asyncio.to_thread(server._get_usage_for_period, 86400 * 7)
    month = await asyncio.to_thread(server._get_usage_for_period, 86400 * 30)
    all_time = await asyncio.to_thread(server._get_usage_for_period, None)
    return {
        "session": {**server._session_tokens, "uptime_seconds": uptime},
        "today": {**today, "cost_usd": round(server._cost_from_tokens(today["input_tokens"], today["output_tokens"]), 4)},
        "week": {**week, "cost_usd": round(server._cost_from_tokens(week["input_tokens"], week["output_tokens"]), 4)},
        "month": {**month, "cost_usd": round(server._cost_from_tokens(month["input_tokens"], month["output_tokens"]), 4)},
        "all_time": {**all_time, "cost_usd": round(server._cost_from_tokens(all_time["input_tokens"], all_time["output_tokens"]), 4)},
    }


@router.post("/api/settings/keys")
async def api_settings_keys(body: KeyUpdate):
    import server
    allowed = {"LOCAL_API_KEY", "TTS_LOCAL_KEY", "LOCAL_URL", "TTS_LOCAL_MODEL", "USER_NAME", "HONORIFIC"}
    if body.key_name not in allowed:
        return JSONResponse({"success": False, "error": "Invalid key name"}, status_code=400)
    server._write_env_key(body.key_name, body.key_value)
    return {"success": True}


class VoiceSelect(BaseModel):
    voice: str


def _active_tts_engine() -> str:
    """'vieneu' | 'edge' | '' — same rule the TTS manager uses to pick an engine."""
    try:
        from engine.server.tts_manager import _resolve_tts_engine
        return _resolve_tts_engine() or ""
    except Exception:
        return ""


def _tts_base_url() -> str:
    from engine.server.tts_manager import TTS_STREAM_URL
    return TTS_STREAM_URL.rsplit("/tts/stream", 1)[0]


async def _tts_voices_call(method: str) -> dict:
    """Hỏi server TTS (cổng 8082) danh sách giọng; lần đầu có thể chờ nạp model."""
    import httpx
    from engine.server.tts_manager import _resolve_tts_engine
    if _resolve_tts_engine() != "vieneu":
        return {"engine": "edge", "default": "", "voices": []}
    url = _tts_base_url() + ("/tts/voices" if method == "GET" else "/tts/voices/reload")
    async with httpx.AsyncClient(timeout=180.0) as client:
        resp = await client.request(method, url)
    resp.raise_for_status()
    return resp.json()


def _with_current(data: dict) -> dict:
    data["current"] = os.getenv("VIENEU_VOICE_ID", "").strip() or data.get("default", "")
    return data


@router.get("/api/tts/voices")
async def api_tts_voices():
    try:
        return _with_current(await _tts_voices_call("GET"))
    except Exception as e:
        return JSONResponse({"error": str(e)[:200]}, status_code=503)


@router.post("/api/tts/voice")
async def api_tts_select_voice(body: VoiceSelect):
    import server
    voice = body.voice.strip()
    if not voice or len(voice) > 80 or any(c in voice for c in "\r\n="):
        return JSONResponse({"success": False, "error": "Invalid voice name"}, status_code=400)
    os.environ["VIENEU_VOICE_ID"] = voice  # tts_manager đọc mỗi lần gọi, có hiệu lực ngay
    server._write_env_key("VIENEU_VOICE_ID", voice)
    return {"success": True, "voice": voice}


@router.post("/api/tts/voices/clone")
async def api_tts_clone_voice(name: str = Form(...), file: UploadFile = File(...)):
    """Lưu mẫu giọng (3–8 giây) vào model/voices/ và đăng ký làm giọng đọc."""
    import re
    from engine.server.vieneu_tts import CLONE_DIR, CLONE_EXTS
    name = name.strip()
    ext = Path(file.filename or "").suffix.lower()
    if not re.fullmatch(r"[\w\- ]{1,40}", name):
        return JSONResponse({"success": False, "error": "Tên giọng chỉ gồm chữ, số, khoảng trắng, - và _"}, status_code=400)
    if ext not in CLONE_EXTS:
        return JSONResponse({"success": False, "error": f"Định dạng phải là {', '.join(sorted(CLONE_EXTS))}"}, status_code=400)
    try:
        content = await read_limited(file.read, max_bytes=10 * 1024 * 1024)
    except UploadTooLarge:
        return JSONResponse({"success": False, "error": "Mẫu quá lớn (tối đa 10MB)"}, status_code=413)
    CLONE_DIR.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread((CLONE_DIR / f"{name}{ext}").write_bytes, content)
    try:
        return _with_current({"success": True, **await _tts_voices_call("POST")})
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)[:200]}, status_code=503)


@router.post("/api/settings/test-llm")
async def api_test_llm(body: KeyTest):
    import server
    from openai import AsyncOpenAI
    key = body.key_value or os.getenv("LOCAL_API_KEY")
    url = os.getenv("LOCAL_URL")
    if not key:
        return {"valid": False, "error": "No key provided"}
    try:
        from engine.server.llm_server import active_model_name
        client = AsyncOpenAI(api_key=key, base_url=url)
        await client.chat.completions.create(model=active_model_name() or server.LOCAL_MODEL, max_tokens=10, messages=[{"role": "user", "content": "Hi"}])
        return {"valid": True}
    except Exception as e:
        return {"valid": False, "error": str(e)[:200]}


@router.post("/api/settings/test-tts")
async def api_test_tts(body: KeyTest):
    import server
    import httpx
    key = body.key_value or os.getenv("TTS_LOCAL_KEY")
    if not key:
        return {"valid": False, "error": "No key provided"}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                server.TTS_LOCAL_URL,
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={"model": server.TTS_LOCAL_MODEL, "input": "test"},
            )
            if resp.status_code in (200, 201):
                return {"valid": True}
            elif resp.status_code == 401:
                return {"valid": False, "error": "Invalid API key"}
            else:
                return {"valid": False, "error": f"HTTP {resp.status_code}"}
    except Exception as e:
        return {"valid": False, "error": str(e)[:200]}


@router.post("/api/settings/reset-tokens")
async def api_reset_tokens():
    import server
    import time
    server._session_start = time.time()
    server._session_tokens = {"input": 0, "output": 0, "api_calls": 0, "tts_calls": 0}
    return {"success": True}


def _scan_agents() -> list[dict]:
    """Agent cards for the HUD and the dashboard Agents page."""
    agents_list = []
    try:
        from engine.prompts import catalog
        agents_catalog = catalog.agents()
        
        # Read guidance and descriptions from prompt/agents.md
        agents_md_path = Path(__file__).parent.parent.parent / "prompt" / "agents.md"
        agents_guidance: dict[str, str] = {}
        if agents_md_path.exists():
            for line in agents_md_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("- "):
                    parts = line[2:].split(":", 1)
                    if len(parts) == 2:
                        agents_guidance[parts[0].strip().lower()] = parts[1].strip()

        # Examples of prompt commands for each agent
        sample_queries: dict[str, str] = {
            "desktop": "mở notepad",
            "dream": "dọn dẹp bộ nhớ và chạy chu kỳ dream",
            "email": "kiểm tra email mới nhất trong Outlook",
            "goose": "mở giao diện Goose",
            "history": "xem lại lịch sử trò chuyện",
            "image": "nâng cấp độ phân giải ảnh bằng Upscayl",
            "media": "mở nhạc lofi trên Youtube",
            "notes": "ghi chú lại ý tưởng dự án",
            "office": "chỉnh sửa tệp báo cáo Word",
            "project": "kiểm tra sức khỏe dự án",
            "rag": "tóm tắt tài liệu đính kèm",
            "weather": "thời tiết Hà Nội hôm nay thế nào",
            "news": "tin tức nổi bật hôm nay",
            "market": "giá vàng SJC hôm nay",
            "shop": "so sánh máy giặt LG và Electrolux",
            "route": "chỉ đường từ nhà đến sân bay",
            "places": "quán cà phê gần đây",
            "cinema": "phim đang chiếu ở CGV",
            "games": "game miễn phí tuần này trên Epic",
            "lunar": "hôm nay âm lịch ngày bao nhiêu",
            "zodiac": "tử vi cung sư tử hôm nay",
            "web": "gợi ý món ăn hợp ngày mưa",
            "security": "quét cổng và kiểm tra an ninh mạng",
            "vision": "chụp màn hình hiện tại",
            "webcam": "mở camera xem trực tiếp",
            "win_control": "phóng to cửa sổ trình duyệt",
        }

        # Format agent key to beautiful Title Case (e.g. desktop -> Agent Desktop, win_control -> Agent Windows Control)
        name_overrides: dict[str, str] = {
            "desktop": "Agent Desktop",
            "win_control": "Agent Windows Control",
            "email": "Agent Email & Calendar",
            "rag": "Agent Document RAG",
            "goose": "Agent Goose",
            "office": "Agent Office Suite",
            "vision": "Agent Vision Screen",
            "webcam": "Agent Webcam Live",
            "security": "Agent Security Guard",
            "weather": "Agent Weather",
            "news": "Agent News",
            "market": "Agent Market",
            "shop": "Agent Shop",
            "route": "Agent Route",
            "places": "Agent Places",
            "cinema": "Agent Cinema",
            "games": "Agent Games",
            "lunar": "Agent Lunar Calendar",
            "zodiac": "Agent Zodiac",
            "web": "Agent Web Research",
            "project": "Agent Project Health",
            "notes": "Agent Notes Manager",
            "media": "Agent Media Stream",
            "image": "Agent Image Upscaler",
            "history": "Agent History Query",
            "dream": "Agent Dream Cycle",
        }

        from engine.orchestrator.registry import AGENT_REGISTRY
        for key, cat_data in agents_catalog.items():
            # nhiều agent tra cứu dùng chung agent_search.py nên liệt kê theo danh mục, không theo file
            module_file = AGENT_REGISTRY.get(key, {}).get("module", "").rsplit(".", 1)[-1]
            title_name = name_overrides.get(key, f"Agent {key.replace('_', ' ').title()}")
            desc = agents_guidance.get(key) or cat_data.get("description") or f"Tác nhân chuyên biệt xử lý {key}"
            agents_list.append({
                "id": key,
                "name": title_name,
                "file": f"{module_file}.py",
                "description": desc,
                "example": sample_queries.get(key, f"@{key}"),
                "tools": [t.get("name") for t in cat_data.get("tools", [])],
                "aliases": cat_data.get("aliases", []),
                # what the command bar actually accepts (fast_paths.resolve_mention)
                "mention": f"@{key}",
            })
        # Sort alphabetically by Agent Name
        agents_list.sort(key=lambda a: a["name"])
    except Exception as e:
        log.warning(f"Error building dynamic agents list: {e}")

    return agents_list


def _scan_catalog_files() -> dict:
    """Hooks, skills, prompts, commands, plugins read from the repo folders.

    Served by /api/settings/catalog when a dashboard page needs them — not on
    every /api/settings/status poll (it used to inline ~90KB there)."""
    # 1. Hooks (scan hooks/ directory)
    hooks_list = []
    try:
        hooks_dir = Path(__file__).parent.parent.parent / "hooks"
        if hooks_dir.exists():
            for f in sorted(hooks_dir.glob("*.py")):
                if f.name != "__init__.py":
                    desc = ""
                    events = []
                    text = f.read_text(encoding="utf-8", errors="ignore")
                    desc_match = re.search(r'__description__\s*=\s*["\']([^"\']+)["\']', text)
                    if desc_match:
                        desc = desc_match.group(1)
                    else:
                        doc_match = re.search(r'"""(.*?)"""', text, re.DOTALL)
                        if doc_match:
                            desc = doc_match.group(1).strip().splitlines()[0]
                    for ev in ["on_startup", "on_shutdown", "on_message_receive", "on_response_generate"]:
                        if f"def {ev}(" in text or f"'{ev}'" in text or f'"{ev}"' in text:
                            events.append(ev)
                    hooks_list.append({
                        "name": f.stem,
                        "file": f.name,
                        "description": desc or f"Hook xử lý sự kiện hệ thống ({f.stem})",
                        "events": events or ["on_message_receive"],
                        "runtime": "python",
                        "active": True,
                        "file_path": f"hooks/{f.name}",
                    })
        hooks_list.sort(key=lambda x: x["name"])
    except Exception as e:
        log.warning(f"Error building dynamic hooks list: {e}")

    # 2. Skills (scan skills/ directory)
    skills_list = []
    try:
        skills_dir = Path(__file__).parent.parent.parent / "skills"
        if skills_dir.exists():
            for skill_folder in sorted(skills_dir.iterdir()):
                if skill_folder.is_dir() and not skill_folder.name.startswith((".", "_")):
                    name = skill_folder.name
                    desc = ""
                    category = "general"
                    tags = []
                    skill_files = list(skill_folder.glob("*.md"))
                    if skill_files:
                        target_file = next((f for f in skill_files if f.name.upper() == "SKILL.MD"), skill_files[0])
                        txt = target_file.read_text(encoding="utf-8", errors="ignore")
                        if txt.startswith("---"):
                            fm_parts = txt.split("---", 2)
                            if len(fm_parts) >= 3:
                                for l in fm_parts[1].strip().splitlines():
                                    if l.startswith("name:"):
                                        name = l.split(":", 1)[1].strip()
                                    elif l.startswith("description:"):
                                        desc = l.split(":", 1)[1].strip()
                                    elif l.startswith("category:"):
                                        category = l.split(":", 1)[1].strip()
                        if not desc:
                            for l in txt.splitlines():
                                l = l.strip()
                                if l.startswith("# "):
                                    name = l[2:].strip()
                                elif l.startswith("## Mô tả") or l.startswith("## Description"):
                                    continue
                                elif l and not l.startswith("#") and not desc:
                                    desc = l
                        skills_list.append({
                            "name": name,
                            "folder": skill_folder.name,
                            "description": desc or f"Kỹ năng tự động hóa {name}",
                            "category": category,
                            "tags": tags or [skill_folder.name],
                            "file_path": f"skills/{skill_folder.name}/{target_file.name}",
                        })
                    else:
                        skills_list.append({
                            "name": name,
                            "folder": skill_folder.name,
                            "description": f"Kỹ năng {name}",
                            "category": "general",
                            "tags": [skill_folder.name],
                            "file_path": f"skills/{skill_folder.name}",
                        })
        skills_list.sort(key=lambda x: x["name"])
    except Exception as e:
        log.warning(f"Error scanning skills directory: {e}")

    # 3. Prompts (scan prompt/ directory)
    prompts_list = []
    try:
        prompts_dir = Path(__file__).parent.parent.parent / "prompt"
        if prompts_dir.exists():
            for pf in sorted(prompts_dir.glob("*.md")):
                content = pf.read_text(encoding="utf-8", errors="ignore")
                lines = content.strip().splitlines()
                desc = ""
                for l in lines:
                    l = l.strip()
                    if l.startswith("#"):
                        desc = l.lstrip("#").strip()
                        break
                    elif l and not desc:
                        desc = l[:120]
                        break
                prompts_list.append({
                    "id": pf.stem,
                    "name": pf.name,
                    "title": pf.stem.replace("_", " ").title(),
                    "description": desc or f"Prompt mẫu {pf.name}",
                    "size_bytes": len(content.encode("utf-8")),
                    "lines_count": len(lines),
                    "file_path": f"prompt/{pf.name}",
                    "content": content,
                })
        prompts_list.sort(key=lambda x: x["name"])
    except Exception as e:
        log.warning(f"Error scanning prompt directory: {e}")

    # 4. Commands (scan commands/ directory)
    commands_list = []
    try:
        commands_dir = Path(__file__).parent.parent.parent / "commands"
        if commands_dir.exists():
            for cf in sorted(commands_dir.glob("*.md")):
                content = cf.read_text(encoding="utf-8", errors="ignore")
                name = cf.stem
                desc = ""
                usage = f"/{cf.stem}"
                category = "general"
                tags = []
                if content.startswith("---"):
                    parts = content.split("---", 2)
                    if len(parts) >= 3:
                        for l in parts[1].strip().splitlines():
                            if l.startswith("name:"):
                                name = l.split(":", 1)[1].strip()
                            elif l.startswith("description:"):
                                desc = l.split(":", 1)[1].strip()
                            elif l.startswith("usage:"):
                                usage = l.split(":", 1)[1].strip()
                            elif l.startswith("category:"):
                                category = l.split(":", 1)[1].strip()
                if not desc:
                    for l in content.splitlines():
                        if l.startswith("# "):
                            desc = l[2:].strip()
                            break
                commands_list.append({
                    "name": name,
                    "file": cf.name,
                    "description": desc or f"Lệnh điều khiển {name}",
                    "usage": usage or f"/{name}",
                    "category": category,
                    "tags": tags,
                    "file_path": f"commands/{cf.name}",
                })
        commands_list.sort(key=lambda x: x["name"])
    except Exception as e:
        log.warning(f"Error scanning commands directory: {e}")

    # 5. Plugins (scan plugins/ directory)
    plugins_list = []
    try:
        plugins_dir = Path(__file__).parent.parent.parent / "plugins"
        if plugins_dir.exists():
            for f in sorted(plugins_dir.glob("*.py")):
                if f.name != "__init__.py":
                    desc = ""
                    txt = f.read_text(encoding="utf-8", errors="ignore")
                    desc_match = re.search(r'__description__\s*=\s*["\']([^"\']+)["\']', txt)
                    if desc_match:
                        desc = desc_match.group(1)
                    else:
                        doc_match = re.search(r'"""(.*?)"""', txt, re.DOTALL)
                        if doc_match:
                            desc = doc_match.group(1).strip().splitlines()[0]
                    plugins_list.append({
                        "name": f.stem,
                        "file": f.name,
                        "description": desc or f"Plugin mở rộng hệ thống ({f.stem})",
                        "runtime": "python",
                        "active": True,
                        "file_path": f"plugins/{f.name}",
                    })
        plugins_list.sort(key=lambda x: x["name"])
    except Exception as e:
        log.warning(f"Error scanning plugins directory: {e}")

    return {"hooks": hooks_list, "skills": skills_list, "prompts": prompts_list,
            "commands": commands_list, "plugins": plugins_list}


_SECRET_FLAG_RE = re.compile(r"(?i)(key|token|secret|passw|auth)")
_SECRET_VALUE_RE = re.compile(r"(?i)^(sk|ctx7sk|ghp|gho|xox[abp]|hf)[-_]|^[A-Za-z0-9_\-]{32,}$")


def _redact_args(args) -> list[str]:
    """MCP args for display: keeps flags/paths, masks the value after a secret-looking
    flag (`--api-key X`, `--token=X`) and anything shaped like a raw key."""
    out: list[str] = []
    hide_next = False
    for raw in args or []:
        arg = str(raw)
        if hide_next:
            out.append("••••")
            hide_next = False
        elif arg.startswith("-") and _SECRET_FLAG_RE.search(arg.split("=", 1)[0]):
            if "=" in arg:
                out.append(arg.split("=", 1)[0] + "=••••")
            else:
                out.append(arg)
                hide_next = True
        elif _SECRET_VALUE_RE.search(arg):
            out.append("••••")
        else:
            out.append(arg)
    return out


def _mcp_server_views(hub_status: dict) -> list[dict]:
    """One row per MCP server: config entries plus hub-only ones, with the hub's live
    status. Never args/env/headers — they carry API keys."""
    from engine.server.mcp_server import read_config
    try:
        cfg = read_config()
    except Exception as e:
        log.warning(f"Error reading MCP config: {e}")
        cfg = {}
    views: list[dict] = []
    for name, entry in (cfg.get("mcpServers") or {}).items():
        enabled = bool(entry.get("enabled", True))
        views.append({
            "name": name,
            "type": entry.get("type", "stdio"),
            "enabled": enabled,
            "status": hub_status.get(name, "disconnected") if enabled else "disabled",
            "command": entry.get("command") or "",
            "args": _redact_args(entry.get("args")),
        })
    known = {v["name"] for v in views}
    for name, status in hub_status.items():
        if name not in known:
            views.append({"name": name, "type": "stdio", "enabled": True, "status": status, "command": ""})
    return views


@router.get("/api/settings/status")
async def api_settings_status(apps: bool = False):
    import server
    await asyncio.to_thread(server._update_session_tokens_from_log)
    _, env_dict = server._read_env()
    l_key = env_dict.get("LOCAL_API_KEY").strip()
    l_url = env_dict.get("LOCAL_URL").strip()
    llm_ok = bool(l_key) and bool(l_url)
    tts_ok = bool(env_dict.get("TTS_LOCAL_URL").strip())
    
    memory_count = 0
    try:
        from engine.core.learning import get_learning_engine
        memory_count = get_learning_engine().get_stats()["total_learnings"]
    except Exception: pass

    messages_count = 0
    conversation_turn_count = 0
    task_count = 0
    try:
        from engine.core.memory import _get_db
        conn = _get_db()
        messages_count = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        conversation_turn_count = messages_count // 2
        task_count = conn.execute("SELECT COUNT(*) FROM tasks WHERE status != 'completed'").fetchone()[0]
        conn.close()
    except Exception: pass

    skill_count = 0
    command_count = 0
    try:
        from engine.tools.skill_manager import get_skill_manager
        sm = get_skill_manager()
        skill_count = sm.get_stats()["total_skills"]
        command_count = sm.get_stats()["total_commands"]
    except Exception:
        pass

    open_apps = []
    if apps:
        try:
            from engine.tools.screen import get_active_windows
            wins = await get_active_windows()
            seen = set()
            skip = {"explorer", "svchost", "taskhostw", "runtimebroker", "jarvis", "python", "conhost", "applicationframehost", "shellexperiencehost"}
            for w in wins:
                a = w["app"].lower()
                if a not in seen and a not in skip:
                    seen.add(a)
                    open_apps.append(w["app"])
        except Exception:
            pass

    mcp_servers = {}
    mcp_connected = 0
    mcp_total = 0
    try:
        from engine.server.mcp_server import get_mcp_hub
        hub = get_mcp_hub()
        mcp_stats = hub.get_stats()
        mcp_servers = mcp_stats.get("servers", {})
        mcp_connected = mcp_stats.get("connected", 0)
        mcp_total = mcp_stats.get("total_servers", 0)
    except Exception:
        pass

    hooks_loaded = 0
    plugins_loaded = 0
    try:
        from engine.tools.load_hook import HookLoader
        hooks_loaded = len(HookLoader.get_instance()._hooks)
    except Exception:
        pass
    try:
        from engine.tools.load_plugin import PluginLoader
        plugins_loaded = len(PluginLoader.get_instance()._plugins)
    except Exception:
        pass

    system = {}
    try:
        import psutil
        ram = psutil.virtual_memory()
        cpu_pct = psutil.cpu_percent(interval=None)
        system["ram_percent"] = round(ram.percent, 1)
        system["ram_used_gb"] = round(ram.used / (1024**3), 1)
        system["ram_total_gb"] = round(ram.total / (1024**3), 1)
        system["cpu_percent"] = cpu_pct
    except Exception:
        pass

    gpus = []
    perf_entries = []
    import subprocess as _sp
    import json as _json
    try:
        result = await asyncio.to_thread(
            _sp.run,
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_PerfFormattedData_GPUPerformanceCounters_GPUAdapterMemory | Select-Object Name, DedicatedUsage, SharedUsage | ConvertTo-Json"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            raw = _json.loads(result.stdout)
            perf_entries = raw if isinstance(raw, list) else [raw]
    except Exception:
        pass

    try:
        result = await asyncio.to_thread(
            _sp.run,
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_VideoController | Select-Object Name, AdapterRAM | ConvertTo-Json"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            raw = _json.loads(result.stdout)
            entries = raw if isinstance(raw, list) else [raw]
            _1MB = 1024 * 1024
            active_perf = [p for p in perf_entries if (p.get("DedicatedUsage") or 0) + (p.get("SharedUsage") or 0) >= _1MB]
            sorted_perf = sorted(active_perf, key=lambda p: (-(p.get("DedicatedUsage") or 0), -(p.get("SharedUsage") or 0)))
            for i, g in enumerate(entries):
                name = g.get("Name", "Unknown GPU") or "Unknown GPU"
                ram_bytes = g.get("AdapterRAM") or 0
                info = {"name": name, "vram_total_mb": round(ram_bytes / (1024**2), 0) if ram_bytes else 0}
                if i < len(sorted_perf):
                    ded = sorted_perf[i].get("DedicatedUsage") or 0
                    sha = sorted_perf[i].get("SharedUsage") or 0
                    info["mem_used_mb"] = round((ded + sha) / (1024**2), 1)
                gpus.append(info)
    except Exception:
        pass

    if gpus:
        try:
            result = await asyncio.to_thread(
                _sp.run,
                ["nvidia-smi", "--query-gpu=index,name,utilization.gpu,memory.used,memory.total,temperature.gpu",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                for line in result.stdout.strip().split("\n"):
                    parts = [p.strip() for p in line.split(",")]
                    if len(parts) >= 6:
                        nv_name = parts[1].lower()
                        for g in gpus:
                            if nv_name in g["name"].lower() or g["name"].lower() in nv_name:
                                g["util_percent"] = int(parts[2])
                                g["mem_used_mb"] = int(parts[3])
                                g["mem_total_mb"] = int(parts[4])
                                g["temp_c"] = int(parts[5])
                                break
        except Exception:
            pass

    npus = []
    try:
        result = await asyncio.to_thread(
            _sp.run,
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_PnPEntity | Select-Object Name | ConvertTo-Json"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            raw = _json.loads(result.stdout)
            entries = raw if isinstance(raw, list) else [raw]
            import re as _re
            for e in entries:
                n = e.get("Name", "") or ""
                if _re.search(r'(?i)\b(npu|neural|ai\s*(boost|engine|accelerator|processor|unit)|intelligence)\b', n):
                    if n not in npus:
                        npus.append(n)
    except Exception:
        pass

    system["gpus"] = gpus
    system["npus"] = npus

    agents_list = await asyncio.to_thread(_scan_agents)

    return {
        "intelligence_core_ok": llm_ok,
        "server_engine_ok": True,
        "llm_server_ok": llm_ok,
        "tts_server_ok": tts_ok,
        "session_active": server._active_voice_connections > 0,
        "memory_count": memory_count,
        "messages_count": messages_count,
        "conversation_turn_count": conversation_turn_count,
        "task_count": task_count,
        "server_port": 8340,
        "uptime_seconds": int(time.time() - server._session_start),
        "skill_count": skill_count,
        "command_count": command_count,
        "hooks_loaded": hooks_loaded,
        "env_keys_set": {
            "llama": llm_ok,
            "fish_audio": tts_ok,
            "fish_voice_id": bool((env_dict.get("TTS_LOCAL_MODEL") or "").strip()),
            "user_name": env_dict.get("USER_NAME"),
        },
        "open_apps": open_apps,
        "mcp_total": mcp_total,
        "mcp_connected": mcp_connected,
        "mcp_servers": mcp_servers,
        "plugins_loaded": plugins_loaded,
        "system": system,
        "agents": agents_list,
        "agents_count": len(agents_list),
        # read-only facts for the dashboard (switching engine/voice stays manual in .env)
        "runtime": {
            "llm_model": (env_dict.get("LOCAL_MODEL") or "").strip(),
            "embed_model": (env_dict.get("LOCAL_EMBED_MODEL") or "").strip(),
            "tts_engine": _active_tts_engine(),
            "vieneu_voice": (env_dict.get("VIENEU_VOICE_ID") or "").strip(),
            "edge_voice": (env_dict.get("TTS_LOCAL_MODEL") or "").strip(),
        },
        "session_tokens": {
            "input": server._session_tokens["input"],
            "output": server._session_tokens["output"],
            "total": server._session_tokens["input"] + server._session_tokens["output"]
        }
    }


@router.get("/api/settings/preferences")
async def api_get_preferences():
    import server
    _, env_dict = server._read_env()
    return {
        "user_name": env_dict.get("USER_NAME"),
        "honorific": env_dict.get("HONORIFIC"),
        "calendar_accounts": env_dict.get("CALENDAR_ACCOUNTS"),
    }


@router.post("/api/settings/preferences")
async def api_save_preferences(body: PreferencesUpdate):
    import server
    server._write_env_key("USER_NAME", body.user_name)
    server._write_env_key("HONORIFIC", body.honorific)
    os.environ["USER_NAME"] = body.user_name  # áp dụng ngay, không cần khởi động lại
    os.environ["HONORIFIC"] = body.honorific
    server._write_env_key("CALENDAR_ACCOUNTS", body.calendar_accounts)
    return {"success": True}


@router.post("/api/prompts/save")
async def api_prompt_save(body: PromptSave):
    """Overwrite an existing prompt/<id>.md from the dashboard. Only existing files,
    plain names (no paths); the in-memory template cache is dropped so it applies now."""
    if not _PROMPT_ID_RE.match(body.id or ""):
        return {"success": False, "error": "Tên prompt không hợp lệ"}
    target = PROMPT_DIR / f"{body.id}.md"
    if not target.is_file():
        return {"success": False, "error": f"Không có prompt {body.id}.md"}
    data = body.content.encode("utf-8")
    if len(data) > _PROMPT_MAX_BYTES:
        return {"success": False, "error": "Prompt quá lớn (tối đa 256KB)"}
    try:
        target.write_bytes(data)
    except OSError as e:
        return {"success": False, "error": str(e)}
    try:
        from engine import prompts as _prompts
        _prompts._CACHE.pop(body.id, None)
    except Exception:
        pass
    return {"success": True}


@router.get("/api/system/readme")
async def api_get_readme():
    """Trả về nội dung README.md gốc để hiển thị trong tab Thông tin của Settings Dashboard."""
    readme_path = Path(__file__).parent.parent.parent / "README.md"
    if readme_path.exists():
        content = readme_path.read_text(encoding="utf-8")
        return {"success": True, "content": content}
    return {"success": False, "error": "README.md not found", "content": ""}


@router.get("/api/mcp/servers")
async def api_get_mcp_servers():
    """MCP servers from config/mcp_config.json with the hub's live status (no args/env: they hold keys)."""
    try:
        from engine.server.mcp_server import get_mcp_hub
        try:
            hub_status = get_mcp_hub().get_stats().get("servers", {})
        except Exception:
            hub_status = {}
        servers = _mcp_server_views(hub_status)
        return {
            "success": True,
            "total": len(servers),
            "connected": sum(1 for s in servers if s["status"] == "connected"),
            "servers": servers,
        }
    except Exception as e:
        return {"success": False, "error": str(e), "servers": []}


class McpToggleBody(BaseModel):
    enabled: bool


class McpAddBody(BaseModel):
    name: str
    type: str = "stdio"
    command: str | None = None
    args: list[str] = []
    url: str | None = None
    env: dict[str, str] | None = None
    headers: dict[str, str] | None = None
    enabled: bool = True


def _from_this_machine(request: Request) -> bool:
    """Bật/tắt/thêm MCP server là chạy lệnh trên máy này: chỉ nhận từ loopback, không nhận từ LAN dù nằm trong danh sách IP cho phép."""
    import ipaddress
    try:
        return ipaddress.ip_address(request.client.host).is_loopback
    except (AttributeError, ValueError):
        return False


_MCP_FORBIDDEN = JSONResponse(
    {"success": False, "error": "Chỉ quản lý MCP được từ chính máy chạy JARVIS."}, status_code=403
)


@router.post("/api/mcp/servers/{name}/enabled")
async def api_mcp_set_enabled(name: str, body: McpToggleBody, request: Request):
    if not _from_this_machine(request):
        return _MCP_FORBIDDEN
    from engine.server.mcp_server import set_server_enabled
    try:
        status = await set_server_enabled(name, body.enabled)
    except KeyError:
        return JSONResponse({"success": False, "error": "Không có máy chủ MCP này."}, status_code=404)
    except Exception as e:
        log.warning(f"MCP toggle failed: {e}")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)
    return {"success": True, "status": status}


@router.post("/api/mcp/servers")
async def api_mcp_add_server(body: McpAddBody, request: Request):
    if not _from_this_machine(request):
        return _MCP_FORBIDDEN
    from engine.server.mcp_server import add_server_config
    try:
        await add_server_config(body.name, body.model_dump(exclude={"name"}))
    except ValueError as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=400)
    except FileExistsError:
        return JSONResponse({"success": False, "error": "Đã có máy chủ trùng tên."}, status_code=409)
    except Exception as e:
        log.warning(f"MCP add failed: {e}")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)
    return {"success": True}


@router.get("/api/graphfy")
async def api_graphfy():
    """Structure map generated from the code (engine/UIUX/graphfy.py)."""
    from engine.UIUX.graphfy import scan
    return {"success": True, **await asyncio.to_thread(scan, Path(__file__).resolve().parents[2])}


@router.get("/api/settings/catalog")
async def api_settings_catalog():
    """Agents/hooks/skills/prompts/commands/plugins for the dashboard pages — fetched when a page opens."""
    agents = await asyncio.to_thread(_scan_agents)
    files = await asyncio.to_thread(_scan_catalog_files)
    return {"success": True, "agents": agents, **files}


@router.get("/api/media/search")
async def api_media_search(q: str = "", source: str = "youtube"):
    if not q:
        return {"results": []}
    try:
        from engine.tools.media_search import search_media
        results = await search_media(q, source)
        return {"results": results, "query": q}
    except Exception as e:
        log.warning(f"Media search failed: {e}")
        return {"results": [], "query": q, "error": str(e)}


@router.get("/api/media/resolve")
async def api_media_resolve(url: str = ""):
    if not url:
        return {"error": "No URL"}
    import re
    embed_url = ""
    title = ""
    yt_match = re.search(r"(?:v=|youtu\.be/|/embed/)([a-zA-Z0-9_-]{11})", url)
    if yt_match:
        vid = yt_match.group(1)
        return {"embed_url": f"https://www.youtube.com/embed/{vid}", "title": title}
    # Chỉ YouTube được phát trong giao diện; trang phim (hhpanda) đã bỏ.
    return {"embed_url": embed_url, "title": title}


@router.get("/api/media/local/{path:path}")
async def api_media_local(path: str):
    import server
    try:
        file_path = resolve_file_under(server.MEDIA_LOCAL_DIR, path)
    except (FileNotFoundError, ValueError):
        return JSONResponse(status_code=404, content={"error": "File not found"})
    return FileResponse(str(file_path))


@router.get("/api/history")
async def api_history(limit: int = 100):
    try:
        from engine.core.memory import get_messages
        history = get_messages(limit)
        return {"success": True, "history": history}
    except Exception as e:
        return {"success": False, "error": str(e), "history": []}


@router.post("/api/restart")
async def api_restart(request: Request):
    """Ask the terminal supervisor to restart after graceful cleanup."""
    log.info("Restart requested — scheduling graceful shutdown")
    async def _restart():
        await asyncio.sleep(0.5)
        os.environ["JARVIS_RESTART_REQUESTED"] = "1"
        uvicorn_server = getattr(request.app.state, "uvicorn_server", None)
        if uvicorn_server is None:
            log.error("Restart requested but Uvicorn server instance is unavailable")
            return
        uvicorn_server.should_exit = True
    # Giữ tham chiếu: event loop chỉ giữ weak-ref tới task, task trần có thể bị GC trước khi chạy.
    task = asyncio.create_task(_restart())
    _pending_tasks.add(task)
    task.add_done_callback(_pending_tasks.discard)
    return {"status": "restarting"}


@router.post("/api/dream/run")
async def api_dream_run():
    """Kích hoạt ngay 1 chu kỳ Dream (tóm tắt/dọn dẹp hội thoại + Wiki cũ) để kiểm thử thủ công."""
    from engine.core.dream import trigger_dream_cycle_now
    trigger_dream_cycle_now()
    return {"status": "started"}


LOG_TAIL_BYTES = 512 * 1024  # file log có thể rất lớn: chỉ đọc phần đuôi
LOG_MAX_LINES = 2000


def _log_dir() -> Path:
    import server
    return server.LOG_DIR


def _tail_log(filename: str, lines: int) -> dict:
    """Last `lines` lines of a fixed log file under the log dir (the UI never sends a path, only which of the three)."""
    path = _log_dir() / filename
    if not path.exists():
        return {"success": False, "error": f"Không tìm thấy {filename}"}
    lines = max(1, min(lines, LOG_MAX_LINES))
    try:
        with open(path, "rb") as f:
            size = f.seek(0, os.SEEK_END)
            f.seek(max(0, size - LOG_TAIL_BYTES))
            raw = f.read()
        text = raw.decode("utf-8-sig", errors="replace")  # security_alerts.log is written as utf-8-sig
        return {"success": True, "logs": "\n".join(text.strip().splitlines()[-lines:])}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.get("/api/logs")
async def api_logs(lines: int = 300):
    return _tail_log("jarvis.log", lines)


@router.get("/api/logs/security")
async def api_logs_security(lines: int = 300):
    return _tail_log("security_alerts.log", lines)


@router.get("/api/logs/tts")
async def api_logs_tts(lines: int = 300):
    return _tail_log("stream_tts.log", lines)


@router.post("/api/upload")
async def api_upload(file: UploadFile = File(...)):
    try:
        from uuid import uuid4
        from engine.core.attachment_store import register_attachment

        try:
            max_bytes = max(1, int(os.getenv("JARVIS_UPLOAD_MAX_BYTES", str(25 * 1024 * 1024))))
        except ValueError:
            max_bytes = 25 * 1024 * 1024
        upload_dir = Path(__file__).parent.parent.parent / "data" / "uploads"
        upload_dir.mkdir(parents=True, exist_ok=True)
        content = await read_limited(file.read, max_bytes=max_bytes)
        original_name = Path(file.filename or "upload").name
        save_path = upload_dir / f"{uuid4().hex}{Path(original_name).suffix.lower()}"
        await asyncio.to_thread(save_path.write_bytes, content)
        attachment = await asyncio.to_thread(
            register_attachment,
            save_path,
            filename=original_name,
            mime_type=file.content_type,
            channel="webui",
        )
        log.info("Uploaded file: %s (%d bytes)", original_name, len(content))

        return {
            "success": True,
            "filename": original_name,
            "size": len(content),
            "attachment_id": attachment.attachment_id,
        }
    except UploadTooLarge as e:
        return JSONResponse(
            status_code=413,
            content={"success": False, "error": "File too large", "max_bytes": e.max_bytes},
        )
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.get("/api/command-bar/skills")
async def api_command_bar_skills():
    """Retrieve all loaded skills, commands, and plugins for frontend autocomplete suggestion."""
    try:
        from engine.tools.skill_manager import get_skill_manager
        sm = get_skill_manager()
        skills = [s.to_dict() for s in sm.skills.values() if s.enabled]
        commands = [c.to_dict() for c in sm.commands.values() if c.enabled]
        
        # Load plugins dynamically
        plugins = []
        try:
            from engine.tools.load_plugin import PluginLoader
            pm = PluginLoader.get_instance()
            discovered = pm.discover()
            for name in discovered:
                p_info = pm._plugins.get(name)
                plugins.append({
                    "name": name,
                    "description": p_info.description if p_info else f"Plugin: {name}",
                    "active": p_info.active if p_info else False,
                    "runtime": p_info.runtime if p_info else "python"
                })
        except Exception as pe:
            log.warning(f"Error loading plugins for autocomplete: {pe}")

        return {
            "success": True,
            "skills": skills,
            "commands": commands,
            "plugins": plugins
        }
    except Exception as e:
        log.error(f"Error in api_command_bar_skills: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


@router.get("/api/command-bar/context")
async def api_command_bar_context():
    """Retrieve agents list and workspace files for frontend autocomplete suggestion."""
    try:
        project_root = Path(__file__).parent.parent.parent
        files = []
        exclude_dirs = {".git", "node_modules", ".venv", "__pycache__", "dist", "data", "logs", "media"}
        exclude_exts = {".pyc", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".bin", ".tq", ".db"}
        
        # Traverse workspace directories to gather files
        for root, dirs, filenames in os.walk(project_root):
            # Prune directory search path
            dirs[:] = [d for d in dirs if d not in exclude_dirs and not d.startswith(".")]
            for filename in filenames:
                file_path = Path(root) / filename
                if file_path.suffix.lower() in exclude_exts:
                    continue
                try:
                    rel_path = file_path.relative_to(project_root)
                    files.append(str(rel_path).replace("\\", "/"))
                except ValueError:
                    continue
                if len(files) >= 50:
                    break
            if len(files) >= 50:
                break
                
        # Get agents and aliases from catalog (spec 2026-09-25)
        try:
            from engine.prompts import catalog
            agents = []
            for name, data in catalog.agents().items():
                agents.append(name)
                for a in data.get("aliases", []):
                    agents.append(a)
        except Exception as ae:
            log.warning(f"Error loading agents from catalog: {ae}")
            agents = ["desktop"]

        return {
            "success": True,
            "agents": sorted(list(set(agents))),
            "files": files
        }
    except Exception as e:
        log.error(f"Error in api_command_bar_context: {e}", exc_info=True)
        return {"success": False, "error": str(e)}



@router.post("/api/stt")
async def api_stt(file: UploadFile = File(...)):
    """REST endpoint nhận file audio WAV từ client để nhận diện giọng nói tiếng Việt."""
    try:
        try:
            max_bytes = max(1, int(os.getenv("JARVIS_STT_MAX_BYTES", str(20 * 1024 * 1024))))
        except ValueError:
            max_bytes = 20 * 1024 * 1024
        content = await read_limited(file.read, max_bytes=max_bytes)
        from engine.server.whisper_server import transcribe_audio
        text = await transcribe_audio(content)
        if isinstance(text, str) and text.startswith("ERROR:"):
            # transcribe_audio reports failure in-band. Reporting that string
            # as a success handed it to the frontend as the transcript, which
            # then sent "ERROR: Whisper busy..." upstream as the user's words.
            log.warning("STT failed: %s", text)
            return {"success": False, "error": text[len("ERROR:"):].strip()}
        return {"success": True, "text": text}
    except UploadTooLarge as e:
        return JSONResponse(
            status_code=413,
            content={"success": False, "error": "Audio too large", "max_bytes": e.max_bytes},
        )
    except Exception as e:
        log.error(f"Error in api_stt: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


@router.post("/api/agents/goose/launch")
async def api_launch_goose():
    """REST endpoint khởi chạy ứng dụng Goose Desktop."""
    try:
        from engine.agents.agent_goose import launch_goose_gui
        success = launch_goose_gui()
        return {"success": success}
    except Exception as e:
        log.error(f"Error launching Goose GUI: {e}")
        return {"success": False, "error": str(e)}

# -- Memory & Notes Management CRUD Endpoints --------------------------------
class NoteUpdateBody(BaseModel):
    id: str  # Dùng slug/string định danh cho Obsidian Note
    title: str
    content: str
    tags: str = ""

class LearningUpdateBody(BaseModel):
    id: int
    content: str
    type_name: str = "lesson"
    importance: int = 5


MemoryControlKind = Literal[
    "learning",
    "workflow",
    "outcome",
    "conversation",
]


class MemoryControlUpdateBody(BaseModel):
    kind: MemoryControlKind
    id: int
    values: dict[str, Any]


class MemoryControlDeleteBody(BaseModel):
    kind: MemoryControlKind
    id: int


class EvolutionUpdateBody(BaseModel):
    id: str
    content: str


@router.get("/api/evolution/list")
async def api_evolution_list(q: str = "", limit: int = 50, offset: int = 0):
    """Hai file tiến hóa (STYLE.md đang áp dụng, Evolution.md nhật ký) cho Settings → Bộ nhớ → Evolution."""
    from engine.core.evolution import list_evolution_files

    items = await asyncio.to_thread(list_evolution_files)
    needle = q.strip().lower()
    if needle:
        items = [i for i in items if needle in i["title"].lower() or needle in i["content"].lower()]
    return {"success": True, "items": items[offset:offset + limit], "total": len(items)}


@router.post("/api/evolution/update")
async def api_evolution_update(body: EvolutionUpdateBody):
    from engine.core.evolution import save_evolution_file

    result = await save_evolution_file(body.id, body.content)
    if result.get("code") == "unknown_id":
        return JSONResponse(result, status_code=404)
    return result


@router.get("/api/memory-control/summary")
async def api_memory_control_summary():
    try:
        from engine.core.learning import get_learning_engine
        from engine.core.memory import get_memory_control_counts

        learning_counts, memory_counts = await asyncio.gather(
            asyncio.to_thread(
                get_learning_engine().get_memory_control_counts
            ),
            asyncio.to_thread(get_memory_control_counts),
        )
        counts = {**learning_counts, **memory_counts}
        return {"success": True, "counts": counts}
    except Exception as exc:
        return JSONResponse(
            {"success": False, "error": str(exc)}, status_code=500
        )


@router.get("/api/memory-control/dependencies")
async def api_memory_control_dependencies(
    kind: MemoryControlKind, id: int
):
    try:
        if kind in {"learning", "workflow", "outcome"}:
            from engine.core.learning import get_learning_engine

            preview = await asyncio.to_thread(
                get_learning_engine().preview_learning_dependencies,
                kind,
                id,
            )
        else:
            from engine.core.memory import preview_memory_dependencies

            preview = await asyncio.to_thread(
                preview_memory_dependencies, kind, id
            )
        return {"success": True, "preview": preview}
    except LookupError:
        return JSONResponse(
            {"success": False, "code": "not_found"}, status_code=404
        )
    except ValueError as exc:
        return JSONResponse(
            {"success": False, "code": str(exc)}, status_code=400
        )


@router.post("/api/memory-control/update")
async def api_memory_control_update(body: MemoryControlUpdateBody):
    try:
        if body.kind in {"learning", "workflow", "outcome"}:
            from engine.core.learning import get_learning_engine

            success = await asyncio.to_thread(
                get_learning_engine().update_learning_control_record,
                body.kind,
                body.id,
                body.values,
            )
        else:
            from engine.core.memory import update_memory_control_record

            success = await asyncio.to_thread(
                update_memory_control_record,
                body.kind,
                body.id,
                body.values,
            )
        if not success:
            return JSONResponse(
                {"success": False, "code": "not_found"}, status_code=404
            )
        return {"success": True}
    except (ValueError, json.JSONDecodeError) as exc:
        return JSONResponse(
            {"success": False, "code": str(exc)}, status_code=400
        )


@router.post("/api/memory-control/delete")
async def api_memory_control_delete(body: MemoryControlDeleteBody):
    try:
        if body.kind in {"learning", "workflow", "outcome"}:
            from engine.core.learning import get_learning_engine

            success = await asyncio.to_thread(
                get_learning_engine().delete_learning_control_record,
                body.kind,
                body.id,
            )
        else:
            from engine.core.memory import delete_memory_control_record

            success = await asyncio.to_thread(
                delete_memory_control_record, body.kind, body.id
            )
        if not success:
            return JSONResponse(
                {"success": False, "code": "not_found"}, status_code=404
            )
        return {"success": True}
    except (ValueError, json.JSONDecodeError) as exc:
        return JSONResponse(
            {"success": False, "code": str(exc)}, status_code=400
        )


@router.get("/api/notes/list")
async def api_notes_list(limit: int = 100):
    try:
        from engine.tools.note_engine import get_note_engine
        notes = await asyncio.to_thread(get_note_engine().list_notes, limit)
        return {"success": True, "notes": notes}
    except Exception as e:
        return {"success": False, "error": str(e)}

@router.get("/api/notes/search")
async def api_notes_search(q: str = "", limit: int = 100):
    try:
        from engine.tools.note_engine import get_note_engine
        notes = await asyncio.to_thread(get_note_engine().search_notes, q, limit)
        return {"success": True, "notes": notes}
    except Exception as e:
        return {"success": False, "error": str(e)}

@router.post("/api/notes/update")
async def api_notes_update(body: NoteUpdateBody):
    try:
        from engine.tools.note_engine import get_note_engine
        success = await asyncio.to_thread(get_note_engine().update_note, body.id, body.content, body.title, body.tags)
        return {"success": success}
    except Exception as e:
        return {"success": False, "error": str(e)}

@router.delete("/api/notes/delete")
async def api_notes_delete(id: str):
    try:
        from engine.tools.note_engine import get_note_engine
        success = await asyncio.to_thread(get_note_engine().delete_note, id)
        return {"success": success}
    except Exception as e:
        return {"success": False, "error": str(e)}

@router.get("/api/learnings/list")
async def api_learnings_list(
    q: str = "", limit: int = 50, offset: int = 0
):
    try:
        from engine.core.learning import get_learning_engine
        page = await asyncio.to_thread(
            get_learning_engine().list_learning_records,
            q,
            limit,
            offset,
        )
        return {"success": True, "learnings": page["items"], **page}
    except Exception as e:
        return {"success": False, "error": str(e)}

@router.get("/api/learnings/search")
async def api_learnings_search(q: str = "", limit: int = 100):
    try:
        from engine.core.learning import get_learning_engine
        page = await asyncio.to_thread(
            get_learning_engine().list_learning_records, q, limit, 0
        )
        return {"success": True, "learnings": page["items"], **page}
    except Exception as e:
        return {"success": False, "error": str(e)}

@router.post("/api/learnings/update")
async def api_learnings_update(body: LearningUpdateBody):
    try:
        from engine.core.learning import get_learning_engine
        success = await asyncio.to_thread(
            get_learning_engine().update_learning_control_record,
            "learning",
            body.id,
            {
                "content": body.content,
                "type": body.type_name,
                "importance": body.importance,
            },
        )
        return {"success": success}
    except Exception as e:
        return {"success": False, "error": str(e)}

@router.delete("/api/learnings/delete")
async def api_learnings_delete(id: int):
    try:
        from engine.core.learning import get_learning_engine
        success = await asyncio.to_thread(
            get_learning_engine().delete_learning_control_record,
            "learning",
            id,
        )
        return {"success": success}
    except Exception as e:
        return {"success": False, "error": str(e)}


class EmbedRecomputeBody(BaseModel):
    id: int | None = None


@router.post("/api/learnings/reembed")
async def api_learnings_reembed(body: EmbedRecomputeBody):
    """Tính lại embedding cho một bản ghi học (id) hoặc tất cả (id=null)."""
    try:
        from engine.core.learning import get_learning_engine
        result = await asyncio.to_thread(
            get_learning_engine().reembed_learnings,
            body.id,
        )
        return {"success": "error" not in result, **result}  # embedder tắt: updated=0 + error → UI báo lỗi
    except Exception as e:
        return {"success": False, "error": str(e)}





# -- Learning System Sync Endpoints (validated workflows + agent outcomes) ------

@router.get("/api/workflows/list")
async def api_workflows_list(
    q: str = "", limit: int = 50, offset: int = 0
):
    try:
        from engine.core.learning import get_learning_engine
        page = await asyncio.to_thread(
            get_learning_engine().list_workflow_records,
            q,
            limit,
            offset,
        )
        return {"success": True, "workflows": page["items"], **page}
    except Exception as e:
        return {"success": False, "error": str(e)}

@router.delete("/api/workflows/delete")
async def api_workflows_delete(id: int):
    try:
        from engine.core.learning import get_learning_engine
        success = await asyncio.to_thread(
            get_learning_engine().delete_learning_control_record,
            "workflow",
            id,
        )
        return {"success": success}
    except Exception as e:
        return {"success": False, "error": str(e)}

@router.get("/api/outcomes/list")
async def api_outcomes_list(
    q: str = "",
    limit: int = 50,
    offset: int = 0,
    agent: str = "",
):
    try:
        from engine.core.learning import get_learning_engine
        page = await asyncio.to_thread(
            get_learning_engine().list_outcome_records,
            q,
            limit,
            offset,
            agent,
        )
        return {"success": True, "outcomes": page["items"], **page}
    except Exception as e:
        return {"success": False, "error": str(e)}


# -- Conversations History -----------------------------------------------------
@router.get("/api/conversations")
async def api_conversations(
    q: str = "", limit: int = 50, offset: int = 0
):
    try:
        from engine.core.memory import list_conversation_records
        page = await asyncio.to_thread(
            list_conversation_records, q, limit, offset
        )
        return {
            "success": True,
            "conversations": page["items"],
            **page,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

def _session_row(row: dict) -> dict:
    """Gắn nhãn nguồn; session_id rỗng (tin cũ trước khi có phiên) hiện là 'legacy'."""
    sid = row["session_id"] or ""
    row["source"] = "web" if sid.startswith("web-") else "telegram" if sid.startswith("tg-") else "legacy"
    row["session_id"] = sid or "legacy"
    return row


@router.get("/api/conversations/sessions")
async def api_conversations_sessions(limit: int = 50):
    try:
        from engine.core.memory import _get_db
        def _fetch():
            conn = _get_db()
            try:
                rows = conn.execute(
                    "SELECT session_id, COUNT(*) as msg_count, MIN(created_at) as started_at, MAX(created_at) as last_msg FROM messages GROUP BY session_id ORDER BY last_msg DESC LIMIT ?",
                    (limit,)
                ).fetchall()
                return [_session_row(dict(r)) for r in rows]
            finally:
                conn.close()
        sessions = await asyncio.to_thread(_fetch)
        return {"success": True, "sessions": sessions}
    except Exception as e:
        return {"success": False, "error": str(e)}

@router.get("/api/conversations/session/{session_id}")
async def api_conversations_session(session_id: str):
    try:
        from engine.core.memory import _get_db
        def _fetch(sid):
            conn = _get_db()
            try:
                rows = conn.execute(
                    "SELECT id, role, content, created_at FROM messages WHERE session_id=? ORDER BY id ASC",
                    (sid,)
                ).fetchall()
                return [dict(r) for r in rows]
            finally:
                conn.close()
        msgs = await asyncio.to_thread(_fetch, "" if session_id == "legacy" else session_id)
        return {"success": True, "messages": msgs}
    except Exception as e:
        return {"success": False, "error": str(e)}

class ConversationUpdateBody(BaseModel):
    id: int
    content: str
    type_name: str = "message"
    importance: int = 5

@router.post("/api/conversations/update")
async def api_conversations_update(body: ConversationUpdateBody):
    try:
        from engine.core.memory import _get_db
        conn = await asyncio.to_thread(_get_db)
        try:
            conn.execute("UPDATE messages SET content=? WHERE id=?", (body.content, body.id))
            conn.commit()
            return {"success": True}
        finally:
            conn.close()
    except Exception as e:
        return {"success": False, "error": str(e)}

@router.delete("/api/conversations/delete")
async def api_conversations_delete(id: int):
    try:
        from engine.core.memory import _get_db
        conn = await asyncio.to_thread(_get_db)
        try:
            conn.execute("DELETE FROM messages WHERE id=?", (id,))
            conn.commit()
            return {"success": True}
        finally:
            conn.close()
    except Exception as e:
        return {"success": False, "error": str(e)}
