"""Xoá bảng memory_registry khỏi data/jarvis.db (đã gỡ khỏi code 2026-10-01).

Bảng này chỉ từng được ghi bởi upsert_distilled_memory (bị xoá ở commit 3d93b45) và không luồng nào đọc nó.
Mặc định CHỈ XEM (không đụng DB). Chạy với --apply để: sao lưu DB vào data/backups/jarvis-<thời gian>.db rồi DROP TABLE.
Chạy khi tắt JARVIS:  python scripts/drop_memory_registry.py            (xem)
                      python scripts/drop_memory_registry.py --apply     (xoá thật, có sao lưu)
"""
import argparse
import datetime
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "data" / "jarvis.db"
DEFAULT_BACKUP_DIR = ROOT / "data" / "backups"


def _has_table(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='memory_registry'").fetchone() is not None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--backup-dir", type=Path, default=DEFAULT_BACKUP_DIR)
    ap.add_argument("--apply", action="store_true", help="xoá thật (mặc định chỉ xem)")
    args = ap.parse_args(argv)

    conn = sqlite3.connect(args.db)
    try:
        if not _has_table(conn):
            print("Không có bảng memory_registry: không còn gì để xoá.")
            return 0
        total = conn.execute("SELECT COUNT(*) FROM memory_registry").fetchone()[0]
        orphan = 0
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='memories'").fetchone():
            orphan = conn.execute("SELECT COUNT(*) FROM memory_registry WHERE memory_id NOT IN (SELECT id FROM memories)").fetchone()[0]
        print(f"memory_registry: {total} dòng, {orphan} mồ côi (trỏ tới bản ghi memories không còn).")
        if not args.apply:
            print("Chế độ XEM: chưa thay đổi gì. Chạy lại với --apply để sao lưu rồi xoá bảng.")
            return 0
        args.backup_dir.mkdir(parents=True, exist_ok=True)
        backup = args.backup_dir / f"jarvis-{datetime.datetime.now():%Y%m%d-%H%M%S}.db"
        with sqlite3.connect(backup) as dest:
            conn.backup(dest)
        dest.close()
        conn.execute("DROP TABLE memory_registry")
        conn.execute("DROP INDEX IF EXISTS idx_memory_registry_memory")
        conn.commit()
        print(f"Đã sao lưu vào {backup} và xoá bảng memory_registry.")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
