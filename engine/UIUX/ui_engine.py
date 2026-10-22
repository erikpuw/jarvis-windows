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

class UserUpdateBody(BaseModel):
    id: str
    values: dict[str, Any]

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


@router.get("/api/reader")
async def read_article_api(url: str):
    """Bóc tách bài báo sạch (reader mode) phục vụ Reader Card trên WebUI."""
    clean_url = (url or "").strip()
    if not clean_url or not (clean_url.startswith("http://") or clean_url.startswith("https://")):
        return JSONResponse({"error": "URL không hợp lệ"}, status_code=400)
    try:
        from engine.tools.browser import browser
        from engine.tools.search_engine import get_source_label, _clean_article_content
        page_data = await browser.visit_article(clean_url, timeout_ms=12_000)
        if not page_data or not page_data.text_content:
            return JSONResponse({"error": "Không thể trích xuất nội dung bài viết từ trang này."}, status_code=404)
        clean_text = _clean_article_content(page_data.text_content)
        title = (page_data.title or "").strip() or "Bài báo"
        source = get_source_label(clean_url)
        return {
            "title": title,
            "source": source,
            "url": clean_url,
            "content": clean_text,
        }
    except Exception as exc:
        log.warning("Không thể đọc bài viết %s: %s", clean_url, exc)
        return JSONResponse({"error": str(exc)}, status_code=500)


@router.get("/api/product")
async def product_card_api(url: str):
    """Thẻ sản phẩm cho nút 👁 trong bảng giá: ảnh, tên, giá, nguồn (engine/tools/product_cards)."""
    clean_url = (url or "").strip()
    if not clean_url.startswith(("http://", "https://")):
        return JSONResponse({"error": "URL không hợp lệ"}, status_code=400)
    try:
        from engine.tools import product_cards
        card = await product_cards.load(clean_url)
    except Exception as exc:
        log.warning("Không thể lấy thẻ sản phẩm %s: %s", clean_url, exc)
        return JSONResponse({"error": str(exc)}, status_code=500)
    return card or JSONResponse({"error": "Không lấy được thông tin sản phẩm."}, status_code=404)



@router.get("/api/health/detailed")
async def health_detailed():
    """Chi tiết trạng thái của toàn bộ hệ thống (LLM, embed, TTS, RAG, DB)."""
    import os
    import time
    import httpx
    from engine.server.llm_server import check_llm_server, check_embed_server, check_stream_tts_server
    
    # 1. LLM (llama.cpp) Status
    llm_url = (os.getenv("LOCAL_URL") or "http://127.0.0.1:8080/v1").strip()
    llm_key = os.getenv("LOCAL_API_KEY", "").strip()
    llm_online, llm_msg, llm_port = check_llm_server(force=True)
    llm_status = "online" if llm_online else "chờ kết nối"
    llm_response_time = None
    if llm_online and llm_url:
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
        except Exception:
            llm_status = "chờ kết nối"

    # 1b. Embed Status (llama.cpp embed server)
    embed_url = (os.getenv("LOCAL_EMBED_URL") or "http://127.0.0.1:8081/v1").strip()
    embed_online, embed_msg, embed_port = check_embed_server(force=True)
    embed_status = "online" if embed_online else "chờ kết nối"

    # 1c. stream_TTS Status (port 8082)
    tts_stream_url = (os.getenv("TTS_STREAM_URL") or "http://127.0.0.1:8082").strip()
    stream_tts_online, stream_tts_msg, stream_tts_port = check_stream_tts_server(force=True)
    stream_tts_status = "online" if stream_tts_online else "chờ kết nối"

    # 4. RAG Status
    rag_enabled = False
    rag_chunks = 0
    rag_files_count = 0
    try:
        from engine.core.rag_engine import get_rag_engine
        rag = get_rag_engine()
        if embed_online:
            try:
                from engine.server.llm_server import get_embed_client
                embed_cl = get_embed_client()
                if embed_cl:
                    await rag.try_self_heal(embed_cl)
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
            "port": llm_port,
            "message": llm_msg,
            "url": llm_url,
            "response_time_ms": llm_response_time
        },
        "embed": {
            "status": embed_status,
            "port": embed_port,
            "message": embed_msg,
            "url": embed_url
        },
        "stream_tts": {
            "status": stream_tts_status,
            "port": stream_tts_port,
            "message": stream_tts_msg,
            "url": tts_stream_url
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
        from engine.core.rag_watcher import get_watch_stats, watch_folder
        from engine.server.llm_server import check_embed_server, get_embed_client

        rag = get_rag_engine()
        embed_online, embed_msg, embed_port = check_embed_server()
        if embed_online:
            try:
                embed_cl = get_embed_client()
                if embed_cl:
                    await rag.try_self_heal(embed_cl)
            except Exception as heal_err:
                log.warning(f"RAG self-heal check failed: {heal_err}")
        indexed_files = rag.get_indexed_files()
        watch_stats = get_watch_stats()

        return {
            "enabled": rag.enabled,
            "total_chunks": len(rag.chunks),
            "indexed_files": indexed_files,
            "watch_folder": str(watch_folder()),
            "watch_db": watch_stats,
            "embed_status": "online" if embed_online else "chờ kết nối",
            "embed_message": embed_msg,
        }
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.delete("/api/rag/document")
async def api_rag_remove_document(file_path: str):
    """Xóa một tệp khỏi kho: bỏ chỉ mục và chuyển tệp gốc vào thùng rác của vault (cùng logic "@rag xóa")."""
    try:
        from engine.rag.runner import remove_document
        removed, trashed = await remove_document(str(Path(file_path).resolve()))
        return {"success": True, "chunks_removed": removed, "trashed_to": str(trashed) if trashed else None}
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
    try:
        server._write_env_key(body.key_name, body.key_value)
    except ValueError as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=400)
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
    from engine.server.llm_server import check_stream_tts_server
    online, msg, port = check_stream_tts_server()
    if not online:
        return {"engine": "vieneu", "default": "", "voices": [], "status": "chờ kết nối", "message": msg}
    url = _tts_base_url() + ("/tts/voices" if method == "GET" else "/tts/voices/reload")
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.request(method, url)
    resp.raise_for_status()
    return resp.json()


