"""Telegram long-polling bridge for Jarvis text chat.

The bridge deliberately reuses the server response pipeline.  It does not
enable voice output and it never makes approval decisions on a user's behalf.
"""

from __future__ import annotations

import asyncio
import contextvars
import functools
import json
import logging
import re
import secrets
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


def load_registered_agents() -> list[tuple[str, str]]:
    """Read direct-agent names and descriptions from catalog (spec 2026-09-25)."""
    try:
        from engine.prompts import catalog
        return [(name, data["description"]) for name, data in catalog.agents().items()]
    except Exception as exc:
        logger.warning("Could not read registered agents: %s", exc)
        return []


def build_telegram_command_menu(commands: list[Any]) -> list[dict[str, str]]:
    """Convert enabled commands scanned from commands/ to Telegram menu entries."""
    menu = [
        {"command": "start", "description": "Kết nối Jarvis"},
        {"command": "help", "description": "Trợ giúp và danh sách lệnh"},
        {"command": "agents", "description": "Danh sách agent (@agent)"},
        {"command": "restart", "description": "Khởi động lại Jarvis"},
    ]
    seen = {item["command"] for item in menu}
    for command in commands:
        name = getattr(command, "name", "")
        if not isinstance(name, str) or not re.fullmatch(r"[a-z0-9_]{1,32}", name) or name in seen:
            continue
        description = " ".join(str(getattr(command, "description", "")).split())[:256] or name
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


def _escape_markdown_v2(text: str) -> str:
    return re.sub(r"([_\*\[\]\(\)~`>#+\-=|{}.!\\])", r"\\\1", text)


def _escape_markdown_v2_url(url: str) -> str:
    """Escape the two characters Telegram reserves inside MarkdownV2 URLs."""
    return url.replace("\\", "\\\\").replace(")", "\\)")


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


def render_telegram_markdown(text: str) -> str:
    """Render a narrow Markdown subset while escaping all Telegram MarkdownV2 syntax."""
    protected: list[str] = []

    def protect(value: str) -> str:
        token = f"\ue000{len(protected)}\ue001"
        protected.append(value)
        return token

    def fenced_code(match: re.Match[str]) -> str:
        content = match.group(1).replace("\\", "\\\\").replace("`", "\\`")
        return protect(f"```{content}```")

    def inline_code(match: re.Match[str]) -> str:
        content = match.group(1).replace("\\", "\\\\").replace("`", "\\`")
        return protect(f"`{content}`")

    def bold(match: re.Match[str]) -> str:
        return protect(f"*{_escape_markdown_v2(match.group(1))}*")

    def italic(match: re.Match[str]) -> str:
        return protect(f"_{_escape_markdown_v2(match.group(1))}_")

    def raw_url(match: re.Match[str]) -> str:
        value = match.group(0)
        url = value.rstrip(".,!?;:")
        suffix = value[len(url):]
        hostname = urlsplit(url).hostname or url
        label = hostname.removeprefix("www.")
        return protect(f"[{_escape_markdown_v2(label)}]({_escape_markdown_v2_url(url)})") + suffix

    rendered = re.sub(r"```(.*?)```", fenced_code, text, flags=re.DOTALL)
    rendered = re.sub(r"`([^`\n]+)`", inline_code, rendered)
    rendered = re.sub(
        r"(?m)^[ \t]*\|.+\|[ \t]*\n[ \t]*\|(?:[ \t]*:?-{3,}:?[ \t]*\|)+[ \t]*\n(?:[ \t]*\|.+\|[ \t]*(?:\n|$))+",
        lambda match: _render_markdown_table(match) + "\n\n",
        rendered,
    )
    rendered = re.sub(
        r"(?m)^#{1,6}\s+(.+?)\s*#*\s*$",
        lambda match: protect(f"*{_escape_markdown_v2(match.group(1))}*"),
        rendered,
    )
    rendered = re.sub(
        r"!\[([^\]\n]*)\]\((?:[^()\s]+|\([^()\s]*\))+\)",
        lambda match: protect(match.group(1).strip() or ""),
        rendered,
    )
    rendered = re.sub(
        r"(!?)\[([^\]\n]+)\]\(([^\s()]+)\)",
        lambda match: protect(
            f"[{_escape_markdown_v2(match.group(2))}]({_escape_markdown_v2_url(match.group(3))})"
        ),
        rendered,
    )
    rendered = re.sub(r"https?://[^\s<>()]+", raw_url, rendered)
    rendered = re.sub(r"\*\*(.+?)\*\*", bold, rendered)
    rendered = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", italic, rendered)
    rendered = _escape_markdown_v2(rendered)
    for index, value in enumerate(protected):
        rendered = rendered.replace(f"\ue000{index}\ue001", value)
    return rendered


