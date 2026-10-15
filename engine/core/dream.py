# -*- coding: utf-8 -*-
"""
JARVIS Dream Cycle — Tự động dọn dẹp/gộp dữ liệu cũ khi hệ thống idle (giống chu kỳ "ngủ mơ"
để củng cố trí nhớ): tóm tắt hội thoại thừa thải trong `messages`, gọn bớt `outcomes`,
và tái tổ chức Obsidian Wiki (`data/wiki/`) — Daily digests, Topics, Errors.md, Evolution.md.

Nguyên tắc an toàn: KHÔNG BAO GIỜ xoá vĩnh viễn. Mọi bản ghi/tệp bị gộp đều được sao lưu vào
`data/dream_archive/` (bảng DB) hoặc `data/wiki/.trash/dream/` (tệp wiki, cùng quy ước
với thùng rác Obsidian có sẵn) trước khi bị xoá/ghi đè, để có thể khôi phục thủ công nếu cần.
"""

import asyncio
import json
import logging
import os
import re
import shutil
import sqlite3
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from engine.server.llm_server import call_llm
from engine.core.memory import DB_PATH, save_memory
from engine.core.memory_tree import WIKI_DIR, ensure_wiki_dirs

log = logging.getLogger("jarvis.dream")

PROJECT_ROOT = Path(__file__).parent.parent.parent
DREAM_ARCHIVE_DIR = PROJECT_ROOT / "data" / "dream_archive"
WIKI_TRASH_DIR = WIKI_DIR / ".trash" / "dream"
ERRORS_LOG = WIKI_DIR / "System" / "Errors.md"
EVOLUTION_LOG = WIKI_DIR / "System" / "Evolution.md"
DREAM_LOG = WIKI_DIR / "System" / "Dream.md"
_MAX_DREAM_LOG_ENTRIES = 20

_DATE_IN_HEADING_RE = re.compile(r"(\d{4})-?(\d{2})-?(\d{2})")

# ponytail: the local quantized model keeps its butler persona ("thưa ngài", offers
# to help more) even inside JSON summary fields despite explicit prompt instructions
# not to — a known instruction-following ceiling for this model, not fixable by
# prompting alone. Drop bullets that read as a question/offer rather than a fact.
# Upgrade path: swap for a stronger/less-quantized model, or a second LLM pass that
# specifically re-checks each bullet if this heuristic starts rejecting good content.
_JUNK_BULLET_RE = re.compile(
    r"\?\s*$|thưa ngài\s*[.!]?\s*$|ngài có (cần|muốn)|bạn có (cần|muốn)|"
    r"cần (tôi )?(cung cấp|hỗ trợ|giúp) thêm|có (yêu cầu|cần) (gì|nào) khác",
    re.IGNORECASE,
)


def _is_junk_bullet(text: str) -> bool:
    return bool(_JUNK_BULLET_RE.search(text))


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


# ---------------------------------------------------------------------------
# Archive helpers — never delete without a recoverable copy first
# ---------------------------------------------------------------------------

def _archive_jsonl(category: str, rows: list[dict], run_id: str) -> Path:
    """Snapshot DB rows about to be deleted into a recoverable JSONL file."""
    out_dir = DREAM_ARCHIVE_DIR / category
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{run_id}.jsonl"
    with open(out_path, "a", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    return out_path


def _archive_wiki_file(path: Path, run_id: str) -> Path:
    """Move a wiki file into the Dream trash (file is fully retired/replaced)."""
    relative = path.relative_to(WIKI_DIR)
    dest = WIKI_TRASH_DIR / run_id / relative
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(path), str(dest))
    return dest


def _archive_wiki_snapshot(path: Path, run_id: str) -> Path:
    """Copy a wiki file's current content into the Dream trash before compacting it in place."""
    relative = path.relative_to(WIKI_DIR)
    dest = WIKI_TRASH_DIR / run_id / relative
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(path), str(dest))
    return dest


# ---------------------------------------------------------------------------
# Pure helpers (no I/O) — safe to unit-test directly
# ---------------------------------------------------------------------------

