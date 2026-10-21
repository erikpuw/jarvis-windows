# -*- coding: utf-8 -*-
"""
JARVIS Evolution Engine — Quản lý tiến hóa hành vi và prompt động.

Spec 2026-10-13 §3.3: đọc bài học (lesson/preference) trong DB, model (grammar + think 128) đề xuất gỡ/gộp bài
trùng, mâu thuẫn, lỗi thời — code áp dụng có rào chắn (_apply_cleanup) — rồi viết STYLE.md (skills/self_evolution/
STYLE.md, nạp vào <giong_dieu> mỗi lượt) từ bài học còn lại. Luật chọn công cụ không đi qua đây: ngài sửa tool →
bảng corrections (engine/turn/corrections.py). Evolution.md ghi mục đã gỡ/gộp để khôi phục.
"""

import asyncio
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from engine.server.llm_server import call_llm
from engine.core.learning import DEDUPE_SIM, _cosine

log = logging.getLogger("jarvis.evolution")

PROJECT_ROOT = Path(__file__).parent.parent.parent

STYLE_FILE = PROJECT_ROOT / "skills" / "self_evolution" / "STYLE.md"
EVOLUTION_LOG = PROJECT_ROOT / "data" / "wiki" / "System" / "Evolution.md"

# Chỉ 1 vòng tiến hóa được ghi file cùng lúc — tránh 2 lượt idle gần nhau
# đọc cùng bản STYLE.md/Evolution.md cũ rồi ghi đè chồng lên nhau.
_evolution_lock = asyncio.Lock()

# ponytail: in-memory, so one extra run after each restart; persist to disk if that ever matters.
_last_inputs_by_user: dict[str, tuple[str, str]] = {}


# ---- Settings → Bộ nhớ → Evolution: đọc và sửa tay hai file tiến hóa ngay trong giao diện ----
EVOLUTION_FILES = (
    ("style", "STYLE.md — luật giọng điệu đang áp dụng"),
    ("log", "Evolution.md — bài học đã gỡ/gộp"),
)
STYLE_MAX_CHARS = 4000  # STYLE.md vào system prompt mỗi lượt chat: người sửa tay cũng không được làm nó phình vô hạn


def _evolution_path(file_id: str, user_id: str | None = None) -> Path | None:
    if user_id and user_id != "admin":
        user_folder = PROJECT_ROOT / "data" / "users" / user_id
        return {
            "style": user_folder / "STYLE.md",
            "log": user_folder / "Evolution.md",
        }.get(file_id)
    # đọc STYLE_FILE/EVOLUTION_LOG lúc gọi (không cache) để test và cấu hình đổi được
    return {"style": STYLE_FILE, "log": EVOLUTION_LOG}.get(file_id)


def list_evolution_files(user_id: str | None = None) -> list[dict]:
    items = []
    for file_id, title in EVOLUTION_FILES:
        path = _evolution_path(file_id, user_id=user_id)
        if path is None:
            continue
        exists = path.exists()
        try:
            rel = str(path.relative_to(PROJECT_ROOT)).replace(os.sep, "/")
        except ValueError:
            rel = str(path).replace(os.sep, "/")
        items.append({
            "id": file_id, "title": title, "path": rel, "exists": exists, "editable": True,
            "content": path.read_text(encoding="utf-8") if exists else "",
            "updated_at": int(path.stat().st_mtime) if exists else None,
        })
    return items


async def save_evolution_file(file_id: str, content: str, user_id: str | None = None) -> dict:
    """Ghi tay một file tiến hóa. Không chờ vòng tiến hóa đang chạy (nó giữ khoá cả phút vì gọi LLM): báo bận để người dùng thử lại."""
    path = _evolution_path(file_id, user_id=user_id)
    if path is None:
        return {"success": False, "code": "unknown_id", "error": "Không có file tiến hóa này."}
    if file_id == "style" and len(content) > STYLE_MAX_CHARS:
        return {"success": False, "code": "too_long",
                "error": f"STYLE.md dài {len(content)} ký tự, tối đa {STYLE_MAX_CHARS} (nó được nạp vào prompt mỗi lượt chat)."}
    if _evolution_lock.locked():
        return {"success": False, "code": "evolution_running", "error": "Đang có một vòng tiến hóa chạy, thử lại sau ít phút."}
    async with _evolution_lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        _write_text_atomic(path, content)
    return {"success": True}


