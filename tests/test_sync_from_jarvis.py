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


def test_update_from_origin_fast_forwards_and_refuses_divergence(tmp_path):
    """Merge PR trên GitHub làm main trên đó đi trước: sync kéo về trước khi commit, khỏi bị từ chối lúc push."""
    def g(*a, cwd):
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=cwd, check=True,
                       capture_output=True)
    remote, local, other = tmp_path / "remote.git", tmp_path / "local", tmp_path / "other"
    g("init", "-q", "--bare", "-b", "main", str(remote), cwd=tmp_path)
    g("clone", "-q", str(remote), str(local), cwd=tmp_path)
    (local / "a.txt").write_text("1", encoding="utf-8")
    g("add", "-A", cwd=local)
    g("commit", "-qm", "1", cwd=local)
    g("push", "-q", "origin", "HEAD:main", cwd=local)
    g("clone", "-q", str(remote), str(other), cwd=tmp_path)
    (other / "b.txt").write_text("2", encoding="utf-8")
    g("add", "-A", cwd=other)
    g("commit", "-qm", "pr merged", cwd=other)
    g("push", "-q", "origin", "HEAD:main", cwd=other)

    assert S.update_from_origin("main", local) is True and (local / "b.txt").exists()

    (local / "c.txt").write_text("3", encoding="utf-8")
    g("add", "-A", cwd=local)
    g("commit", "-qm", "local", cwd=local)
    (other / "d.txt").write_text("4", encoding="utf-8")
    g("add", "-A", cwd=other)
    g("commit", "-qm", "remote", cwd=other)
    g("push", "-q", "origin", "HEAD:main", cwd=other)
    assert S.update_from_origin("main", local) is False
