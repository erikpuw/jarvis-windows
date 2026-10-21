# engine/turn/schema.py
"""JSON schema ép vòng chọn tool: "tool" đứng đầu; none chỉ có "tool" — câu trả lời viết bằng chữ thường ở vòng sau
(log 2026-10-12 18:08: "say" trong JSON → Gemma viết câu hứa "Để tôi lên thực đơn…" thay vì nội dung)."""
from engine.tools import registry

NONE = {"type": "object", "properties": {"tool": {"const": "none"}}, "required": ["tool"], "additionalProperties": False}


def _branch(name: str) -> dict:
    p = registry.parameters(name)
    args = {"type": "object", "properties": p["properties"], "required": p["required"], "additionalProperties": False}
    return {"type": "object", "properties": {"tool": {"const": name}, "say": {"type": "string", "minLength": 1}, "args": args},
            "required": ["tool", "say", "args"], "additionalProperties": False}


def build(attachment_context=None, only: str | None = None, user_id: str | None = None) -> dict:
    """only = lệnh /tool, @tool: bắt buộc đúng tool đó."""
    if only:
        return {"anyOf": [_branch(only)]}
    return {"anyOf": [NONE, *(_branch(n) for n in registry.chat_names(attachment_context, user_id=user_id))]}


def response_format(s: dict) -> dict:
    return {"type": "json_schema", "json_schema": {"name": "turn", "schema": s}}
