"""Shared gate telling background work when a live conversation is in flight.

This counter used to live inside LearningEngine, so only conversation learning
and the Dream cycle ever consulted it. Self-healing, cognitive evolution and
the rest called the same single local LLM with no idea the user was mid
sentence, adding seconds to the reply they were waiting on — and self-healing
went further, draining the live WebSocket's message queue from its 60s loop.

Background jobs await wait_until_chat_idle() before doing expensive or
intrusive work; interactive entrypoints bracket a turn with
begin_interactive_chat()/end_interactive_chat().
"""

import asyncio
import contextlib
import contextvars
import logging
import os

log = logging.getLogger("jarvis.activity_gate")

_DEFAULT_IDLE_GRACE_SECONDS = 5.0


class ActivityGate:
    def __init__(self, idle_grace_seconds: float = _DEFAULT_IDLE_GRACE_SECONDS):
        self._interactive_chats = 0
        self._generation = 0
        self._idle_grace_seconds = idle_grace_seconds
        self._idle_event = asyncio.Event()
        self._idle_event.set()

    @property
    def interactive_chats(self) -> int:
        return self._interactive_chats

    @property
    def generation(self) -> int:
        return self._generation

    def is_chat_active(self) -> bool:
        return self._interactive_chats > 0

    def begin(self) -> None:
        self._interactive_chats += 1
        self._generation += 1
        self._idle_event.clear()

    def end(self) -> None:
        self._interactive_chats = max(0, self._interactive_chats - 1)
        self._generation += 1
        if self._interactive_chats == 0:
            self._idle_event.set()

    async def wait_until_idle(self, grace_seconds: float | None = None) -> None:
        """Block until no interactive chat has been active for the grace period.

        The generation check makes a turn that starts and finishes inside the
        grace window still count as activity, so a fast back-and-forth doesn't
        let background work slip in between two sentences.
        """
        grace = self._idle_grace_seconds if grace_seconds is None else grace_seconds
        while True:
            await self._idle_event.wait()
            generation = self._generation
            if grace > 0:
                await asyncio.sleep(grace)
            if self._interactive_chats == 0 and generation == self._generation:
                return


class InferenceGate:
    """Keeps background work from competing with a live turn for the GPU.

    One machine hosts the chat LLM, the TTS backbone and the embedding server,
    and every caller — hot path, agents, Dream, Learning, Self-Healing,
    Evolution, RAG — went through the same client first-come-first-served, so a
    background generation could sit in front of the reply the user was waiting
    on.

    Interactive callers are never blocked (blocking them could deadlock a turn
    that fans out into several calls); they only announce themselves, and
    background callers wait for that to clear and then take a bounded slot so
    they cannot stampede the GPU either. A generation already in flight is not
    preempted — it cannot be cancelled safely — but the next one waits.
    """

    def __init__(self, limit: int | None = None):
        if limit is None:
            limit = max(1, int(os.getenv("LLM_MAX_BACKGROUND_CALLS", "1")))
        self._sem = asyncio.Semaphore(limit)
        self._interactive_pending = 0
        self._clear = asyncio.Event()
        self._clear.set()

    @property
    def interactive_pending(self) -> int:
        return self._interactive_pending

    @contextlib.asynccontextmanager
    async def slot(self, *, interactive: bool):
        if interactive:
            self._interactive_pending += 1
            self._clear.clear()
            try:
                yield
            finally:
                self._interactive_pending = max(0, self._interactive_pending - 1)
                if self._interactive_pending == 0:
                    self._clear.set()
            return

        await self._clear.wait()
        async with self._sem:
            yield


_gate = ActivityGate()
_inference_gate = InferenceGate()

# Marks the current task (and tasks it spawns) as serving a live user turn, so
# call_llm can prioritise it without every call site growing a new argument.
_interactive_turn: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "jarvis_interactive_turn", default=False
)


def get_gate() -> ActivityGate:
    return _gate


def get_inference_gate() -> InferenceGate:
    return _inference_gate


def mark_interactive_turn() -> None:
    _interactive_turn.set(True)


def in_interactive_turn() -> bool:
    return _interactive_turn.get()


def is_chat_active() -> bool:
    return _gate.is_chat_active()


def begin_interactive_chat() -> None:
    _gate.begin()


def end_interactive_chat() -> None:
    _gate.end()


async def wait_until_chat_idle(grace_seconds: float | None = None) -> None:
    await _gate.wait_until_idle(grace_seconds)
