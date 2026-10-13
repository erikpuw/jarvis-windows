# -*- coding: utf-8 -*-
"""
JARVIS Evolution Engine — Quản lý tiến hóa hành vi và prompt động.

Đọc Learning.md/Preferences.md, tách bài học thành 2 track:
- STYLE: cách Jarvis nói/hành xử trong chat (giọng điệu, emoji, và cả các quy tắc
  hành vi phát ngôn như "không nói đang dùng công cụ khi chỉ đang chat thường").
  Ghi thẳng vào skills/self_evolution/STYLE.md — file này ĐƯỢC nạp vào system
  prompt mỗi lượt chat (engine/prompts/chat.py), nên chỉ chứa nội dung an toàn để chat
  model tự do diễn giải: sai chỉ làm câu trả lời dở hơn, không làm gãy routing.
- ROUTING: agent nào nên xử lý loại yêu cầu nào. KHÔNG có file "SKILL.md" sống
  nữa — engine/router (gate) và orchestrator/classifier.py (chọn agent) đã đo
  thực nghiệm rằng tiêm luật routing tự sinh vào đó làm giảm độ chính xác định
  tuyến (spec 2026-09-21: mất 7/53 route đúng). Nên ROUTING chỉ được ghi vào
  data/wiki/System/Evolution.md dưới dạng ĐỀ XUẤT chờ người duyệt — không nơi
  nào trong hệ thống tự động đọc và áp dụng nó.
"""

import asyncio
import difflib
import logging
import os
import re
from pathlib import Path
from engine.server.llm_server import call_llm
from engine.core.evolution_parser import parse_evolution_response

log = logging.getLogger("jarvis.evolution")

PROJECT_ROOT = Path(__file__).parent.parent.parent

STYLE_FILE = PROJECT_ROOT / "skills" / "self_evolution" / "STYLE.md"
EVOLUTION_LOG = PROJECT_ROOT / "data" / "wiki" / "System" / "Evolution.md"

# Chỉ 1 vòng tiến hóa được ghi file cùng lúc — tránh 2 lượt idle gần nhau
# đọc cùng bản STYLE.md/Evolution.md cũ rồi ghi đè chồng lên nhau.
_evolution_lock = asyncio.Lock()

# ponytail: in-memory, so one extra run after each restart; persist to disk if that ever matters.
_last_inputs: tuple[str, str] | None = None


# ---- Settings → Bộ nhớ → Evolution: đọc và sửa tay hai file tiến hóa ngay trong giao diện ----
EVOLUTION_FILES = (
    ("style", "STYLE.md — luật giọng điệu đang áp dụng"),
    ("log", "Evolution.md — nhật ký luật tiến hóa (Routing chỉ là đề xuất chờ duyệt)"),
)
STYLE_MAX_CHARS = 4000  # STYLE.md vào system prompt mỗi lượt chat: người sửa tay cũng không được làm nó phình vô hạn


def _evolution_path(file_id: str) -> Path | None:
    # đọc STYLE_FILE/EVOLUTION_LOG lúc gọi (không cache) để test và cấu hình đổi được
    return {"style": STYLE_FILE, "log": EVOLUTION_LOG}.get(file_id)


def list_evolution_files() -> list[dict]:
    items = []
    for file_id, title in EVOLUTION_FILES:
        path = _evolution_path(file_id)
        exists = path.exists()
        try:
            rel = str(path.relative_to(PROJECT_ROOT)).replace(os.sep, "/")
        except ValueError:
            rel = str(path)
        items.append({
            "id": file_id, "title": title, "path": rel, "exists": exists, "editable": True,
            "content": path.read_text(encoding="utf-8") if exists else "",
            "updated_at": int(path.stat().st_mtime) if exists else None,
        })
    return items


async def save_evolution_file(file_id: str, content: str) -> dict:
    """Ghi tay một file tiến hóa. Không chờ vòng tiến hóa đang chạy (nó giữ khoá cả phút vì gọi LLM): báo bận để người dùng thử lại."""
    path = _evolution_path(file_id)
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


_MAX_RULE_BULLETS = 6
_MAX_RULE_CHARS = 900


# STYLE.md: tối đa 12 luật sửa lỗi giao tiếp tinh gọn; routing vẫn 6.
_STYLE_MAX_BULLETS = 12
_STYLE_MAX_CHARS = 3500  # dưới STYLE_MAX_CHARS (4000) của trình sửa tay
_ADMIN_LABEL_RE = re.compile(r"\*\*\[MỚI\]\*\*\s*|\s*\(Từ `[^`]+`(?: trong Preferences\.md)?\)|\s*\(dựa trên `[^`]+`\)")

