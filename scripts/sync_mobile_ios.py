"""Đồng bộ an toàn mã nguồn từ repo gốc E:\\workspace\\jarvis-mobile sang E:\\workspace\\jarvis-windows\\frontend\\mobile.

Đặc điểm an toàn:
- KHÓA BẢO VỆ: Chỉ cho phép chạy trên nhánh 'feat/mobile-ios', TUYỆT ĐỐI không chạm vào 'main'.
- Tự động bỏ qua rác build: .dart_tool/, build/, .gradle/, .idea/, *.iml, ephemeral/, android/
- Chỉ cập nhật những file thực sự có thay đổi nội dung.

Cách dùng:
  python scripts/sync_mobile_ios.py          # Đồng bộ thật
  python scripts/sync_mobile_ios.py --dry-run # Xem trước danh sách thay đổi
"""
import argparse
from pathlib import Path
import shutil
import subprocess
import sys

TARGET_BRANCH = "feat/mobile-ios"
PRIMARY_SOURCE = Path(r"E:\workspace\jarvis-mobile\mobile")
FALLBACK_SOURCE = Path(r"E:\workspace\jarvis-mobile")
TARGET_DIR = Path(r"E:\workspace\jarvis-windows\frontend\mobile")

EXCLUDE_DIRS = {
    ".git", ".dart_tool", "build", ".gradle", ".idea", ".vscode",
    "ephemeral", "Pods", ".symlinks", "android"
}

EXCLUDE_EXTENSIONS = {
    ".iml", ".DS_Store"
}

EXCLUDE_FILES = {
    ".flutter-plugins-dependencies"
}


def verify_branch() -> bool:
    try:
        branch = subprocess.check_output(
            ["git", "branch", "--show-current"],
            cwd=TARGET_DIR.parents[1],
            text=True
        ).strip()
        if branch != TARGET_BRANCH:
            print(f"❌ [LỖI BẢO VỆ]: Nhánh hiện tại là '{branch}', KHÔNG PHẢI '{TARGET_BRANCH}'.")
            print(f"👉 Vui lòng chuyển sang nhánh iOS trước: git checkout {TARGET_BRANCH}")
            return False
        return True
    except Exception as exc:
        print(f"❌ Không thể kiểm tra nhánh git: {exc}")
        return False


def resolve_source() -> Path | None:
    if PRIMARY_SOURCE.exists() and (PRIMARY_SOURCE / "pubspec.yaml").is_file():
        return PRIMARY_SOURCE
    if FALLBACK_SOURCE.exists() and (FALLBACK_SOURCE / "pubspec.yaml").is_file():
        return FALLBACK_SOURCE
    return None


def should_skip(rel_path: Path) -> bool:
    parts = set(rel_path.parts)
    if parts & EXCLUDE_DIRS:
        return True
    if rel_path.suffix in EXCLUDE_EXTENSIONS:
        return True
    if rel_path.name in EXCLUDE_FILES:
        return True
    return False


def sync(dry_run: bool = False) -> int:
    if not verify_branch():
        return 1

    source_dir = resolve_source()
    if not source_dir:
        print(f"❌ Không tìm thấy mã nguồn Flutter tại {PRIMARY_SOURCE} hoặc {FALLBACK_SOURCE}")
        return 1

    if not TARGET_DIR.exists():
        print(f"❌ Không tìm thấy thư mục đích: {TARGET_DIR}")
        return 1

    print(f"📦 Nguồn: {source_dir}")
    print(f"🎯 Đích:  {TARGET_DIR}\n")

    copied = 0
    skipped = 0

    for src_path in source_dir.rglob("*"):
        if src_path.is_dir():
            continue
        rel_path = src_path.relative_to(source_dir)
        if should_skip(rel_path):
            skipped += 1
            continue

        dst_path = TARGET_DIR / rel_path
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
    print(f"\n✨ {action} {copied} tệp (bỏ qua {skipped} tệp rác/build).")
    if not dry_run:
        print("👉 Bước tiếp theo: chạy `python scripts/verify_mobile_ios.py` để chạy toàn bộ test iOS trước khi push!\n")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Đồng bộ riêng nhánh feat/mobile-ios từ jarvis-mobile")
    parser.add_argument("--dry-run", action="store_true", help="Chỉ xem trước, không ghi file")
    args = parser.parse_args()
    sys.exit(sync(dry_run=args.dry_run))
