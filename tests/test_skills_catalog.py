"""The Dashboard's Skills list counts what the skill loader loads: only folders with a SKILL.md (2026-10-18: it also listed
skills/self_evolution, which holds the learned STYLE.md, so Skills said 3 while Tổng quan said 2)."""
from engine.UIUX.ui_engine import _scan_catalog_files
from engine.tools.skill_manager import SKILLS_DIR, SkillManager


def test_catalog_skills_match_the_loader():
    folders = {s["folder"] for s in _scan_catalog_files()["skills"]}
    assert "self_evolution" not in folders
    with_skill_md = {p.parent.name for p in SKILLS_DIR.rglob("*.md") if p.name.lower() in ("skill.md", "skills.md")}
    assert folders == with_skill_md
    m = SkillManager()
    m.scan_skills()
    assert len(folders) == m.get_stats()["total_skills"]