_STYLE_PROMPT_MAX = 8
# Luật xưng hô chỉ ở <danh_tinh> của prompt/jarvis.md; tool/agent/lệnh không phải giọng điệu (spec 2026-10-12 mục 1.4).
# Chỉ bỏ dòng NÓI VỀ xưng hô — không bỏ dòng có chữ "tôi/ngài": luật evolution viết ngôi thứ nhất (log 2026-10-12: mất 10/11).
_STYLE_BANNED = re.compile(r"xưng|thưa ngài|gọi người dùng|cách gọi|(?<!\w)(?:tool|agents?|tác nhân|lệnh|json)(?!\w)|@",
                           re.IGNORECASE)


def style_lines(text: str) -> list[str]:
    """Dòng STYLE.md được nạp vào prompt và được ghi lại: chỉ '- …', bỏ nhãn quản trị, trùng, xưng hô, tool; ≤ 8."""
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
    return out[:_STYLE_PROMPT_MAX]


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


def _deduplicate_style_bullets(bullets: list[str]) -> list[str]:
    """Khử trùng lặp và gộp các luật phong cách giao tiếp cùng chủ đề.
    - Xưng hô / đại từ: giữ 1 luật duy nhất.
    - Hài hước / dí dỏm / giọng miền Nam: giữ 1 luật duy nhất.
    - Emoji: giữ 1 luật duy nhất.
    - Phản ứng khi người dùng không hài lòng / phàn nàn: gộp lại thành 1 luật tinh gọn.
    - Lời chào kết thúc: giữ 1 luật duy nhất.
    - Bỏ các luật trùng lặp ý hoặc có độ tương đồng từ ngữ cao.
    """
    cleaned: list[str] = []
    has_pronoun = False
    has_humor = False
    has_emoji = False
    has_salutation = False
    has_frustration = False

    for b in bullets:
        line = b.strip()
        if not line.startswith("- "):
            continue
        line_clean = _ADMIN_LABEL_RE.sub("", line).strip()
        low = line_clean.lower()

        # 1. Nhóm xưng hô
        if "xưng 'tôi'" in low or "gọi người dùng là 'ngài'" in low or "quy tắc về xưng hô" in low:
            if not has_pronoun:
                cleaned.append("- Tôi luôn xưng 'tôi' và gọi người dùng là 'ngài' trong mọi tương tác.")
                has_pronoun = True
            continue

        # 2. Nhóm hài hước miền Nam
        if "hài hước" in low or "dí dỏm" in low or "miền nam sài gòn" in low:
            if not has_humor:
                cleaned.append("- Giọng văn của tôi mang phong cách hài hước và dí dỏm đặc trưng của miền Nam Sài Gòn.")
                has_humor = True
            continue

        # 3. Nhóm emoji
        if "emoji" in low:
            if not has_emoji:
                cleaned.append("- Tôi sử dụng emoji phù hợp để làm cho cuộc trò chuyện sinh động hơn.")
                has_emoji = True
            continue

        # 4. Nhóm thái độ khi người dùng phàn nàn / không hài lòng
        if "không hài lòng" in low or "thất vọng" in low or "xin lỗi hoặc giải thích quá dài" in low:
            if not has_frustration:
                cleaned.append("- Khi ngài bày tỏ sự không hài lòng, tôi tránh xin lỗi dài dòng hoặc cảm xúc quá đà, tập trung giải quyết vấn đề.")
                has_frustration = True
            continue

        # 5. Nhóm lời chào kết thúc
        if "lời chào kết thúc" in low or "chào kết thúc" in low:
            if not has_salutation:
                cleaned.append("- Chỉ sử dụng lời chào kết thúc một lần duy nhất ở cuối phản hồi khi cần.")
                has_salutation = True
            continue

        # 6. Các luật khác: kiểm tra trùng lặp với các luật đã giữ lại
        if any(_similar(line_clean, c) for c in cleaned):
            continue

        cleaned.append(line_clean)

    return cleaned


def _style_sources(sources: list[str], current_style: str) -> list[str]:
    """Căn cứ cho luật STYLE: bài học nguồn + luật đang có trong STYLE.md (đã duyệt ở lần trước). Thiếu phần sau thì luật
    cũ không liên quan bị coi là bịa và bị xóa (evolution_probe 2026-10-08: luật emoji/khen mất 3/3)."""
    return sources + [_ADMIN_LABEL_RE.sub("", b)[2:] for b in _extract_bullets(current_style)]


