"""Dùng skill JARVIS tự viết (ngài 2026-10-20): câu giống một câu mẫu của skill category learned (EmbeddingGemma 2,
cùng ngưỡng "cùng ý" của embed_probe) → các bước nạp vào vòng chọn tool, mỗi vòng bị grammar ép đúng tool của bước đó
(loop.run_loop skill=…). Không khớp, embedder lỗi → None, lượt đi đường cũ."""
import logging
import re
import unicodedata

from engine.core import learning
from engine.tools import skill_manager

log = logging.getLogger("jarvis.turn")

SKILL_SIM = 0.91   # skill_use_probe 2026-10-20: cùng ý 0.911-0.948; "có tin gì mới không" 0.903, "hôm nay thế nào" 0.896
# "1. weather — thời tiết Huế | kiểm chứng: có trạng thái trời và nhiệt độ" (skill_writer ghi đúng dạng này)
_STEP = re.compile(r"^\d+\.\s+(\w+)\s+—\s+(.+?)\s+\|\s+kiểm chứng:\s+(.+)$")
_CHECK_CHARS = 4000  # kết quả đưa vào lần kiểm chứng (bảng giá tổng hợp dài)
_CHECK_SCHEMA = {"type": "object", "properties": {"ly_do": {"type": "string", "minLength": 1}, "dat": {"type": "boolean"}},
                 "required": ["ly_do", "dat"], "additionalProperties": False}
_VECS: dict[str, list | None] = {}  # vector câu mẫu; câu mẫu chỉ đổi khi tạo skill mới


def _embed(text: str) -> list | None:
    return learning.LearningEngine._embed_text(text)


def _vec(text: str) -> list | None:
    """Vector câu đã chuẩn hoá: live 2026-10-20 "Báo cáo buổi sáng cho tôi đi." vs "báo cáo sáng nay đi" 0.876,
    chuẩn hoá cả hai (chữ thường, bỏ dấu câu) thì 0.919."""
    text = learning.normalize_query(text)
    if text not in _VECS:
        _VECS[text] = _embed(text)
    return _VECS[text]


def _words(text: str) -> str:
    """Chữ thường không dấu, chỉ chữ số (vd "Báo cáo buổi sáng!" → "bao cao buoi sang") để so với tên skill."""
    text = unicodedata.normalize("NFD", (text or "").lower().replace("đ", "d"))
    return " ".join(re.findall(r"[a-z0-9]+", "".join(c for c in text if unicodedata.category(c) != "Mn")))


def _parse(content: str, tools: set[str]) -> tuple[list[str], list[tuple[str, str, str]], str]:
    """(câu mẫu, bước (tool, việc, kiểm chứng), tiêu chí tổng hợp). Ngài 2026-10-20: skill phải có kiểm chứng hẳn hoi;
    có dòng bước thiếu kiểm chứng hoặc thiếu "Tổng hợp:" → không bước nào, skill không chạy."""
    samples, steps, summary, bad = [], [], "", False
    for line in (ln.strip() for ln in content.splitlines()):
        if line.startswith("Câu mẫu:"):
            samples = [s.strip() for s in line[len("Câu mẫu:"):].split(";") if s.strip()]
        elif line.startswith("Tổng hợp:"):
            summary = line[len("Tổng hợp:"):].strip()
        elif m := _STEP.match(line):
            if m.group(1) in tools:  # bước dùng tool đã gỡ thì bỏ
                steps.append((m.group(1), m.group(2).strip(), m.group(3).strip()))
        elif re.match(r"^\d+\.\s", line):
            bad = True
    return samples, ([] if bad or not summary else steps), summary


def match(text: str, tools: set[str]) -> dict | None:
    try:
        sm = skill_manager.get_skill_manager()
        if not sm.skills:
            sm.scan_skills()
        learned = [s for s in sm.list_skills() if s.category == "learned"]
        if not learned:
            return None
        said = f" {_words(text)} "
        for s in learned:  # ngài 2026-10-20 chọn: câu có đúng cụm tên skill → chạy skill đó, không cần embedding
            _, steps, summary = _parse(s.content, tools)
            if steps and f" {_words(s.name)} " in said:
                log.info("[TURN] skill %s gọi bằng tên", s.name)
                return {"name": s.name, "steps": steps, "tong_hop": summary}
        q = _embed(learning.normalize_query(text))
        best, best_sim = None, SKILL_SIM
        for s in learned:
            samples, steps, summary = _parse(s.content, tools)
            for sample in samples if steps else []:
                sim = learning._cosine(q, _vec(sample))
                if sim is not None and sim >= best_sim:
                    best, best_sim = {"name": s.name, "steps": steps, "tong_hop": summary}, sim
        if best:
            log.info("[TURN] skill %s khớp (cosine %.2f)", best["name"], best_sim)
        return best
    except Exception as exc:  # embedder/tệp lỗi: lượt chạy như chưa có skill
        log.warning("[TURN] không tra được skill: %s", exc)
        return None


def block(skill: dict, step: int) -> str:
    """Khối cho vòng chọn tool thứ `step` của skill (ngài 2026-10-20): vòng chọn biết đang chạy skill và đang ở bước
    nào; "say" vòng đầu báo đang chạy skill, các vòng sau chỉ báo ngắn bước đang làm, không nhắc kết quả bước trước."""
    n = len(skill["steps"])
    steps = "\n".join(f"{i}. {tool} — {job}" for i, (tool, job, _) in enumerate(skill["steps"], 1))
    tool, job, _ = skill["steps"][step - 1]
    # probe 2026-10-20: "say là câu báo ngài bạn đang chạy…" → model chép "Bạn đang chạy skill"; nêu nội dung, không nêu vai.
    # Bước 2+: câu báo do loop viết (model nói sai bước), không dặn "say"
    say = f' "say" là một câu ngắn với ngài: skill {skill["name"]} bắt đầu, việc đầu tiên là {job}.' if step == 1 else ""
    return (f'<skill ten="{skill["name"]}">\nBạn đang chạy skill này cho ngài, mỗi vòng một bước theo thứ tự; tham số '
            f"lấy từ lời ngài và việc của bước.\n{steps}\n\nVòng này là bước {step}/{n}: {tool} — {job}.{say}\n</skill>")


async def verify(criterion: str, result: str) -> tuple[bool, str]:
    """Kết quả (của một bước hoặc đoạn tổng hợp) có đạt tiêu chí không: grammar {ly_do, dat} + think 128.
    Lỗi gọi model → không đạt (không cho skill đi tiếp khi chưa kiểm chứng được)."""
    import json
    from engine.prompts import load
    from engine.prompts.learning import json_format
    from engine.server import llm_server
    try:
        r = await llm_server.call_llm(
            messages=[{"role": "system", "content": load("skill_check")},
                      {"role": "user", "content": f"<tieu_chi>\n{criterion}\n</tieu_chi>\n\n"
                                                  f"<ket_qua>\n{(result or '')[:_CHECK_CHARS]}\n</ket_qua>"}],
            stream=False, temperature=0.0, thinking=True, thinking_budget=128, max_tokens=400,
            response_format=json_format("skill_check", _CHECK_SCHEMA))
        data = json.loads((r.choices[0].message.content or "").strip())
        log.info("[TURN] kiểm chứng '%s': %s (%s)", criterion, data["dat"], data["ly_do"])
        return bool(data["dat"]), str(data["ly_do"]).strip()
    except Exception as exc:
        log.warning("[TURN] kiểm chứng lỗi: %s", exc)
        return False, "không kiểm chứng được kết quả"
