import asyncio
from pathlib import Path

from engine.tools import check_project as cp
from engine.tools import fix_self as fs


def test_unexpected_changes_ignores_target_and_flags_others():
    target = str(fs.PROJECT_ROOT / "engine" / "a.py")
    before = {"engine/a.py": "1", "x.py": "1"}
    after = {"engine/a.py": "2", "x.py": "2", "new.py": "3"}
    assert fs.unexpected_changes(before, after, target) == ["new.py", "x.py"]


def test_repair_rejects_file_outside_project(tmp_path):
    outside = tmp_path / "evil.py"
    outside.write_text("x = 1\n")
    ok, msg = asyncio.run(fs.run_goose_repair_loop(str(outside), "err"))
    assert not ok and "ngoài" in msg


def test_check_project_reports_missing_goose(monkeypatch):
    monkeypatch.setattr(cp.shutil, "which", lambda _: None)
    out = asyncio.run(cp.check_project(None, None))
    assert "Không tìm thấy Goose CLI" in out


def test_check_project_prompt_names_root_and_is_short():
    system, prompt = cp.build_project_check_prompts(Path("E:/x/jarvis"), "kiểm tra dự án")
    assert "jarvis" in system and "jarvis" in prompt and "kiểm tra dự án" in prompt
    assert "MCP" not in system + prompt
    assert len(system + prompt) < 800