class TelegramSession:
    """Small WebSocket-compatible sink used by the existing text pipeline."""

    is_telegram = True
    tts_disabled = True
    cancel_requested = False
    media_active = False

    def __init__(self, bot: "TelegramBot", chat_id: int, observer_ws: Any = None) -> None:
        self._bot = bot
        self._chat_id = chat_id
        self._observer_ws = observer_ws
        self._tracker_message_ids: dict[str, int] = {}
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
        elif (
            event_type == "interactive"
            and isinstance(data.get("card"), dict)
            and data["card"].get("type") == "tracker"
        ):
            card = data["card"]
            card_id = card.get("id")
            if not isinstance(card_id, str) or not card_id:
                return
            message_id = self._tracker_message_ids.get(card_id)
            if message_id is None and card.get("status") != "active":
                return
            message_id = await self._bot._send_agent_tracker(self._chat_id, card, message_id)
            if card.get("status") in {"completed", "failed"}:
                self._tracker_message_ids.pop(card_id, None)
            elif isinstance(message_id, int):
                self._tracker_message_ids[card_id] = message_id
        elif event_type == "screenshot_processed":
            await self._bot._send_screenshot(self._chat_id)


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
        self._pending_commands: dict[int, str] = {}
        self._message_tasks: set[asyncio.Task] = set()
        self._menu_commands = build_telegram_command_menu([])
        self._bot_info: dict[str, Any] = {}
        self._bot_username: str = ""
        # Dedicated pool. Every blocking Telegram call used to go through
        # asyncio.to_thread, i.e. the one default executor shared by the whole
        # process — and getUpdates long-polls for 25-40s continuously, so it
        # squatted a slot permanently and starved the voice hot path, which
        # needs several to_thread slots per turn.
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="telegram")

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

    async def broadcast(self, text: str) -> None:
        """Gửi chủ động tới mọi chat được phép (engine/jobs báo kết quả tìm việc mỗi sáng)."""
        for chat_id in sorted(self._allowed_chat_ids):
            try:
                await self._send_text(chat_id, text)
            except (OSError, URLError, ValueError):
                logger.warning("Telegram broadcast failed for chat %s", chat_id, exc_info=True)

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
        except (OSError, URLError, ValueError):
            logger.warning("Could not fetch Telegram bot info via getMe", exc_info=True)

        try:
            await self._request("deleteWebhook", {"drop_pending_updates": True})
            logger.info("Telegram polling initialized; stale updates discarded")
        except (OSError, URLError, ValueError):
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
                if is_transient_polling_timeout(exc):
                    logger.info(
                        "Telegram polling interrupted (%s %s); retrying", type(exc).__name__, exc
                    )
                else:
                    logger.warning("Telegram polling request failed; retrying", exc_info=True)
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=3)
                except TimeoutError:
                    pass
            except Exception:
                # Bất kỳ lỗi nào ngoài các loại cụ thể ở trên (vd. HTTPException,
                # phản hồi Telegram dị dạng) trước đây sẽ thoát hẳn khỏi vòng lặp
                # và tắt polling vĩnh viễn — không có gì tự khởi động lại. Bắt
                # rộng ở đây để bot luôn tự thử lại thay vì im lặng ngừng phản hồi.
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
            from engine.tools.skill_manager import get_skill_manager

            manager = get_skill_manager()
            manager.scan_commands(recursive=True)
            self._menu_commands = build_telegram_command_menu(manager.list_commands())
            await self._request("setMyCommands", {"commands": self._menu_commands})
            logger.info("Telegram bot commands registered (%d)", len(self._menu_commands))
        except (OSError, URLError, ValueError):
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
            if not isinstance(chat_id, int) or chat_id not in self._allowed_chat_ids:
                if isinstance(chat_id, int):
                    logger.warning(
                        "Rejected Telegram message from a non-allowed chat: chat_id=%s",
                        chat_id,
                    )
                return
            sender_info = self._extract_sender_info(message)
            caption = message.get("caption") if isinstance(message.get("caption"), str) else ""
            content_text = text if isinstance(text, str) else caption

            if not self._is_mentioned_or_targeted(message, content_text or ""):
                logger.info(
                    "Ignoring Telegram group message not targeted to bot: chat_id=%s, sender=%s",
                    chat_id,
                    sender_info.get("sender_label"),
                )
                return

            clean_text = self._sanitize_text(content_text or "")

            upload = extract_telegram_upload(message)
            if upload is not None:
                await self._handle_upload(chat_id, upload, caption, sender_info=sender_info)
                return
            if not clean_text:
                await self._send_text(chat_id, "Hiện bot chỉ nhận tin nhắn văn bản.")
                return

            if clean_text.lower().startswith("/"):
                if await self._handle_command(chat_id, clean_text):
                    return

            await self._handle_text(chat_id, clean_text, sender_info=sender_info)
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

    @staticmethod
    def _load_command(command_name: str) -> Any:
        """Resolve a hot-loadable command definition from commands/."""
        from engine.server.slash_commands import load_command
        return load_command(command_name)

    @staticmethod
    def _command_spec(command: Any) -> dict:
        """Parse a command's `usage` frontmatter into a param-name -> hint dict."""
        from engine.server.slash_commands import command_spec
        return command_spec(command)

    @staticmethod
    def _build_command_prompt(command_name: str, spec: dict) -> str:
        """Ask the user to supply the command's required parameter(s)."""
        from engine.server.slash_commands import build_command_prompt
        return build_command_prompt(command_name, spec)

    @staticmethod
    def _resolve_pending_command(command_name: str, spec: dict, value: str) -> str:
        """Turn the user's reply into a directive the pipeline can execute."""
        from engine.server.slash_commands import resolve_command_directive
        return resolve_command_directive(command_name, spec, value)

    async def _dispatch_bare_command(self, chat_id: int, command_name: str) -> bool:
        """Handle a menu command tapped without arguments.

        Commands with required params ask for the value and remember the
        pending command; commands without params execute immediately.
        """
        command = self._load_command(command_name)
        if command is None:
            lines = [
                f"💡 *Lệnh /{command_name}:*\n",
                f"Không tìm thấy lệnh `/{command_name}` trong hệ thống.",
            ]
            await self._send_text(chat_id, "\n".join(lines))
            return True
        spec = self._command_spec(command)
        if spec:
            self._pending_commands[chat_id] = command_name
            await self._send_text(chat_id, self._build_command_prompt(command_name, spec))
            return True
        await self._handle_text(chat_id, f"Thực hiện lệnh {command_name}")
        return True

    async def _handle_command(self, chat_id: int, text: str) -> bool:
        """Handle a Telegram slash command. Returns True if handled."""
        self._pending_commands.pop(chat_id, None)
        parts = text.split(maxsplit=1)
        cmd = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        if cmd in ("/start",):
            await self._send_text(chat_id, "Jarvis đã kết nối. Bạn có thể nhắn tin tại đây.")
            return True

        if cmd in ("/restart",):
            request_restart = getattr(self._server, "request_restart", None)
            if not self.queue_restart_notice(chat_id):
                await self._send_text(chat_id, "Jarvis chua the luu yeu cau khoi dong lai.")
                return True
            if not callable(request_restart) or not request_restart():
                self._clear_restart_notice()
                await self._send_text(chat_id, "Jarvis chua the khoi dong lai luc nay.")
                return True
            await self._send_text(chat_id, "Jarvis đang khởi động lại.")
            return True

        if cmd in ("/help", "/commands", "/start"):
            lines = ["*Jarvis Telegram Bot*\n"]
            lines.append("Dùng */lệnh* từ menu hoặc gõ trực tiếp câu hỏi.")
            lines.append("")
            lines.append("*Danh sách lệnh:*")
            for c in self._menu_commands:
                if c["command"] in ("help", "agents"):
                    continue
                lines.append(f"/{c['command']} — {c['description']}")
            lines.append("")
            lines.append("/agents — Xem danh sách agent đặc biệt")
            lines.append("/help — Trợ giúp này")
            lines.append("")
            lines.append("Hoặc chat tự nhiên — Jarvis sẽ tự hiểu.")
            await self._send_text(chat_id, "\n".join(lines))
            return True

        if cmd in ("/agents", "/agent"):
            agents = load_registered_agents()
            lines = ["*Danh sách agent (@agent):*\n"]
            lines.append("Gõ *@tên_agent* ở đầu câu hỏi để gọi trực tiếp.\n")
            for name, desc in agents:
                lines.append(f"@{name} — {desc}")
            lines.append("")
            lines.append("Ví dụ: *@search* phim đang chiếu")
            await self._send_text(chat_id, "\n".join(lines))
            return True

        if not args.strip():
            return await self._dispatch_bare_command(chat_id, cmd.lstrip("/"))

        # Command invoked with inline arguments (e.g. "/open_app task manager"):
        # resolve the params deterministically and forward the directive to the
        # pipeline so the arguments are not left to the router as raw text.
        command_name = cmd.lstrip("/")
        command = self._load_command(command_name)
        if command is not None:
            spec = self._command_spec(command)
            if spec:
                directive = self._resolve_pending_command(command_name, spec, args.strip())
                await self._handle_text(chat_id, directive)
                return True

        return False

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
    ) -> None:
        set_session(f"tg-{chat_id}")
        pending_command = self._pending_commands.get(chat_id)
        if pending_command:
            command = self._load_command(pending_command)
            spec = self._command_spec(command)
            if spec:
                text = self._resolve_pending_command(pending_command, spec, text)
            self._pending_commands.pop(chat_id, None)

        if self._server.openai_client is None:
            if pending_command:
                self._pending_commands[chat_id] = pending_command
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
        observer_ws = getattr(self._server, "_active_ws_session", None)
        telegram_session = TelegramSession(self, chat_id, observer_ws)
        if isinstance(sender_info, dict):
            telegram_session.sender_info = sender_info
        from engine.main.flow_agents import FlowAgents
        from engine.core.learning import get_learning_engine
        learning_engine = get_learning_engine()
        flow_agents = FlowAgents(telegram_session, self._server.safe_ws_send_json)

        typing_task = None
        learning_started = False
        turn_started_at = time.time()
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
                flow_agents=flow_agents,
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
                {"role": "assistant", "content": response},
            )
        )
        del history[:-30]
        from engine.core.learning import outcome_for_turn
        outcome_id, outcome_status = outcome_for_turn(telegram_session, turn_started_at)
        await self._persist_conversation(
            text,
            response,
            user_already_saved=True,
            outcome_id=outcome_id,
            ask_user=getattr(telegram_session, "pending_ask_user", ""),
            action_run=getattr(telegram_session, "pending_action_run", ""),
        )
        self._start_reflection(
            text,
            response,
            outcome_id=outcome_id,
            outcome_status=outcome_status,
        )
        await self._send_text(chat_id, response)

    async def _save_user_message(self, user_text: str) -> None:
        try:
            from engine.core.memory import save_message
            await self._to_thread(save_message, "user", user_text)
        except Exception:
            logger.warning("Telegram user message persistence failed", exc_info=True)

    async def _prepare_first_turn_context(
        self, user_text: str, history: list[dict[str, str]]
    ) -> str:
        return user_text

    def _start_reflection(
        self,
        user_text: str,
        response_text: str,
        outcome_id: int | None = None,
        outcome_status: str | None = None,
    ) -> None:
        try:
            from engine.core.learning import get_learning_engine
            get_learning_engine().schedule_conversation_learning(
                user_text,
                response_text,
                outcome_id=outcome_id,
                outcome_status=outcome_status,
            )
            logger.info("Telegram learning queued for idle processing session=%s", get_session())
        except Exception:
            logger.warning("Telegram learning queue failed", exc_info=True)

    async def _persist_conversation(
        self,
        user_text: str,
        response_text: str,
        user_already_saved: bool = False,
        outcome_id: int | None = None,
        ask_user: str = "",
        action_run: str = "",
    ) -> None:
        """Apply the same durable chat records used by the web transport."""
        try:
            from engine.core.memory import save_message
            from engine.core.memory_tree import save_daily_digest

            if not user_already_saved:
                await self._to_thread(save_message, "user", user_text)
            persistence_started = time.monotonic()
            await self._to_thread(save_message, "assistant", response_text, "", ask_user, action_run)
            logger.info(
                "Telegram response persistence: assistant_message elapsed=%.3fs",
                time.monotonic() - persistence_started,
            )
            persistence_started = time.monotonic()
            await self._to_thread(
                save_daily_digest,
                user_text,
                response_text,
                outcome_id=outcome_id,
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

    async def _send_text(self, chat_id: int, text: str) -> None:
        for part in split_telegram_text(text):
            try:
                await self._request(
                    "sendMessage",
                    {
                        "chat_id": chat_id,
                        "text": render_telegram_markdown(part),
                        "parse_mode": "MarkdownV2",
                    },
                )
            except (OSError, URLError, ValueError):
                logger.info("Telegram MarkdownV2 rejected; retrying plain text")
                await self._request("sendMessage", {"chat_id": chat_id, "text": part})

    async def _send_agent_tracker(
        self, chat_id: int, card: dict[str, Any], message_id: int | None = None
    ) -> int | None:
        """Create or update the single status message for one active agent."""
        title = str(card.get("title") or "Agent")[:200]
        label = str(card.get("label") or "Đang xử lý")[:500]
        status = card.get("status")
        status_text = {
            "active": "đang xử lý…",
            "completed": "hoàn tất",
            "failed": "gặp lỗi",
        }.get(status, "đang xử lý…")
        text = f"{title} — {status_text}\n{label}"
        try:
            if message_id is None:
                result = await self._request("sendMessage", {"chat_id": chat_id, "text": text})
                returned_id = result.get("message_id") if isinstance(result, dict) else None
                return returned_id if isinstance(returned_id, int) else None
            await self._request(
                "editMessageText",
                {"chat_id": chat_id, "message_id": message_id, "text": text},
            )
            return message_id
        except (OSError, URLError, ValueError):
            logger.debug("Telegram agent tracker status failed", exc_info=True)
            return message_id

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
        if not isinstance(chat_id, int) or chat_id not in self._allowed_chat_ids:
            logger.warning("Rejected Telegram callback from a non-allowed chat")
            await self._answer_callback(callback_id, "Không được phép")
            return
        parts = data.split(":") if isinstance(data, str) else []
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

    async def _send_screenshot(self, chat_id: int) -> None:
        screenshot = Path(__file__).resolve().parents[2] / "media" / "screenshot.png"
        if not screenshot.is_file():
            logger.warning("Telegram screenshot file is unavailable")
            return
        try:
            await self._to_thread(self._post_photo, chat_id, screenshot)
        except (OSError, URLError, ValueError):
            logger.warning("Telegram screenshot upload failed", exc_info=True)

    def _post_photo(self, chat_id: int, path: Path) -> None:
        boundary = f"----JarvisTelegram{secrets.token_hex(8)}"
        image = path.read_bytes()
        body = (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"chat_id\"\r\n\r\n{chat_id}\r\n"
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"photo\"; filename=\"{path.name}\"\r\n"
            "Content-Type: image/png\r\n\r\n"
        ).encode("utf-8") + image + f"\r\n--{boundary}--\r\n".encode("utf-8")
        request = Request(
            f"https://api.telegram.org/bot{self._token}/sendPhoto",
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        with urlopen(request, timeout=40) as response:
            result = json.loads(response.read().decode("utf-8"))
        if not result.get("ok"):
            raise ValueError("Telegram sendPhoto returned an unsuccessful response")
