"""scripts/sync_mobile_ios.py: chỉ chép file git đang theo dõi ở nguồn (kể cả android/), xóa file đích đã bị xóa ở nguồn."""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.sync_mobile_ios import sync


def _repo(root: Path, files: dict[str, str], track: list[str]) -> Path:
    root.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    subprocess.run(["git", "add", "-f", *track], cwd=root, check=True)
    return root


def test_sync_copies_tracked_files_and_removes_stale(tmp_path):
    src = _repo(tmp_path / "src", {
        "lib/main.dart": "new",
        "android/app/build.gradle.kts": "android",
        "ios/Flutter/ephemeral/flutter_lldbinit": "generated",
    }, track=["lib/main.dart", "android/app/build.gradle.kts"])
    dst = _repo(tmp_path / "dst", {
        "lib/main.dart": "old",
        "lib/stale.dart": "gone upstream",
        "android/.gradle/cache.bin": "local build cache",
    }, track=["lib/main.dart", "lib/stale.dart"])

    assert sync(src, dst) == 0

    assert (dst / "lib/main.dart").read_text(encoding="utf-8") == "new"
    assert (dst / "android/app/build.gradle.kts").read_text(encoding="utf-8") == "android"
    assert not (dst / "lib/stale.dart").exists()
    assert not (dst / "ios/Flutter/ephemeral/flutter_lldbinit").exists()
    assert (dst / "android/.gradle/cache.bin").exists()


def test_dry_run_changes_nothing(tmp_path):
    src = _repo(tmp_path / "src", {"lib/main.dart": "new"}, track=["lib/main.dart"])
    dst = _repo(tmp_path / "dst", {"lib/main.dart": "old", "lib/stale.dart": "x"},
                track=["lib/main.dart", "lib/stale.dart"])

    assert sync(src, dst, dry_run=True) == 0

    assert (dst / "lib/main.dart").read_text(encoding="utf-8") == "old"
    assert (dst / "lib/stale.dart").exists()