def _with_current(data: dict, current_voice: str = None) -> dict:
    if current_voice:
        data["current"] = current_voice
    else:
        data["current"] = os.getenv("VIENEU_VOICE_ID", "").strip() or data.get("default", "")
    return data


@router.get("/api/tts/voices")
async def api_tts_voices(request: Request = None):
    try:
        user_voice = None
        if request is not None:
            from engine.UIUX.memory_lock import get_current_user
            user = get_current_user(request)
            if user and user.get("tts_voice_id"):
                user_voice = user["tts_voice_id"].strip()
        return _with_current(await _tts_voices_call("GET"), current_voice=user_voice)
    except Exception as e:
        return JSONResponse({"error": str(e)[:200]}, status_code=503)


@router.post("/api/tts/voice")
async def api_tts_select_voice(body: VoiceSelect, request: Request = None):
    import server
    voice = body.voice.strip()
    if not voice or len(voice) > 80 or any(c in voice for c in "\r\n="):
        return JSONResponse({"success": False, "error": "Invalid voice name"}, status_code=400)

    from engine.UIUX.memory_lock import get_current_user
    user = get_current_user(request) if request is not None else None

    from engine.core.memory import _get_db
    if user:
        uid = user["id"]
        role = user.get("role", "member")
        with _get_db() as conn:
            conn.execute("UPDATE users SET tts_voice_id = ? WHERE id = ?", (voice, uid))
            conn.commit()
        if role == "admin":
            os.environ["VIENEU_VOICE_ID"] = voice
            server._write_env_key("VIENEU_VOICE_ID", voice)
    else:
        # Fallback cuộc gọi nội bộ hoặc kiểm thử không kèm token
        os.environ["VIENEU_VOICE_ID"] = voice
        server._write_env_key("VIENEU_VOICE_ID", voice)
        try:
            with _get_db() as conn:
                conn.execute("UPDATE users SET tts_voice_id = ? WHERE id = 'admin'", (voice,))
                conn.commit()
        except Exception:
            pass

    return {"success": True, "voice": voice}


@router.post("/api/tts/voices/clone")
async def api_tts_clone_voice(name: str = Form(...), file: UploadFile = File(...), request: Request = None):
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
        user_voice = None
        if request is not None:
            from engine.UIUX.memory_lock import get_current_user
            user = get_current_user(request)
            if user and user.get("tts_voice_id"):
                user_voice = user["tts_voice_id"].strip()
        return _with_current({"success": True, **await _tts_voices_call("POST")}, current_voice=user_voice)
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)[:200]}, status_code=503)


@router.post("/api/settings/test-llm")
async def api_test_llm(body: KeyTest):
    import server
    from openai import AsyncOpenAI
    from engine.server.llm_server import check_llm_server

    is_online, msg, port = check_llm_server(force=True)
    if not is_online:
        return {"valid": False, "error": msg, "status": "chờ kết nối"}

    key = body.key_value or os.getenv("LOCAL_API_KEY")
    url = os.getenv("LOCAL_URL")
    if not key:
        return {"valid": False, "error": "No key provided"}
    try:
        from engine.server.llm_server import active_model_name
        client = AsyncOpenAI(api_key=key, base_url=url, max_retries=0)
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


def _scan_mentions(admin: bool = True) -> list[dict]:
    """Cards for the dashboard Mention page: exactly what @ accepts (engine/turn/entry: @rag + every registry tool)."""
    cards = []
    try:
        from engine.tools import registry
        from engine.turn.entry import mention_list
        for m in mention_list(user_id="admin" if admin else "user-member"):
            name = m["name"]
            spec = registry.get(name)
            usage = registry.usage(name)[len(name) + 1:] if spec else " <câu hỏi>"
            cards.append({
                "id": name,
                "name": name,
                "file": spec.fn.__module__.rsplit(".", 1)[-1] + ".py" if spec else "engine/rag",
                "description": m["description"],
                "example": f"@{name}{usage}",
                "mention": f"@{name}",
            })
    except Exception as e:
        log.warning(f"Error building mention list: {e}")
    return cards