def _write_text_atomic(path: Path, content: str) -> None:
    """Write `content` to `path` atomically (temp file + os.replace).

    engine/prompts/chat.py re-reads STYLE.md on every single LLM call — a crash
    mid-write with a plain write_text() would leave a truncated file fed
    straight into every subsequent request's system prompt.
    """
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(content, encoding="utf-8")
    os.replace(str(tmp_path), str(path))


# STYLE.md: tối đa 12 luật sửa lỗi giao tiếp tinh gọn.
_STYLE_MAX_BULLETS = 12
_ADMIN_LABEL_RE = re.compile(r"\*\*\[MỚI\]\*\*\s*|\s*\(Từ `[^`]+`(?: trong Preferences\.md)?\)|\s*\(dựa trên `[^`]+`\)")

_MAX_CLEANUP = 5  # gỡ + gộp tối đa mỗi lần evolution (spec 2026-10-13 §3.3)
# Thứ Jarvis đã bỏ: bài học nhắc tới thì lỗi thời, code tự gỡ (ngài 2026-10-13 chọn: model đoán "lỗi thời" sót bài agent,
# gỡ nhầm bài khen). Gỡ một tính năng khỏi Jarvis thì thêm từ vào đây.
_OBSOLETE = re.compile(r"(?<!\w)(?:agents?|tác nhân|@control)(?!\w)", re.IGNORECASE)
# Luật xưng hô chỉ ở <danh_tinh> của prompt/jarvis.md; tool/agent/lệnh không phải giọng điệu (spec 2026-10-12 mục 1.4).
# Chỉ bỏ dòng NÓI VỀ xưng hô — không bỏ dòng có chữ "tôi/ngài": luật evolution viết ngôi thứ nhất (log 2026-10-12: mất 10/11).
_STYLE_BANNED = re.compile(r"xưng|thưa ngài|gọi người dùng|cách gọi|(?<!\w)(?:tool|agents?|tác nhân|lệnh|json)(?!\w)|@",
                           re.IGNORECASE)


def style_lines(text: str) -> list[str]:
    """Dòng STYLE.md được nạp vào prompt và được ghi lại: chỉ '- …', bỏ nhãn quản trị, trùng, xưng hô, tool; ≤ 12."""
    out, seen = [], set()
    for line in (text or "").splitlines():
        if not line.lstrip().startswith("- "):
            continue
        clean = " ".join(_ADMIN_LABEL_RE.sub("", line.strip()).split())
        key = re.sub(r"\W+", " ", clean).strip().lower()
        if not key or key in seen or _STYLE_BANNED.search(clean[2:]):
            continue
        seen.add(key)
        out.append(clean)
    return out[:_STYLE_MAX_BULLETS]  # cùng trần STYLE_SCHEMA: trần 8 cũ cắt mất luật emoji (2026-10-14)


def _is_off_topic_style_rule(line: str) -> bool:
    """Kiểm tra xem luật có lạc đề khỏi phong cách giao tiếp/giọng điệu (STYLE) không.
    STYLE chỉ quản lý cách nói năng, xưng hô, giọng điệu, thái độ, emoji, độ dài.
    Không được chứa các quy tắc nghiệp vụ/công cụ cụ thể (như tra giá, đi ngủ, mở app).
    """
    low = line.lower()
    off_topic_patterns = [
        r"hỏi\s+về\s+giá",
        r"giá\s+một\s+mặt\s+hàng",
        r"khu\s+vực\s+cụ\s+thể",
        r"đi\s+ngủ",
        r"chế\s+độ\s+chờ",
        r"gọi\s+(?:các\s+)?tác\s+nhân",
        r"gọi\s+agent",
        r"mở\s+(?:edge|terminal|app|chrome)",
        r"thu\s+nhỏ",
        r"phóng\s+to",
        r"windows\s+update",
        r"tiến\s+độ\s+công\s+việc",
        r"cung\s+cấp\s+hình\s+ảnh",
    ]
    return any(re.search(p, low) for p in off_topic_patterns)