def _cap_rules(text: str, max_bullets: int = _MAX_RULE_BULLETS, max_chars: int = _MAX_RULE_CHARS) -> str:
    """Hard limit for rule files that are re-read into prompts on every call:
    the bullet-count ask in the LLM prompt is only a request. Keeps the header, strips admin labels
    ([MỚI], nguồn gốc), drops duplicate bullets, then at most max_bullets / max_chars."""
    head, bullets, seen = [], [], set()
    for line in text.splitlines():
        if line.lstrip().startswith("- "):
            line = _ADMIN_LABEL_RE.sub("", line)
            key = re.sub(r"\W+", " ", line).strip().lower()
            if key not in seen:
                seen.add(key)
                bullets.append(line.rstrip())
        else:
            head.append(line)
    kept, size = [], 0
    for b in bullets[:max_bullets]:
        if size + len(b) > max_chars:
            break
        kept.append(b)
        size += len(b)
    return "\n".join(head).rstrip() + ("\n" + "\n".join(kept) if kept else "") + "\n"


_MAX_INPUT_ENTRIES = 20


def _newest_entries(text: str, limit: int = _MAX_INPUT_ENTRIES) -> str:
    """Learning.md/Preferences.md grow with the DB; feed evolution only the
    newest `limit` "- [`key`] ..." entries (DB order is oldest first)."""
    lines = text.splitlines()
    entry_idx = [i for i, l in enumerate(lines) if l.startswith("- [`")]
    drop = set(entry_idx[:-limit]) if len(entry_idx) > limit else set()
    return "\n".join(l for i, l in enumerate(lines) if i not in drop)


def _extract_bullets(md_text: str) -> list[str]:
    """Pull just the '- ...' rule lines out of a SKILL.md/STYLE.md body, ignoring
    the YAML frontmatter and the '# ... Rules' heading."""
    return [line.strip() for line in md_text.splitlines() if line.strip().startswith("- ")]


def _similar(a: str, b: str) -> bool:
    """Same rule, reworded or extended? Cheap text checks only: near-identical (difflib ≥ 0.8)
    or the shorter one shares ≥ 80% of its words with the other (min 4 words). No embedding used:
    e5-small's cosine cannot distinguish topics (đo 2026-10-01)."""
    norm = lambda s: re.sub(r"\W+", " ", s).strip().lower()
    na, nb = norm(a), norm(b)
    if difflib.SequenceMatcher(None, na, nb).ratio() >= 0.8:
        return True
    wa, wb = set(na.split()), set(nb.split())
    if min(len(wa), len(wb)) >= 4 and len(wa & wb) / min(len(wa), len(wb)) >= 0.8:
        return True
    return False


def _merge_rules(new_text: str, old_text: str) -> str | None:
    """None = same bullet set as current, nothing to write. A block with under half
    the current bullets is a delta, not a rewrite: merge it in new-first so the
    existing rules are not clobbered."""
    old_b = [_ADMIN_LABEL_RE.sub("", b) for b in _extract_bullets(old_text)]
    new_b = [_ADMIN_LABEL_RE.sub("", b) for b in _extract_bullets(new_text)]

    # Hợp nhất và khử trùng lặp có chọn lọc
    all_bullets = new_b + [o for o in old_b if not any(_similar(o, n) for n in new_b)]
    deduped = _deduplicate_style_bullets(all_bullets)

    # Giới hạn số lượng tối đa _STYLE_MAX_BULLETS và dung lượng _STYLE_MAX_CHARS
    kept_bullets = []
    size = 0
    for b in deduped[:_STYLE_MAX_BULLETS]:
        if size + len(b) > _STYLE_MAX_CHARS:
            break
        kept_bullets.append(b)
        size += len(b)

    final_text = "# Self Evolution Style Rules\n" + "\n".join(kept_bullets) + "\n"
    return None if set(kept_bullets) == set(old_b) else final_text


# Độ phủ từ vựng tối thiểu: luật có căn cứ khi ≥ 40% số từ (đã bỏ dấu) của luật nằm trong một bài học nguồn
_GROUNDED_OVERLAP = 0.4


def _entries(text: str) -> list[str]:
    """Lesson/preference texts from Learning.md / Preferences.md ("- [`key`] text")."""
    return re.findall(r"(?m)^- \[`[^`]+`\] (.*)$", text)


