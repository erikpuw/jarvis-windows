"""Vietnamese learning keys + evolution rule cap. Run: python tests/test_learning_key_and_rule_cap.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.core.learning import LearningEngine, _lexically_similar


def test_vietnamese_key_keeps_letters_instead_of_underscores():
    assert LearningEngine._normalise_key("Chỉ chạy khi cần") == "chi_chay_khi_can"
    assert LearningEngine._normalise_key("đồng_ý") == "dong_y"
    assert LearningEngine._normalise_key("snake_case_key") == "snake_case_key"


def test_lexical_dedupe_catches_rephrased_and_keeps_distinct():
    assert _lexically_similar("Chỉ chạy khi được yêu cầu, không tự động chạy khi đang hỏi đáp.",
                              "Chỉ chạy khi được yêu cầu, không chạy tự động khi đang hỏi đáp")
    assert not _lexically_similar("Sử dụng giọng miền Nam Sài Gòn", "Người dùng thích cơm tấm, bò né")


def test_consolidate_keeps_newest_and_removes_older_duplicate(tmp_path=None):
    import sqlite3, tempfile
    from unittest import mock
    db = Path(tempfile.mkdtemp()) / "l.db"
    conn = sqlite3.connect(db); conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE learnings (id INTEGER PRIMARY KEY, type TEXT, content TEXT, embedding TEXT)")
    conn.executemany("INSERT INTO learnings (type, content, embedding) VALUES (?,?,'')", [
        ("lesson", "Không tự động chạy công cụ khi người dùng chỉ đang trò chuyện"),
        ("lesson", "Không tự động chạy công cụ khi người dùng chỉ đang trò chuyện thông thường"),
        ("preference", "Thích cơm tấm"),
    ])
    conn.commit(); conn.close()
    le = LearningEngine.__new__(LearningEngine)
    def _conn():
        c = sqlite3.connect(db); c.row_factory = sqlite3.Row; return c
    le._get_learning_db = _conn
    le._sync_learning_wiki = lambda: None
    assert le.consolidate_learnings() == 1
    ids = [r["id"] for r in _conn().execute("SELECT id FROM learnings ORDER BY id")]
    assert ids == [2, 3], ids


if __name__ == "__main__":
    test_vietnamese_key_keeps_letters_instead_of_underscores()
    test_cap_rules_dedupes_and_limits()
    test_lexical_dedupe_catches_rephrased_and_keeps_distinct()
    test_newest_entries_keeps_header_and_last_n()
    test_consolidate_keeps_newest_and_removes_older_duplicate()
    print("OK: learning key / rule cap tests passed")
