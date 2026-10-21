"""Bảng outcomes/workflows (spec 2026-10-13). Run: python -m pytest tests/test_outcomes_workflows.py -v"""
import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import engine.core.memory as memory
from engine.core import learning

OLD_SCHEMA = """
CREATE TABLE agent_outcomes (id INTEGER PRIMARY KEY AUTOINCREMENT, agent TEXT NOT NULL, query TEXT NOT NULL,
    status TEXT NOT NULL, result TEXT DEFAULT '', traces TEXT DEFAULT '[]', created_at REAL NOT NULL);
CREATE TABLE validated_workflows (id INTEGER PRIMARY KEY AUTOINCREMENT, agent TEXT NOT NULL, intent TEXT NOT NULL,
    tool_chain TEXT NOT NULL, argument_keys TEXT NOT NULL, success_evidence TEXT NOT NULL,
    validation_count INTEGER NOT NULL DEFAULT 1, status TEXT NOT NULL DEFAULT 'validated', wiki_path TEXT NOT NULL,
    sample_queries TEXT NOT NULL DEFAULT '[]', created_at REAL NOT NULL, updated_at REAL NOT NULL,
    UNIQUE(agent, tool_chain));
"""


def _patch_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(learning, "MEMORY_DB_PATH", tmp_path / "jarvis.db")
    monkeypatch.setattr(learning, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(learning, "LEARNING_HUB_WIKI_PATH", tmp_path / "hub.md")
    for name in ("PREFERENCES_WIKI_PATH", "LESSONS_WIKI_PATH"):
        monkeypatch.setattr(learning, name, tmp_path / f"{name}.md")
    wf = tmp_path / "Workflows"
    monkeypatch.setattr(learning, "WORKFLOWS_WIKI_DIR", wf)
    monkeypatch.setattr(learning, "WORKFLOWS_HUB_WIKI_PATH", wf / "Công cụ.md")
    monkeypatch.setattr(memory, "DB_PATH", tmp_path / "jarvis.db")
    monkeypatch.setattr(learning.LearningEngine, "_embed_text", staticmethod(lambda c: [0.0] * 8))
    return wf


@pytest.fixture
def engine(tmp_path, monkeypatch):
    _patch_paths(tmp_path, monkeypatch)
    memory.init_db()
    return learning.LearningEngine()


def _tables(db: Path) -> set[str]:
    c = sqlite3.connect(db)
    names = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    c.close()
    return names


def test_migration_moves_outcomes_and_drops_agent_workflows(tmp_path, monkeypatch):
    wf = _patch_paths(tmp_path, monkeypatch)
    memory.init_db()
    c = sqlite3.connect(tmp_path / "jarvis.db")
    c.executescript(OLD_SCHEMA)
    c.execute("INSERT INTO agent_outcomes(agent,query,status,result,traces,created_at) "
              "VALUES('desktop','mở notepad','success','ok','[]',5)")
    c.execute("INSERT INTO validated_workflows(agent,intent,tool_chain,argument_keys,success_evidence,wiki_path,"
              "created_at,updated_at) VALUES('market','giá vàng','[\"market_price\"]','[]','ok',?,1,1)",
              (str(wf / "market.md"),))
    c.commit()
    c.close()
    wf.mkdir()
    (wf / "market.md").write_text("cũ", encoding="utf-8")

    le = learning.LearningEngine()

    names = _tables(tmp_path / "jarvis.db")
    assert {"outcomes", "workflows"} <= names and not {"agent_outcomes", "validated_workflows"} & names
    page = le.list_outcome_records()
    assert page["total"] == 1 and page["items"][0]["tools"] == "desktop"
    assert le.list_workflow_records()["total"] == 0
    assert not (wf / "market.md").exists()
    learning.LearningEngine()  # chạy lại init không lỗi
    assert le.list_outcome_records()["total"] == 1


def test_outcome_list_filter_counts_and_delete(engine, tmp_path):
    c = sqlite3.connect(tmp_path / "jarvis.db")
    c.execute("INSERT INTO outcomes(tools,query,status,result,traces,created_at) VALUES('weather','thời tiết','success','ok','[]',1)")
    c.execute("INSERT INTO outcomes(tools,query,status,result,traces,created_at) VALUES('open_app','mở word','failed','x','[]',2)")
    c.commit()
    c.close()
    assert engine.list_outcome_records(tool="weather")["total"] == 1
    assert engine.get_memory_control_counts()["outcomes"] == 2
    oid = engine.list_outcome_records(tool="open_app")["items"][0]["id"]
    assert engine.delete_learning_control_record("outcome", oid) is True
    assert engine.get_memory_control_counts()["outcomes"] == 1


def test_workflow_columns_update_and_delete(engine, tmp_path):
    wf = learning.WORKFLOWS_WIKI_DIR
    c = sqlite3.connect(tmp_path / "jarvis.db")
    c.execute("INSERT INTO workflows(tools,intent,tool_chain,sample_queries,success_evidence,validation_count,"
              "wiki_path,created_at,updated_at) VALUES('weather','thời tiết huế',?,'[\"thời tiết huế\"]','ok',1,?,1,1)",
              (json.dumps([{"tool": "weather", "args": {"location": "huế"}, "say": "Tôi xem."}]), str(wf / "weather.md")))
    c.commit()
    c.close()
    item = engine.list_workflow_records()["items"][0]
    assert set(item) == {"id", "tools", "intent", "tool_chain", "sample_queries", "success_evidence",
                         "validation_count", "wiki_path", "created_at", "updated_at"}
    assert engine.update_learning_control_record("workflow", item["id"], {"intent": "thời tiết Huế"}) is True
    assert (wf / "weather.md").read_text(encoding="utf-8").startswith("# Workflows: weather")
    assert engine.delete_learning_control_record("workflow", item["id"]) is True
    assert engine.get_memory_control_counts()["workflows"] == 0
    assert not (wf / "weather.md").exists()


CHAIN = [{"tool": "open_app", "args": {"app_name": "notepad"}, "say": "Tôi mở Notepad."}]


def test_normalize_query():
    assert learning.normalize_query("  Mở   Notepad!! ") == "mở notepad"
    assert learning.normalize_query("Giá vàng, hôm nay?") == "giá vàng hôm nay"


def test_record_outcome(engine):
    oid = engine.record_outcome("weather", "thời tiết huế", "success", "Huế 28 độ", [{"tool": "weather"}])
    item = engine.list_outcome_records()["items"][0]
    assert item["id"] == oid and item["tools"] == "weather" and json.loads(item["traces"]) == [{"tool": "weather"}]


def test_save_workflow_create_then_merge(engine):
    wid = engine.save_workflow("Mở Notepad", CHAIN, "Đã mở Notepad.")
    again = engine.save_workflow("mở notepad giúp tôi", CHAIN, "Xong.")
    assert again == wid
    item = engine.list_workflow_records()["items"][0]
    assert item["tools"] == "open_app" and item["intent"] == "Mở Notepad" and item["validation_count"] == 2
    assert json.loads(item["sample_queries"]) == ["mở notepad", "mở notepad giúp tôi"]
    assert (learning.WORKFLOWS_WIKI_DIR / "open_app.md").is_file()


def test_sentence_moves_to_newest_workflow(engine):
    first = engine.save_workflow("mở word", CHAIN, "a")
    other = [{"tool": "open_app", "args": {"app_name": "word"}, "say": "Tôi mở Word."}]
    second = engine.save_workflow("mở word", other, "b")
    rows = {r["id"]: json.loads(r["sample_queries"]) for r in engine.list_workflow_records()["items"]}
    assert rows[first] == [] and rows[second] == ["mở word"]
    assert engine.find_workflow("Mở Word")["id"] == second


def test_find_workflow_normalizes(engine):
    wid = engine.save_workflow("mở notepad", CHAIN, "ok")
    got = engine.find_workflow("Mở Notepad!")
    assert got == {"id": wid, "tools": "open_app", "tool_chain": CHAIN}
    assert engine.find_workflow("mở notepad đi") is None
    assert engine.find_workflow("") is None


def test_sample_queries_capped_at_20(engine):
    for i in range(25):
        engine.save_workflow(f"mở notepad {i}", CHAIN, "ok")
    samples = json.loads(engine.list_workflow_records()["items"][0]["sample_queries"])
    assert len(samples) == 20 and samples[-1] == "mở notepad 24"
