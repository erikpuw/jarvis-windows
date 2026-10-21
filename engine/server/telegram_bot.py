"""Telegram long-polling bridge for Jarvis text chat.

The bridge deliberately reuses the server response pipeline.  It does not
enable voice output and it never makes approval decisions on a user's behalf.
"""

from __future__ import annotations

import asyncio
import contextvars
import functools
import html
import json
import logging
import mimetypes
import os
import re
import secrets
import socket
import ssl
import tempfile
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen
from uuid import uuid4

from engine.core.session_context import get_session, set_session


logger = logging.getLogger(__name__)

TELEGRAM_TEXT_LIMIT = 4096
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
# Giới hạn tải tệp lên của Bot API: ảnh 10MB, tệp thường 50MB (khác với
# MAX_UPLOAD_BYTES vốn là trần tải xuống của người dùng gửi lên).
TELEGRAM_PHOTO_MAX_BYTES = 10 * 1024 * 1024
TELEGRAM_DOCUMENT_MAX_BYTES = 50 * 1024 * 1024
OUTPUT_CAPTION_LIMIT = 1024
UPLOAD_DIR = Path(__file__).resolve().parents[2] / "data" / "uploads"
RESTART_NOTICE_PATH = Path(__file__).resolve().parents[2] / "data" / "telegram_restart_notice.json"
RESTART_NOTICE_MAX_AGE_SECONDS = 10 * 60
ALLOWED_DOCUMENT_EXTENSIONS = {".pdf", ".docx", ".xlsx", ".txt", ".csv"}
ALLOWED_DOCUMENT_MIME_TYPES = {
    ".pdf": {"application/pdf"},
    ".docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
    ".xlsx": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
    ".txt": {"text/plain"},
    ".csv": {"text/csv", "application/csv", "application/vnd.ms-excel"},
}


_TRANSIENT_CONNECTION_ERRORS = (TimeoutError, ConnectionResetError, ConnectionAbortedError)


def is_transient_polling_timeout(error: BaseException) -> bool:
    """A long-poll timeout or a dropped connection is an expected transport
    condition, not a code failure — Telegram's long-poll leaves a connection
    open for ~25s and Windows/the remote host resets it occasionally.
    Telegram-side 5xx (502 Bad Gateway, …) and 429 rate limits are transient too."""
    if isinstance(error, HTTPError):
        return error.code == 429 or error.code >= 500
    return isinstance(error, _TRANSIENT_CONNECTION_ERRORS) or (
        isinstance(error, URLError) and isinstance(error.reason, _TRANSIENT_CONNECTION_ERRORS)
    )


def is_network_offline_error(error: BaseException) -> bool:
    """Kiểm tra xem lỗi có phải do mất mạng Internet, rớt điện hoặc DNS không phân giải được."""
    if isinstance(error, (socket.gaierror, socket.herror)):
        return True
    if isinstance(error, URLError):
        reason = error.reason
        if isinstance(reason, (socket.gaierror, socket.herror, ssl.SSLError)):
            return True
        if isinstance(reason, OSError):
            if getattr(reason, "errno", None) in (11001, 10051, 10060, 10065, -2, -3):
                return True
        reason_str = str(reason).lower()
        if (
            "getaddrinfo failed" in reason_str
            or "network is unreachable" in reason_str
            or "temporary failure in name resolution" in reason_str
            or "name or service not known" in reason_str
            or "certificate verify failed" in reason_str
        ):
            return True
    return False


@dataclass(frozen=True)
class TelegramUpload:
    """Validated Telegram file metadata accepted for local download."""

    file_id: str
    extension: str
    display_name: str


def _is_allowed_upload_size(value: Any) -> bool:
    return value is None or (isinstance(value, int) and 0 <= value <= MAX_UPLOAD_BYTES)


def extract_telegram_upload(message: dict[str, Any]) -> TelegramUpload | None:
    """Return supported image/document metadata, never trusting a remote filename path."""
    photos = message.get("photo")
    if isinstance(photos, list):
        for photo in reversed(photos):
            if not isinstance(photo, dict) or not _is_allowed_upload_size(photo.get("file_size")):
                continue
            file_id = photo.get("file_id")
            if isinstance(file_id, str) and file_id:
                return TelegramUpload(file_id=file_id, extension=".jpg", display_name="image.jpg")

    document = message.get("document")
    if not isinstance(document, dict) or not _is_allowed_upload_size(document.get("file_size")):
        return None
    file_id = document.get("file_id")
    raw_name = document.get("file_name")
    if not isinstance(file_id, str) or not file_id or not isinstance(raw_name, str):
        return None
    display_name = Path(raw_name).name.strip()
    extension = Path(display_name).suffix.lower()
    mime_type = document.get("mime_type")
    if (
        not display_name
        or extension not in ALLOWED_DOCUMENT_EXTENSIONS
        or (isinstance(mime_type, str) and mime_type not in ALLOWED_DOCUMENT_MIME_TYPES[extension])
    ):
        return None
    return TelegramUpload(file_id=file_id, extension=extension, display_name=display_name)


def parse_allowed_chat_ids(value: str) -> set[int]:
    """Parse a comma-separated allow-list, discarding malformed entries."""
    chat_ids: set[int] = set()
    for item in value.split(","):
        try:
            chat_ids.add(int(item.strip()))
        except (TypeError, ValueError):
            continue
    return chat_ids


def build_telegram_command_menu(commands: list[Any] | None = None) -> list[dict[str, str]]:
    """Convert enabled tools from registry to Telegram menu entries."""
    from engine.tools import registry
    menu = [
        {"command": "start", "description": "Kết nối Jarvis"},
        {"command": "help", "description": "Trợ giúp và danh sách lệnh"},
        {"command": "restart", "description": "Khởi động lại Jarvis"},
    ]
    seen = {item["command"] for item in menu}
    for name in sorted(registry.names()):
        if name in seen or not re.fullmatch(r"[a-z0-9_]{1,32}", name):
            continue
        # câu đầu của mô tả: mô tả đầy đủ (khi nào dùng/không dùng, de67719) dài quá → setMyCommands 400 (log 2026-10-15)
        full = " ".join(registry.description(name).split())
        description = (re.split(r"(?<=[.!?])\s", full, maxsplit=1)[0][:120]) or name
        menu.append({"command": name, "description": description})
        seen.add(name)
        if len(menu) == 100:
            break
    return menu



def split_telegram_text(text: str, limit: int = TELEGRAM_TEXT_LIMIT) -> list[str]:
    """Keep outgoing messages within Telegram's documented text limit."""
    if not text:
        return [""]

    parts: list[str] = []
    remaining = text
    while len(remaining) > limit:
        cut_at = max(remaining.rfind("\n", 0, limit), remaining.rfind(" ", 0, limit))
        if cut_at <= 0:
            cut_at = limit
        parts.append(remaining[:cut_at].rstrip())
        remaining = remaining[cut_at:].lstrip()
    if remaining:
        parts.append(remaining)
    return parts


