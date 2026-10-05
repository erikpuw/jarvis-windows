"""Priority, single-writer dispatch for a frontend WebSocket."""

from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict, deque
from typing import Any


logger = logging.getLogger("jarvis.ws_dispatcher")


class WebSocketEventDispatcher:
    """Serialize writes while allowing low-priority UI telemetry to coalesce."""

    def __init__(self, ws: Any) -> None:
        self._ws = ws
        self._high: deque[dict[str, Any]] = deque()
        self._low: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._wake = asyncio.Event()
        self._idle = asyncio.Event()
        self._idle.set()
        self._closed = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="websocket-event-dispatcher")

    async def enqueue(self, data: dict[str, Any]) -> bool:
        if self._closed:
            return False
        if self._is_low_priority(data):
            self._low[self._coalesce_key(data)] = data
        else:
            self._high.append(data)
        self._idle.clear()
        self._wake.set()
        return True

    async def drain(self) -> None:
        await self._idle.wait()

    async def close(self) -> None:
        self._closed = True
        self._wake.set()
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

    async def _run(self) -> None:
        try:
            while not self._closed:
                await self._wake.wait()
                while self._high or self._low:
                    data = self._high.popleft() if self._high else self._low.popitem(last=False)[1]
                    try:
                        await self._ws.send_json(data)
                    except (RuntimeError, ConnectionError, ValueError) as exc:
                        logger.debug("WebSocket dispatcher send failed: %s", type(exc).__name__)
                        self._closed = True
                        break
                    except Exception as exc:
                        if type(exc).__name__ in {"WebSocketDisconnect", "ClientDisconnected"}:
                            logger.debug("WebSocket dispatcher client disconnected: %s", type(exc).__name__)
                        else:
                            logger.warning("WebSocket dispatcher send failed", exc_info=True)
                        self._closed = True
                        break
                self._wake.clear()
                if not self._high and not self._low:
                    self._idle.set()
        except asyncio.CancelledError:
            raise

    @staticmethod
    def _is_low_priority(data: dict[str, Any]) -> bool:
        if data.get("type") == "flow_step":
            return True
        card = data.get("card")
        return data.get("type") == "interactive" and isinstance(card, dict) and card.get("type") == "tracker"

    @staticmethod
    def _coalesce_key(data: dict[str, Any]) -> str:
        if data.get("type") == "flow_step":
            step = data.get("step")
            if isinstance(step, dict):
                return f"flow:{step.get('id', step.get('label', 'latest'))}"
        card = data.get("card")
        if isinstance(card, dict):
            return f"card:{card.get('id', 'latest')}"
        return str(data.get("type", "status"))
