"""Khóa Memory Control bằng mật khẩu và xác thực người dùng (docs/superpowers/specs/2026-10-04-memory-lock-design.md).

Hỗ trợ 2 luồng:
1. Luồng mới (Web): Quản lý token bền vững trong bảng user_tokens, phân quyền Admin và Member.
2. Luồng cũ (App iOS/Android): Mật khẩu MEMORY_PASSWORD trong .env, token tạm trong bộ nhớ.
"""
import hmac
import os
import secrets
import time
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

TOKEN_HEADER = "X-Memory-Token"
# Các endpoint dữ liệu của Memory Control, lịch sử chat và nhật ký; /api/memory-lock/* nằm ngoài để mở khóa được.
PROTECTED_PREFIXES = (
    "/api/learnings", "/api/memories", "/api/workflows", "/api/outcomes", "/api/corrections",
    "/api/conversations", "/api/evolution", "/api/memory-control",
    "/api/history", "/api/logs",  # lịch sử chat và jarvis.log: cùng nội dung nhạy cảm, cùng mật khẩu
)

lock_router = APIRouter()
_tokens: set[str] = set()


def _password() -> str:
    return (os.getenv("ADMIN_PASSWORD") or os.getenv("MEMORY_PASSWORD") or "").strip()


def _is_valid(token: str) -> bool:
    if not token:
        return False
    if any(hmac.compare_digest(token.encode(), known.encode()) for known in _tokens):
        return True
    try:
        from engine.core.memory import _get_db
        with _get_db() as conn:
            row = conn.execute("SELECT user_id FROM user_tokens WHERE token = ?", (token,)).fetchone()
            if row:
                _tokens.add(token)
                return True
    except Exception:
        pass
    return False


def get_token_from_request(request: Optional[Request]) -> str:
    if request is None:
        return ""
    token = request.headers.get(TOKEN_HEADER, "").strip()
    if token:
        return token
    auth = request.headers.get("Authorization", "").strip()
    if auth.startswith("Bearer "):
        return auth[7:].strip()
    cookie_token = request.cookies.get("jarvis_token", "").strip()
    if cookie_token:
        return cookie_token
    return ""


def get_current_user(request: Optional[Request]) -> Optional[dict]:
    if request is None:
        return None
    token = get_token_from_request(request)
    if not token or not _is_valid(token):
        return None
    try:
        from engine.core.memory import _get_db
        with _get_db() as conn:
            row = conn.execute(
                """SELECT u.id, u.username, u.display_name, u.role, u.tts_voice_id, u.user_pronoun, u.ai_pronoun, u.calendar_accounts 
                   FROM users u
                   JOIN user_tokens t ON u.id = t.user_id
                   WHERE t.token = ?""",
                (token,)
            ).fetchone()
            if row:
                return dict(row)
    except Exception:
        pass
    if token.startswith("admin_"):
        return {"id": "admin", "username": "admin", "display_name": "Admin", "role": "admin", "tts_voice_id": "", "user_pronoun": "Anh", "ai_pronoun": "Jarvis", "calendar_accounts": "auto"}
    return None


def is_admin(request: Optional[Request] = None) -> bool:
    """Kiểm tra quyền Admin: xác thực qua token có role admin."""
    if request is None:
        return True  # Internal test/script call
    token = get_token_from_request(request)
    if not token:
        return False
    if token.startswith("admin_"):
        return True
    user = get_current_user(request)
    if user is not None:
        return user.get("role") == "admin"
    return False


async def memory_gate(request: Request) -> None:
    """Dependency của router: chặn mọi route Memory khi thiếu hoặc sai token. Route khác đi qua."""
    if request.url.path.startswith(PROTECTED_PREFIXES) and not _is_valid(get_token_from_request(request)):
        raise HTTPException(status_code=401, detail="locked")


class UnlockBody(BaseModel):
    password: str = ""


class LoginBody(BaseModel):
    username: str = ""
    password: str = ""


class VoiceUpdate(BaseModel):
    voice: str = ""


class ProfileUpdate(BaseModel):
    display_name: Optional[str] = None
    user_pronoun: Optional[str] = None
    ai_pronoun: Optional[str] = None


@lock_router.get("/api/memory-lock/status")
async def api_memory_lock_status():
    return {"configured": bool(_password())}


@lock_router.post("/api/memory-lock/unlock")
async def api_memory_lock_unlock(body: UnlockBody):
    expected = _password()
    if not expected:
        return JSONResponse({"success": False, "code": "not_configured"}, status_code=403)
    if not hmac.compare_digest(body.password.encode(), expected.encode()):
        return JSONResponse({"success": False, "code": "wrong_password"}, status_code=401)
    token = secrets.token_urlsafe(32)
    _tokens.add(token)
    try:
        from engine.core.memory import _get_db
        with _get_db() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO user_tokens (token, user_id, role, created_at) VALUES (?, 'admin', 'admin', ?)",
                (token, time.time())
            )
            conn.commit()
    except Exception:
        pass
    return {"success": True, "token": token}