# Độ phủ từ vựng tối thiểu: luật có căn cứ khi ≥ 40% số từ (đã bỏ dấu) của luật nằm trong một bài học nguồn
_GROUNDED_OVERLAP = 0.4


def _bad_rule(line: str, sources: list[str]) -> str | None:
    """Vì sao luật STYLE không được ghi, None = được: chứa thẻ giao thức, lạc đề nghiệp vụ/công cụ, hoặc không có
    bài học nào làm căn cứ (model tự bịa). Căn cứ = độ phủ từ vựng của luật trong một bài học nguồn."""
    forbidden = ["<ask_user>", "<action_run>", "<offer_protocol>"]
    line_lower = line.lower()
    for kw in forbidden:
        if kw in line_lower:
            return f"luật STYLE vi phạm chủ đề bị cấm ({kw}): do persona và soul_rules quản lý độc quyền"
    if _is_off_topic_style_rule(line):
        return "luật nghiệp vụ/công cụ cụ thể không thuộc phong cách giao tiếp STYLE"

    # Căn cứ: ≥ _GROUNDED_OVERLAP số từ của luật phải xuất hiện trong một bài học nguồn
    from engine.core.learning import _lexical_tokens
    norm = lambda s: re.sub(r"\W+", " ", s).strip().lower()
    line_tokens = _lexical_tokens(norm(line))
    if not line_tokens:
        return "không có bài học nào làm căn cứ"

    for s in sources:
        source_tokens = _lexical_tokens(norm(s))
        if source_tokens and len(line_tokens & source_tokens) / len(line_tokens) >= _GROUNDED_OVERLAP:
            return None
    return "không có bài học nào làm căn cứ"


def _write_evolution_log(cleaned: list[str], user_id: str | None = None) -> None:
    """Evolution.md: mục đã gỡ/gộp kèm nội dung cũ để khôi phục. Luật đang áp dụng nằm ở STYLE.md, không chép lại."""
    try:
        target_log = _evolution_path("log", user_id=user_id) or EVOLUTION_LOG
        text = target_log.read_text(encoding="utf-8") if target_log.exists() else ""
        old, area = [], None
        for line in text.splitlines():
            if line.startswith("## "):
                area = line[3:].strip()
            elif line.startswith("- ") and area == "Đã dọn":
                old.append(line)
        out = "# Jarvis Evolution Log\n\n<!-- JARVIS-MANAGED-EVOLUTION -->\n\n## Đã dọn\n" + "\n".join(old + cleaned) + "\n"
        target_log.parent.mkdir(parents=True, exist_ok=True)
        target_log.write_text(out, encoding="utf-8")
        log.info("🧬 Đã cập nhật Evolution.md (%s)", target_log)
    except Exception as e:
        log.warning(f"🧬 Không ghi được Evolution.md: {e}")


def _vec(item: dict | None) -> list | None:
    raw = (item or {}).get("embedding")
    return json.loads(raw) if raw else None


