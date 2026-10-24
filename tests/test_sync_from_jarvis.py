"""sync_from_jarvis: tệp nguồn đã xoá thì xoá ở repo GitHub, tệp riêng của repo GitHub được giữ (2026-10-24: gỡ Jev ở
jarvis nhưng engine/turn/jev + test Jev còn lại làm CI đỏ)."""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import sync_from_jarvis as S


def test_sync_copies_new_and_deletes_files_gone_from_source(tmp_path, monkeypatch):
    src, dst = tmp_path / "jarvis", tmp_path / "jarvis-windows"
    (src / "engine").mkdir(parents=True)
    (src / "engine" / "giữ.py").write_text("x = 2\n", encoding="utf-8")
    for rel in ("engine/giữ.py", "engine/jev_gate.py", "scripts/verify_ci.py", "CHANGELOG.md"):
        (dst / rel).parent.mkdir(parents=True, exist_ok=True)
        (dst / rel).write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=dst, check=True)
    subprocess.run(["git", "add", "-A"], cwd=dst, check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init"], cwd=dst, check=True)
    monkeypatch.setattr(S, "SOURCE_DIR", src)
    monkeypatch.setattr(S, "TARGET_DIR", dst)
    assert S.sync() == 0
    assert (dst / "engine" / "giữ.py").read_text(encoding="utf-8") == "x = 2\n"
    assert not (dst / "engine" / "jev_gate.py").exists()
    assert (dst / "scripts" / "verify_ci.py").exists() and (dst / "CHANGELOG.md").exists()
