import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import engine.core.learning as learning
import engine.core.memory as memory


def test_message_ids_reuse_gaps_and_restart_after_clear(monkeypatch, tmp_path):
    monkeypatch.setattr(memory, "DB_PATH", tmp_path / "messages.db")
    memory.init_db()

    ids = [memory.save_message("user", f"message {n}", "session") for n in range(1, 4)]
    memory.save_feedback(ids[1], 1, "old message feedback")
    conn = memory._get_db()
    memory.delete_messages_by_id(conn, [ids[1]])
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM feedback").fetchone()[0] == 0
    conn.close()

    assert memory.save_message("user", "message 4", "session") == ids[1]
    conn = memory._get_db()
    assert [row[0] for row in conn.execute("SELECT id FROM messages ORDER BY id")] == [1, 2, 3]
    conn.close()

    conn = memory._get_db()
    conn.execute("DELETE FROM messages")
    conn.commit()
    conn.close()
    assert memory.save_message("user", "message after clear", "session") == 1


def test_learning_ids_reuse_gaps_and_restart_after_clear(monkeypatch, tmp_path):
    monkeypatch.setattr(learning, "MEMORY_DB_PATH", tmp_path / "learning.db")
    monkeypatch.setattr(learning, "LEGACY_LEARN_DB_PATH", tmp_path / "missing-legacy.db")
    engine = learning.LearningEngine.__new__(learning.LearningEngine)
    monkeypatch.setattr(engine, "_sync_learning_wiki", lambda: None)
    monkeypatch.setattr(engine, "_embedding_fields", lambda _content: ("[]", ""))
    engine._init_db()

    facts = [
        "The capital of France is Paris.",
        "Earth has seven continents.",
        "SQL tables store rows and columns.",
    ]
    for n, fact in enumerate(facts, 1):
        assert engine._store_learning(fact, "fact", f"fact-{n}")
    conn = engine._get_learning_db()
    conn.execute("DELETE FROM learnings WHERE id=2")
    conn.commit()
    conn.close()

    assert engine._store_learning("The Pacific Ocean is the largest.", "fact", "fact-4")
    conn = engine._get_learning_db()
    assert conn.execute(
        "SELECT id FROM learnings WHERE semantic_key='fact-4'"
    ).fetchone()[0] == 2
    assert [row[0] for row in conn.execute("SELECT id FROM learnings ORDER BY id")] == [1, 2, 3]
    conn.execute("DELETE FROM learnings")
    conn.commit()
    conn.close()

    assert engine._store_learning(
        "Python was created by Guido van Rossum.", "fact", "fact-after-clear"
    )
    conn = engine._get_learning_db()
    assert conn.execute(
        "SELECT id FROM learnings WHERE semantic_key='fact-after-clear'"
    ).fetchone()[0] == 1
    conn.close()