def _apply_cleanup(le, parsed: dict, items: list[dict], budget: int = _MAX_CLEANUP) -> tuple[list[str], list[dict]]:
    """Gỡ/gộp theo đề xuất của model với rào chắn code (spec §3.3): id phải có thật, chỉ "trùng"/gộp khi cosine
    ≥ DEDUPE_SIM, tối đa `budget` mục. Trả (dòng ghi Evolution.md, bài học còn lại)."""
    by_id = {i["id"]: dict(i) for i in items}
    done: list[str] = []
    for r in parsed.get("remove") or []:
        if len(done) >= budget:
            break
        rid, keep, why = r.get("id"), r.get("keep_id"), r.get("why")
        # chỉ gỡ "trùng" đã kiểm bằng cosine; "mâu thuẫn" không xoá (ngài 2026-10-14: cosine không tách được trái ý /
        # khác chủ đề 0.853 vs 0.851, model gỡ nhầm bài khen) — lượt viết STYLE theo bài mới hơn
        if rid not in by_id or why != "trùng":
            continue
        sim = _cosine(_vec(by_id.get(rid)), _vec(by_id.get(keep))) if keep in by_id and keep != rid else None
        if sim is None or sim < DEDUPE_SIM:
            log.info("🧬 Bỏ đề xuất gỡ #%s (trùng #%s): cosine %s < %.2f", rid, keep, sim, DEDUPE_SIM)
            continue
        if le.delete_learning_control_record("learning", rid):
            done.append(f"- [gỡ #{rid}, {why}] {by_id.pop(rid)['content']}")
    for m in parsed.get("merge") or []:
        ids = [i for i in dict.fromkeys(m.get("ids") or []) if i in by_id]
        content = str(m.get("content") or "").strip()
        if len(ids) < 2 or not content or len(done) + len(ids) - 1 > budget:
            continue
        newest = max(ids, key=lambda i: by_id[i]["created_at"])
        sims = [_cosine(_vec(by_id[i]), _vec(by_id[newest])) for i in ids if i != newest]
        if any(s is None or s < DEDUPE_SIM for s in sims):  # gộp ý trái nhau → ý cũ đè ý mới (probe 2026-10-13)
            log.info("🧬 Bỏ đề xuất gộp %s: không cùng ý (cosine %s)", ids, sims)
            continue
        le.update_learning_control_record("learning", newest, {"content": content})
        by_id[newest]["content"] = content
        for i in ids:
            if i != newest and le.delete_learning_control_record("learning", i):
                done.append(f"- [gộp #{i} → #{newest}] {by_id.pop(i)['content']}")
    return done, list(by_id.values())


async def trigger_cognitive_evolution(user_id: str | None = None) -> dict:
    """Entry point công khai — đảm bảo tối đa 1 vòng tiến hóa chạy cùng lúc."""
    if _evolution_lock.locked():
        log.info("🧬 Bỏ qua: một vòng tiến hóa khác đang chạy, tránh ghi đè chồng chéo STYLE.md/Evolution.md.")
        return {"success": True, "path": "", "error": None, "skipped": "already_running"}
    # Learning preempts itself for a live turn but spawned this as a free
    # running task, so the heaviest job in the system kept calling the shared
    # local LLM while the user was mid-conversation.
    from engine.core.activity_gate import wait_until_chat_idle
    await wait_until_chat_idle()
    async with _evolution_lock:
        return await _run_cognitive_evolution(user_id=user_id)


def _items_text(items: list[dict]) -> str:
    return "\n".join(
        f"#{i['id']} [{i['type']}, {datetime.fromtimestamp(i['created_at']):%Y-%m-%d}] {i['content']}" for i in items)


async def _ask(prompt: str, name: str, schema: dict) -> dict:
    from engine.prompts.learning import json_format
    response = await call_llm(messages=[{"role": "user", "content": prompt}], temperature=0.0, thinking=True,
                              thinking_budget=128, max_tokens=1500, response_format=json_format(name, schema))
    return json.loads(response.choices[0].message.content)


