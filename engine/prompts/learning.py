"""Quản lý các prompt learning, evolution, dream, self-healing (spec 2026-09-25 mục 2)."""
from engine.prompts import load


def json_format(name: str, schema: dict) -> dict:
    """Grammar JSON schema cho llama.cpp (cùng kiểu engine/turn/schema.response_format)."""
    return {"type": "json_schema", "json_schema": {"name": name, "schema": schema}}


_TEXT = {"type": "string", "minLength": 1}


def propose_schema(tool_names: list[str]) -> dict:
    tools = {"enum": list(tool_names)}
    learn = {"type": "object", "properties": {"kind": {"enum": ["lesson", "preference", "user_fact"]}, "key": _TEXT,
                                              "content": _TEXT, "evidence": _TEXT},
             "required": ["kind", "key", "content", "evidence"], "additionalProperties": False}
    fix = {"type": "object", "properties": {"kind": {"const": "tool_fix"}, "query": _TEXT, "wrong_tool": tools,
                                            "right_tool": tools, "evidence": _TEXT},
           "required": ["kind", "query", "wrong_tool", "right_tool", "evidence"], "additionalProperties": False}
    rule = {"type": "object", "properties": {"kind": {"const": "tool_rule"}, "topic": _TEXT, "right_tool": tools,
                                             "evidence": _TEXT},
            "required": ["kind", "topic", "right_tool", "evidence"], "additionalProperties": False}
    retract = {"type": "object", "properties": {"kind": {"const": "retract"}, "target_id": {"type": "integer"},
                                                "evidence": _TEXT},
               "required": ["kind", "target_id", "evidence"], "additionalProperties": False}
    return {"type": "object", "properties": {"proposals": {"type": "array", "items": {"anyOf": [learn, fix, rule, retract]},
                                                           "maxItems": 4}},
            "required": ["proposals"], "additionalProperties": False}


def build_learning_propose_prompt(context: str, latest: str = "", just_learned: str = "", tools: str = "",
                                  used_tools: str = "") -> str:
    """Xây dựng prompt đề xuất bài học (vòng 1); chỉ học từ <luot_moi>, <hoi_thoai> là ngữ cảnh."""
    return load("learning_propose", context=context, latest=latest or context, just_learned=just_learned or "(không có)",
                tools=tools or "(không có)", used_tools=used_tools or "(không có)")


CRITIQUE_SCHEMA = {"type": "object", "properties": {"decision": {"enum": ["skip", "merge", "replace", "new"]},
                                                   "reason": {"type": "string"}, "merged_content": {"type": "string"}},
                   "required": ["decision", "reason", "merged_content"], "additionalProperties": False}


def build_learning_critique_prompt(proposal: str, existing_item: str = "") -> str:
    """Xây dựng prompt phản biện bài học vòng 2."""
    return load("learning_critique", proposal=proposal, existing_item=existing_item or "Không có mục nào tương tự.")


def build_evolution_prompt(items: str) -> str:
    """Evolution lần 1: đề xuất gỡ/gộp bài học (spec 2026-10-13 §3.3)."""
    return load("evolution", items=items)


def build_style_prompt(items: str) -> str:
    """Evolution lần 2: viết STYLE từ bài học còn lại SAU khi code áp rào chắn (probe 2026-10-13: viết chung một lần
    thì STYLE theo quyết định gỡ sai của model, mất luật "ngắn gọn", "xin lỗi")."""
    return load("evolution_style", items=items)


EVOLUTION_SCHEMA = {
    "type": "object",
    "properties": {
        "remove": {"type": "array", "maxItems": 5, "items": {
            "type": "object", "properties": {"id": {"type": "integer"}, "why": {"enum": ["trùng"]},
                                            "keep_id": {"type": "integer"}},
            "required": ["id", "why", "keep_id"], "additionalProperties": False}},
        "merge": {"type": "array", "maxItems": 3, "items": {
            "type": "object", "properties": {"ids": {"type": "array", "items": {"type": "integer"}, "minItems": 2},
                                            "content": _TEXT},
            "required": ["ids", "content"], "additionalProperties": False}},
    },
    "required": ["remove", "merge"], "additionalProperties": False,
}
STYLE_SCHEMA = {"type": "object", "properties": {"style": {"type": "array", "maxItems": 12, "items": _TEXT}},
                "required": ["style"], "additionalProperties": False}


DREAM_MESSAGE_SCHEMA = {"type": "object", "properties": {"trivial": {"type": "boolean"}, "summary": {"type": "string"}},
                        "required": ["trivial", "summary"], "additionalProperties": False}
DREAM_WIKI_SCHEMA = {"type": "object", "properties": {"bullets": {"type": "array", "maxItems": 3, "items": _TEXT}},
                     "required": ["bullets"], "additionalProperties": False}
SELF_HEALING_SCHEMA = {"type": "object", "properties": {
    "classification": {"enum": ["CODE_BUG", "TRANSIENT", "CONFIG", "DEPENDENCY", "OTHER"]},
    "summary": _TEXT, "action": _TEXT}, "required": ["classification", "summary", "action"], "additionalProperties": False}


def build_dream_message_prompt(transcript: str) -> str:
    """Dream: đánh giá một đoạn hội thoại cũ có đáng giữ không."""
    return load("dream_message", transcript=transcript).rstrip("\n")


def build_dream_wiki_prompt(title: str, content: str) -> str:
    """Dream: nén một ghi chú Obsidian cũ."""
    return load("dream_wiki", title=title, content=content).rstrip("\n")


def build_self_healing_prompt(project_file: str, err_snippet: str) -> str:
    """Phân loại lỗi từ log và viết entry cho Errors.md."""
    return load("self_healing", project_file=project_file, err_snippet=err_snippet).rstrip("\n")
