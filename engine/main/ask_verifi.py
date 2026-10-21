"""Shared WebSocket confirmation cards and their pending-response registry."""

import asyncio
import logging
import uuid
from typing import Any, Dict


log = logging.getLogger("jarvis.ask_verifi")

# Distinguishes "queue was empty" from "dequeued ws_reader's None disconnect
# sentinel". Collapsing both into None swallowed the sentinel, so the main loop
# in server.py never saw it and the session hung for the full timeout.
_NOTHING = object()

pending_verifications: Dict[str, asyncio.Future] = {}
pending_input_cards: Dict[str, asyncio.Future] = {}
pending_selection_cards: Dict[str, asyncio.Future] = {}


async def ask_user_confirmation(
    ws: Any,
    safe_send: Any,
    action_name: str,
    message: str,
    timeout: float = 300.0,
) -> bool:
    """Send an approval card and wait for its matching interactive response."""
    card_id = f"confirm_{uuid.uuid4().hex[:8]}"
    card_payload = {
        "id": card_id,
        "type": "approve",
        "title": "YÊU CẦU XÁC NHẬN HÀNH ĐỘNG",
        "description": f"{message} (Hành động: {action_name})",
        "approveLabel": "Đồng ý",
        "rejectLabel": "Từ chối",
    }
    future = asyncio.get_running_loop().create_future()
    pending_verifications[card_id] = future
    log.info("Sending verification request: %s for action %r", card_id, action_name)
    await safe_send(ws, {"type": "interactive", "card": card_payload})

    try:
        started_at = asyncio.get_running_loop().time()
        while not future.done():
            if asyncio.get_running_loop().time() - started_at >= timeout:
                log.warning("Verification %s timed out after %ss.", card_id, timeout)
                return False

            message_queue = getattr(ws, "message_queue", None)
            if message_queue and not message_queue.empty():
                try:
                    response = message_queue.get_nowait()
                except asyncio.QueueEmpty:
                    response = _NOTHING
                if response is None:
                    await message_queue.put(None)
                    log.warning("Verification %s aborted: client disconnected.", card_id)
                    return False
                if response is not _NOTHING:
                    if response.get("type") == "interactive_response":
                        response_card_id = response.get("cardId", "")
                        action = response.get("action", "")
                        log.info(
                            "[Verification Helper] Dequeued interactive_response: card_id=%s, action=%s",
                            response_card_id,
                            action,
                        )
                        target = pending_verifications.get(response_card_id)
                        if target is not None and not target.done():
                            target.set_result(action == "approve")
                        else:
                            await message_queue.put(response)
                            await asyncio.sleep(0.05)
                    else:
                        await message_queue.put(response)
                        await asyncio.sleep(0.05)
            await asyncio.sleep(0.1)

        result = future.result()
        log.info("Verification %s resolved with result: %s", card_id, result)
        return result
    finally:
        pending_verifications.pop(card_id, None)


async def ask_user_text(
    ws: Any,
    safe_send: Any,
    action_name: str,
    message: str,
    *,
    value: str = "",
    placeholder: str = "Nhập nội dung...",
    timeout: float = 300.0,
) -> str | None:
    """Send a text-input card and return submitted text, or None when cancelled."""
    card_id = f"input_{uuid.uuid4().hex[:8]}"
    card_payload = {
        "id": card_id,
        "type": "input",
        "title": "NHẬP NỘI DUNG",
        "description": f"{message} (Hành động: {action_name})",
        "value": value,
        "placeholder": placeholder,
        "submitLabel": "Xác nhận nội dung",
        "cancelLabel": "Hủy",
    }
    future = asyncio.get_running_loop().create_future()
    pending_input_cards[card_id] = future
    log.info("Sending text input request: %s for action %r", card_id, action_name)
    await safe_send(ws, {"type": "interactive", "card": card_payload})

    try:
        started_at = asyncio.get_running_loop().time()
        while not future.done():
            if asyncio.get_running_loop().time() - started_at >= timeout:
                log.warning("Text input %s timed out after %ss.", card_id, timeout)
                return None

            message_queue = getattr(ws, "message_queue", None)
            if message_queue and not message_queue.empty():
                try:
                    response = message_queue.get_nowait()
                except asyncio.QueueEmpty:
                    response = _NOTHING
                if response is None:
                    await message_queue.put(None)
                    log.warning("Text input %s aborted: client disconnected.", card_id)
                    return None
                if response is not _NOTHING:
                    if (
                        response.get("type") == "interactive_response"
                        and response.get("cardId") == card_id
                    ):
                        action = response.get("action")
                        future.set_result(response.get("value", "") if action == "submit" else None)
                    else:
                        await message_queue.put(response)
                        await asyncio.sleep(0.05)
            await asyncio.sleep(0.1)

        return future.result()
    finally:
        pending_input_cards.pop(card_id, None)


async def ask_user_selection(
    ws: Any,
    safe_send: Any,
    action_name: str,
    message: str,
    options: list[dict[str, str]],
    *,
    timeout: float = 300.0,
) -> str | None:
    """Send a single-choice card and return its selected opaque option id."""
    if not options:
        return None
    card_id = f"select_{uuid.uuid4().hex[:8]}"
    future = asyncio.get_running_loop().create_future()
    pending_selection_cards[card_id] = future
    await safe_send(ws, {"type": "interactive", "card": {
        "id": card_id,
        "type": "select",
        "title": "CHỌN MỘT MỤC",
        "description": f"{message} (Hành động: {action_name})",
        # WebUI và Telegram đọc opt["value"]; người gọi truyền {"id", "label"}.
        "options": [{"value": o.get("value", o.get("id")), "label": o.get("label", "")} for o in options],
        "multiple": False,
        "submitLabel": "Xác nhận",
    }})
    try:
        started_at = asyncio.get_running_loop().time()
        while not future.done():
            if asyncio.get_running_loop().time() - started_at >= timeout:
                return None
            queue = getattr(ws, "message_queue", None)
            if queue and not queue.empty():
                try:
                    response = queue.get_nowait()
                except asyncio.QueueEmpty:
                    response = _NOTHING
                if response is None:
                    await queue.put(None)
                    log.warning("Selection %s aborted: client disconnected.", card_id)
                    return None
                if response is not _NOTHING:
                    if response.get("type") == "interactive_response" and response.get("cardId") == card_id:
                        values = response.get("value")
                        future.set_result(values[0] if response.get("action") == "submit" and isinstance(values, list) and values else None)
                    else:
                        await queue.put(response)
                        await asyncio.sleep(0.05)
            await asyncio.sleep(0.1)
        return future.result()
    finally:
        pending_selection_cards.pop(card_id, None)
