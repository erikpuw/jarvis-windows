"""Đồng bộ mã nguồn từ workspace chính (E:\\workspace\\jarvis) sang repo GitHub (E:\\workspace\\jarvis-windows),
chạy CI local, xanh thì tự commit. Push lên GitHub vẫn tự làm tay (lệnh in ra ở cuối).

Tự động:
- KHÓA BẢO VỆ: chỉ chạy trên nhánh 'main' của jarvis-windows, repo phải sạch (không có thay đổi chưa commit).
- Bỏ qua rác: __pycache__, .git, .env, data/, logs/, node_modules/, frontend/dist, *.pem, mobile/
- Giữ nguyên các tệp cấu hình CI quan trọng: ruff.toml, requirements-ci.txt, .github/, .gitignore
- Sau khi chép: chạy scripts/verify_ci.py; XANH thì git add + commit, ĐỎ thì không commit.

Cách dùng (đường dẫn đã cố định, nhưng nên đứng ở repo GitHub cho khỏi nhầm):
  cd E:\\workspace\\jarvis-windows
  git checkout main
  python scripts/sync_from_jarvis.py          # Đồng bộ + CI + commit
  python scripts/sync_from_jarvis.py --dry-run # Xem trước danh sách tệp sẽ chép
"""
import argparse
from datetime import datetime
from pathlib import Path
import shutil
import subprocess
import sys

SOURCE_DIR = Path(r"E:\workspace\jarvis")
TARGET_DIR = Path(r"E:\workspace\jarvis-windows")
TARGET_BRANCH = "main"

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


def git(*args: str, cwd: Path = TARGET_DIR) -> str:
    return subprocess.check_output(["git", *args], cwd=cwd, text=True, encoding="utf-8").strip()


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


def same_content(a: bytes, b: bytes) -> bool:
    """Bằng nhau, hoặc là văn bản chỉ khác CRLF/LF (jarvis lưu LF, jarvis-windows bật autocrlf)."""
    if a == b:
        return True
    if b"\0" in a or b"\0" in b:  # tệp nhị phân: so từng byte
        return False
    return a.replace(b"\r\n", b"\n") == b.replace(b"\r\n", b"\n")


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
        # Chỉ copy nếu file đích chưa có hoặc nội dung khác nhau (bỏ qua khác biệt CRLF/LF)
        if dst_path.exists():
            try:
                if same_content(src_path.read_bytes(), dst_path.read_bytes()):
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
    return 0


def main(dry_run: bool) -> int:
    print(f"📦 Nguồn (dự án chính): {SOURCE_DIR}")
    print(f"🎯 Repo GitHub:          {TARGET_DIR}  (nhánh {TARGET_BRANCH})\n")

    branch = git("branch", "--show-current")
    if branch != TARGET_BRANCH:
        print(f"❌ [LỖI BẢO VỆ]: Nhánh hiện tại là '{branch}', KHÔNG PHẢI '{TARGET_BRANCH}'.")
        print(f"👉 cd {TARGET_DIR} ; git checkout {TARGET_BRANCH}")
        return 1
    if not dry_run and git("status", "--porcelain"):
        print(f"❌ Repo {TARGET_DIR} đang có thay đổi chưa commit, dừng để không commit lẫn.")
        print("👉 Commit chúng trước, hoặc bỏ đi bằng: git restore .")
        return 1
    if git("status", "--porcelain", cwd=SOURCE_DIR):
        print(f"⚠️  Nguồn {SOURCE_DIR} có thay đổi CHƯA commit, chúng cũng sẽ được chép sang.\n")

    rc = sync(dry_run=dry_run)
    if rc or dry_run:
        return rc
    if not git("status", "--porcelain"):
        print("✅ Repo không có gì thay đổi, không cần commit.")
        return 0

    if subprocess.run([sys.executable, str(TARGET_DIR / "scripts" / "verify_ci.py")]).returncode != 0:
        print("🚨 CI ĐỎ: KHÔNG commit. Tệp đã chép vẫn nằm trong repo.")
        print(f"👉 Sửa ở nguồn {SOURCE_DIR}, rồi trong {TARGET_DIR}: git restore . ; chạy lại script này.")
        return 1

    git("add", "-A")
    git("commit", "-q", "-m", f"sync: tu jarvis {datetime.now():%Y-%m-%d %H:%M}")
    print(f"✅ Đã commit: {git('log', '--oneline', '-1')}")
    print("\n📤 BƯỚC CUỐI (tự làm tay):")
    print(f"  cd {TARGET_DIR}")
    print(f"  git push origin {TARGET_BRANCH}\n")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Đồng bộ jarvis → jarvis-windows (main), chạy CI, tự commit")
    parser.add_argument("--dry-run", action="store_true", help="Chỉ xem trước, không ghi file")
    args = parser.parse_args()
    sys.exit(main(dry_run=args.dry_run))
