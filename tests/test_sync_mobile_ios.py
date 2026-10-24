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


def test_file_deleted_at_source_but_not_committed_is_removed_too(tmp_path):
    """Xoá ở jarvis-mobile (chưa commit) thì repo GitHub cũng xoá theo, như sync_from_jarvis (theo đĩa, không theo index)."""
    src = _repo(tmp_path / "src", {"lib/main.dart": "x", "lib/old_feature.dart": "x"},
                track=["lib/main.dart", "lib/old_feature.dart"])
    (src / "lib/old_feature.dart").unlink()
    dst = _repo(tmp_path / "dst", {"lib/main.dart": "x", "lib/old_feature.dart": "x"},
                track=["lib/main.dart", "lib/old_feature.dart"])

    assert sync(src, dst) == 0

    assert not (dst / "lib/old_feature.dart").exists() and (dst / "lib/main.dart").exists()


def test_line_ending_only_difference_is_not_copied(tmp_path):
    """autocrlf=true: chuyển nhánh ghi CRLF ra đĩa; so từng byte thì chép lại 18 tệp, git add chuẩn hoá về như cũ, commit
    rỗng làm script đổ lỗi (2026-10-24). Khác mỗi CRLF/LF thì không chép."""
    src = _repo(tmp_path / "src", {"lib/main.dart": ""}, track=["lib/main.dart"])
    (src / "lib/main.dart").write_bytes(b"a\nb\n")  # write_text trên Windows đã tự đổi sang CRLF
    dst = _repo(tmp_path / "dst", {}, track=[])
    (dst / "lib").mkdir()
    (dst / "lib/main.dart").write_bytes(b"a\r\nb\r\n")

    assert sync(src, dst) == 0

    assert (dst / "lib/main.dart").read_bytes() == b"a\r\nb\r\n"