async def _run_cognitive_evolution(user_id: str | None = None) -> dict:
    """Lần 1: model đề xuất gỡ/gộp, code áp rào chắn. Lần 2: viết STYLE.md từ bài học CÒN LẠI (spec 2026-10-13 §3.3;
    probe 2026-10-13: viết STYLE cùng lượt dọn thì STYLE theo quyết định gỡ sai của model)."""
    uid = user_id or "admin"
    log.info("🧬 Bắt đầu tiến trình tự tích lũy & tiến hóa (Self-Evolution) cho user=%s...", uid)
    results = {"success": False, "path": "", "error": None}
    from engine.core.learning import get_learning_engine
    from engine.core.memory import strip_emojis
    from engine.prompts.learning import EVOLUTION_SCHEMA, STYLE_SCHEMA, build_evolution_prompt, build_style_prompt
    le = get_learning_engine()
    target_style = _evolution_path("style", user_id=uid) or STYLE_FILE
    items = await asyncio.to_thread(le.evolution_items, user_id=uid)
    if not items:
        log.warning("🧬 Không tìm thấy dữ liệu học để tự tiến hóa (user=%s).", uid)
        return results
    current_style = target_style.read_text(encoding="utf-8").strip() if target_style.exists() else ""
    if (_items_text(items), current_style) == _last_inputs_by_user.get(uid):
        log.info("🧬 Bài học và STYLE không đổi từ lần tiến hóa trước, bỏ qua (user=%s).", uid)
        results["success"] = True
        return results
    try:
        # chỉ bài học cách cư xử (sở thích "phim về agent tình báo" không lỗi thời), tính vào trần _MAX_CLEANUP; ghi log
        # ngay sau khi xoá để lần gọi LLM sau có lỗi cũng không mất nội dung (review 2026-10-14)
        obsolete, gone = [], set()
        for i in [i for i in items if i["type"] == "lesson" and _OBSOLETE.search(i["content"])][:_MAX_CLEANUP]:
            if await asyncio.to_thread(le.delete_learning_control_record, "learning", i["id"]):
                obsolete.append(f"- [gỡ #{i['id']}, lỗi thời] {i['content']}")
                gone.add(i["id"])
        if obsolete:
            await asyncio.to_thread(_write_evolution_log, obsolete, user_id=uid)
        items = [i for i in items if i["id"] not in gone]
        parsed = await _ask(build_evolution_prompt(_items_text(items)), "evolution", EVOLUTION_SCHEMA)
        cleaned, remaining = await asyncio.to_thread(_apply_cleanup, le, parsed, items, _MAX_CLEANUP - len(obsolete))
        if cleaned:
            await asyncio.to_thread(_write_evolution_log, cleaned, user_id=uid)
        # kèm ngày (bài trái ý: theo bài mới hơn), không kèm nhãn loại: "[preference] giọng miền Nam" bị model coi là
        # sở thích đời sống, bỏ khỏi STYLE (probe 2026-10-13)
        plain = "\n".join(f"#{i['id']} [{datetime.fromtimestamp(i['created_at']):%Y-%m-%d}] {i['content']}"
                          for i in sorted(remaining, key=lambda i: i["created_at"], reverse=True))
        styled = await _ask(build_style_prompt(plain), "evolution_style", STYLE_SCHEMA)
        sources = [i["content"] for i in remaining]
        kept = []
        for s in styled.get("style") or []:
            line = f"- {strip_emojis(str(s)).strip()}"
            why = _bad_rule(line, sources) if str(s).strip() else "rỗng"
            if why:
                log.warning("🧬 Bỏ luật không hợp lệ (%s): %s", why, line)
            else:
                kept.append(line)
        kept = style_lines("\n".join(kept))[:_STYLE_MAX_BULLETS]
        if kept:
            target_style.parent.mkdir(parents=True, exist_ok=True)
            _write_text_atomic(target_style, "# Self Evolution Style Rules\n" + "\n".join(kept) + "\n")
            log.info(f"🧬 Đã cập nhật style rules: {target_style}")
        elif current_style:
            log.info("🧬 Model không trả luật hợp lệ: giữ STYLE.md hiện tại.")
        _last_inputs_by_user[uid] = (_items_text(remaining),
                                     target_style.read_text(encoding="utf-8").strip() if target_style.exists() else "")
        results["success"] = True
        results["path"] = str(target_style)
    except Exception as e:
        log.error(f"🧬 Thất bại trong quá trình tự tiến hóa: {e}", exc_info=True)
        results["error"] = str(e)
    return results
