"""API thanh bên phiên chat web: danh sách phiên của chính người gọi và đọc lại tin của một phiên.

Chỉ phiên web-xxxxxxxx (WS_SESSION_RE). Admin = user_id 'admin', kèm tin có user_id rỗng/NULL (memory.save_message mặc định admin).
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from engine.core.session_context import session_title
from engine.UIUX.memory_lock import get_current_user, memory_gate

router = APIRouter(dependencies=[Depends(memory_gate)])

WEB_SESSION_LIKE = "web-%"


def _caller_id(request: Request) -> str:
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="locked")
    return user["id"]


def _owner_clause(uid: str) -> tuple[str, tuple]:
    if uid == "admin":
        return "(m.user_id IN ('admin', '') OR m.user_id IS NULL)", ()
    return "m.user_id = ?", (uid,)


@router.get("/api/sessions/mine")
async def api_sessions_mine(request: Request, limit: int = Query(50, ge=1, le=200)):
    from engine.core.memory import _get_db
    owner, params = _owner_clause(_caller_id(request))
    with _get_db() as conn:
        rows = conn.execute(
            f"""SELECT m.session_id, MIN(m.created_at) AS started_at, MAX(m.created_at) AS last_msg, COUNT(*) AS msg_count
                FROM messages m
                WHERE m.session_id LIKE ? AND {owner}
                GROUP BY m.session_id
                ORDER BY last_msg DESC
                LIMIT ?""",
            (WEB_SESSION_LIKE, *params, limit),
        ).fetchall()
        sessions = []
        for row in rows:
            first = conn.execute(
                "SELECT content FROM messages WHERE session_id = ? AND role = 'user' ORDER BY id LIMIT 1",
                (row["session_id"],),
            ).fetchone()
            sessions.append({
                "session_id": row["session_id"],
                "title": session_title(first["content"] if first else ""),
                "started_at": row["started_at"],
                "last_msg": row["last_msg"],
                "msg_count": row["msg_count"],
            })
    return {"success": True, "sessions": sessions}


@router.get("/api/sessions/mine/{session_id}")
async def api_sessions_mine_read(session_id: str, request: Request):
    from engine.core.memory import _get_db
    owner, params = _owner_clause(_caller_id(request))
    with _get_db() as conn:
        rows = conn.execute(
            f"""SELECT m.id, m.role, m.content, m.created_at
                FROM messages m
                WHERE m.session_id = ? AND m.session_id LIKE ? AND {owner}
                ORDER BY m.id""",
            (session_id, WEB_SESSION_LIKE, *params),
        ).fetchall()
    if not rows:
        return JSONResponse({"success": False, "code": "not_found"}, status_code=404)
    return {"success": True, "messages": [dict(r) for r in rows]}
