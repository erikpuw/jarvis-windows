"""
Plugin: kiểm tra sức khoẻ thư mục skills/ ngay lúc server khởi động.

PluginLoader chỉ import module + gọi setup() một lần lúc nạp (không có cơ chế
đăng ký tool cho LLM gọi lại — xem load_plugin.py) nên plugin phù hợp nhất
cho việc chạy một tác vụ một lần khi start, kiểu health-check này. Không đổi
gì trong skills/, chỉ log cảnh báo để người viết skill biết mà sửa tay.
"""

import logging

log = logging.getLogger("jarvis.plugins.skill_healthcheck")

__description__ = "Quét skills/ lúc khởi động, cảnh báo skill thiếu description/nội dung/bị trùng tên."

_GENERIC_DESC_PREFIXES = ("Auto-created skill for", "Kỹ năng ")


def _check_skills() -> list[str]:
    from engine.tools.skill_manager import get_skill_manager, SKILLS_DIR

    mgr = get_skill_manager()
    mgr.scan_skills()

    issues = []
    md_files = list(SKILLS_DIR.glob("**/SKILL.md"))
    if len(md_files) != len(mgr.skills):
        issues.append(
            f"Có {len(md_files)} file SKILL.md nhưng chỉ nạp được {len(mgr.skills)} skill — "
            "khả năng cao 2 skill trùng 'name' trong frontmatter nên 1 cái bị đè mất."
        )

    for skill in mgr.skills.values():
        desc = (skill.description or "").strip()
        if not desc:
            issues.append(f"Skill '{skill.name}': không có description — _matches() gần như không bao giờ chọn được skill này.")
        elif desc.startswith(_GENERIC_DESC_PREFIXES):
            issues.append(f"Skill '{skill.name}': description tự sinh chung chung ({desc!r}) — nên viết lại cụ thể hơn để dễ match từ khóa.")

        if not (skill.content or "").strip():
            issues.append(f"Skill '{skill.name}': nội dung rỗng, chỉ có frontmatter.")

    return issues


def setup() -> bool:
    try:
        issues = _check_skills()
    except Exception as e:
        log.warning("[skill_healthcheck] Không quét được skills/: %s", e)
        return True  # không chặn server khởi động vì health-check lỗi

    if not issues:
        log.info("[skill_healthcheck] skills/ ổn, không phát hiện vấn đề.")
    else:
        log.warning("[skill_healthcheck] Phát hiện %d vấn đề trong skills/:", len(issues))
        for issue in issues:
            log.warning("[skill_healthcheck]   - %s", issue)

    return True