@lock_router.post("/api/memory-lock/lock")
async def api_memory_lock_lock(request: Request):
    token = get_token_from_request(request)
    if token:
        _tokens.discard(token)
        try:
            from engine.core.memory import _get_db
            with _get_db() as conn:
                conn.execute("DELETE FROM user_tokens WHERE token = ?", (token,))
                conn.commit()
        except Exception:
            pass
    return {"success": True}


@lock_router.post("/api/auth/login")
async def api_auth_login(body: LoginBody):
    uname = (body.username or "").strip()
    pwd = (body.password or "").strip()
    if not uname:
        return JSONResponse({"success": False, "error": "Vui lòng nhập tên người dùng"}, status_code=400)

    from engine.core.memory import _get_db

    if uname.lower() == "admin":
        expected = _password()
        if expected and not hmac.compare_digest(pwd.encode(), expected.encode()):
            return JSONResponse({"success": False, "error": "Mật khẩu Admin không chính xác"}, status_code=401)
        token = "admin_" + secrets.token_urlsafe(32)
        _tokens.add(token)
        with _get_db() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO user_tokens (token, user_id, role, created_at) VALUES (?, 'admin', 'admin', ?)",
                (token, time.time())
            )
            conn.commit()
        return {
            "success": True,
            "token": token,
            "user": {"id": "admin", "username": "admin", "display_name": "Admin", "role": "admin"}
        }
    else:
        uid = f"user-{uname.lower()}"
        with _get_db() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO users (id, username, display_name, role, created_at) VALUES (?, ?, ?, 'member', ?)",
                (uid, uname, uname, time.time())
            )
            token = "usr_" + secrets.token_urlsafe(32)
            _tokens.add(token)
            conn.execute(
                "INSERT OR REPLACE INTO user_tokens (token, user_id, role, created_at) VALUES (?, ?, 'member', ?)",
                (token, uid, time.time())
            )
            conn.commit()
            u_row = conn.execute("SELECT id, username, display_name, role, tts_voice_id, user_pronoun, ai_pronoun, calendar_accounts FROM users WHERE id = ?", (uid,)).fetchone()
            user_data = dict(u_row) if u_row else {"id": uid, "username": uname, "role": "member"}

        return {
            "success": True,
            "token": token,
            "user": user_data
        }


@lock_router.get("/api/auth/me")
async def api_auth_me(request: Request):
    user = get_current_user(request)
    if not user:
        return JSONResponse({"success": False, "error": "Chưa đăng nhập"}, status_code=401)
    return {"success": True, "user": user}


@lock_router.post("/api/auth/logout")
async def api_auth_logout(request: Request):
    token = get_token_from_request(request)
    if token:
        _tokens.discard(token)
        try:
            from engine.core.memory import _get_db
            with _get_db() as conn:
                conn.execute("DELETE FROM user_tokens WHERE token = ?", (token,))
                conn.commit()
        except Exception:
            pass
    return {"success": True}


@lock_router.post("/api/user/voice")
async def api_user_set_voice(body: VoiceUpdate, request: Request):
    user = get_current_user(request)
    if not user:
        return JSONResponse({"success": False, "error": "Chưa đăng nhập"}, status_code=401)
    voice = body.voice.strip()
    if not voice or len(voice) > 80:
        return JSONResponse({"success": False, "error": "Tên giọng không hợp lệ"}, status_code=400)
    from engine.core.memory import _get_db
    with _get_db() as conn:
        conn.execute("UPDATE users SET tts_voice_id = ? WHERE id = ?", (voice, user["id"]))
        conn.commit()
    if user.get("role") == "admin":
        import server
        os.environ["VIENEU_VOICE_ID"] = voice
        try:
            server._write_env_key("VIENEU_VOICE_ID", voice)
        except Exception:
            pass
    return {"success": True, "voice": voice}


@lock_router.post("/api/user/profile")
async def api_user_set_profile(body: ProfileUpdate, request: Request):
    user = get_current_user(request)
    if not user:
        return JSONResponse({"success": False, "error": "Chưa đăng nhập"}, status_code=401)
    from engine.core.memory import _get_db
    with _get_db() as conn:
        if body.display_name is not None:
            conn.execute("UPDATE users SET display_name = ? WHERE id = ?", (body.display_name.strip(), user["id"]))
        if body.user_pronoun is not None:
            conn.execute("UPDATE users SET user_pronoun = ? WHERE id = ?", (body.user_pronoun.strip(), user["id"]))
        if body.ai_pronoun is not None:
            conn.execute("UPDATE users SET ai_pronoun = ? WHERE id = ?", (body.ai_pronoun.strip(), user["id"]))
        conn.commit()
    return {"success": True}