def _scan_catalog_files(admin: bool = True) -> dict:
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

    # 2. Skills (scan skills/ directory recursively including skills/agents/<agent>)
    skills_list = []
    try:
        skills_dir = Path(__file__).parent.parent.parent / "skills"
        if skills_dir.exists():
            # một kỹ năng = một thư mục có SKILL.md, đúng quy tắc của skill_manager.scan_skills: thư mục chỉ có .md khác
            # (skills/self_evolution/STYLE.md, phong cách tự học) không phải kỹ năng — từng làm Skills đếm 3, Tổng quan 2
            folders_map = {mf.parent: mf for mf in skills_dir.rglob("*.md") if mf.name.lower() in ("skill.md", "skills.md")}

            for skill_folder, target_file in sorted(folders_map.items(), key=lambda item: item[0].as_posix()):
                if skill_folder == skills_dir:
                    continue
                name = skill_folder.name
                rel_parts = skill_folder.relative_to(skills_dir).parts
                category = rel_parts[0] if len(rel_parts) > 1 else "general"
                tags = list(rel_parts)
                desc = ""

                txt = target_file.read_text(encoding="utf-8", errors="ignore").lstrip("\ufeff")
                if txt.startswith("---"):
                    fm_parts = txt.split("---", 2)
                    if len(fm_parts) >= 3:
                        for l in fm_parts[1].strip().splitlines():
                            if l.startswith("title:"):
                                title_val = l.split(":", 1)[1].strip()
                                if title_val:
                                    name = title_val
                            elif l.startswith("name:") and name == skill_folder.name:
                                name = l.split(":", 1)[1].strip()
                            elif l.startswith("description:"):
                                desc = l.split(":", 1)[1].strip()
                            elif l.startswith("category:"):
                                category = l.split(":", 1)[1].strip()
                if not desc:
                    for l in txt.splitlines():
                        l = l.strip()
                        if l.startswith("# "):
                            if name == skill_folder.name:
                                name = l[2:].strip()
                        elif l.startswith("## Mô tả") or l.startswith("## Description"):
                            continue
                        elif l and not l.startswith("#") and not desc:
                            desc = l

                rel_file_path = target_file.relative_to(skills_dir.parent).as_posix()
                skills_list.append({
                    "name": name,
                    "folder": skill_folder.name,
                    "description": desc or f"Kỹ năng {name}",
                    "category": category,
                    "tags": tags,
                    "file_path": rel_file_path,
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

    # 4. Commands (sinh từ registry)
    commands_list = [{  # engine/server/slash_commands: /help, then /<any registry tool>
        "name": "help", "file": "slash_commands.py", "description": "Liệt kê mọi lệnh / đang dùng được.",
        "usage": "/help", "category": "tool", "tags": [], "file_path": "engine/server/slash_commands.py", "example": "/help",
    }]
    try:
        from engine.tools import registry
        for name in sorted(registry.names()):
            spec = registry.get(name)
            if spec and spec.admin_only and not admin:
                continue
            params = registry.params(name)
            mod_name = spec.fn.__module__.rsplit(".", 1)[-1] if spec and hasattr(spec, "fn") else "tool"
            commands_list.append({
                "name": name,
                "file": f"{name}.py",
                "description": registry.description(name),
                "usage": f"/{name}{' <' + ', '.join(params) + '>' if params else ''}",
                "category": "tool",
                "tags": [spec.kind] if spec else [],
                "file_path": f"engine/tools/catalog/{mod_name}.py",
                "example": registry.usage(name),
            })
    except Exception as e:
        log.warning(f"Error building commands list from registry: {e}")

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
    try:
        from engine.tools.skill_manager import get_skill_manager
        skill_count = get_skill_manager().get_stats()["total_skills"]
    except Exception:
        pass
    from engine.tools import registry
    command_count = len(registry.names()) + 1  # /help + /<tool> (engine/server/slash_commands)

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
        "mentions_count": len(registry.names()) + 1,  # @rag + @<tool> (engine/turn/entry)
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
async def api_get_preferences(request: Request):
    from engine.UIUX.memory_lock import get_current_user
    user = get_current_user(request) if request else None

    # Thành viên thông thường: đọc dữ liệu cô lập từ SQLite bảng users
    if user and user.get("role") != "admin":
        return {
            "user_name": user.get("display_name") or user.get("username") or "",
            "honorific": user.get("user_pronoun") or "Bạn",
            "calendar_accounts": user.get("calendar_accounts") or "",
        }

    # Quản trị viên: ưu tiên thông tin trong users nếu đã đặt, fallback về .env
    import server
    _, env_dict = server._read_env()
    if user and user.get("role") == "admin":
        from engine.core.memory import _get_db
        try:
            with _get_db() as conn:
                row = conn.execute("SELECT display_name, user_pronoun, calendar_accounts FROM users WHERE id = 'admin'").fetchone()
                if row and (row["display_name"] or row["user_pronoun"]):
                    return {
                        "user_name": row["display_name"] or env_dict.get("USER_NAME") or "Admin",
                        "honorific": row["user_pronoun"] or env_dict.get("HONORIFIC") or "sir",
                        "calendar_accounts": row["calendar_accounts"] or env_dict.get("CALENDAR_ACCOUNTS") or "auto",
                    }
        except Exception:
            pass

    return {
        "user_name": env_dict.get("USER_NAME"),
        "honorific": env_dict.get("HONORIFIC"),
        "calendar_accounts": env_dict.get("CALENDAR_ACCOUNTS"),
    }


@router.post("/api/settings/preferences")
async def api_save_preferences(body: PreferencesUpdate, request: Request):
    from engine.UIUX.memory_lock import get_current_user
    user = get_current_user(request) if request else None

    if user:
        uid = user["id"]
        from engine.core.memory import _get_db
        with _get_db() as conn:
            conn.execute(
                """
                UPDATE users
                SET display_name = ?, user_pronoun = ?, calendar_accounts = ?
                WHERE id = ?
                """,
                (body.user_name.strip(), body.honorific.strip(), body.calendar_accounts.strip(), uid)
            )
            conn.commit()

        # Chỉ có admin mới được phép đồng bộ và ghi đè .env hệ thống
        if user.get("role") == "admin":
            import server
            try:
                server._write_env_key("USER_NAME", body.user_name)
                server._write_env_key("HONORIFIC", body.honorific)
                server._write_env_key("CALENDAR_ACCOUNTS", body.calendar_accounts)
            except ValueError as e:
                return JSONResponse({"success": False, "error": str(e)}, status_code=400)
            os.environ["USER_NAME"] = body.user_name
            os.environ["HONORIFIC"] = body.honorific
        return {"success": True}

    import server
    try:
        server._write_env_key("USER_NAME", body.user_name)
        server._write_env_key("HONORIFIC", body.honorific)
        server._write_env_key("CALENDAR_ACCOUNTS", body.calendar_accounts)
    except ValueError as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=400)
    os.environ["USER_NAME"] = body.user_name
    os.environ["HONORIFIC"] = body.honorific
    return {"success": True}


@router.post("/api/prompts/save")
async def api_prompt_save(body: PromptSave, request: Request = None):
    """Overwrite an existing prompt/<id>.md from the dashboard. Only existing files,
    plain names (no paths); the in-memory template cache is dropped so it applies now."""
    from engine.UIUX.memory_lock import is_admin
    if not is_admin(request):
        return JSONResponse({"success": False, "error": "Chỉ có quyền Admin mới được phép đọc hoặc sửa Prompt hệ thống"}, status_code=403)
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
    from engine.UIUX.memory_lock import get_current_user
    current_user = get_current_user(request)
    if current_user and current_user.get("role") != "admin":
        return JSONResponse({"success": False, "error": "Chỉ Quản trị viên mới có quyền bật/tắt MCP server."}, status_code=403)
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
    from engine.UIUX.memory_lock import get_current_user
    current_user = get_current_user(request)
    if current_user and current_user.get("role") != "admin":
        return JSONResponse({"success": False, "error": "Chỉ Quản trị viên mới có quyền thêm MCP server."}, status_code=403)
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
async def api_settings_catalog(request: Request = None):
    """Mentions/hooks/skills/prompts/commands/plugins for the dashboard pages — fetched when a page opens."""
    from engine.UIUX.memory_lock import is_admin
    admin = is_admin(request)
    mentions = await asyncio.to_thread(_scan_mentions, admin)
    files = await asyncio.to_thread(_scan_catalog_files, admin)
    if not admin:
        files["prompts"] = []
    return {"success": True, "mentions": mentions, **files}


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
    response = FileResponse(str(file_path))
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@router.get("/api/outputs/{token}")
async def api_output_file(token: str, download: int = 0):
    """Phục vụ tệp tool vừa bàn giao (ảnh upscale, tài liệu Office).

    Token do ``output_delivery`` cấp khi bắn event ``output_file`` nên không có
    cách đoán đường dẫn tuỳ ý. ``download=1`` buộc trình duyệt lưu tệp
    (nút Tải về), mặc định xem inline (thẻ ảnh trong chat).
    """
    from engine.core.output_delivery import lookup_output_file

    file_path = lookup_output_file(token)
    if file_path is None or not file_path.is_file():
        return JSONResponse(status_code=404, content={"error": "File not found"})
    return FileResponse(
        str(file_path),
        filename=file_path.name if download else None,
        content_disposition_type="attachment" if download else "inline",
    )


@router.get("/api/history")
async def api_history(request: Request = None, limit: int = 100):
    try:
        from engine.core.memory import get_messages
        from engine.UIUX.memory_lock import get_current_user, is_admin
        user_id = None
        if request is not None:
            current_user = get_current_user(request)
            if not is_admin(request) and current_user:
                user_id = current_user.get("id")
        history = get_messages(limit, user_id=user_id or "")
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


PERF_LOG_MAX_BYTES = 5 * 1024 * 1024  # ~5 phút x 1 mẫu/giây chỉ vài trăm KB; quá ngưỡng thì bắt đầu file mới
PERF_LOG_MAX_BODY = 64 * 1024


@router.post("/api/perf-log")
async def api_perf_log(request: Request):
    """Mẫu số liệu của bảng ?debug=1 (frontend/src/perf-debug.ts), ghi nối vào logs/perf.jsonl: đọc lại sau một phiên trên iPhone
    (Safari không có DevTools). `reset` = trang vừa mở, bắt đầu file mới. Chỉ ghi, không đọc nên không nằm sau khóa Memory."""
    body = await request.body()
    if len(body) > PERF_LOG_MAX_BODY:
        return JSONResponse({"success": False, "error": "too large"}, status_code=413)
    try:
        data = json.loads(body)
        samples = [s for s in data.get("samples", []) if isinstance(s, dict)]
    except Exception:
        return JSONResponse({"success": False, "error": "bad json"}, status_code=400)
    path = _log_dir() / "perf.jsonl"
    fresh = data.get("reset") or (path.exists() and path.stat().st_size > PERF_LOG_MAX_BYTES)
    with open(path, "w" if fresh else "a", encoding="utf-8") as f:
        for s in samples:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")
    return {"success": True}


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
        from engine.tools import registry
        sm = get_skill_manager()
        skills = [s.to_dict() for s in sm.skills.values() if s.enabled]
        commands = [
            {
                "name": n,
                "description": registry.description(n),
                "usage": ", ".join(registry.params(n)),
                "enabled": True,
            }
            for n in registry.names()
        ]

        
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
async def api_command_bar_context(request: Request):
    """Gợi ý @ (chế độ + tool, sinh từ registry) và tệp trong workspace cho ô nhập."""
    try:
        from engine.turn.entry import mention_list
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
                
        from engine.UIUX.memory_lock import is_admin
        admin = is_admin(request)
        return {
            "success": True,
            "mentions": mention_list(user_id="admin" if admin else "user-member"),
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
        from engine.tools.catalog.system import launch_goose
        success = launch_goose()
        return {"success": success}

    except Exception as e:
        log.error(f"Error launching Goose GUI: {e}")
        return {"success": False, "error": str(e)}

# -- Memory Management CRUD Endpoints -----------------------------------------
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
    "correction",
]
# Kiểu bản ghi nằm trong learning engine; còn lại (conversation) ở engine.core.memory
_LEARNING_CONTROL_KINDS = {"learning", "workflow", "outcome", "correction"}


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
async def api_evolution_list(
    request: Request = None, q: str = "", limit: int = 50, offset: int = 0
):
    """Hai file tiến hóa (STYLE.md đang áp dụng, Evolution.md nhật ký) cho Settings → Bộ nhớ → Evolution."""
    from engine.core.evolution import list_evolution_files
    from engine.UIUX.memory_lock import get_current_user, is_admin

    user_id = None
    if request is not None:
        current_user = get_current_user(request)
        if not is_admin(request) and current_user:
            user_id = current_user.get("id")

    items = await asyncio.to_thread(list_evolution_files, user_id=user_id)
    needle = q.strip().lower()
    if needle:
        items = [i for i in items if needle in i["title"].lower() or needle in i["content"].lower()]
    return {"success": True, "items": items[offset:offset + limit], "total": len(items)}


@router.post("/api/evolution/update")
async def api_evolution_update(
    body: EvolutionUpdateBody, request: Request = None
):
    from engine.core.evolution import save_evolution_file
    from engine.UIUX.memory_lock import get_current_user, is_admin

    user_id = None
    if request is not None:
        current_user = get_current_user(request)
        if not is_admin(request) and current_user:
            user_id = current_user.get("id")

    result = await save_evolution_file(body.id, body.content, user_id=user_id)
    if result.get("code") == "unknown_id":
        return JSONResponse(result, status_code=404)
    return result


@router.get("/api/memory-control/summary")
async def api_memory_control_summary(request: Request = None):
    try:
        from engine.core.learning import get_learning_engine
        from engine.core.memory import get_memory_control_counts
        from engine.tools.gym_engine import count_all_gym_records
        from engine.UIUX.memory_lock import get_current_user, is_admin

        user_id = None
        if request is not None:
            current_user = get_current_user(request)
            if not is_admin(request) and current_user:
                user_id = current_user.get("id")

        learning_counts, memory_counts, gym_count = await asyncio.gather(
            asyncio.to_thread(
                get_learning_engine().get_memory_control_counts,
                user_id,
            ),
            asyncio.to_thread(get_memory_control_counts, user_id),
            asyncio.to_thread(count_all_gym_records, user_id),
        )
        user_count = 0
        if request is None or is_admin(request):
            try:
                from engine.core.memory import _get_db
                with _get_db() as conn:
                    user_count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            except Exception:
                pass

        counts = {**learning_counts, **memory_counts, "gym": gym_count, "user": user_count}
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
        if kind in _LEARNING_CONTROL_KINDS:
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
async def api_memory_control_update(
    body: MemoryControlUpdateBody, request: Request = None
):
    try:
        from engine.UIUX.memory_lock import get_current_user, is_admin

        if request is not None and not is_admin(request):
            current_user = get_current_user(request)
            if not current_user:
                return JSONResponse(
                    {"success": False, "error": "Unauthorized"}, status_code=401
                )
            user_id = current_user.get("id")
            if body.kind == "learning":
                from engine.core.learning import get_learning_engine

                conn = get_learning_engine()._get_learning_db()
                row = conn.execute(
                    "SELECT user_id FROM learnings WHERE id=?", (body.id,)
                ).fetchone()
                conn.close()
                if not row:
                    return JSONResponse(
                        {"success": False, "code": "not_found"}, status_code=404
                    )
                if row["user_id"] != user_id:
                    return JSONResponse(
                        {"success": False, "error": "Forbidden"}, status_code=403
                    )
            elif body.kind == "conversation":
                from engine.core.memory import _get_db

                with _get_db() as conn:
                    row = conn.execute(
                        "SELECT user_id FROM messages WHERE id=?", (body.id,)
                    ).fetchone()
                if not row:
                    return JSONResponse(
                        {"success": False, "code": "not_found"}, status_code=404
                    )
                if row["user_id"] != user_id:
                    return JSONResponse(
                        {"success": False, "error": "Forbidden"}, status_code=403
                    )
            else:
                return JSONResponse(
                    {"success": False, "error": "Forbidden: Admin access required"},
                    status_code=403,
                )

        if body.kind in _LEARNING_CONTROL_KINDS:
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
async def api_memory_control_delete(
    body: MemoryControlDeleteBody, request: Request = None
):
    try:
        from engine.UIUX.memory_lock import get_current_user, is_admin

        if request is not None and not is_admin(request):
            current_user = get_current_user(request)
            if not current_user:
                return JSONResponse(
                    {"success": False, "error": "Unauthorized"}, status_code=401
                )
            user_id = current_user.get("id")
            if body.kind == "learning":
                from engine.core.learning import get_learning_engine

                conn = get_learning_engine()._get_learning_db()
                row = conn.execute(
                    "SELECT user_id FROM learnings WHERE id=?", (body.id,)
                ).fetchone()
                conn.close()
                if not row:
                    return JSONResponse(
                        {"success": False, "code": "not_found"}, status_code=404
                    )
                if row["user_id"] != user_id:
                    return JSONResponse(
                        {"success": False, "error": "Forbidden"}, status_code=403
                    )
            elif body.kind == "conversation":
                from engine.core.memory import _get_db

                with _get_db() as conn:
                    row = conn.execute(
                        "SELECT user_id FROM messages WHERE id=?", (body.id,)
                    ).fetchone()
                if not row:
                    return JSONResponse(
                        {"success": False, "code": "not_found"}, status_code=404
                    )
                if row["user_id"] != user_id:
                    return JSONResponse(
                        {"success": False, "error": "Forbidden"}, status_code=403
                    )
            else:
                return JSONResponse(
                    {"success": False, "error": "Forbidden: Admin access required"},
                    status_code=403,
                )

        if body.kind in _LEARNING_CONTROL_KINDS:
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


@router.get("/api/learnings/list")
async def api_learnings_list(
    request: Request, q: str = "", limit: int = 50, offset: int = 0
):
    try:
        from engine.core.learning import get_learning_engine
        from engine.UIUX.memory_lock import get_current_user, is_admin

        user_id = None
        if request is not None:
            current_user = get_current_user(request)
            if not is_admin(request) and current_user:
                user_id = current_user.get("id")

        page = await asyncio.to_thread(
            get_learning_engine().list_learning_records,
            q,
            limit,
            offset,
            user_id=user_id,
        )
        return {"success": True, "learnings": page["items"], **page}
    except Exception as e:
        return {"success": False, "error": str(e)}

@router.get("/api/learnings/search")
async def api_learnings_search(request: Request, q: str = "", limit: int = 100):
    try:
        from engine.core.learning import get_learning_engine
        from engine.UIUX.memory_lock import get_current_user, is_admin

        user_id = None
        if request is not None:
            current_user = get_current_user(request)
            if not is_admin(request) and current_user:
                user_id = current_user.get("id")

        page = await asyncio.to_thread(
            get_learning_engine().list_learning_records, q, limit, 0, user_id=user_id
        )
        return {"success": True, "learnings": page["items"], **page}
    except Exception as e:
        return {"success": False, "error": str(e)}

@router.post("/api/learnings/update")
async def api_learnings_update(
    body: LearningUpdateBody, request: Request = None
):
    try:
        from engine.core.learning import get_learning_engine
        from engine.UIUX.memory_lock import get_current_user, is_admin

        if request is not None and not is_admin(request):
            current_user = get_current_user(request)
            if not current_user:
                return JSONResponse(
                    {"success": False, "error": "Unauthorized"}, status_code=401
                )
            conn = get_learning_engine()._get_learning_db()
            row = conn.execute(
                "SELECT user_id FROM learnings WHERE id=?", (body.id,)
            ).fetchone()
            conn.close()
            if not row:
                return JSONResponse(
                    {"success": False, "code": "not_found"}, status_code=404
                )
            if row["user_id"] != current_user.get("id"):
                return JSONResponse(
                    {"success": False, "error": "Forbidden"}, status_code=403
                )

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
async def api_learnings_delete(id: int, request: Request = None):
    try:
        from engine.core.learning import get_learning_engine
        from engine.UIUX.memory_lock import get_current_user, is_admin

        if request is not None and not is_admin(request):
            current_user = get_current_user(request)
            if not current_user:
                return JSONResponse(
                    {"success": False, "error": "Unauthorized"}, status_code=401
                )
            conn = get_learning_engine()._get_learning_db()
            row = conn.execute(
                "SELECT user_id FROM learnings WHERE id=?", (id,)
            ).fetchone()
            conn.close()
            if not row:
                return JSONResponse(
                    {"success": False, "code": "not_found"}, status_code=404
                )
            if row["user_id"] != current_user.get("id"):
                return JSONResponse(
                    {"success": False, "error": "Forbidden"}, status_code=403
                )

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
async def api_learnings_reembed(
    body: EmbedRecomputeBody, request: Request = None
):
    """Tính lại embedding cho một bản ghi học (id) hoặc tất cả (id=null)."""
    try:
        from engine.core.learning import get_learning_engine
        from engine.UIUX.memory_lock import get_current_user, is_admin

        if request is not None and not is_admin(request):
            if body.id is None:
                return JSONResponse(
                    {
                        "success": False,
                        "error": "Forbidden: Admin access required to reembed all",
                    },
                    status_code=403,
                )
            current_user = get_current_user(request)
            if not current_user:
                return JSONResponse(
                    {"success": False, "error": "Unauthorized"}, status_code=401
                )
            conn = get_learning_engine()._get_learning_db()
            row = conn.execute(
                "SELECT user_id FROM learnings WHERE id=?", (body.id,)
            ).fetchone()
            conn.close()
            if not row:
                return JSONResponse(
                    {"success": False, "code": "not_found"}, status_code=404
                )
            if row["user_id"] != current_user.get("id"):
                return JSONResponse(
                    {"success": False, "error": "Forbidden"}, status_code=403
                )

        result = await asyncio.to_thread(
            get_learning_engine().reembed_learnings,
            body.id,
        )
        return {"success": "error" not in result, **result}  # embedder tắt: updated=0 + error → UI báo lỗi
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.get("/api/gym/list")
async def api_gym_list(q: str = "", limit: int = 50, offset: int = 0, request: Request = None):
    """Danh sách bản ghi Gym Memory (hồ sơ, bài tập, cân nặng, thói quen)."""
    try:
        from engine.tools.gym_engine import list_all_gym_records
        from engine.UIUX.memory_lock import get_current_user, is_admin

        user_id = None
        if request is not None and hasattr(request, "headers"):
            current_user = get_current_user(request)
            if not is_admin(request) and current_user:
                user_id = current_user.get("id")

        res = await asyncio.to_thread(list_all_gym_records, q, limit, offset, user_id=user_id)
        return res
    except Exception as exc:
        return JSONResponse(
            {"success": False, "error": str(exc)}, status_code=500
        )


@router.delete("/api/gym/delete")
async def api_gym_delete(id: str = "", request: Request = None):
    """Xóa một bản ghi Gym Memory theo định dạng id (vd: profile_1, workout_2, weight_3, habit_4)."""
    try:
        from engine.tools.gym_engine import delete_gym_memory_item
        from engine.UIUX.memory_lock import get_current_user, is_admin

        user_id = None
        if request is not None and hasattr(request, "headers"):
            current_user = get_current_user(request)
            if not is_admin(request) and current_user:
                user_id = current_user.get("id")

        res = await asyncio.to_thread(delete_gym_memory_item, id, user_id=user_id)
        return {"success": bool(res)}
    except Exception as exc:
        return JSONResponse(
            {"success": False, "error": str(exc)}, status_code=500
        )


@router.get("/api/users/list")
async def api_users_list(request: Request, q: str = "", limit: int = 50, offset: int = 0):
    """Danh sách người dùng cho Quản trị viên trong Memory Control Center."""
    from engine.UIUX.memory_lock import is_admin
    if request is not None and not is_admin(request):
        return JSONResponse({"success": False, "error": "Chỉ Quản trị viên mới có quyền xem danh sách người dùng."}, status_code=403)
    try:
        from engine.core.memory import _get_db
        with _get_db() as conn:
            needle = q.strip().lower()
            if needle:
                rows = conn.execute(
                    "SELECT id, username, display_name, role, user_pronoun, ai_pronoun, telegram_chat_id, created_at FROM users "
                    "WHERE LOWER(username) LIKE ? OR LOWER(display_name) LIKE ? OR LOWER(id) LIKE ? OR LOWER(telegram_chat_id) LIKE ? "
                    "ORDER BY created_at DESC",
                    (f"%{needle}%", f"%{needle}%", f"%{needle}%", f"%{needle}%")
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, username, display_name, role, user_pronoun, ai_pronoun, telegram_chat_id, created_at FROM users "
                    "ORDER BY created_at DESC"
                ).fetchall()

        items = []
        for r in rows:
            uid = r["id"]
            role = r["role"] or "member"
            name = r["display_name"] or r["username"] or uid
            items.append({
                "id": uid,
                "type": "user",
                "username": r["username"],
                "display_name": r["display_name"] or "",
                "role": role,
                "user_pronoun": r["user_pronoun"] or "",
                "ai_pronoun": r["ai_pronoun"] or "",
                "telegram_chat_id": r["telegram_chat_id"] or "",
                "title": f"[{role.upper()}] {name} (@{r['username']})",
                "content": f"Tài khoản: {r['username']} | Tên: {name} | Vai trò: {role} | Telegram: {r['telegram_chat_id'] or 'Chưa liên kết'} | Xưng hô: {r['user_pronoun'] or 'N/A'} (JARVIS: {r['ai_pronoun'] or 'N/A'})",
                "created_at": r["created_at"],
            })
        return {
            "success": True,
            "users": items[offset:offset + limit],
            "items": items[offset:offset + limit],
            "total": len(items)
        }
    except Exception as exc:
        return JSONResponse({"success": False, "error": str(exc)}, status_code=500)


@router.delete("/api/users/delete")
async def api_users_delete(request: Request, id: str = ""):
    """Xóa một người dùng và toàn bộ dữ liệu cô lập (learnings, hội thoại, thư mục cá nhân)."""
    from engine.UIUX.memory_lock import is_admin
    if request is not None and not is_admin(request):
        return JSONResponse({"success": False, "error": "Chỉ Quản trị viên mới có quyền xóa người dùng."}, status_code=403)
    if not id:
        return JSONResponse({"success": False, "error": "Thiếu mã người dùng (id)."}, status_code=400)
    if id == "admin":
        return JSONResponse({"success": False, "error": "Không thể xóa tài khoản Quản trị viên (Admin)!"}, status_code=400)

    try:
        import shutil
        from pathlib import Path
        from engine.core.memory import _get_db

        with _get_db() as conn:
            user_row = conn.execute("SELECT id, username, role FROM users WHERE id = ?", (id,)).fetchone()
            if not user_row:
                return JSONResponse({"success": False, "error": "Không tìm thấy người dùng này."}, status_code=404)
            if user_row["role"] == "admin":
                return JSONResponse({"success": False, "error": "Không thể xóa tài khoản Quản trị viên!"}, status_code=400)

            conn.execute("DELETE FROM users WHERE id = ?", (id,))
            conn.execute("DELETE FROM user_tokens WHERE user_id = ?", (id,))
            conn.execute("DELETE FROM learnings WHERE user_id = ?", (id,))
            conn.execute("DELETE FROM messages WHERE user_id = ?", (id,))
            conn.commit()

        # Dọn sạch thư mục cá nhân data/users/{id}
        user_folder = Path(__file__).resolve().parents[2] / "data" / "users" / id
        if user_folder.is_dir():
            shutil.rmtree(user_folder, ignore_errors=True)

        return {"success": True, "message": f"Đã xóa người dùng {id} và toàn bộ dữ liệu thành công."}
    except Exception as exc:
        return JSONResponse({"success": False, "error": str(exc)}, status_code=500)


@router.post("/api/users/update")
async def api_users_update(request: Request, body: UserUpdateBody):
    """Cập nhật thông tin người dùng (chỉ dành cho Quản trị viên)."""
    from engine.UIUX.memory_lock import is_admin
    if request is not None and not is_admin(request):
        return JSONResponse({"success": False, "error": "Chỉ Quản trị viên mới có quyền cập nhật thông tin người dùng."}, status_code=403)

    uid = (body.id or "").strip()
    if not uid:
        return JSONResponse({"success": False, "error": "Thiếu mã người dùng (id)."}, status_code=400)

    values = body.values or {}
    if not values:
        return {"success": True, "message": "Không có dữ liệu thay đổi."}

    try:
        from engine.core.memory import _get_db
        with _get_db() as conn:
            user_row = conn.execute("SELECT id, username, role FROM users WHERE id = ?", (uid,)).fetchone()
            if not user_row:
                return JSONResponse({"success": False, "error": "Không tìm thấy người dùng này."}, status_code=404)

            updates = []
            params = []

            # 1. Đổi username
            if "username" in values:
                new_uname = str(values["username"] or "").strip()
                if not new_uname:
                    return JSONResponse({"success": False, "error": "Tên đăng nhập không được để trống."}, status_code=400)
                if uid == "admin" and new_uname != "admin":
                    return JSONResponse({"success": False, "error": "Không thể đổi tên đăng nhập của tài khoản admin gốc."}, status_code=400)
                existing = conn.execute("SELECT id FROM users WHERE username = ? AND id != ?", (new_uname, uid)).fetchone()
                if existing:
                    return JSONResponse({"success": False, "error": f"Tên đăng nhập '{new_uname}' đã tồn tại."}, status_code=400)
                updates.append("username = ?")
                params.append(new_uname)

            # 2. Đổi display_name, user_pronoun, ai_pronoun, tts_voice_id, telegram_chat_id
            for field in ["display_name", "user_pronoun", "ai_pronoun", "tts_voice_id", "telegram_chat_id"]:
                if field in values:
                    val = str(values[field] or "").strip()
                    updates.append(f"{field} = ?")
                    params.append(val)

            # 3. Đổi role
            if "role" in values:
                new_role = str(values["role"] or "").strip().lower()
                if new_role not in ("admin", "member"):
                    return JSONResponse({"success": False, "error": "Vai trò chỉ có thể là 'admin' hoặc 'member'."}, status_code=400)
                if uid == "admin" and new_role != "admin":
                    return JSONResponse({"success": False, "error": "Không thể hạ quyền của tài khoản admin gốc."}, status_code=400)
                updates.append("role = ?")
                params.append(new_role)

            if updates:
                params.append(uid)
                conn.execute(f"UPDATE users SET {', '.join(updates)} WHERE id = ?", params)
                conn.commit()

        return {"success": True, "message": f"Đã cập nhật thông tin người dùng {uid} thành công."}
    except Exception as exc:
        return JSONResponse({"success": False, "error": str(exc)}, status_code=500)



# -- Learning System Sync Endpoints (workflows + outcomes) ------------------------

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

@router.get("/api/corrections/list")
async def api_corrections_list(q: str = "", limit: int = 50, offset: int = 0):
    try:
        from engine.core.learning import get_learning_engine
        page = await asyncio.to_thread(get_learning_engine().list_correction_records, q, limit, offset)
        return {"success": True, "corrections": page["items"], **page}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.get("/api/outcomes/list")
async def api_outcomes_list(
    q: str = "",
    limit: int = 50,
    offset: int = 0,
    tool: str = "",
):
    try:
        from engine.core.learning import get_learning_engine
        page = await asyncio.to_thread(
            get_learning_engine().list_outcome_records,
            q,
            limit,
            offset,
            tool,
        )
        return {"success": True, "outcomes": page["items"], **page}
    except Exception as e:
        return {"success": False, "error": str(e)}


# -- Conversations History -----------------------------------------------------
@router.get("/api/conversations")
async def api_conversations(
    request: Request = None, q: str = "", limit: int = 50, offset: int = 0
):
    try:
        from engine.core.memory import list_conversation_records
        from engine.UIUX.memory_lock import get_current_user, is_admin

        user_id = None
        if request is not None:
            current_user = get_current_user(request)
            if not is_admin(request) and current_user:
                user_id = current_user.get("id")

        page = await asyncio.to_thread(
            list_conversation_records, q, limit, offset, user_id=user_id
        )
        return {
            "success": True,
            "conversations": page["items"],
            **page,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

def _session_row(row: dict) -> dict:
    """Gắn nhãn nguồn và thiết bị; session_id rỗng (tin cũ trước khi có phiên) hiện là 'legacy'."""
    from engine.core.memory import session_device
    sid = row["session_id"] or ""
    row["source"] = "web" if sid.startswith("web-") else "telegram" if sid.startswith("tg-") else "legacy"
    row["device"] = session_device(sid, row.get("device"))
    row["session_id"] = sid or "legacy"
    return row


@router.get("/api/conversations/sessions")
async def api_conversations_sessions(request: Request = None, limit: int = 50):
    try:
        from engine.core.memory import _get_db
        from engine.UIUX.memory_lock import get_current_user, is_admin
        current_user = get_current_user(request) if request is not None else None
        is_adm = is_admin(request) if request is not None else True
        def _fetch():
            conn = _get_db()
            try:
                if not is_adm and current_user:
                    uid = current_user.get("id")
                    rows = conn.execute(
                        "SELECT m.session_id, COUNT(*) as msg_count, MIN(m.created_at) as started_at, MAX(m.created_at) as last_msg, d.device"
                        " FROM messages m LEFT JOIN session_devices d ON d.session_id = m.session_id"
                        " WHERE m.user_id = ?"
                        " GROUP BY m.session_id ORDER BY last_msg DESC LIMIT ?",
                        (uid, limit)
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT m.session_id, COUNT(*) as msg_count, MIN(m.created_at) as started_at, MAX(m.created_at) as last_msg, d.device"
                        " FROM messages m LEFT JOIN session_devices d ON d.session_id = m.session_id"
                        " WHERE m.user_id = 'admin' OR m.user_id IS NULL OR m.user_id = ''"
                        " GROUP BY m.session_id ORDER BY last_msg DESC LIMIT ?",
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
async def api_conversations_session(session_id: str, request: Request = None):
    try:
        from engine.core.memory import _get_db
        from engine.UIUX.memory_lock import get_current_user, is_admin

        current_user = get_current_user(request) if request is not None else None
        is_adm = is_admin(request) if request is not None else True
        uid = current_user.get("id") if (not is_adm and current_user) else None

        def _fetch(sid):
            conn = _get_db()
            try:
                if uid:
                    rows = conn.execute(
                        "SELECT id, role, content, created_at FROM messages WHERE session_id=? AND user_id=? ORDER BY id ASC",
                        (sid, uid)
                    ).fetchall()
                else:
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

@router.delete("/api/conversations/session/{session_id}")
async def api_conversations_delete_session(session_id: str, request: Request):
    try:
        from engine.core.memory import delete_session_messages
        from engine.UIUX.memory_lock import get_current_user, is_admin
        current_user = get_current_user(request) if request is not None else None
        is_adm = is_admin(request) if request is not None else True
        target_sid = "" if session_id == "legacy" else session_id
        uid = current_user.get("id") if (not is_adm and current_user) else None
        
        affected = await asyncio.to_thread(delete_session_messages, target_sid, uid)
        return {"success": True, "deleted_count": affected}
    except Exception as e:
        return {"success": False, "error": str(e)}

@router.delete("/api/conversations/delete")
async def api_conversations_delete(id: int):
    try:
        from engine.core.memory import _get_db, delete_messages_by_id
        conn = await asyncio.to_thread(_get_db)
        try:
            delete_messages_by_id(conn, [id])
            conn.commit()
            return {"success": True}
        finally:
            conn.close()
    except Exception as e:
        return {"success": False, "error": str(e)}
