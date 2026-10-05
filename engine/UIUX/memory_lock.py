"""Khóa Memory Control bằng mật khẩu (docs/superpowers/specs/2026-10-04-memory-lock-design.md).

Mật khẩu chỉ đọc từ biến môi trường MEMORY_PASSWORD (.env): không có endpoint nào đặt hay đổi nó.
Chưa cấu hình = khóa hẳn. Nhập đúng thì nhận một token ngẫu nhiên (giữ trong bộ nhớ tiến trình, mất khi khởi động lại);
mọi endpoint dữ liệu Memory đòi token đó ở header X-Memory-Token, nếu không trả 401 "locked".
"""
import hmac
import os
import secrets

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

TOKEN_HEADER = "X-Memory-Token"
# Các endpoint dữ liệu của Memory Control, lịch sử chat và nhật ký; /api/memory-lock/* nằm ngoài để mở khóa được.
PROTECTED_PREFIXES = (
    "/api/learnings", "/api/memories", "/api/workflows", "/api/outcomes",
    "/api/conversations", "/api/notes", "/api/evolution", "/api/memory-control",
    "/api/history", "/api/logs",  # lịch sử chat và jarvis.log: cùng nội dung nhạy cảm, cùng mật khẩu
)

lock_router = APIRouter()
_tokens: set[str] = set()


def _password() -> str:
    return os.getenv("MEMORY_PASSWORD", "").strip()


def _is_valid(token: str) -> bool:
    return any(hmac.compare_digest(token.encode(), known.encode()) for known in _tokens) if token else False


async def memory_gate(request: Request) -> None:
    """Dependency của router: chặn mọi route Memory khi thiếu hoặc sai token. Route khác đi qua."""
    if request.url.path.startswith(PROTECTED_PREFIXES) and not _is_valid(request.headers.get(TOKEN_HEADER, "")):
        raise HTTPException(status_code=401, detail="locked")


class UnlockBody(BaseModel):
    password: str = ""


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
    return {"success": True, "token": token}


@lock_router.post("/api/memory-lock/lock")
async def api_memory_lock_lock(request: Request):
    _tokens.discard(request.headers.get(TOKEN_HEADER, ""))
    return {"success": True}