def _split_message_chunks(messages: list[dict], gap_seconds: int = 1800) -> list[list[dict]]:
    """Split a chronological message list into conversation-like chunks by idle gaps."""
    chunks: list[list[dict]] = []
    current: list[dict] = []
    prev_ts: float | None = None
    for msg in messages:
        ts = msg["created_at"]
        if current and prev_ts is not None and (ts - prev_ts) > gap_seconds:
            chunks.append(current)
            current = []
        current.append(msg)
        prev_ts = ts
    if current:
        chunks.append(current)
    return chunks


def _split_log_entries(content: str) -> tuple[str, list[tuple[Optional[date], str]]]:
    """Split a `## `-delimited System/*.md log into (preamble, [(entry_date_or_None, block), ...]).

    Entries whose heading has no parseable date are kept with date=None so rotation never
    silently drops content it doesn't understand.
    """
    lines = content.splitlines(keepends=True)
    preamble_lines: list[str] = []
    entries: list[tuple[Optional[date], str]] = []
    current_lines: list[str] = []
    current_date: Optional[date] = None
    in_entry = False

    def flush():
        if current_lines:
            entries.append((current_date, "".join(current_lines)))

    for line in lines:
        if line.startswith("## "):
            if in_entry:
                flush()
            current_lines = [line]
            in_entry = True
            match = _DATE_IN_HEADING_RE.search(line)
            if match:
                y, m, d = match.groups()
                try:
                    current_date = date(int(y), int(m), int(d))
                except ValueError:
                    current_date = None
            else:
                current_date = None
        elif in_entry:
            current_lines.append(line)
        else:
            preamble_lines.append(line)
    if in_entry:
        flush()
    return "".join(preamble_lines), entries


# ---------------------------------------------------------------------------
# LLM-driven summarization
# ---------------------------------------------------------------------------

async def _ask_json(prompt: str, name: str, schema: dict, what: str) -> Optional[dict]:
    """Grammar JSON + think 128 (cách chung cho model nhỏ, 2026-10-14). None = không có phán đoán dùng được
    (rỗng, JSON hỏng, transport trả tool call của Headroom…): caller coi là 'thử lại chu kỳ sau', không phải 'trivial'."""
    from engine.prompts.learning import json_format
    response = await call_llm(messages=[{"role": "user", "content": prompt}], temperature=0.0, thinking=True,
                              thinking_budget=128, max_tokens=800, response_format=json_format(name, schema))
    choice = response.choices[0]
    raw = (choice.message.content or "").strip()
    try:
        data = json.loads(raw)
    except Exception:
        data = None
    if not isinstance(data, dict):
        log.warning("Dream: no usable JSON for %s (finish_reason=%s, raw=%r) — will retry next cycle",
                    what, choice.finish_reason, raw[:200])
        return None
    return data


async def _summarize_message_chunk(chunk: list[dict]) -> Optional[dict]:
    transcript = "\n".join(f"{m['role']}: {m['content']}" for m in chunk)[:6000]
    from engine.prompts.learning import DREAM_MESSAGE_SCHEMA, build_dream_message_prompt
    data = await _ask_json(build_dream_message_prompt(transcript), "dream_message", DREAM_MESSAGE_SCHEMA,
                           "a message chunk")
    if data is None or not isinstance(data.get("trivial"), bool):
        return None
    summary = str(data.get("summary") or "").strip()
    if summary and _is_junk_bullet(summary):
        summary = ""
    return {"trivial": data["trivial"], "summary": summary}


async def _summarize_wiki_note(content: str, title: str) -> Optional[str]:
    """Returns "" when the LLM judged nothing worth keeping (safe to archive), None when no usable judgment."""
    text = content.strip()
    if not text:
        return ""
    from engine.prompts.learning import DREAM_WIKI_SCHEMA, build_dream_wiki_prompt
    data = await _ask_json(build_dream_wiki_prompt(title, text[:6000]), "dream_wiki", DREAM_WIKI_SCHEMA, f"'{title}'")
    bullets = None if data is None else data.get("bullets")
    if not isinstance(bullets, list):
        return None
    clean_bullets = [str(b).strip() for b in bullets if str(b).strip() and not _is_junk_bullet(str(b))]
    return "\n".join(f"- {b}" for b in clean_bullets)


# ---------------------------------------------------------------------------
# Section 1 — messages (SQLite chat history)
# ---------------------------------------------------------------------------

