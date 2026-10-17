"""
JARVIS Memory — conversation history (messages) and feedback, stored in SQLite.
"""

import logging
import re
import sqlite3
import time
from pathlib import Path

from engine.core.session_context import get_session
from engine.core.db_ids import insert_with_lowest_free_id

log = logging.getLogger("jarvis.memory")

_EMOJI_RE = re.compile(
    "["
    "\U0001F1E6-\U0001F1FF"  # Regional indicator symbols (emoji cờ quốc gia)
    "\U0001F300-\U0001FAFF"  # Pictographs, emoticons, transport, supplemental symbols A/B, extended-A
    "\U00002600-\U000026FF"  # Miscellaneous Symbols
    "\U00002700-\U000027BF"  # Dingbats
    "\U00002B00-\U00002BFF"  # Miscellaneous Symbols and Arrows (★ ⭐ ...)
    "\U0000FE0F"              # Variation Selector-16 (emoji presentation selector)
    "\U0000200D"              # Zero Width Joiner (nối emoji ghép)
    "\U000020E3"              # Combining Enclosing Keycap (1️⃣ 2️⃣ ...)
    "]+",
    flags=re.UNICODE,
)

_IMAGE_RE = re.compile(
    r"!\[.*?\]\(.*?\)"                     # Markdown image ![alt](url)
    r"|data:image\/[a-zA-Z;,\/+=%0-9-]+"  # Base64 data URI
    r"|<img[^>]*>"                          # HTML img tag
    r"|!\[\[.*?\]\]",                       # Obsidian wiki embed [[image.png]]
    flags=re.UNICODE | re.IGNORECASE,
)


def strip_emojis(text: str) -> str:
    return _EMOJI_RE.sub("", text).strip()


def strip_images(text: str) -> str:
    return _IMAGE_RE.sub("", text).strip()


DB_PATH = Path(__file__).parent.parent.parent / "data" / "jarvis.db"


def _get_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = _get_db()
    conn.executescript("""
        -- semantic memory đã gỡ 2026-10-17: không luồng nào đọc bảng này
        DROP TABLE IF EXISTS memory_fts;
        DROP TABLE IF EXISTS memories;

        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            session_id TEXT DEFAULT '',
            created_at REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id TEXT DEFAULT '',
            rating INTEGER NOT NULL,
            comment TEXT DEFAULT '',
            created_at REAL NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_feedback_created ON feedback(created_at DESC);

        -- thiết bị đã mở phiên chat web (frontend/src/ws.ts getDeviceType → ?device=): Settings ghi rõ "web trên iPhone"
        CREATE TABLE IF NOT EXISTS session_devices (
            session_id TEXT PRIMARY KEY,
            device TEXT NOT NULL,
            created_at REAL NOT NULL
        );
    """)
    msg_cols = {r["name"] for r in conn.execute("PRAGMA table_info(messages)")}
    for col in ("ask_user", "action_run"):
        if col in msg_cols:
            try:
                conn.execute(f"ALTER TABLE messages DROP COLUMN {col}")
            except Exception as e:
                log.debug("DROP COLUMN %s skipped: %s", col, e)
    conn.commit()
    conn.close()
    log.info("🗄️ Memory database initialized")


def delete_messages_by_id(conn: sqlite3.Connection, ids: list[int]) -> int:
    """Delete messages and their feedback so a reused message ID cannot inherit it."""
    ids = tuple(dict.fromkeys(int(message_id) for message_id in ids))
    if not ids:
        return 0
    if not conn.in_transaction:
        conn.execute("BEGIN IMMEDIATE")
    conn.executemany(
        """DELETE FROM feedback
           WHERE message_id=? AND EXISTS (SELECT 1 FROM messages WHERE id=?)""",
        [(str(message_id), message_id) for message_id in ids],
    )
    return conn.executemany(
        "DELETE FROM messages WHERE id=?", [(message_id,) for message_id in ids]
    ).rowcount


