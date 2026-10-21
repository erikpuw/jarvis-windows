"""JARVIS tự viết skill (ngài 2026-10-20): skills/writing-skills/SKILL.md là prompt, một lần gọi LLM bị grammar ép
{ten, mo_ta, cau_mau, buoc[{cong_cu, viec, kiem_chung}], tong_hop} với cong_cu chỉ là tên tool thật; code bỏ bước lạ rồi ghi
skills/<ten>/SKILL.md bằng skill_manager.create_skill (không ghi đè skill đã có)."""
import json
import logging

from engine.tools import registry, skill_manager

log = logging.getLogger("jarvis.skill_writer")
GUIDE = skill_manager.PROJECT_ROOT / "skills" / "writing-skills" / "SKILL.md"
_TEXT = {"type": "string", "minLength": 1}


def _tools() -> list[str]:
    return [n for n in registry.chat_names(None) if n != "save_skill"]


def _schema(tools: list[str]) -> dict:
    # ngài 2026-10-20: mỗi bước bắt buộc có tiêu chí kiểm chứng, skill bắt buộc có tiêu chí cho đoạn tổng hợp cuối
    step = {"type": "object", "properties": {"cong_cu": {"enum": tools}, "viec": _TEXT, "kiem_chung": _TEXT},
            "required": ["cong_cu", "viec", "kiem_chung"], "additionalProperties": False}
    return {"type": "object", "properties": {
        "ten": _TEXT, "mo_ta": _TEXT, "cau_mau": {"type": "array", "minItems": 2, "maxItems": 4, "items": _TEXT},
        "buoc": {"type": "array", "minItems": 1, "maxItems": 5, "items": step}, "tong_hop": _TEXT},
        "required": ["ten", "mo_ta", "cau_mau", "buoc", "tong_hop"], "additionalProperties": False}


def _messages(request: str, last_run: list[dict], tools: list[str]) -> list[dict]:
    guide = skill_manager.get_skill_manager().load_skill_from_file(GUIDE)
    run = "\n".join(f"{i}. {s['tool']} {json.dumps(s.get('args') or {}, ensure_ascii=False)}"
                    for i, s in enumerate(last_run, 1)) or "(không có)"
    catalog = "\n".join(f"- {n}: {registry.description(n)}" for n in tools)
    return [{"role": "system", "content": guide.content if guide else ""},
            {"role": "user", "content": f"<yeu_cau>\n{request}\n</yeu_cau>\n\n<lan_chay>\n{run}\n</lan_chay>\n\n"
                                        f"<cong_cu>\n{catalog}\n</cong_cu>"}]


async def write_skill(request: str, last_run: list[dict]) -> str:
    from engine.prompts.learning import json_format
    from engine.server import llm_server
    from engine.tools.catalog.files import _slug
    tools = _tools()
    try:
        r = await llm_server.call_llm(messages=_messages(request, last_run, tools), stream=False, temperature=0.0,
                                      thinking=True, thinking_budget=128, max_tokens=900,
                                      response_format=json_format("skill", _schema(tools)))
        draft = json.loads((r.choices[0].message.content or "").strip())
    except Exception as exc:
        log.warning("[SKILL] viết skill lỗi: %s", exc)
        return "Chưa tạo được skill: model không trả bản nháp dùng được."
    # grammar đã ép; chặn lại khi chạy không grammar: tool lạ hoặc thiếu tiêu chí kiểm chứng thì bỏ bước
    steps = [s for s in draft.get("buoc", []) if s.get("cong_cu") in tools and str(s.get("kiem_chung", "")).strip()]
    if not steps or not str(draft.get("tong_hop", "")).strip():
        return "Chưa tạo được skill: cần ít nhất một bước dùng công cụ JARVIS đang có, mỗi bước và phần tổng hợp có kiểm chứng."
    name = _slug(draft["ten"])
    body = (f"Câu mẫu: {'; '.join(c.strip() for c in draft['cau_mau'])}\n\n"
            + "\n".join(f"{i}. {s['cong_cu']} — {s['viec'].strip()} | kiểm chứng: {s['kiem_chung'].strip()}"
                        for i, s in enumerate(steps, 1))
            + f"\n\nTổng hợp: {draft['tong_hop'].strip()}\n")
    res = skill_manager.create_skill(name, body, category="learned", description=draft["mo_ta"])
    if not res.get("success"):
        return f"Skill {name} đã có, không ghi đè." if "exists" in str(res.get("error")) else f"Chưa tạo được skill: {res.get('error')}"
    return f"Đã tạo skill {name}: {draft['mo_ta'].strip()}\n{body}"