def _render_markdown_table(match: re.Match[str]) -> str:
    """Degrade a WebUI Markdown table to readable Telegram text.

    Strips image markdown (![…](…)) from cells — Telegram cannot inline-display
    arbitrary web images — and skips rows that become empty after stripping.
    """
    rows = [line.strip().strip("|") for line in match.group(0).splitlines()]
    headers = [value.strip() for value in rows[0].split("|")]
    values = [
        [value.strip() for value in row.split("|")]
        for row in rows[2:]
    ]
    rendered_rows = []
    for row in values:
        cleaned = [re.sub(r"!\[[^\]]*\]\((?:[^()]+|\([^()]*\))*\)", "", cell).strip() for cell in row]
        if not any(cleaned):
            continue
        cells = [f"{header}: {value}" for header, value in zip(headers, cleaned)]
        rendered_rows.append("\n".join(cells))
    return "\n\n".join(rendered_rows)


def render_telegram_html(text: str) -> str:
    """Render a narrow Markdown subset as Telegram HTML (parse_mode HTML).

    HTML mode only reserves <, > and &, so ordinary punctuation never gets a message rejected the way MarkdownV2 did.
    """
    protected: list[str] = []

    def protect(value: str) -> str:
        token = f"{len(protected)}"
        protected.append(value)
        return token

    def esc(value: str) -> str:
        return html.escape(value, quote=False)

    def link(label: str, url: str) -> str:
        return protect(f'<a href="{html.escape(url)}">{esc(label)}</a>')

    def raw_url(match: re.Match[str]) -> str:
        value = match.group(0)
        url = value.rstrip(".,!?;:")
        hostname = urlsplit(url).hostname or url
        return link(hostname.removeprefix("www."), url) + value[len(url):]

    rendered = re.sub(r"```[\w+-]*\n?(.*?)```", lambda m: protect(f"<pre>{esc(m.group(1))}</pre>"), text, flags=re.DOTALL)
    rendered = re.sub(r"`([^`\n]+)`", lambda m: protect(f"<code>{esc(m.group(1))}</code>"), rendered)
    rendered = re.sub(
        r"(?m)^[ \t]*\|.+\|[ \t]*\n[ \t]*\|(?:[ \t]*:?-{3,}:?[ \t]*\|)+[ \t]*\n(?:[ \t]*\|.+\|[ \t]*(?:\n|$))+",
        lambda match: _render_markdown_table(match) + "\n\n",
        rendered,
    )
    rendered = re.sub(r"(?m)^#{1,6}\s+(.+?)\s*#*\s*$", lambda m: protect(f"<b>{esc(m.group(1))}</b>"), rendered)
    rendered = re.sub(
        r"!\[([^\]\n]*)\]\((?:[^()\s]+|\([^()\s]*\))+\)",
        lambda match: protect(esc(match.group(1).strip())),
        rendered,
    )
    rendered = re.sub(r"\[([^\]\n]+)\]\(([^\s()]+)\)", lambda m: link(m.group(1), m.group(2)), rendered)
    rendered = re.sub(r"https?://[^\s<>()]+", raw_url, rendered)
    rendered = re.sub(r"\*\*(.+?)\*\*", lambda m: protect(f"<b>{esc(m.group(1))}</b>"), rendered)
    rendered = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", lambda m: protect(f"<i>{esc(m.group(1))}</i>"), rendered)
    rendered = esc(rendered)
    # newest first: a later value (bold) can wrap an earlier token (a link inside it)
    for index in range(len(protected) - 1, -1, -1):
        rendered = rendered.replace(f"{index}", protected[index])
    return rendered


class TelegramSession:
    """Small WebSocket-compatible sink used by the existing text pipeline."""

    is_telegram = True
    tts_disabled = True
    cancel_requested = False
    media_active = False
    forced_command: dict | None = None
    pending_slash_command: str | None = None


    def __init__(self, bot: "TelegramBot", chat_id: int, observer_ws: Any = None, user_id: str = "admin") -> None:
        self._bot = bot
        self._chat_id = chat_id
        self._observer_ws = observer_ws
        self.user_id = user_id
        self.message_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    async def send_json(self, data: dict[str, Any]) -> None:
        event_type = data.get("type")
        if event_type in {"interactive", "screenshot_processed"} and self._observer_ws is not None:
            await self._bot._server.safe_ws_send_json(self._observer_ws, data)
        if (
            event_type == "interactive"
            and isinstance(data.get("card"), dict)
            and data["card"].get("type") == "approve"
        ):
            await self._bot._send_confirmation(self._chat_id, data["card"])
        elif (
            event_type == "interactive"
            and isinstance(data.get("card"), dict)
            and data["card"].get("type") == "select"
        ):
            await self._bot._send_selection(self._chat_id, data["card"])
        elif event_type == "screenshot_processed":
            filename = data.get("filename") if isinstance(data, dict) else None
            await self._bot._send_screenshot(self._chat_id, filename=filename)
        elif event_type == "output_file":
            await self._bot._send_output_file(self._chat_id, data)


