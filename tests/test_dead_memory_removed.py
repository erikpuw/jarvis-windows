"""Semantic memory, wiki_sync và Redis đã gỡ: dream chỉ lưu tóm tắt vào archive jsonl."""
import asyncio
import importlib
import json

import pytest

from engine.core import dream, memory


@pytest.mark.parametrize("module", ["engine.core.wiki_sync", "engine.server.redis_server"])
def test_dead_modules_are_gone(module):
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(module)


def test_memory_has_no_semantic_store():
    for name in ("SemanticMemoryEngine", "save_memory", "get_important_memories",
                 "delete_memory", "update_memory", "delete_memory_by_source"):
        assert not hasattr(memory, name), name


def test_dream_keeps_summaries_in_archive_jsonl(tmp_path, monkeypatch):
    rows = [
        {"id": 1, "role": "user", "content": "a", "created_at": 1.0},
        {"id": 2, "role": "assistant", "content": "b", "created_at": 2.0},
    ]
    deleted = []
    monkeypatch.setattr(dream, "DREAM_ARCHIVE_DIR", tmp_path)
    monkeypatch.setattr(dream, "_fetch_old_messages", lambda cutoff: rows)
    monkeypatch.setattr(dream, "_delete_messages_by_id", deleted.extend)

    async def fake_summary(chunk):
        return {"trivial": False, "summary": "Ngài thích cà phê"}

    monkeypatch.setattr(dream, "_summarize_message_chunk", fake_summary)
    report = asyncio.run(dream._dream_consolidate_messages("run1", 30))

    assert report["kept"] == 1 and deleted == [1, 2]
    lines = (tmp_path / "summaries" / "run1.jsonl").read_text(encoding="utf-8").splitlines()
    saved = json.loads(lines[0])
    assert saved["summary"] == "Ngài thích cà phê" and saved["message_ids"] == [1, 2]


def test_learning_embed_uses_shared_embed_client(monkeypatch):
    from engine.core import learning
    from engine.server import llm_server

    class Fake:
        class embeddings:
            @staticmethod
            def create(input, model):
                return type("R", (), {"data": [type("D", (), {"embedding": [0.1, 0.2]})()]})()

    monkeypatch.setattr(llm_server, "get_embed_client", lambda: Fake())
    assert learning.LearningEngine._embed_text("x") == [0.1, 0.2]
    monkeypatch.setattr(llm_server, "get_embed_client", lambda: None)
    assert learning.LearningEngine._embed_text("x") is None
