"""Registry (memory_registry) đã bị gỡ (2026-10-01, ngài chọn phương án A): không còn nơi nào ghi vào bảng này
từ khi upsert_distilled_memory bị xoá (3d93b45); 12/14 dòng mồ côi; không luồng chat/learning nào đọc nó."""
import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import engine.core.memory as memory


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(memory, "DB_PATH", tmp_path / "jarvis.db")
    memory.init_db()
    return tmp_path / "jarvis.db"


def _tables(path):
    c = sqlite3.connect(path)
    names = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    c.close()
    return names


def test_init_db_no_longer_creates_registry(db):
    assert "memory_registry" not in _tables(db)


def test_delete_memory_works_without_registry_table(db):
    mem_id = memory.save_memory("Người dùng thích cà phê sữa", "preference", "test", 5)
    assert memory.delete_memory(mem_id) is True


def test_delete_memory_works_with_leftover_registry_table(db):
    """DB cũ của ngài còn bảng (chưa chạy script xoá): code mới không được vấp vào nó."""
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE memory_registry (id INTEGER PRIMARY KEY, semantic_key TEXT, mem_type TEXT, memory_id INTEGER, wiki_scope TEXT, updated_at REAL)")
    c.commit(); c.close()
    mem_id = memory.save_memory("x", "fact", "test", 5)
    assert memory.delete_memory(mem_id) is True


def test_registry_kind_is_gone_from_memory_control(db):
    assert not hasattr(memory, "list_registry_records")
    assert not hasattr(memory, "list_memory_records")
    assert "registry" not in memory.get_memory_control_counts()
    assert "memories" not in memory.get_memory_control_counts()
    for kind in ("registry", "memory"):
        for fn, args in ((memory.preview_memory_dependencies, (kind, 1)),
                         (memory.update_memory_control_record, (kind, 1, {"wiki_scope": "x"})),
                         (memory.delete_memory_control_record, (kind, 1))):
            with pytest.raises(ValueError, match="unsupported_kind"):
                fn(*args)


def test_ui_and_frontend_no_longer_expose_registry():
    ui = (ROOT / "engine" / "UIUX" / "ui_engine.py").read_text(encoding="utf-8")
    ts = (ROOT / "frontend" / "src" / "settings" / "memory.ts").read_text(encoding="utf-8")
    assert "memory-registry" not in ui and "list_registry_records" not in ui and '"registry"' not in ui
    assert "registry" not in ts.lower()


def _load_script():
    if not (ROOT / "scripts" / "drop_memory_registry.py").exists():
        pytest.skip("scripts/drop_memory_registry.py không có trong repo (script dọn dữ liệu cũ, chỉ có ở máy tác giả)")
    spec = importlib.util.spec_from_file_location("drop_memory_registry", ROOT / "scripts" / "drop_memory_registry.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _legacy_db(tmp_path):
    path = tmp_path / "jarvis.db"
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE memories (id INTEGER PRIMARY KEY, content TEXT)")
    c.execute("INSERT INTO memories VALUES (1, 'còn')")
    c.execute("CREATE TABLE memory_registry (id INTEGER PRIMARY KEY, semantic_key TEXT, mem_type TEXT, memory_id INTEGER, wiki_scope TEXT, updated_at REAL)")
    c.executemany("INSERT INTO memory_registry(semantic_key, mem_type, memory_id, updated_at) VALUES (?, 'fact', ?, 1)",
                  [("a", 1), ("b", 99)])
    c.commit(); c.close()
    return path


def test_drop_script_dry_run_changes_nothing(tmp_path, capsys):
    path = _legacy_db(tmp_path)
    assert _load_script().main(["--db", str(path), "--backup-dir", str(tmp_path / "bk")]) == 0
    assert "memory_registry" in _tables(path)
    assert not (tmp_path / "bk").exists()
    out = capsys.readouterr().out
    assert "2" in out and "mồ côi" in out  # báo số dòng và số dòng mồ côi


def test_drop_script_apply_backs_up_then_drops(tmp_path):
    path = _legacy_db(tmp_path)
    assert _load_script().main(["--db", str(path), "--backup-dir", str(tmp_path / "bk"), "--apply"]) == 0
    assert "memory_registry" not in _tables(path)
    backups = list((tmp_path / "bk").glob("jarvis-*.db"))
    assert len(backups) == 1 and "memory_registry" in _tables(backups[0])
    c = sqlite3.connect(path)
    assert c.execute("SELECT content FROM memories").fetchone()[0] == "còn"  # bảng khác nguyên vẹn
    c.close()
    # chạy lại khi bảng đã mất: không lỗi
    assert _load_script().main(["--db", str(path), "--backup-dir", str(tmp_path / "bk"), "--apply"]) == 0
