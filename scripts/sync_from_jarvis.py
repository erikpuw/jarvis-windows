"""Đồng bộ mã nguồn từ workspace chính (E:\\workspace\\jarvis) sang repo GitHub (E:\\workspace\\jarvis-windows).

Tự động:
- Bỏ qua rác: __pycache__, .git, .env, data/, logs/, node_modules/, frontend/dist, *.pem, mobile/
- Giữ nguyên các tệp cấu hình CI quan trọng: ruff.toml, requirements-ci.txt, .github/, .gitignore
- Báo cáo chi tiết các tệp được cập nhật.

Cách dùng:
  python scripts/sync_from_jarvis.py          # Đồng bộ thật
  python scripts/sync_from_jarvis.py --dry-run # Xem trước danh sách tệp sẽ chép
"""
import argparse
from pathlib import Path
import shutil
import sys

SOURCE_DIR = Path(r"E:\workspace\jarvis")
TARGET_DIR = Path(r"E:\workspace\jarvis-windows")

EXCLUDE_DIRS = {
    ".git", ".gitnexus", ".claude", ".gemini", ".vscode", ".impeccable",
    ".arch", ".superpowers", "data", "logs", "__pycache__", "node_modules",
    ".pytest_cache", ".ruff_cache", "mobile", ".agents", "dist"
}

EXCLUDE_FILES = {
    ".env", "cert.pem", "key.pem"
}

PRESERVE_TARGET_FILES = {
    "ruff.toml", "requirements-ci.txt", ".gitignore"
}

PRESERVE_TARGET_DIRS = {
    ".github"
}


def should_skip(rel_path: Path) -> bool:
    parts = set(rel_path.parts)
    if parts & EXCLUDE_DIRS:
        return True
    if parts & PRESERVE_TARGET_DIRS:
        return True
    if rel_path.name in EXCLUDE_FILES or rel_path.name in PRESERVE_TARGET_FILES:
        return True
    if rel_path.suffix == ".pyc":
        return True
    return False


def sync(dry_run: bool = False) -> int:
    if not SOURCE_DIR.exists():
        print(f"❌ Không tìm thấy thư mục nguồn: {SOURCE_DIR}")
        return 1
    if not TARGET_DIR.exists():
        print(f"❌ Không tìm thấy thư mục đích: {TARGET_DIR}")
        return 1

    copied = 0
    skipped = 0

    for src_path in SOURCE_DIR.rglob("*"):
        if src_path.is_dir():
            continue
        rel_path = src_path.relative_to(SOURCE_DIR)
        if should_skip(rel_path):
            skipped += 1
            continue

        dst_path = TARGET_DIR / rel_path
        # Chỉ copy nếu file đích chưa có hoặc nội dung khác nhau
        if dst_path.exists():
            try:
                if src_path.stat().st_size == dst_path.stat().st_size and src_path.read_bytes() == dst_path.read_bytes():
                    continue
            except Exception:
                pass

        if dry_run:
            print(f"[DRY-RUN] Sẽ chép: {rel_path}")
        else:
            dst_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_path, dst_path)
            print(f"Copied: {rel_path}")
        copied += 1

    action = "Sẽ chép" if dry_run else "Đã đồng bộ"
    print(f"\n✨ {action} {copied} tệp (bỏ qua {skipped} tệp rác/CI được bảo vệ).")
    if not dry_run and copied > 0:
        print("👉 Bước tiếp theo: chạy `python scripts/verify_ci.py` để kiểm tra độ xanh trước khi push!\n")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Đồng bộ an toàn từ jarvis sang jarvis-windows")
    parser.add_argument("--dry-run", action="store_true", help="Chỉ xem trước, không ghi file")
    args = parser.parse_args()
    sys.exit(sync(dry_run=args.dry_run))