def _list_memory_table(
    table: str,
    columns: str,
    search_columns: tuple[str, ...],
    order_column: str,
    q: str,
    limit: int,
    offset: int,
) -> dict:
    if table != "messages":
        raise ValueError("unsupported_table")
    page_limit = max(1, min(int(limit), 200))
    page_offset = max(0, int(offset))
    query = (q or "").strip().lower()
    params: list[object] = []
    where = ""
    if query:
        where = " WHERE " + " OR ".join(
            f"LOWER(CAST({column} AS TEXT)) LIKE ?"
            for column in search_columns
        )
        params = [f"%{query}%"] * len(search_columns)
    conn = _get_db()
    total = conn.execute(
        f"SELECT COUNT(*) FROM {table}{where}", params
    ).fetchone()[0]
    rows = conn.execute(
        f"""SELECT {columns} FROM {table}{where}
            ORDER BY {order_column} DESC LIMIT ? OFFSET ?""",
        [*params, page_limit, page_offset],
    ).fetchall()
    conn.close()
    return {
        "items": [dict(row) for row in rows],
        "total": total,
        "limit": page_limit,
        "offset": page_offset,
    }


SESSION_DEVICES = ("desktop", "ios", "android", "mobile")


def record_session_device(session_id: str, device: str) -> None:
    """Ghi thiết bị của phiên web lúc socket nối; lần nối lại sau (cùng trang) không đổi giá trị đầu. Tên lạ bị bỏ qua."""
    if not session_id or device not in SESSION_DEVICES:
        return
    conn = _get_db()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO session_devices (session_id, device, created_at) VALUES (?, ?, ?)",
            (session_id, device, time.time()),
        )
        conn.commit()
    finally:
        conn.close()


def session_device(session_id: str, recorded: str | None) -> str:
    """Thiết bị hiển thị của một phiên: đã ghi → tên đó; Telegram → "telegram"; còn lại (phiên cũ) → ""."""
    if recorded:
        return recorded
    return "telegram" if (session_id or "").startswith("tg-") else ""


def list_conversation_records(
    q: str = "", limit: int = 50, offset: int = 0
) -> dict:
    page = _list_memory_table(
        "messages",
        "id, role, content, session_id, created_at",
        ("role", "content", "session_id"),
        "created_at",
        q,
        limit,
        offset,
    )
    sids = sorted({i["session_id"] for i in page["items"] if i.get("session_id")})
    devices: dict[str, str] = {}
    if sids:
        conn = _get_db()
        try:
            rows = conn.execute(
                f"SELECT session_id, device FROM session_devices WHERE session_id IN ({','.join('?' * len(sids))})", sids
            ).fetchall()
            devices = {r["session_id"]: r["device"] for r in rows}
        finally:
            conn.close()
    for item in page["items"]:
        item["device"] = session_device(item.get("session_id") or "", devices.get(item.get("session_id") or ""))
    return page


def get_memory_control_counts() -> dict[str, int]:
    conn = _get_db()
    try:
        return {
            "conversations": conn.execute(
                "SELECT COUNT(*) FROM messages"
            ).fetchone()[0],
        }
    finally:
        conn.close()


def update_memory_control_record(
    kind: str, record_id: int, values: dict
) -> bool:
    schemas = {
        "conversation": (
            "messages",
            {"role", "content", "session_id"},
        ),
    }
    if kind not in schemas:
        raise ValueError("unsupported_kind")
    table, allowed = schemas[kind]
    clean = {key: value for key, value in values.items() if key in allowed}
    if not clean or clean.keys() != values.keys():
        raise ValueError("invalid_payload")
    conn = _get_db()
    if kind == "conversation" and "role" in clean:
        if clean["role"] not in {"user", "assistant", "system", "tool"}:
            conn.close()
            raise ValueError("invalid_role")
    assignments = ", ".join(f"{field}=?" for field in clean)
    affected = conn.execute(
        f"UPDATE {table} SET {assignments} WHERE id=?",
        [*clean.values(), record_id],
    ).rowcount
    conn.commit()
    conn.close()
    return affected > 0


