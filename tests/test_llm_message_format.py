"""Định dạng Gemma 4: đúng một system turn ở đầu, rồi user/model xen kẽ (ai.google.dev, Gemma 4 Prompt Formatting).
Đo 2026-10-08: gộp mọi system về đầu giữ nguyên chất lượng chat; ghép vào lượt user làm tụt (command_help 10→4/10)."""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.server import llm_server


def test_gemma_profile_merges_all_system_messages_first():
    assert llm_server.MODEL_PROFILES["gemma"]["merge_system_first"] is True


def test_gemma_request_has_one_system_turn_first(monkeypatch):
    seen = {}

    class _Completions:
        async def create(self, **params):
            seen.update(params)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))], usage=None)
    client = SimpleNamespace(model="gemma", chat=SimpleNamespace(completions=_Completions()))
    monkeypatch.setattr(llm_server, "get_llm_client", lambda: client)
    monkeypatch.setattr(llm_server, "active_model_profile", lambda: llm_server.MODEL_PROFILES["gemma"])
    msgs = [{"role": "system", "content": "S"}, {"role": "user", "content": "a"}, {"role": "assistant", "content": "b"},
            {"role": "system", "content": "T"}, {"role": "user", "content": "q"}]
    asyncio.run(llm_server._call_llm_inner(msgs, thinking=False))
    assert seen["messages"] == [{"role": "system", "content": "S\n\nT"}, {"role": "user", "content": "a"},
                                {"role": "assistant", "content": "b"}, {"role": "user", "content": "q"}]