def _bad_rule(line: str, sources: list[str], routing: bool) -> str | None:
    """Why this rule must not be written, else None: it names an agent/@control usage
    that does not exist, or no lesson supports it (the LLM invented it). Grounding (cả luật STYLE
    lẫn routing) dùng độ phủ từ vựng của luật trong bài học nguồn, không dùng cosine embedding
    (e5-small không phân biệt được chủ đề; đo 2026-10-01)."""
    if not routing:
        # Luật STYLE chỉ bị chặn khi chứa chính các thẻ giao thức hoặc lạc đề nghiệp vụ cụ thể
        forbidden = ["<ask_user>", "<action_run>", "<offer_protocol>"]
        line_lower = line.lower()
        for kw in forbidden:
            if kw in line_lower:
                return f"luật STYLE vi phạm chủ đề bị cấm ({kw}): do persona và soul_rules quản lý độc quyền"
        if _is_off_topic_style_rule(line):
            return "luật nghiệp vụ/công cụ cụ thể không thuộc phong cách giao tiếp STYLE"
    else:
        from engine.tools import registry
        known = set(registry.names()) | {f"agent_{k}" for k in registry.names()} | {"agent_control"}


        if re.search(r"@control\s+`?agent_(?!control)", line):
            return "@control chỉ dành cho agent_control"
        unknown = [t for t in re.findall(r"\bagent_[a-z_]+", line) if t not in known]
        if unknown:
            return f"agent không tồn tại: {unknown[0]}"

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


def _prepare_rules(new_text: str, old_text: str, sources: list[str], routing: bool) -> str | None:
    """Drop unsupported/invented rules from the new block, then merge with the current one."""
    kept = []
    for line in new_text.splitlines():
        why = _bad_rule(line, sources, routing) if line.lstrip().startswith("- ") else None
        if why:
            log.warning("🧬 Bỏ luật không hợp lệ (%s): %s", why, line.strip())
        else:
            kept.append(line)
    return _merge_rules("\n".join(kept) + "\n", old_text)


def _write_evolution_log(skill_lines: list[str], style_lines: list[str]) -> None:
    """Evolution.md = the rules evolution has added so far, per area. No dates and no
    per-run entries: a rule already listed (or a rewording of it) is not added again,
    so the file only grows when evolution learns something genuinely new."""
    try:
        text = EVOLUTION_LOG.read_text(encoding="utf-8") if EVOLUTION_LOG.exists() else ""
        areas: dict[str, list[str]] = {"Routing": [], "Giao tiếp": []}
        area = None
        for line in text.splitlines():
            if line.startswith("## "):
                area = line[3:].strip()
            elif line.startswith("- ") and area in areas:
                areas[area].append(line)
        for name, lines in (("Routing", skill_lines), ("Giao tiếp", style_lines)):
            for line in lines:
                if not any(_similar(line, old) for old in areas[name]):
                    areas[name].append(line)
        out = "# Jarvis Evolution Log\n\n<!-- JARVIS-MANAGED-EVOLUTION -->\n"
        for name, lines in areas.items():
            if lines:
                out += f"\n## {name}\n" + "\n".join(lines) + "\n"
        EVOLUTION_LOG.parent.mkdir(parents=True, exist_ok=True)
        EVOLUTION_LOG.write_text(out, encoding="utf-8")
        log.info("🧬 Đã cập nhật Evolution.md")
    except Exception as e:
        log.warning(f"🧬 Không ghi được Evolution.md: {e}")


async def trigger_cognitive_evolution() -> dict:
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
        return await _run_cognitive_evolution()


def _current_routing_proposals() -> str:
    """Đề xuất routing đã có trong Evolution.md (mục '## Routing'), để prompt không
    đề xuất lại y hệt điều đã ghi."""
    if not EVOLUTION_LOG.exists():
        return ""
    area = None
    lines = []
    for line in EVOLUTION_LOG.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            area = line[3:].strip()
        elif line.startswith("- ") and area == "Routing":
            lines.append(line)
    return "\n".join(lines)