def _fetch_old_messages(cutoff: float):
    conn = _connect()
    try:
        return conn.execute(
            "SELECT id, role, content, created_at FROM messages WHERE created_at < ? ORDER BY created_at ASC",
            (cutoff,),
        ).fetchall()
    finally:
        conn.close()


def _delete_messages_by_id(ids_to_delete: list[int]) -> None:
    conn = _connect()
    try:
        from engine.core.memory import delete_messages_by_id

        delete_messages_by_id(conn, ids_to_delete)
        conn.commit()
    finally:
        conn.close()


async def _dream_consolidate_messages(run_id: str, retention_days: int) -> dict:
    # Dream chạy song song với hội thoại sống (cùng ghi vào jarvis.db) — mọi
    # thao tác SQLite chặn (blocking) ở đây phải chạy qua to_thread, nếu không
    # một lần tranh chấp khoá DB có thể đóng băng cả event loop (và WebSocket
    # giọng nói đang phục vụ người dùng) tới vài giây.
    cutoff = time.time() - retention_days * 86400
    rows = await asyncio.to_thread(_fetch_old_messages, cutoff)
    if not rows:
        return {"chunks": 0, "kept": 0, "dropped": 0, "messages_removed": 0}

    messages = [dict(r) for r in rows]
    chunks = _split_message_chunks(messages)
    kept = dropped = skipped = 0
    archive_rows: list[dict] = []
    ids_to_delete: list[int] = []

    for chunk in chunks:
        if len(chunk) < 2:
            dropped += 1
            archive_rows.extend(chunk)
            ids_to_delete.extend(m["id"] for m in chunk)
            continue
        try:
            result = await _summarize_message_chunk(chunk)
            if result is None:
                # No usable judgment this cycle (e.g. Headroom tool-call round-trip) —
                # leave the chunk untouched so it's reconsidered next cycle, never
                # silently drop real chat history because of an infra hiccup.
                skipped += 1
                continue
            if result["trivial"] or not result["summary"]:
                dropped += 1
            else:
                await asyncio.to_thread(
                    save_memory, result["summary"], mem_type="fact", source="dream_cycle", importance=4
                )
                kept += 1
            archive_rows.extend(chunk)
            ids_to_delete.extend(m["id"] for m in chunk)
        except Exception as exc:
            log.warning("Dream: skip chunk (%d messages) after error: %s", len(chunk), exc)
            continue

    if ids_to_delete:
        _archive_jsonl("messages", archive_rows, run_id)
        await asyncio.to_thread(_delete_messages_by_id, ids_to_delete)

    return {
        "chunks": len(chunks), "kept": kept, "dropped": dropped,
        "skipped": skipped, "messages_removed": len(ids_to_delete),
    }


# ---------------------------------------------------------------------------
# Section 2 — outcomes (rule-based: workflows already
# captures the distilled essence of successful patterns, so raw outcomes
# older than retention are safe to prune; failures kept 2x longer for debugging)
# ---------------------------------------------------------------------------

def _fetch_stale_outcomes(cutoff: float, failure_cutoff: float) -> list[dict]:
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT id, tools, query, status, result, traces, created_at FROM outcomes "
            "WHERE (status = 'success' AND created_at < ?) OR (status != 'success' AND created_at < ?)",
            (cutoff, failure_cutoff),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _delete_outcomes_by_id(ids: list[int]) -> None:
    conn = _connect()
    try:
        conn.executemany("DELETE FROM outcomes WHERE id = ?", [(i,) for i in ids])
        conn.commit()
    finally:
        conn.close()


async def _dream_prune_outcomes(run_id: str, retention_days: int) -> dict:
    cutoff = time.time() - retention_days * 86400
    failure_cutoff = time.time() - retention_days * 2 * 86400
    rows = await asyncio.to_thread(_fetch_stale_outcomes, cutoff, failure_cutoff)
    if not rows:
        return {"removed": 0}
    ids = [r["id"] for r in rows]
    _archive_jsonl("outcomes", rows, run_id)
    await asyncio.to_thread(_delete_outcomes_by_id, ids)
    return {"removed": len(ids)}


# ---------------------------------------------------------------------------
# Section 3 — Obsidian wiki: daily digests get compacted into the monthly rollup
# ---------------------------------------------------------------------------