class TelegramBot:
    """Receive allowed Telegram text messages and forward them to Jarvis."""

    def __init__(
        self,
        token: str,
        allowed_chat_ids: set[int],
        server_module: Any,
    ) -> None:
        self._token = token.strip()
        self._allowed_chat_ids = allowed_chat_ids
        self._server = server_module
        self._stop_event = asyncio.Event()
        self._offset: int | None = None
        self._histories: dict[int, list[dict[str, str]]] = defaultdict(list)
        self._pending_callbacks: dict[str, tuple[int, str, float, str, list[str]]] = {}
        self._pending_attachments: dict[int, str] = {}
        self._sessions: dict[int, TelegramSession] = {}
        # Tải bản gốc upscale: (tên tệp, token output_file) chờ gắn nút ⬇ vào
        # tin phản hồi cuối cùng của lượt, thay vì gửi rời gây trùng lặp.
        self._pending_downloads: dict[int, tuple[str, str]] = {}
        self._message_tasks: set[asyncio.Task] = set()
        self._menu_commands = build_telegram_command_menu()
        self._bot_info: dict[str, Any] = {}
        self._bot_username: str = ""
        self._is_offline: bool = False
        # Dedicated pool. Every blocking Telegram call used to go through
        # asyncio.to_thread, i.e. the one default executor shared by the whole
        # process — and getUpdates long-polls for 25-40s continuously, so it
        # squatted a slot permanently and starved the voice hot path, which
        # needs several to_thread slots per turn.
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="telegram")

    def _get_session(self, chat_id: int, user_id: str = "admin") -> TelegramSession:
        if chat_id not in self._sessions:
            observer_ws = getattr(self._server, "_active_ws_session", None)
            self._sessions[chat_id] = TelegramSession(self, chat_id, observer_ws, user_id=user_id)
        else:
            self._sessions[chat_id].user_id = user_id
        return self._sessions[chat_id]

    def _resolve_user_for_chat(self, chat_id: int) -> dict | None:
        """Tra cứu user tương ứng với chat_id.

        Ưu tiên:
        1. Bảng `users` trong SQLite (theo telegram_chat_id).
        2. Nếu chat_id nằm trong `self._allowed_chat_ids` (.env): coi là Admin mặc định.
        3. Không tìm thấy: trả về None.
        """
        from engine.core.memory import get_user_by_telegram_chat_id
        user = get_user_by_telegram_chat_id(chat_id)
        if user:
            return user
        if chat_id in self._allowed_chat_ids:
            return {
                "id": "admin",
                "username": "admin",
                "display_name": "Admin",
                "role": "admin",
                "user_pronoun": "Anh",
                "ai_pronoun": "Jarvis",
            }
        return None

    async def _handle_link_command(self, chat_id: int, clean_text: str) -> bool:
        """Xử lý lệnh liên kết tài khoản Telegram với Jarvis."""
        parts = clean_text.split(maxsplit=1)
        cmd = parts[0].lower()
        if cmd not in ("/link", "/start"):
            return False

        token = ""
        if cmd == "/link" and len(parts) > 1:
            token = parts[1].strip()
        elif cmd == "/start" and len(parts) > 1 and parts[1].strip().startswith("link_"):
            token = parts[1].strip().removeprefix("link_").strip()
        elif cmd == "/link":
            await self._send_text(
                chat_id,
                "📌 Vui lòng nhập mã token liên kết theo cú pháp: /link <mã_token>\n(Bạn có thể lấy mã token từ web Jarvis hoặc nhờ Admin cấp)."
            )
            return True

        if not token:
            return False

        try:
            from engine.core.memory import _get_db, link_telegram_chat_id
            with _get_db() as conn:
                row = conn.execute(
                    """SELECT u.id, u.username, u.display_name, u.role
                       FROM users u
                       JOIN user_tokens t ON u.id = t.user_id
                       WHERE t.token = ?""",
                    (token,)
                ).fetchone()
                if row:
                    uid = row["id"]
                    name = row["display_name"] or row["username"]
                    role = row["role"] or "member"
                    link_telegram_chat_id(uid, chat_id)
                    success_msg = (
                        f"✅ Liên kết thành công với tài khoản: **{name}** (`@{row['username']}`)\n"
                        f"Vai trò: `{role.upper()}`\n\n"
                        f"Từ bây giờ mọi tương tác của bạn qua Telegram sẽ được ghi nhận và đồng bộ riêng cho tài khoản này!"
                    )
                    await self._send_text(chat_id, success_msg)
                    return True
                else:
                    await self._send_text(
                        chat_id,
                        "❌ Mã liên kết không hợp lệ hoặc đã hết hạn. Vui lòng kiểm tra lại."
                    )
                    return True
        except Exception as exc:
            logger.warning("Lỗi xử lý link Telegram chat_id %s: %s", chat_id, exc)
            await self._send_text(chat_id, "Đã xảy ra lỗi khi liên kết tài khoản. Vui lòng thử lại sau.")
            return True


    def _check_connectivity(self) -> bool:
        """Kiểm tra nhanh kết nối tới Telegram API qua socket chuẩn."""
        try:
            with socket.create_connection(("api.telegram.org", 443), timeout=5):
                return True
        except OSError:
            return False

    async def _handle_network_offline(self, exc: BaseException) -> None:
        """Tạm dừng polling khi mất mạng hoặc mất điện để tránh spam log."""
        if not self._is_offline:
            self._is_offline = True
            logger.warning(
                "Mất kết nối Internet/Telegram (%s); tạm dừng polling và chờ khôi phục mạng...",
                exc,
            )
        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=15)
                break
            except TimeoutError:
                pass
            if await self._to_thread(self._check_connectivity):
                self._is_offline = False
                logger.info("Đã khôi phục kết nối mạng; tiếp tục Telegram polling.")
                break

    async def _to_thread(self, fn, *args, **kwargs):
        loop = asyncio.get_running_loop()
        if kwargs:
            fn = functools.partial(fn, **kwargs)
        # run_in_executor không sao chép contextvars (asyncio.to_thread thì có): thiếu dòng này thread nền mất session id.
        return await loop.run_in_executor(self._executor, contextvars.copy_context().run, fn, *args)

    def queue_restart_notice(self, chat_id: int) -> bool:
        """Persist the requesting chat so the replacement worker can confirm startup."""
        temporary_path = RESTART_NOTICE_PATH.with_suffix(".tmp")
        try:
            RESTART_NOTICE_PATH.parent.mkdir(parents=True, exist_ok=True)
            temporary_path.write_text(
                json.dumps({"chat_id": chat_id, "requested_at": time.time()}), encoding="utf-8"
            )
            temporary_path.replace(RESTART_NOTICE_PATH)
            return True
        except OSError:
            logger.warning("Could not persist Telegram restart notice", exc_info=True)
            return False

    def _clear_restart_notice(self) -> None:
        try:
            RESTART_NOTICE_PATH.unlink(missing_ok=True)
        except OSError:
            logger.warning("Could not clear Telegram restart notice", exc_info=True)

    async def send_pending_restart_notice(self) -> bool:
        """Confirm a completed restart once, only to the originally allowed chat."""
        try:
            notice = json.loads(RESTART_NOTICE_PATH.read_text(encoding="utf-8"))
            chat_id = notice.get("chat_id")
            requested_at = notice.get("requested_at")
        except (OSError, ValueError, json.JSONDecodeError):
            self._clear_restart_notice()
            return False

        if (
            not isinstance(chat_id, int)
            or chat_id not in self._allowed_chat_ids
            or not isinstance(requested_at, (int, float))
            or time.time() - requested_at > RESTART_NOTICE_MAX_AGE_SECONDS
        ):
            self._clear_restart_notice()
            return False

        try:
            await self._send_text(chat_id, "Jarvis đã khởi động lại hoàn tất.")
        except (OSError, URLError, ValueError):
            logger.warning("Could not send Telegram restart completion notice", exc_info=True)
            return False
        self._clear_restart_notice()
        return True

    async def stop(self) -> None:
        self._stop_event.set()
        for task in tuple(self._message_tasks):
            task.cancel()
        if self._message_tasks:
            await asyncio.gather(*self._message_tasks, return_exceptions=True)
        # Don't wait on the in-flight long poll; it can still be 40s from
        # returning and shutdown is already bounded upstream.
        self._executor.shutdown(wait=False, cancel_futures=True)

    async def run(self) -> None:
        """Run until shutdown; transient Telegram failures are retried."""
        if not self._token or not self._allowed_chat_ids:
            return

        try:
            bot_info = await self._request("getMe", {})
            if isinstance(bot_info, dict):
                self._bot_info = bot_info
                self._bot_username = str(bot_info.get("username", "")).lower()
                logger.info(
                    "Telegram bot info initialized: @%s (id=%s)",
                    self._bot_username,
                    bot_info.get("id"),
                )
        except (OSError, URLError, ValueError) as exc:
            if is_network_offline_error(exc):
                logger.warning("Không thể lấy thông tin bot Telegram do mất mạng: %s", exc)
            else:
                logger.warning("Could not fetch Telegram bot info via getMe", exc_info=True)

        try:
            await self._request("deleteWebhook", {"drop_pending_updates": True})
            logger.info("Telegram polling initialized; stale updates discarded")
        except (OSError, URLError, ValueError) as exc:
            if is_network_offline_error(exc):
                logger.warning("Không thể dọn dẹp webhook Telegram do mất mạng: %s", exc)
            else:
                logger.warning("Telegram webhook cleanup failed; retrying polling", exc_info=True)

        await self._register_commands()

        while not self._stop_event.is_set():
            try:
                updates = await self._request(
                        "getUpdates",
                        {
                            "offset": self._offset,
                            "timeout": 25,
                            "allowed_updates": ["message", "callback_query"],
                        },
                )
                if updates:
                    logger.info("Telegram polling received %d update(s)", len(updates))
                if self._is_offline:
                    self._is_offline = False
                    logger.info("Đã khôi phục kết nối mạng; tiếp tục Telegram polling.")
                for update in updates:
                    update_id = update.get("update_id")
                    if isinstance(update_id, int):
                        self._offset = update_id + 1
                    if isinstance(update.get("callback_query"), dict):
                        logger.info("Received Telegram callback update")
                        await self._handle_update(update)
                    elif isinstance(update.get("message"), dict):
                        logger.info("Received Telegram message update")
                        task = asyncio.create_task(self._handle_update(update))
                        self._message_tasks.add(task)
                        task.add_done_callback(self._message_tasks.discard)
                    else:
                        logger.info("Received unsupported Telegram update")
            except asyncio.CancelledError:
                raise
            except (OSError, URLError, ValueError, KeyError) as exc:
                if is_network_offline_error(exc):
                    await self._handle_network_offline(exc)
                elif is_transient_polling_timeout(exc):
                    logger.info(
                        "Telegram polling interrupted (%s %s); retrying", type(exc).__name__, exc
                    )
                    try:
                        await asyncio.wait_for(self._stop_event.wait(), timeout=3)
                    except TimeoutError:
                        pass
                else:
                    logger.warning("Telegram polling request failed; retrying", exc_info=True)
                    try:
                        await asyncio.wait_for(self._stop_event.wait(), timeout=3)
                    except TimeoutError:
                        pass
            except Exception as exc:
                # Bất kỳ lỗi nào ngoài các loại cụ thể ở trên (vd. HTTPException,
                # phản hồi Telegram dị dạng) trước đây sẽ thoát hẳn khỏi vòng lặp
                # và tắt polling vĩnh viễn — không có gì tự khởi động lại. Bắt
                # rộng ở đây để bot luôn tự thử lại thay vì im lặng ngừng phản hồi.
                if is_network_offline_error(exc):
                    await self._handle_network_offline(exc)
                else:
                    logger.warning("Unexpected error in Telegram polling loop; retrying", exc_info=True)
                    try:
                        await asyncio.wait_for(self._stop_event.wait(), timeout=3)
                    except TimeoutError:
                        pass

    async def _request(self, method: str, payload: dict[str, Any]) -> Any:
        body = await self._to_thread(self._post, method, payload)
        if not body.get("ok"):
            raise ValueError(f"Telegram {method} returned an unsuccessful response")
        return body.get("result")

    def _post(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        request = Request(
            f"https://api.telegram.org/bot{self._token}/{method}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=40) as response:
            return json.loads(response.read().decode("utf-8"))

    async def _register_commands(self) -> None:
        """Register the bot command menu with Telegram (setMyCommands)."""
        try:
            self._menu_commands = build_telegram_command_menu()
            await self._request("setMyCommands", {"commands": self._menu_commands})
            logger.info("Telegram bot commands registered (%d)", len(self._menu_commands))

        except (OSError, URLError, ValueError) as exc:
            if is_network_offline_error(exc):
                logger.warning("Không thể đăng ký menu lệnh Telegram do mất mạng: %s", exc)
            else:
                logger.warning("Could not register Telegram bot commands", exc_info=True)

    def _extract_sender_info(self, message: dict[str, Any]) -> dict[str, str]:
        sender = message.get("from") if isinstance(message.get("from"), dict) else {}
        first_name = str(sender.get("first_name", "")).strip()
        last_name = str(sender.get("last_name", "")).strip()
        username = str(sender.get("username", "")).strip()
        user_id = sender.get("id")

        full_name = f"{first_name} {last_name}".strip()
        display_name = full_name or (f"@{username}" if username else f"User_{user_id}")
        if username and full_name:
            sender_label = f"{full_name} (@{username})"
        elif username:
            sender_label = f"@{username}"
        else:
            sender_label = display_name

        return {
            "display_name": display_name,
            "username": username,
            "sender_label": sender_label,
            "user_id": str(user_id) if user_id is not None else "",
        }

    def _is_mentioned_or_targeted(self, message: dict[str, Any], text: str) -> bool:
        chat = message.get("chat") if isinstance(message.get("chat"), dict) else {}
        chat_type = str(chat.get("type", ""))
        chat_id = chat.get("id")
        is_group = (isinstance(chat_id, int) and chat_id < 0) or chat_type in ("group", "supergroup")

        if not is_group:
            return True

        import os
        require_mention = os.getenv("TELEGRAM_GROUP_REQUIRE_MENTION", "true").lower() in ("true", "1", "yes")
        if not require_mention:
            return True

        text_lower = text.lower().strip()

        if text_lower.startswith("/"):
            return True

        if self._bot_username and f"@{self._bot_username}" in text_lower:
            return True

        if "jarvis" in text_lower:
            return True

        reply_to = message.get("reply_to_message")
        if isinstance(reply_to, dict):
            reply_from = reply_to.get("from")
            if isinstance(reply_from, dict):
                bot_id = self._bot_info.get("id")
                if bot_id and reply_from.get("id") == bot_id:
                    return True
                if (
                    reply_from.get("is_bot")
                    and self._bot_username
                    and str(reply_from.get("username", "")).lower() == self._bot_username
                ):
                    return True

        return False

    def _sanitize_text(self, text: str) -> str:
        if not text:
            return ""

        cleaned = text.strip()

        if cleaned.startswith("/"):
            parts = cleaned.split(maxsplit=1)
            rest = parts[1] if len(parts) > 1 else ""
            if rest:
                cleaned = rest.strip()
            else:
                cmd = parts[0]
                if "@" in cmd:
                    cmd = cmd.split("@")[0]
                cleaned = cmd

        targets = ["@jarvis"]
        if self._bot_username:
            targets.append(f"@{self._bot_username.lower()}")

        for target in targets:
            pattern = re.compile(re.escape(target), re.IGNORECASE)
            cleaned = pattern.sub("", cleaned).strip()

        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned

    async def _handle_update(self, update: dict[str, Any]) -> None:
        chat_id: int | None = None
        try:
            callback = update.get("callback_query")
            if isinstance(callback, dict):
                await self._handle_callback(callback)
                return
            message = update.get("message")
            if not isinstance(message, dict):
                return
            chat = message.get("chat")
            chat_id = chat.get("id") if isinstance(chat, dict) else None
            text = message.get("text")
            if not isinstance(chat_id, int):
                return

            caption = message.get("caption") if isinstance(message.get("caption"), str) else ""
            content_text = text if isinstance(text, str) else caption
            clean_text = self._sanitize_text(content_text or "")

            user_info = self._resolve_user_for_chat(chat_id)
            if user_info is None:
                # Kiểm tra nếu là lệnh liên kết tài khoản /link
                if clean_text.lower().startswith("/link") or (clean_text.lower().startswith("/start") and "link_" in clean_text.lower()):
                    await self._handle_link_command(chat_id, clean_text)
                    return
                logger.warning(
                    "Rejected Telegram message from an unlinked/non-allowed chat: chat_id=%s",
                    chat_id,
                )
                await self._send_text(
                    chat_id,
                    "⚠️ Tài khoản Telegram của bạn chưa được liên kết với hệ thống Jarvis.\n"
                    "Vui lòng gửi lệnh `/link <mã_token>` để liên kết tài khoản hoặc liên hệ Quản trị viên."
                )
                return

            # Nếu đã liên kết mà vẫn gửi /link
            if clean_text.lower().startswith("/link"):
                await self._handle_link_command(chat_id, clean_text)
                return

            user_id = user_info["id"]
            sender_info = self._extract_sender_info(message)

            if not self._is_mentioned_or_targeted(message, content_text or ""):
                logger.info(
                    "Ignoring Telegram group message not targeted to bot: chat_id=%s, sender=%s",
                    chat_id,
                    sender_info.get("sender_label"),
                )
                return

            upload = extract_telegram_upload(message)
            if upload is not None:
                await self._handle_upload(chat_id, upload, caption, sender_info=sender_info)
                return
            if not clean_text:
                await self._send_text(chat_id, "Hiện bot chỉ nhận tin nhắn văn bản.")
                return

            session = self._get_session(chat_id, user_id=user_id)

            if clean_text.lower().startswith("/start"):
                role_label = user_info.get("role", "member").upper()
                name_label = user_info.get("display_name") or user_info.get("username") or "bạn"
                await self._send_text(
                    chat_id,
                    f"Jarvis đã kết nối với tài khoản **{name_label}** ({role_label}).\n"
                    f"Bạn có thể nhắn tin tại đây. Gõ `/help` để xem danh sách lệnh được phép."
                )
                return

            if clean_text.lower().startswith("/restart"):
                if user_info.get("role") != "admin":
                    await self._send_text(chat_id, "Lệnh này chỉ dành cho Quản trị viên (Admin).")
                    return
                request_restart = getattr(self._server, "request_restart", None)
                if not self.queue_restart_notice(chat_id):
                    await self._send_text(chat_id, "Jarvis chua the luu yeu cau khoi dong lai.")
                    return
                if not callable(request_restart) or not request_restart():
                    self._clear_restart_notice()
                    await self._send_text(chat_id, "Jarvis chua the khoi dong lai luc nay.")
                    return
                await self._send_text(chat_id, "Jarvis đang khởi động lại.")
                return

            async def _send(payload: dict) -> None:
                if payload.get("type") == "text_chunk" and payload.get("text"):
                    await self._send_text(chat_id, payload["text"])

            from engine.server.slash_commands import handle_slash_message
            routed_text = await handle_slash_message(session, clean_text, _send)
            if routed_text is None:
                return

            await self._handle_text(chat_id, routed_text, sender_info=sender_info, session=session, user_id=user_id)
        except Exception:
            # Trước đây một exception ngoài phạm vi except hẹp của các hàm con
            # (vd. _handle_upload/_handle_text) sẽ biến mất dưới dạng unretrieved
            # task exception — không log rõ, không phản hồi người dùng, không ai
            # biết tin nhắn đó "rơi" ở đâu. Bắt rộng ở biên xử lý 1 update để
            # luôn có log và (khi đã biết chat_id) báo lỗi cho người dùng.
            logger.error("Unhandled error while processing Telegram update", exc_info=True)
            if isinstance(chat_id, int):
                try:
                    await self._send_text(chat_id, "Đã xảy ra lỗi khi xử lý yêu cầu của bạn.")
                except Exception:
                    pass


    async def _handle_upload(
        self,
        chat_id: int,
        upload: TelegramUpload,
        caption: str,
        sender_info: dict[str, str] | None = None,
    ) -> None:
        try:
            path = await self._download_upload(upload)
            from engine.core.attachment_store import register_attachment
            attachment = register_attachment(
                path,
                filename=upload.display_name,
                channel="telegram",
            )
        except (OSError, URLError, ValueError):
            logger.warning("Telegram upload download failed", exc_info=True)
            await self._send_text(chat_id, "Không thể tải tài liệu này. Vui lòng thử lại.")
            return

        if not caption.strip():
            self._pending_attachments[chat_id] = attachment.attachment_id
            await self._send_text(
                chat_id,
                f"Đã nhận {upload.display_name}. Hãy nói cho tôi biết cần xử lý gì.",
            )
            return
        await self._handle_text(
            chat_id,
            caption.strip(),
            attachment_id=attachment.attachment_id,
            sender_info=sender_info,
        )

    async def _download_upload(self, upload: TelegramUpload) -> Path:
        file_info = await self._request("getFile", {"file_id": upload.file_id})
        file_path = file_info.get("file_path") if isinstance(file_info, dict) else None
        if not isinstance(file_path, str) or not file_path:
            raise ValueError("Telegram did not return a downloadable file path")
        content = await self._to_thread(self._download_file_bytes, file_path)
        if len(content) > MAX_UPLOAD_BYTES:
            raise ValueError("Telegram upload exceeds size limit")
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        destination = UPLOAD_DIR / f"{uuid4().hex}{upload.extension}"
        await self._to_thread(destination.write_bytes, content)
        logger.info("Telegram upload saved: %s (%d bytes)", destination.name, len(content))
        return destination

    def _download_file_bytes(self, file_path: str) -> bytes:
        url = f"https://api.telegram.org/file/bot{self._token}/{quote(file_path, safe='/')}"
        with urlopen(url, timeout=40) as response:
            content = response.read(MAX_UPLOAD_BYTES + 1)
        if len(content) > MAX_UPLOAD_BYTES:
            raise ValueError("Telegram upload exceeds size limit")
        return content

    async def _handle_text(
        self,
        chat_id: int,
        text: str,
        attachment_id: str | None = None,
        sender_info: dict[str, str] | None = None,
        session: TelegramSession | None = None,
        user_id: str | None = None,
    ) -> None:
        user_info = self._resolve_user_for_chat(chat_id)
        current_uid = user_id or (user_info.get("id") if user_info else "admin")
        from engine.core.session_context import set_current_user_id
        set_session(f"tg-{chat_id}")
        set_current_user_id(current_uid)
        if self._server.openai_client is None:
            await self._send_text(chat_id, "LLM của Jarvis chưa sẵn sàng. Vui lòng thử lại sau.")
            return

        attachment_id = attachment_id or self._pending_attachments.pop(chat_id, None)
        attachment_context = None
        if attachment_id:
            from engine.core.attachment_store import resolve_attachment
            attachment_context = await self._to_thread(resolve_attachment, attachment_id)
            if attachment_context is None:
                await self._send_text(
                    chat_id,
                    "Tệp đính kèm đã hết hạn hoặc không còn tồn tại. Vui lòng tải lại tệp.",
                )
                return

        try:
            from engine.core.guardrails import verify_input
            is_safe, reason = verify_input(text)
        except Exception:
            logger.exception("Telegram Input Guardrail failed")
            is_safe, reason = True, ""
        if not is_safe:
            response = f"Cảnh báo bảo mật: {reason}"
            await self._persist_conversation(text, response)
            await self._send_text(chat_id, response)
            return

        history = self._histories[chat_id]
        prepared_text = await self._prepare_first_turn_context(text, history)
        telegram_session = session or self._get_session(chat_id, user_id=current_uid)
        telegram_session.user_id = current_uid
        if isinstance(sender_info, dict):
            telegram_session.sender_info = sender_info
        from engine.core.learning import get_learning_engine
        learning_engine = get_learning_engine()

        typing_task = None
        learning_started = False
        try:
            await self._save_user_message(text)
            typing_task = asyncio.create_task(self._typing_loop(chat_id))
            learning_engine.begin_interactive_chat()
            from engine.core.activity_gate import mark_interactive_turn
            mark_interactive_turn()
            learning_started = True
            response = await self._server.generate_response_stream(
                prepared_text,
                self._server.openai_client,
                telegram_session,
                last_response=next(
                    (item["content"] for item in reversed(history) if item["role"] == "assistant"),
                    "",
                ),
                conversation_history=history,
                flow_tracker=None,
                attachment_context=attachment_context,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Telegram message could not be processed by Jarvis")
            await self._send_text(chat_id, "Jarvis gặp lỗi khi xử lý tin nhắn này.")
            return
        finally:
            try:
                if learning_started:
                    learning_engine.end_interactive_chat()
                if typing_task is not None:
                    typing_task.cancel()
                    await asyncio.gather(typing_task, return_exceptions=True)
            finally:
                if attachment_id:
                    from engine.core.attachment_store import discard_attachment
                    discard_attachment(attachment_id)

        response = (response or "").strip() or "Jarvis chưa tạo được phản hồi."
        history.extend(
            (
                {"role": "user", "content": text},
                {"role": "assistant", "content": response, **getattr(telegram_session, "last_turn", {})},
            )
        )
        del history[:-30]
        await self._persist_conversation(text, response, user_already_saved=True, user_id=current_uid)
        self._start_reflection(text, response, user_id=current_uid)
        # Nút ⬇ tải bản gốc (nếu lượt này có ảnh upscale): gắn vào chính tin
        # phản hồi cuối cùng, không gửi rời gây trùng lặp.
        pending = self._take_pending_download(chat_id)
        await self._send_text(
            chat_id, response, reply_markup=self._download_keyboard(pending[1] if pending else "")
        )

    async def _save_user_message(self, user_text: str, user_id: str | None = None) -> None:
        try:
            from engine.core.memory import save_message
            from engine.core.session_context import set_current_user_id
            if user_id:
                set_current_user_id(user_id)
            await self._to_thread(save_message, "user", user_text)
        except Exception:
            logger.warning("Telegram user message persistence failed", exc_info=True)

    async def _prepare_first_turn_context(
        self, user_text: str, history: list[dict[str, str]]
    ) -> str:
        return user_text

    def _start_reflection(self, user_text: str, response_text: str, user_id: str | None = None) -> None:
        try:
            from engine.core.learning import get_learning_engine
            from engine.core.session_context import get_current_user_id
            uid = user_id or get_current_user_id() or "admin"
            get_learning_engine().schedule_conversation_learning(user_text, response_text, user_id=uid)
            logger.info("Telegram learning queued for idle processing session=%s (user=%s)", get_session(), uid)
        except Exception:
            logger.warning("Telegram learning queue failed", exc_info=True)

    async def _persist_conversation(
        self,
        user_text: str,
        response_text: str,
        user_already_saved: bool = False,
        user_id: str | None = None,
    ) -> None:
        """Apply the same durable chat records used by the web transport."""
        try:
            from engine.core.memory import save_message
            from engine.core.memory_tree import save_daily_digest
            from engine.core.session_context import set_current_user_id

            if user_id:
                set_current_user_id(user_id)
            if not user_already_saved:
                await self._to_thread(save_message, "user", user_text)
            persistence_started = time.monotonic()
            await self._to_thread(save_message, "assistant", response_text, "")
            logger.info(
                "Telegram response persistence: assistant_message elapsed=%.3fs",
                time.monotonic() - persistence_started,
            )
            persistence_started = time.monotonic()
            await self._to_thread(
                save_daily_digest,
                user_text,
                response_text,
            )
            logger.info(
                "Telegram response persistence: daily_digest elapsed=%.3fs",
                time.monotonic() - persistence_started,
            )
            logger.info("Telegram conversation persisted: user and assistant messages")
            logger.info("Telegram user: %s", user_text)
            logger.info("JARVIS: %s", response_text)
        except Exception:
            logger.warning("Telegram conversation persistence failed", exc_info=True)

    async def _send_text(
        self, chat_id: int, text: str, reply_markup: dict[str, Any] | None = None
    ) -> None:
        parts = split_telegram_text(text)
        for index, part in enumerate(parts):
            payload: dict[str, Any] = {
                "chat_id": chat_id,
                "text": render_telegram_html(part),
                "parse_mode": "HTML",
            }
            if reply_markup is not None and index == len(parts) - 1:
                payload["reply_markup"] = reply_markup
            try:
                await self._request("sendMessage", payload)
            except (OSError, URLError, ValueError):
                logger.info("Telegram HTML rejected; retrying plain text")
                fallback: dict[str, Any] = {"chat_id": chat_id, "text": part}
                if reply_markup is not None and index == len(parts) - 1:
                    fallback["reply_markup"] = reply_markup
                await self._request("sendMessage", fallback)

    async def _typing_loop(self, chat_id: int) -> None:
        while True:
            try:
                await self._request("sendChatAction", {"chat_id": chat_id, "action": "typing"})
            except (OSError, URLError, ValueError):
                logger.debug("Telegram typing status failed", exc_info=True)
            await asyncio.sleep(4)

    async def _send_confirmation(self, chat_id: int, card: dict[str, Any]) -> None:
        card_id = card.get("id")
        if not isinstance(card_id, str) or not card_id:
            logger.warning("Telegram interactive card has no valid id")
            return
        request_id = secrets.token_urlsafe(12)
        self._pending_callbacks[request_id] = (chat_id, card_id, time.monotonic() + 300.0, "confirm", [])
        keyboard = {
            "inline_keyboard": [[
                {"text": "Đồng ý", "callback_data": f"jarvis:confirm:{request_id}:approve"},
                {"text": "Từ chối", "callback_data": f"jarvis:confirm:{request_id}:reject"},
            ]]
        }
        await self._request(
            "sendMessage",
            {
                "chat_id": chat_id,
                "text": card.get("description") or card.get("title") or "Yêu cầu xác nhận",
                "reply_markup": keyboard,
            },
        )

    async def _send_selection(self, chat_id: int, card: dict[str, Any]) -> None:
        card_id = card.get("id")
        options = card.get("options")
        if not isinstance(card_id, str) or not isinstance(options, list):
            return
        safe_options = [item for item in options[:8] if isinstance(item, dict) and isinstance(item.get("value"), str)]
        if not safe_options:
            return
        request_id = secrets.token_urlsafe(12)
        values = [item["value"] for item in safe_options]
        self._pending_callbacks[request_id] = (chat_id, card_id, time.monotonic() + 300.0, "select", values)
        keyboard = {"inline_keyboard": [
            [{"text": str(item.get("label", item["value"]))[:60], "callback_data": f"jarvis:select:{request_id}:{index}"}]
            for index, item in enumerate(safe_options)
        ]}
        await self._request("sendMessage", {"chat_id": chat_id, "text": card.get("description") or card.get("title") or "Chọn một mục", "reply_markup": keyboard})

    async def _handle_callback(self, callback: dict[str, Any]) -> None:
        callback_id = callback.get("id")
        callback_message = callback.get("message")
        callback_chat = callback_message.get("chat") if isinstance(callback_message, dict) else None
        chat_id = callback_chat.get("id") if isinstance(callback_chat, dict) else None
        data = callback.get("data", "")
        if not isinstance(callback_id, str):
            return
        logger.info("Handling Telegram confirmation callback")
        user_info = self._resolve_user_for_chat(chat_id) if isinstance(chat_id, int) else None
        if not user_info:
            logger.warning("Rejected Telegram callback from an unlinked/non-allowed chat")
            await self._answer_callback(callback_id, "Không được phép")
            return
        parts = data.split(":") if isinstance(data, str) else []
        if len(parts) == 3 and parts[0] == "jarvis" and parts[1] == "dl":
            await self._handle_download_callback(callback_id, chat_id, parts[2])
            return
        if len(parts) != 4 or parts[0] != "jarvis" or parts[1] not in {"confirm", "select"}:
            await self._answer_callback(callback_id, "Yêu cầu không hợp lệ")
            return
        pending = self._pending_callbacks.pop(parts[2], None)
        if pending is None or pending[0] != chat_id or pending[2] < time.monotonic() or pending[3] != parts[1]:
            logger.info("Telegram confirmation callback is expired or unknown")
            await self._answer_callback(callback_id, "Yêu cầu đã hết hiệu lực")
            return
        if parts[1] == "select":
            from engine.main.ask_verifi import pending_selection_cards
            future = pending_selection_cards.get(pending[1])
            try:
                choice = pending[4][int(parts[3])]
            except (ValueError, IndexError):
                future = None
                choice = None
            if future is not None and not future.done() and choice is not None:
                future.set_result(choice)
                text = "Đã chọn"
            else:
                text = "Yêu cầu đã được xử lý"
        else:
            from engine.main.ask_verifi import pending_verifications
            future = pending_verifications.get(pending[1])
            approved = parts[3] == "approve"
            if future is not None and not future.done():
                future.set_result(approved)
                text = "Đã đồng ý" if approved else "Đã từ chối"
            else:
                text = "Yêu cầu đã được xử lý"
        await self._answer_callback(callback_id, text)

    async def _answer_callback(self, callback_id: str, text: str) -> None:
        try:
            await self._request(
                "answerCallbackQuery",
                {"callback_query_id": callback_id, "text": text},
            )
        except (OSError, URLError, ValueError):
            # The protected operation is already resolved. A stale Telegram
            # callback acknowledgement must not interrupt long polling.
            logger.info("Telegram callback acknowledgement was unavailable")

    async def _send_screenshot(self, chat_id: int, filename: str | None = None) -> None:
        media_dir = Path(__file__).resolve().parents[2] / "media"
        screenshot = media_dir / (filename if filename else "screenshot.png")
        if not screenshot.is_file():
            screenshot = media_dir / "screenshot.png"
        if not screenshot.is_file():
            logger.warning("Telegram screenshot file is unavailable")
            return
        try:
            await self._to_thread(
                self._post_file,
                chat_id,
                screenshot,
                method="sendPhoto",
                field="photo",
                content_type="image/png",
            )
        except (OSError, URLError, ValueError):
            logger.warning("Telegram screenshot upload failed", exc_info=True)

    async def _send_output_file(self, chat_id: int, payload: dict[str, Any]) -> None:
        """Đưa tệp tool tạo ra về chat.

        Ảnh: chỉ gửi khung xem trước thuần túy (sendPhoto không caption —
        không chữ, không nút). Nút icon ⬇ tải bản gốc được gắn vào tin phản
        hồi cuối cùng của lượt (qua ``_pending_downloads``), không gửi rời.
        Tài liệu Office gửi sendDocument thẳng.
        """
        path = Path(str(payload.get("path") or ""))
        kind = payload.get("kind") if payload.get("kind") in {"image", "document"} else "document"
        caption = str(payload.get("caption") or "").strip()[:OUTPUT_CAPTION_LIMIT]
        name = path.name or str(payload.get("name") or "tệp")

        if not path.is_file():
            logger.warning("Telegram output file is unavailable: %s", path)
            await self._send_text(chat_id, f"Không tìm thấy tệp kết quả: {name}")
            return

        size = path.stat().st_size
        if size > TELEGRAM_DOCUMENT_MAX_BYTES:
            logger.warning("Telegram output file too large: %s (%d bytes)", path, size)
            await self._send_text(
                chat_id,
                f"Tệp {name} nặng {size // (1024 * 1024)}MB, vượt giới hạn "
                f"{TELEGRAM_DOCUMENT_MAX_BYTES // (1024 * 1024)}MB của Telegram. "
                f"Tệp vẫn được lưu tại: {path}",
            )
            return

        # Ảnh: chỉ gửi khung xem trước thuần túy; lượt tải bản gốc chờ gắn nút
        # ⬇ vào tin phản hồi cuối lượt (không gửi rời).
        if kind == "image":
            photo_path: Path | None = path
            temp_preview = False
            if size > TELEGRAM_PHOTO_MAX_BYTES:
                # Ảnh upscale 4x PNG hầu như luôn vượt trần photo 10MB: dựng
                # bản xem JPEG nhẹ để chat vẫn hiện khung xem trước.
                built = await self._to_thread(self._build_photo_preview, path)
                if built is None:
                    photo_path = None
                else:
                    photo_path, temp_preview = built, True
            if photo_path is not None:
                temp_path = photo_path if temp_preview else None
                try:
                    await self._to_thread(
                        self._post_file,
                        chat_id,
                        photo_path,
                        method="sendPhoto",
                        field="photo",
                    )
                except (OSError, URLError, ValueError):
                    logger.warning("Telegram sendPhoto failed; sending as document", exc_info=True)
                    photo_path = None
                finally:
                    if temp_path is not None:
                        try:
                            temp_path.unlink()
                        except OSError:
                            pass
                if photo_path is not None:
                    self._remember_download(chat_id, name, payload)
                    return

        try:
            await self._to_thread(
                self._post_file,
                chat_id,
                path,
                method="sendDocument",
                field="document",
                caption=caption or f"Tệp {name}",
            )
        except (OSError, URLError, ValueError):
            logger.warning("Telegram sendDocument failed for %s", path, exc_info=True)
            await self._send_text(
                chat_id,
                f"Không gửi được {name} tới Telegram. Tệp vẫn lưu tại: {path}",
            )

    def _remember_download(self, chat_id: int, name: str, payload: dict[str, Any]) -> None:
        """Giữ (tên tệp, token) để gắn nút icon ⬇ vào tin phản hồi cuối lượt."""
        token = ""
        url = str(payload.get("url") or "")
        if "/api/outputs/" in url:
            token = url.rsplit("/", 1)[-1].split("?", 1)[0]
        if token:
            self._pending_downloads[chat_id] = (name, token)

    def _take_pending_download(self, chat_id: int) -> tuple[str, str] | None:
        """Lấy và xóa lượt tải chờ gắn nút (hết lượt là hết hiệu lực nút)."""
        return self._pending_downloads.pop(chat_id, None)

    @staticmethod
    def _download_keyboard(token: str) -> dict[str, Any] | None:
        """Bàn phím một nút icon ⬇ duy nhất (không thêm chữ nào) tải bản gốc."""
        if not token:
            return None
        return {"inline_keyboard": [[{"text": "⬇", "callback_data": f"jarvis:dl:{token}"}]]}

    async def _handle_download_callback(self, callback_id: str, chat_id: int, token: str) -> None:
        """Bấm nút ⬇ trên hàng phản hồi: gửi bản gốc của tệp tương ứng."""
        from engine.core.output_delivery import lookup_output_file

        file_path = lookup_output_file(token) if token else None
        if file_path is None or not file_path.is_file():
            await self._answer_callback(callback_id, "Tệp đã hết hiệu lực")
            return
        try:
            too_big = file_path.stat().st_size > TELEGRAM_DOCUMENT_MAX_BYTES
        except OSError:
            await self._answer_callback(callback_id, "Tệp đã hết hiệu lực")
            return
        if too_big:
            await self._answer_callback(callback_id, "Tệp vượt giới hạn của Telegram")
            return
        try:
            await self._to_thread(
                self._post_file,
                chat_id,
                file_path,
                method="sendDocument",
                field="document",
            )
        except (OSError, URLError, ValueError):
            logger.warning("Telegram callback download failed for %s", file_path, exc_info=True)
            await self._answer_callback(callback_id, "Không gửi được tệp")
            return
        await self._answer_callback(callback_id, "Đang gửi tệp")

    def _build_photo_preview(self, path: Path) -> Path | None:
        """Nén ảnh vượt trần photo thành bản xem JPEG nhẹ vừa khung 10MB.

        Trả đường dẫn tệp tạm (caller xóa sau khi gửi); trả None khi không
        dựng được để caller rớt xuống sendDocument như cũ.
        """
        try:
            from PIL import Image
        except ImportError:
            logger.warning("PIL is unavailable; oversized image falls back to document")
            return None
        try:
            with Image.open(path) as img:
                img = img.convert("RGB")
                for max_side, quality in ((2560, 85), (1920, 82), (1600, 78), (1280, 72)):
                    frame = img.copy()
                    frame.thumbnail((max_side, max_side))
                    fd, tmp_name = tempfile.mkstemp(prefix="jarvis-preview-", suffix=".jpg")
                    try:
                        with os.fdopen(fd, "wb") as fh:
                            frame.save(fh, "JPEG", quality=quality, optimize=True)
                    except Exception:
                        try:
                            Path(tmp_name).unlink()
                        except OSError:
                            pass
                        raise
                    if Path(tmp_name).stat().st_size <= TELEGRAM_PHOTO_MAX_BYTES - 512 * 1024:
                        return Path(tmp_name)
                    try:
                        Path(tmp_name).unlink()
                    except OSError:
                        pass
        except Exception:
            logger.warning("Could not build Telegram photo preview for %s", path, exc_info=True)
            return None
        return None

    def _post_file(
        self,
        chat_id: int,
        path: Path,
        *,
        method: str,
        field: str,
        caption: str | None = None,
        content_type: str | None = None,
    ) -> None:
        boundary = f"----JarvisTelegram{secrets.token_hex(8)}"
        data = path.read_bytes()
        filename = re.sub(r'["\r\n]', "", path.name)
        mime = content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"
        head = (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"chat_id\"\r\n\r\n{chat_id}\r\n"
        )
        if caption:
            head += (
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"caption\"\r\n\r\n"
                f"{caption}\r\n"
            )
        head += (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{field}\"; "
            f"filename=\"{filename}\"\r\nContent-Type: {mime}\r\n\r\n"
        )
        body = head.encode("utf-8") + data + f"\r\n--{boundary}--\r\n".encode("utf-8")
        request = Request(
            f"https://api.telegram.org/bot{self._token}/{method}",
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        with urlopen(request, timeout=40) as response:
            result = json.loads(response.read().decode("utf-8"))
        if not result.get("ok"):
            raise ValueError(f"Telegram {method} returned an unsuccessful response")
