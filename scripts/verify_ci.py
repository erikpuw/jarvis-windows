"""Giả lập toàn bộ quy trình CI của GitHub Actions ngay trên máy local.

Chạy: python scripts/verify_ci.py (sync_from_jarvis.py tự gọi script này trước khi commit)
Lưu ý: GitHub chạy Ubuntu + requirements-ci.txt; máy local có thể có thêm gói (vd vieneu) nên local xanh
chưa chắc GitHub xanh.
"""
from pathlib import Path
import subprocess
import sys
import tempfile

REPO_DIR = Path(__file__).resolve().parents[1]
# Thư mục tạm riêng: pytest mặc định tạo symlink pytest-current, trên Windows có lúc kẹt quyền làm pytest báo lỗi
PYTEST_TMP = Path(tempfile.gettempdir()) / "jarvis-verify-ci"


def run_step(name: str, cmd: list[str]) -> bool:
    print(f"\n🔹 [CI CHECK] {name}...")
    res = subprocess.run(cmd, cwd=REPO_DIR)
    if res.returncode != 0:
        print(f"❌ [THẤT BẠI] Bước '{name}' bị lỗi (exit code {res.returncode})!")
        return False
    print(f"✅ [THÀNH CÔNG] {name} OK")
    return True


def main() -> int:
    steps = [
        ("1. Ruff Lint", ["ruff", "check", "."]),
        ("2. Compile Python", [sys.executable, "-m", "compileall", "-q", "server.py", "engine", "hooks", "plugins"]),
        ("3. Kiểm tra import nội bộ", [sys.executable, ".github/scripts/check_imports.py"]),
        ("4. Pytest (loại trừ tests/live)", [sys.executable, "-m", "pytest", "tests", "-q", "--ignore=tests/live", "--ignore-glob=tests/test_live_*",
                                            f"--basetemp={PYTEST_TMP}"]),
    ]

    for name, cmd in steps:
        if not run_step(name, cmd):
            print("\n🚨 DỪNG LẠI: Phát hiện lỗi, KHÔNG ĐƯỢC push lên GitHub để tránh báo đỏ CI!\n")
            return 1

    print("\n🎉 HOÀN TẤT: Toàn bộ 4 bước CI đều XANH!\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
