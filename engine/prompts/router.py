"""Quản lý prompt định tuyến và nạp bốn hướng dẫn route skill."""
import json
from pathlib import Path

from engine.prompts import load

_ROUTING_SKILLS_DIR = Path(__file__).resolve().parents[2] / "skills" / "router"
_ROUTING_SKILLS = ("general", "general_knowledge", "orchestrator", "attachment_clarify")


def build_gate_system_prompt(has_attachment: bool = False) -> str:
    attachment_context = (
        "Ngữ cảnh user có metadata của tệp đính kèm đáng tin cậy."
        if has_attachment else "Lượt này không có metadata tệp đính kèm; không chọn attachment_clarify."
    )
    skills = "\n\n".join(
        (_ROUTING_SKILLS_DIR / name / "SKILL.md").read_text(encoding="utf-8").strip()
        for name in _ROUTING_SKILLS
    )
    return f"{load('router_gate').rstrip()}\n{attachment_context}\n\n{skills}"


def build_classifier_system_prompt(
    attachment_metadata: dict | None = None, extra_context: str = "", offer_context: str = ""
) -> str:
    system = load("classifier").rstrip("\n")
    if attachment_metadata is not None:
        system += " Tệp đính kèm đáng tin cậy: " + json.dumps(attachment_metadata, ensure_ascii=False)
    if extra_context:
        system += " " + extra_context
    if offer_context:
        system += " " + offer_context
    return system


def build_offer_context(ask: str, tool: str = "") -> str:
    """Lời đề nghị đang chờ, đưa cho classifier khi ngài đáp lại nó."""
    if not ask:
        return ""
    return (f"Lượt trước Jarvis đã đề nghị (chưa làm): {ask}"
            + (f" [công cụ: {tool}]" if tool else "")
            + ". Nếu yêu cầu hiện tại là đồng ý hoặc sửa lại đề nghị đó, chọn agent theo đề nghị "
              "và viết query là câu lệnh cụ thể.")