def extract_day_summary_from_month(month_content: str, day_str: str) -> str:
    """Pull the compact per-day block written by _append_month_summary() under
    '## Tóm tắt Dream (bản gốc đã lưu trữ)' in a monthly rollup file.

    Public (no leading underscore) because history_engine.py's date-range
    lookups need this: once Dream archives a day's original note into
    .trash/dream/, the live daily/<date>.md path no longer exists, and without
    this fallback a query for that date would silently come back empty even
    though the day's content is still available, just relocated."""
    heading = "## Tóm tắt Dream (bản gốc đã lưu trữ)"
    idx = month_content.find(heading)
    if idx < 0:
        return ""
    section = month_content[idx + len(heading):]
    marker = f"### {day_str}"
    day_idx = section.find(marker)
    if day_idx < 0:
        return ""
    body = section[day_idx + len(marker):]
    next_idx = body.find("\n### ")
    if next_idx >= 0:
        body = body[:next_idx]
    return body.strip()


def _remove_day_link(content: str, day_str: str) -> str:
    """Drop the '## Các ngày' bullet for a day whose original daily note Dream
    just archived. memory_tree.py writes that bullet as
    '- [[daily/MM-YYYY/YYYY-MM-DD|YYYY-MM-DD]]' pointing at the live file path —
    once the file moves into .trash/dream/, the link is dead, so leaving the
    bullet in place would defeat Dream's own "keep only what's necessary"
    purpose by littering the month rollup with broken references."""
    marker = f"|{day_str}]]"
    lines = [
        line for line in content.splitlines()
        if not (line.lstrip().startswith("- [[") and marker in line)
    ]
    return "\n".join(lines)


def _drop_day_link_in_month(month_dir: Path, day_str: str) -> None:
    """Same cleanup as _append_month_summary does inline, for the case where
    the day was judged trivial (no summary block added, so nothing else would
    have touched the '## Các ngày' list)."""
    month_file = month_dir / f"Tháng {month_dir.name}.md"
    if not month_file.exists():
        return
    content = month_file.read_text(encoding="utf-8")
    updated = _remove_day_link(content, day_str)
    if updated != content:
        month_file.write_text(updated.rstrip() + "\n", encoding="utf-8")


def _append_month_summary(month_dir: Path, day_str: str, summary: str) -> None:
    month_key = month_dir.name
    month_file = month_dir / f"Tháng {month_key}.md"
    heading = "## Tóm tắt Dream (bản gốc đã lưu trữ)"
    block = f"\n### {day_str}\n{summary}\n"
    content = month_file.read_text(encoding="utf-8") if month_file.exists() else f"# Hội thoại tháng {month_key}\n"
    content = _remove_day_link(content, day_str)
    if heading not in content:
        content = content.rstrip() + f"\n\n{heading}\n"
    month_file.write_text(content.rstrip() + block + "\n", encoding="utf-8")


async def _dream_consolidate_wiki_daily(run_id: str, retention_days: int) -> dict:
    ensure_wiki_dirs()
    daily_root = WIKI_DIR / "daily"
    if not daily_root.exists():
        return {"archived": 0}

    cutoff_date = (datetime.now() - timedelta(days=retention_days)).date()
    archived = skipped = 0
    for month_dir in sorted(p for p in daily_root.iterdir() if p.is_dir()):
        for day_file in sorted(month_dir.glob("*.md")):
            if day_file.name.startswith("Tháng "):
                continue  # monthly rollup file, not a daily note
            try:
                day_date = datetime.strptime(day_file.stem, "%Y-%m-%d").date()
            except ValueError:
                continue
            if day_date >= cutoff_date:
                continue
            try:
                content = day_file.read_text(encoding="utf-8")
                summary = await _summarize_wiki_note(content, title=day_file.stem)
                if summary is None:
                    # No usable judgment this cycle — keep the original in place,
                    # never archive a file we never actually got to summarize.
                    skipped += 1
                    continue
                if summary:
                    _append_month_summary(month_dir, day_file.stem, summary)
                else:
                    _drop_day_link_in_month(month_dir, day_file.stem)
                _archive_wiki_file(day_file, run_id)
                archived += 1
            except Exception as exc:
                log.warning("Dream: skip daily note %s after error: %s", day_file, exc)
    return {"archived": archived, "skipped": skipped}


