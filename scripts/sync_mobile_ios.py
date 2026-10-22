"""Đồng bộ an toàn mã nguồn từ repo gốc E:\\workspace\\jarvis-mobile sang E:\\workspace\\jarvis-windows\\frontend\\mobile.

Đặc điểm an toàn:
- KHÓA BẢO VỆ: Chỉ cho phép chạy trên nhánh 'feat/mobile-ios', TUYỆT ĐỐI không chạm vào 'main'.
- Chỉ chép file mà git ở nguồn đang theo dõi (cả ios/ lẫn android/), nên rác build và file sinh tự động
  (.dart_tool/, build/, .gradle/, ephemeral/, *.iml, local.properties...) không bao giờ bị chép sang.
- File đích đang được git theo dõi nhưng đã bị xóa ở nguồn sẽ bị xóa theo (test/mã cũ không nằm lại).
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


def tracked_files(directory: Path) -> set[str]:
    """Đường dẫn (tương đối với directory) của các file git đang theo dõi trong directory."""
    out = subprocess.check_output(["git", "ls-files", "-z"], cwd=directory, text=True, encoding="utf-8")
    return {p for p in out.split("\0") if p}


def sync(source_dir: Path, target_dir: Path, dry_run: bool = False) -> int:
    print(f"📦 Nguồn: {source_dir}")
    print(f"🎯 Đích:  {target_dir}\n")

    source_files = tracked_files(source_dir)
    copied = 0
    for rel in sorted(source_files):
        src_path = source_dir / rel
        if not src_path.is_file():  # đã xóa ở nguồn nhưng chưa commit
            continue
        dst_path = target_dir / rel
        if dst_path.is_file() and src_path.read_bytes() == dst_path.read_bytes():
            continue
        if dry_run:
            print(f"[DRY-RUN] Sẽ chép: {rel}")
        else:
            dst_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_path, dst_path)
            print(f"Copied: {rel}")
        copied += 1

    removed = 0
    for rel in sorted(tracked_files(target_dir) - source_files):
        dst_path = target_dir / rel
        if not dst_path.is_file():
            continue
        if dry_run:
            print(f"[DRY-RUN] Sẽ xóa: {rel}")
        else:
            dst_path.unlink()
            print(f"Removed: {rel}")
        removed += 1

    action = "Sẽ" if dry_run else "Đã"
    print(f"\n✨ {action} chép {copied} tệp, xóa {removed} tệp.")
    if not dry_run:
        print("👉 Bước tiếp theo: chạy `python scripts/verify_mobile_ios.py` để chạy toàn bộ test iOS trước khi push!\n")
    return 0


def main(dry_run: bool) -> int:
    if not verify_branch():
        return 1
    source_dir = resolve_source()
    if not source_dir:
        print(f"❌ Không tìm thấy mã nguồn Flutter tại {PRIMARY_SOURCE} hoặc {FALLBACK_SOURCE}")
        return 1
    if not TARGET_DIR.exists():
        print(f"❌ Không tìm thấy thư mục đích: {TARGET_DIR}")
        return 1
    return sync(source_dir, TARGET_DIR, dry_run=dry_run)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Đồng bộ riêng nhánh feat/mobile-ios từ jarvis-mobile")
    parser.add_argument("--dry-run", action="store_true", help="Chỉ xem trước, không ghi file")
    args = parser.parse_args()
    sys.exit(main(dry_run=args.dry_run))
