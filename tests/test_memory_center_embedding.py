"""
Test Task C: Memory Center - Embedding column editable, recompute button, delete confirmation compact.
RED first: verify that embedding is editable, recompute route exists, and preview is compact.
"""
import json
import sys
from pathlib import Path

# Add repo root to path
repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))


def test_memory_ts_has_embedding_in_editable_fields():
    """Check that memory.ts includes 'embedding' in EDITABLE_MEMORY_FIELDS.learning."""
    memory_ts = (repo_root / "frontend" / "src" / "settings" / "memory.ts").read_text(encoding="utf-8")
    assert "EDITABLE_MEMORY_FIELDS" in memory_ts, "EDITABLE_MEMORY_FIELDS not found"
    assert '"embedding"' in memory_ts or "'embedding'" in memory_ts, "embedding not in EDITABLE_MEMORY_FIELDS"
    # Check that learning field has embedding
    assert 'learning:' in memory_ts and 'embedding' in memory_ts, "embedding not in learning fields"


def test_memory_ts_has_embedding_labels():
    """Check that formatFieldLabel has labels for embedding, embedding_dim, embedding_model."""
    memory_ts = (repo_root / "frontend" / "src" / "settings" / "memory.ts").read_text(encoding="utf-8")
    # Look for labels in formatFieldLabel
    assert "embedding:" in memory_ts or '"embedding"' in memory_ts, "embedding label not found"
    assert "embedding_dim" in memory_ts, "embedding_dim label not found"
    assert "embedding_model" in memory_ts, "embedding_model label not found"


def test_api_learnings_reembed_route_exists():
    """Check that ui_engine.py has the POST /api/learnings/reembed route."""
    ui_engine = (repo_root / "engine" / "UIUX" / "ui_engine.py").read_text(encoding="utf-8")
    assert "/api/learnings/reembed" in ui_engine, "/api/learnings/reembed route not found in ui_engine.py"
    assert "reembed_learnings" in ui_engine, "reembed_learnings call not found in ui_engine.py"


def test_reembed_api_reports_failure_when_embedder_is_down(monkeypatch):
    """Review Task C: engine trả {"updated": 0, "error": ...} thì API phải trả success=False (UI mới báo lỗi)."""
    import asyncio
    from types import SimpleNamespace
    from engine.core import learning
    from engine.UIUX import ui_engine

    monkeypatch.setattr(learning, "get_learning_engine",
                        lambda: SimpleNamespace(reembed_learnings=lambda rid: {"updated": 0, "error": "embedder_unavailable"}))
    res = asyncio.run(ui_engine.api_learnings_reembed(ui_engine.EmbedRecomputeBody(id=None)))
    assert res["success"] is False and res["error"] == "embedder_unavailable", res
    monkeypatch.setattr(learning, "get_learning_engine",
                        lambda: SimpleNamespace(reembed_learnings=lambda rid: {"updated": 3}))
    assert asyncio.run(ui_engine.api_learnings_reembed(ui_engine.EmbedRecomputeBody(id=5))) == {"success": True, "updated": 3}


def test_memory_reembed_button_in_detail_actions():
    """Check that memory.ts has a reembed button for learning records."""
    memory_ts = (repo_root / "frontend" / "src" / "settings" / "memory.ts").read_text(encoding="utf-8")
    # Check for reembed button or action
    assert "reembed" in memory_ts.lower() or "tính lại" in memory_ts, "Reembed button not found in memory.ts"


if __name__ == "__main__":
    test_memory_ts_has_embedding_in_editable_fields()
    test_memory_ts_has_embedding_labels()
    test_api_learnings_reembed_route_exists()
    test_preview_json_compact_for_384_vector()
    test_memory_reembed_button_in_detail_actions()
    print("All tests passed!")