def preview_memory_dependencies(kind: str, record_id: int) -> dict:
    table = {
        "conversation": "messages",
    }.get(kind)
    if not table:
        raise ValueError("unsupported_kind")
    conn = _get_db()
    row = conn.execute(
        f"SELECT * FROM {table} WHERE id=?", (record_id,)
    ).fetchone()
    conn.close()
    if not row:
        raise LookupError("not_found")
    return {
        "will_delete": {
            "records": [dict(row)],
            "wiki_paths": [],
        },
        "will_update": [],
        "related_only": [],
    }


def delete_memory_control_record(kind: str, record_id: int) -> bool:
    preview_memory_dependencies(kind, record_id)  # kiểm tra loại hợp lệ và bản ghi tồn tại
    if kind == "conversation":
        conn = _get_db()
        affected = delete_messages_by_id(conn, [record_id])
        conn.commit()
        conn.close()
        return affected > 0
    raise ValueError("unsupported_kind")


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------

def save_message(role: str, content: str, session_id: str = "", ask_user: str = "", action_run: str = "") -> int:
    content = strip_images(strip_emojis(content))
    session_id = session_id or get_session()
    conn = _get_db()

    # Duplicate = same role AND content as the very last row OF THIS SESSION.
    last = conn.execute(
        "SELECT id, role, content FROM messages WHERE session_id = ? ORDER BY id DESC LIMIT 1",
        (session_id,),
    ).fetchone()
    if last and last["role"] == role and last["content"] == content:
        conn.close()
        log.info(f"💬 Message duplicate skipped: role={role} session={session_id or '-'}")
        return last["id"]

    cur = insert_with_lowest_free_id(
        conn,
        "messages",
        ("role", "content", "session_id", "created_at"),
        (role, content, session_id, time.time()),
    )
    conn.commit()
    conn.close()

    log.info(f"💬 Message [{role}] session={session_id or '-'}")
    return cur.lastrowid

def get_messages(limit: int = 100, session_id: str = "") -> list[dict]:
    conn = _get_db()
    if session_id:
        rows = conn.execute(
            "SELECT id, role, content, created_at, session_id FROM messages WHERE session_id = ? ORDER BY id DESC LIMIT ?",
            (session_id, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, role, content, created_at, session_id FROM messages ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    conn.close()
    result = [dict(r) for r in rows]
    result.reverse()
    return result


# ---------------------------------------------------------------------------
# Conversation Quality Metrics (Feature 4)
# ---------------------------------------------------------------------------

def save_feedback(message_id: str, rating: int, comment: str = "") -> int:
    """Lưu feedback thumbs up/down từ người dùng về phản hồi của JARVIS.
    rating: 1 = thumbs up, -1 = thumbs down, 0 = neutral.
    """
    conn = _get_db()
    cur = insert_with_lowest_free_id(
        conn,
        "feedback",
        ("message_id", "rating", "comment", "created_at"),
        (str(message_id), int(rating), str(comment), time.time()),
    )
    fb_id = cur.lastrowid
    conn.commit()
    conn.close()
    log.info(f"Feedback saved: id={fb_id}, rating={rating}, msg_id={message_id!r}")
    return fb_id


def get_feedback_stats(days: int = 30) -> dict:
    """Trả về thống kê feedback trong N ngày gần nhất."""
    since = time.time() - days * 86400
    conn = _get_db()
    rows = conn.execute(
        "SELECT rating, COUNT(*) as cnt FROM feedback WHERE created_at >= ? GROUP BY rating",
        (since,)
    ).fetchall()
    conn.close()
    stats = {"thumbs_up": 0, "thumbs_down": 0, "total": 0, "days": days}
    for row in rows:
        if row["rating"] > 0:
            stats["thumbs_up"] += row["cnt"]
        elif row["rating"] < 0:
            stats["thumbs_down"] += row["cnt"]
        stats["total"] += row["cnt"]
    if stats["total"] > 0:
        stats["satisfaction_pct"] = round(stats["thumbs_up"] / stats["total"] * 100, 1)
    else:
        stats["satisfaction_pct"] = None
    return stats


# ---------------------------------------------------------------------------
# Module init
# ---------------------------------------------------------------------------

init_db()
