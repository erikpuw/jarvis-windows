"""scripts/clean_learnings_2026_10.py: mặc định chỉ xem; --apply sao lưu rồi xóa dòng rác + bỏ (ví dụ/Evidence: …)."""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.clean_learnings_2026_10 import clean


def _db(tmp_path):
    p = tmp_path / "jarvis.db"
    c = sqlite3.connect(p)
    c.execute("CREATE TABLE learnings (id INTEGER PRIMARY KEY, type TEXT, content TEXT, source TEXT, importance INT, "
              "created_at REAL, semantic_key TEXT, embedding TEXT, embedding_model TEXT)")
    c.executemany("INSERT INTO learnings (id, type, content, semantic_key, embedding) VALUES (?,?,?,?,'')", [
        (7, "user_fact", "Người dùng đã xác nhận rằng các kết quả hiện tại đã đạt yêu cầu.", "user_is_satisfied_with_current_performance"),
        (304, "user_fact", "Người dùng quan tâm đến việc tập gym.", "user_is_interested_in_agent_system"),
        (10, "lesson", "Khi yêu cầu không rõ (ví dụ: 'mở bài tôi thích'), hãy làm rõ.", "repeat_request_when_unclear"),
        (11, "user_fact", "Người dùng thích bài 'Making My Way'.", "music_preference_artist_song"),
    ])
    c.commit()
    c.close()
    return p


def _rows(p):
    c = sqlite3.connect(p)
    out = dict(c.execute("SELECT id, content FROM learnings").fetchall())
    c.close()
    return out


def test_dry_run_reports_and_touches_nothing(tmp_path):
    p = _db(tmp_path)
    before = _rows(p)
    r = clean(p, apply=False, backup_dir=tmp_path / "bk")
    assert sorted(r["delete"]) == [7, 304] and [i for i, _, _ in r["sanitize"]] == [10]
    assert r["backup"] is None and _rows(p) == before and not (tmp_path / "bk").exists()


def test_apply_backs_up_deletes_and_sanitizes(tmp_path):
    p = _db(tmp_path)
    r = clean(p, apply=True, backup_dir=tmp_path / "bk")
    assert r["backup"].exists() and 7 in _rows(r["backup"])
    assert _rows(p) == {10: "Khi yêu cầu không rõ, hãy làm rõ.", 11: "Người dùng thích bài 'Making My Way'."}