async def _run_cognitive_evolution() -> dict:
    """Đọc Learning.md/Preferences.md, tự phân tích và ghi STYLE.md (sống) +
    đề xuất routing vào Evolution.md (chờ duyệt, không tự động áp dụng)."""
    log.info("🧬 Bắt đầu tiến trình tự tích lũy & tiến hóa (Self-Evolution)...")
    results = {
        "success": False,
        "path": "",
        "error": None
    }

    learning_path = PROJECT_ROOT / "data" / "wiki" / "System" / "Learning.md"
    pref_path = PROJECT_ROOT / "data" / "wiki" / "System" / "Preferences.md"

    learning_content = learning_path.read_text(encoding="utf-8").strip() if learning_path.exists() else ""
    pref_content = pref_path.read_text(encoding="utf-8").strip() if pref_path.exists() else ""

    learning_content = _newest_entries(learning_content)
    pref_content = _newest_entries(pref_content)

    if not learning_content and not pref_content:
        log.warning("🧬 Không tìm thấy dữ liệu học để tự tiến hóa.")
        return results

    global _last_inputs
    if (learning_content, pref_content) == _last_inputs:
        log.info("🧬 Learning/Preferences không đổi từ lần tiến hóa trước, bỏ qua.")
        results["success"] = True
        return results

    sources = _entries(learning_content) + _entries(pref_content)

    try:
        # 1. Đọc trạng thái hiện tại: STYLE.md sống, đề xuất routing đã có trong Evolution.md
        current_style = STYLE_FILE.read_text(encoding="utf-8").strip() if STYLE_FILE.exists() else ""
        current_routing_proposals = _current_routing_proposals()

        from engine.prompts.learning import build_evolution_prompt
        prompt = build_evolution_prompt(
            pref_content=pref_content,
            learning_content=learning_content,
            current_routing_proposals=current_routing_proposals,
            current_style=current_style,
        )

        response = await call_llm(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,  # tổng hợp luật có cấu trúc: tất định (0.3 dao động 2/3, evolution_probe 2026-10-08)
            thinking=False
        )
        content = response.choices[0].message.content.strip()

        parsed = parse_evolution_response(content)
        _last_inputs = (learning_content, pref_content)
        need_evolution = parsed["need_evolution"]
        reason = parsed.get("reason", "")
        log.info(f"🧬 Đánh giá nhu cầu tiến hóa: ({reason})")

        if not need_evolution:
            log.info("🧬 Không cần tiến hóa thêm ở lượt này.")
            results["success"] = True
            results["path"] = str(STYLE_FILE) if STYLE_FILE.exists() else ""
            return results

        # 3. Routing: lọc luật bịa/vô căn cứ, KHÔNG ghi file sống — chỉ đưa vào
        #    Evolution.md làm đề xuất. Style: vẫn ghi STYLE_FILE (sống, đọc mỗi lượt chat).
        style_written = False

        # Emoji chỉ thể hiện lúc chat trực tiếp; luật lưu vào STYLE.md/Evolution.md không giữ emoji.
        from engine.core.memory import strip_emojis

        routing_rules_raw = _cap_rules(strip_emojis(parsed.get("routing_rules", "").strip()))
        routing_bullets = []
        if "# Self Evolution Routing Rules" in routing_rules_raw:
            for line in routing_rules_raw.splitlines():
                if not line.lstrip().startswith("- "):
                    continue
                why = await asyncio.to_thread(_bad_rule, line, sources, True)
                if why:
                    log.warning("🧬 Bỏ đề xuất routing không hợp lệ (%s): %s", why, line.strip())
                else:
                    routing_bullets.append(line.strip())

        style_rules = _cap_rules(strip_emojis(parsed.get("style_rules", "").strip()), _STYLE_MAX_BULLETS, _STYLE_MAX_CHARS)
        if "# Self Evolution Style Rules" in style_rules and (style_rules := await asyncio.to_thread(_prepare_rules, style_rules, current_style, _style_sources(sources, current_style), False)):
            # Cùng bộ lọc với engine/turn/prompt.py khi nạp (spec 2026-10-12 mục 1.4)
            style_rules = "# Self Evolution Style Rules\n" + "\n".join(style_lines(style_rules)) + "\n"
            STYLE_FILE.parent.mkdir(parents=True, exist_ok=True)
            _write_text_atomic(STYLE_FILE, style_rules)
            style_written = True
            log.info(f"🧬 Đã cập nhật style rules: {STYLE_FILE}")

        if routing_bullets or style_written:
            final_style = style_rules if style_written else current_style
            await asyncio.to_thread(
                _write_evolution_log,
                routing_bullets,
                _extract_bullets(final_style),
            )
            results["success"] = True
            results["path"] = str(STYLE_FILE)
        else:
            log.info("🧬 Cần tiến hóa nhưng không có nội dung mới hợp lệ.")
            results["success"] = True
    except Exception as e:
        log.error(f"🧬 Thất bại trong quá trình tự tiến hóa: {e}", exc_info=True)
        results["error"] = str(e)
        
    return results