# ---------------------------------------------------------------------------
# Section 4 — Obsidian wiki topics: compact only files that have grown large
# ---------------------------------------------------------------------------

async def _dream_compact_wiki_topics(run_id: str, line_threshold: int = 120) -> dict:
    topics_dir = WIKI_DIR / "topics"
    if not topics_dir.exists():
        return {"compacted": 0}

    compacted = 0
    for topic_file in sorted(topics_dir.glob("*.md")):
        try:
            content = topic_file.read_text(encoding="utf-8")
            lines = content.splitlines()
            if len(lines) < line_threshold:
                continue
            summary = await _summarize_wiki_note(content, title=topic_file.stem)
            if not summary:
                continue
            _archive_wiki_snapshot(topic_file, run_id)
            header = lines[0] if lines else f"# {topic_file.stem}"
            new_content = f"{header}\n\n<!-- Dream: đã nén từ {len(lines)} dòng, bản gốc trong .trash/dream/{run_id} -->\n\n{summary}\n"
            topic_file.write_text(new_content, encoding="utf-8")
            compacted += 1
        except Exception as exc:
            log.warning("Dream: skip topic %s after error: %s", topic_file, exc)
    return {"compacted": compacted}


# ---------------------------------------------------------------------------
# Section 5 — System logs (Errors.md / Evolution.md) rotation, rule-based
# ---------------------------------------------------------------------------

async def _rotate_system_log(path: Path, run_id: str, retention_days: int, archive_title: str) -> dict:
    if not path.exists():
        return {"archived": 0}
    content = path.read_text(encoding="utf-8")
    preamble, entries = _split_log_entries(content)
    cutoff = (datetime.now() - timedelta(days=retention_days)).date()

    keep: list[str] = []
    archive: list[str] = []
    for entry_date, text in entries:
        if entry_date is not None and entry_date < cutoff:
            archive.append(text)
        else:
            keep.append(text)
    if not archive:
        return {"archived": 0}

    archive_dir = path.parent / "Archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive_path = archive_dir / path.name
    write_header = not archive_path.exists()
    with open(archive_path, "a", encoding="utf-8") as f:
        if write_header:
            f.write(f"# {archive_title}\n\n")
        f.write("".join(archive))

    note = f"\n> Các mục cũ hơn {retention_days} ngày đã được Dream chuyển sang [[System/Archive/{path.stem}]].\n\n"
    path.write_text(preamble.rstrip("\n") + "\n" + note + "".join(keep), encoding="utf-8")
    return {"archived": len(archive)}


# ---------------------------------------------------------------------------
# Dream's own log — self-bounded so it never becomes the next thing to prune
# ---------------------------------------------------------------------------

def _write_dream_log(report: dict) -> None:
    try:
        lines = [
            f"## {report['run_id']}",
            f"- Bắt đầu: {report['started_at']} — Kết thúc: {report['finished_at']}",
        ]
        for key in ("messages", "outcomes", "wiki_daily", "wiki_topics", "errors_log", "evolution_log"):
            lines.append(f"- {key}: {report.get(key)}")
        new_entry = "\n".join(lines) + "\n"

        DREAM_LOG.parent.mkdir(parents=True, exist_ok=True)
        existing = DREAM_LOG.read_text(encoding="utf-8") if DREAM_LOG.exists() else ""
        _, entries = _split_log_entries(existing)
        entry_texts = [text for _, text in entries] + [new_entry]
        entry_texts = entry_texts[-_MAX_DREAM_LOG_ENTRIES:]

        header = (
            "# Dream Cycle Log\n\n"
            f"Lịch sử các lần Dream tự dọn dẹp dữ liệu (giữ tối đa {_MAX_DREAM_LOG_ENTRIES} lần gần nhất).\n\n"
        )
        DREAM_LOG.write_text(header + "".join(entry_texts), encoding="utf-8")
    except Exception as exc:
        log.warning("Dream: failed to write Dream.md log: %s", exc)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

async def _dream_consolidate_learnings() -> dict:
    from engine.core.learning import get_learning_engine
    return {"removed": await asyncio.to_thread(get_learning_engine().consolidate_learnings)}


