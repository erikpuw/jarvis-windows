"""Dọn bảng learnings (nguồn của Preferences.md / Learning.md → STYLE.md → prompt chat), rà soát 2026-10-08.

- Xóa dòng rác: khóa sai nội dung, sự kiện một lần ghi thành sự thật lâu dài.
- Bỏ "(ví dụ: …)" / "(Evidence: …)" khỏi nội dung (engine.core.learning.strip_examples): câu của ngài lọt vào prompt chat.
Mặc định DRY-RUN (chỉ liệt kê). --apply: sao lưu data/jarvis.db rồi mới sửa, sau đó đồng bộ lại wiki.
    rtk python scripts/clean_learnings_2026_10.py
    rtk python scripts/clean_learnings_2026_10.py --apply
"""
import argparse
import datetime
import shutil
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from engine.core.learning import strip_examples  # noqa: E402

DEFAULT_DB = PROJECT_ROOT / "data" / "jarvis.db"
DEFAULT_BACKUP_DIR = PROJECT_ROOT / "data" / "backups"
DELETE_KEYS = {
    "user_is_interested_in_agent_system",          # khóa nói "agent system", nội dung là tập gym (trùng afternoon_activity_gym)
    "user_is_satisfied_with_current_performance",  # xác nhận một lần, không phải sự thật lâu dài
    "webui_improvement_feedback",                  # sự kiện một lần
}


def clean(db_path: Path, apply: bool = False, backup_dir: Path = DEFAULT_BACKUP_DIR) -> dict:
    conn = sqlite3.connect(str(db_path))
    rows = conn.execute("SELECT id, semantic_key, content FROM learnings").fetchall()
    delete = [i for i, key, _ in rows if key in DELETE_KEYS]
    sanitize = [(i, c, strip_examples(c)) for i, key, c in rows if key not in DELETE_KEYS and strip_examples(c) != c]
    backup = None
    if apply and (delete or sanitize):
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup = backup_dir / f"jarvis_{datetime.datetime.now():%Y%m%d_%H%M%S}_learnings.db"
        shutil.copy2(db_path, backup)
        conn.executemany("DELETE FROM learnings WHERE id=?", [(i,) for i in delete])
        # ponytail: embedding cũ giữ nguyên — learning không dùng cosine (đo 2026-10-01), nên không gọi lại máy embedding.
        conn.executemany("UPDATE learnings SET content=? WHERE id=?", [(new, i) for i, _, new in sanitize])
        conn.commit()
    conn.close()
    return {"delete": delete, "sanitize": sanitize, "backup": backup}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="sửa thật (mặc định chỉ xem)")
    args = ap.parse_args()
    r = clean(DEFAULT_DB, apply=args.apply)
    print("APPLY" if args.apply else "DRY-RUN (thêm --apply để sửa)")
    print(f"Xóa {len(r['delete'])} dòng: {r['delete']}")
    print(f"Làm sạch {len(r['sanitize'])} dòng:")
    for i, old, new in r["sanitize"]:
        print(f"  id {i}:\n    trước: {old}\n    sau:   {new}")
    if r["backup"]:
        print(f"Đã sao lưu: {r['backup']}")
        from engine.core.learning import get_learning_engine
        get_learning_engine()._sync_learning_wiki()  # Preferences.md / Learning.md khớp DB
        print("Đã đồng bộ lại data/wiki/System/Preferences.md và Learning.md")


if __name__ == "__main__":
    main()
