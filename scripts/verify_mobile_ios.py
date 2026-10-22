"""Kiểm tra toàn bộ CI test cho nhánh feat/mobile-ios trước khi push lên GitHub.

Chạy: python scripts/verify_mobile_ios.py

Bao gồm:
1. Khóa bảo vệ nhánh (chỉ chạy trên feat/mobile-ios).
2. Flutter pub get (đồng bộ package).
3. Flutter analyze (kiểm tra lint/syntax sạch sẽ).
4. Flutter test (chạy 345+ unit & widget test cho app mobile).
5. Test script sync_mobile_ios.
App mobile chỉ được kiểm thử ở đây (local); GitHub CI (ci.yml) bỏ qua frontend/mobile, Codemagic chỉ build iOS.
"""
from pathlib import Path
import shutil
import subprocess
import sys

TARGET_BRANCH = "feat/mobile-ios"
REPO_DIR = Path(__file__).resolve().parents[1]
MOBILE_DIR = REPO_DIR / "frontend" / "mobile"
FLUTTER_BIN = shutil.which("flutter") or "flutter"


def verify_branch() -> bool:
    try:
        branch = subprocess.check_output(
            ["git", "branch", "--show-current"],
            cwd=REPO_DIR,
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


def run_cmd(name: str, cmd: list[str], cwd: Path | None = None) -> bool:
    print(f"\n🔹 [MOBILE CI] {name}...")
    # shell=True trên Windows để thực thi file .bat/.cmd của Flutter
    res = subprocess.run(cmd, cwd=cwd or REPO_DIR, shell=(sys.platform == "win32"))
    if res.returncode != 0:
        print(f"❌ [THẤT BẠI] Bước '{name}' gặp lỗi (exit code {res.returncode})!")
        return False
    print(f"✅ [THÀNH CÔNG] {name} OK")
    return True


def main() -> int:
    if not verify_branch():
        return 1

    if not MOBILE_DIR.exists():
        print(f"❌ Không tìm thấy thư mục: {MOBILE_DIR}")
        return 1

    steps = [
        ("1. Flutter Pub Get", [FLUTTER_BIN, "pub", "get"], MOBILE_DIR),
        ("2. Flutter Analyze (Lint & Typecheck)", [FLUTTER_BIN, "analyze"], MOBILE_DIR),
        ("3. Flutter Unit & Widget Tests", [FLUTTER_BIN, "test"], MOBILE_DIR),
        ("4. Sync Script Test", [sys.executable, "-m", "pytest", "tests/test_sync_mobile_ios.py", "-q",
                                 "-p", "no:cacheprovider"], REPO_DIR),
    ]

    for name, cmd, cwd in steps:
        if not run_cmd(name, cmd, cwd):
            print("\n🚨 DỪNG LẠI: Phát hiện lỗi kiểm thử! KHÔNG ĐƯỢC push để tránh báo đỏ CI!\n")
            return 1

    print("\n🎉 HOÀN TẤT: Toàn bộ kiểm thử Mobile đều XANH 100%!\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