async def run_dream_cycle() -> dict:
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    log.info("💤 Dream cycle started: run_id=%s", run_id)
    report: dict[str, Any] = {"run_id": run_id, "started_at": datetime.now().isoformat()}

    retention_days = int(os.getenv("DREAM_RETENTION_DAYS", "14"))
    outcome_retention_days = int(os.getenv("DREAM_OUTCOME_RETENTION_DAYS", str(retention_days)))

    sections = [
        ("messages", _dream_consolidate_messages(run_id, retention_days)),
        ("outcomes", _dream_prune_outcomes(run_id, outcome_retention_days)),
        ("learnings", _dream_consolidate_learnings()),
        ("wiki_daily", _dream_consolidate_wiki_daily(run_id, retention_days)),
        ("wiki_topics", _dream_compact_wiki_topics(run_id)),
        ("errors_log", _rotate_system_log(ERRORS_LOG, run_id, retention_days, "Errors Archive")),
        ("evolution_log", _rotate_system_log(EVOLUTION_LOG, run_id, retention_days, "Evolution Archive")),
    ]
    for name, coro in sections:
        try:
            report[name] = await coro
        except Exception as exc:
            log.warning("Dream: section '%s' failed: %s", name, exc)
            report[name] = {"error": str(exc)}

    report["finished_at"] = datetime.now().isoformat()
    _write_dream_log(report)
    log.info("💤 Dream cycle finished: run_id=%s -> %s", run_id, report)
    return report


# ---------------------------------------------------------------------------
# Scheduling — mirrors self_healing.py's watcher-loop pattern, gated on a
# nightly quiet window and on the chat being idle (reuses LearningEngine's
# activity counter so Dream never competes with the user for the LLM).
# ---------------------------------------------------------------------------

_watcher_task: Optional[asyncio.Task] = None
_last_run_ts: float = 0.0


def _dream_enabled() -> bool:
    return os.getenv("DREAM_ENABLED", "true").strip().lower() not in {"0", "false", "no"}


def _chat_is_idle() -> bool:
    try:
        from engine.core.learning import get_learning_engine
        engine = get_learning_engine()
        engine._ensure_runtime_state()
        return engine._interactive_chats == 0
    except Exception:
        return True


def _in_quiet_window(now: datetime) -> bool:
    start = int(os.getenv("DREAM_QUIET_HOUR_START", "2"))
    end = int(os.getenv("DREAM_QUIET_HOUR_END", "5"))
    return start <= now.hour < end


async def _dream_watcher_loop():
    global _last_run_ts
    log.info("💤 Dream: background watcher loop started.")
    check_interval = 1800  # kiểm tra mỗi 30 phút xem có nên chạy 1 chu kỳ Dream không
    while True:
        try:
            if _dream_enabled():
                interval_hours = float(os.getenv("DREAM_INTERVAL_HOURS", "24"))
                due = (time.time() - _last_run_ts) >= interval_hours * 3600
                if due and _in_quiet_window(datetime.now()) and _chat_is_idle():
                    await run_dream_cycle()
                    _last_run_ts = time.time()
        except Exception as exc:
            log.warning("Dream watcher error: %s", exc)
        await asyncio.sleep(check_interval)


def start_dream_watcher():
    """Khởi động task chạy nền của Dream Cycle (idempotent, giống Self-Healing)."""
    global _watcher_task
    if _watcher_task is None:
        _watcher_task = asyncio.create_task(_dream_watcher_loop())


async def shutdown_dream_watcher():
    global _watcher_task
    if _watcher_task is not None and not _watcher_task.done():
        _watcher_task.cancel()
        try:
            await _watcher_task
        except (asyncio.CancelledError, Exception):
            pass
    _watcher_task = None


def trigger_dream_cycle_now() -> asyncio.Task:
    """Fire-and-forget manual trigger (dùng cho endpoint REST hoặc lệnh thủ công)."""
    global _last_run_ts
    task = asyncio.create_task(run_dream_cycle())

    def _mark_done(_task: asyncio.Task) -> None:
        global _last_run_ts
        _last_run_ts = time.time()

    task.add_done_callback(_mark_done)
    return task
