import asyncio
import json
import sqlite3
import time
import logging
import re
import sys
import unicodedata
from pathlib import Path

import numpy as np
from engine.core.db_ids import insert_with_lowest_free_id
from typing import Optional, Any

PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

log = logging.getLogger("jarvis.learning")

LEGACY_LEARN_DB_PATH = PROJECT_ROOT / "data" / "learning" / "learn.db"
MEMORY_DB_PATH = PROJECT_ROOT / "data" / "jarvis.db"
WORKFLOWS_WIKI_DIR = PROJECT_ROOT / "data" / "wiki" / "System" / "Workflows"
PREFERENCES_WIKI_PATH = PROJECT_ROOT / "data" / "wiki" / "System" / "Preferences.md"
LESSONS_WIKI_PATH = PROJECT_ROOT / "data" / "wiki" / "System" / "Learning.md"
WORKFLOWS_HUB_WIKI_PATH = WORKFLOWS_WIKI_DIR / "Công cụ.md"
LEARNING_HUB_WIKI_PATH = PROJECT_ROOT / "data" / "wiki" / "System" / "Học hỏi.md"


def _write_wiki_link_index(path: Path, targets) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    links = [f"[[{target}]]" for target in targets]
    content = "\n".join(links) + ("\n" if links else "")
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return
    path.write_text(content, encoding="utf-8")


_QUERY_PUNCT = re.compile(r"[.,!?;:\"'“”‘’…()\[\]]")


def normalize_query(text: str) -> str:
    """Khoá khớp workflow: chữ thường, bỏ dấu câu, gộp khoảng trắng."""
    return " ".join(_QUERY_PUNCT.sub(" ", text or "").casefold().split())


def _cosine(a, b) -> float | None:
    """Cosine hai vector; thiếu hoặc khác số chiều (đổi embedder) → None, không lỗi."""
    if not a or not b or len(a) != len(b):
        return None
    va, vb = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    n = float(np.linalg.norm(va) * np.linalg.norm(vb))
    return float(va @ vb / n) if n else None


_CORRECTION_WINDOW = 86400  # lời sửa phải đến trong 24 giờ sau lượt dùng sai tool (spec 2026-10-13 §1)
MAX_PROPOSALS = 4  # một lượt dạy 3-4 luật (log 2026-10-14 19:30: tối đa 2 làm rơi luật thứ 3)
_CORRECTION = re.compile(r"sai rồi|nhầm rồi|phải dùng|phải tra|dùng \S+ (?:đi|mới đúng)")
DEDUPE_SIM = 0.90  # embed_probe 2026-10-13: cùng ý ≥ 0.86, khác ý ≤ 0.82 (EmbeddingGemma 2)


def _sync_learning_hub() -> None:
    _write_wiki_link_index(
        LEARNING_HUB_WIKI_PATH,
        ("Errors", "Learning", "Preferences", "Evolution"),
    )


_EXAMPLE_PAREN_RE = re.compile(r"\s*\((?:ví dụ|vd|chẳng hạn|evidence)\b[^)]*\)", re.IGNORECASE)


def strip_examples(text: str) -> str:
    """Bài học chỉ nêu khái niệm: bỏ "(ví dụ: …)"/"(Evidence: …)". Các câu đó vào prompt chat mỗi lượt và model chép
    theo (Learning.md 2026-10-08 có "(ví dụ: 'mở bài tôi thích')"); bằng chứng đã nằm ở trường evidence."""
    return re.sub(r"\.\s*\.", ".", _EXAMPLE_PAREN_RE.sub("", text or "")).strip()


def _is_valid_learning_text(content: Any, min_len: int = 10, max_len: int = 1200) -> bool:
    """Kiểm tra tính hợp lệ cơ bản của chuỗi văn bản tri thức/bài học."""
    if not isinstance(content, str):
        return False
    normalized = " ".join(content.split()).strip()
    return min_len <= len(normalized) <= max_len


LEXICAL_DUPLICATE_THRESHOLD = 0.40
LEXICAL_CONTAINMENT_THRESHOLD = 0.70
LEXICAL_CLOSEST_MIN = 0.10


def _lexical_tokens(text: str) -> set[str]:
    folded = unicodedata.normalize("NFKD", (text or "").lower().replace("đ", "d"))
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    return {w for w in re.findall(r"[a-z0-9]+", folded) if len(w) > 1}


_FILLER_TOKENS = {"luon", "that", "rat", "hay", "nhe", "nha", "khi", "va", "cua", "cho", "la", "se", "nen", "phai", "cung",
                  "hon", "nhu", "vay", "the", "nao"}


def adds_new_information(new: str, old: str) -> bool:
    """Câu mới có thêm ý mà câu cũ chưa có không (≥ 2 từ nội dung mới)? Nói lại điều đã học bằng chữ khác thì không
    (probe 2026-10-08: 'Luôn trả lời ngắn gọn.' đè lên 'Trả lời ngắn gọn, không giải thích dài dòng.')."""
    return len(_lexical_tokens(new) - _lexical_tokens(old) - _FILLER_TOKENS) >= 2


def _lexically_similar(a: str, b: str) -> bool:
    """Độ tương đồng từ vựng kết hợp Jaccard và Containment (tỷ lệ bao hàm từ của câu ngắn trong câu dài)."""
    ta, tb = _lexical_tokens(a), _lexical_tokens(b)
    if not ta or not tb:
        return False
    inter = len(ta & tb)
    if not inter:
        return False
    jaccard = inter / len(ta | tb)
    if jaccard >= LEXICAL_DUPLICATE_THRESHOLD:
        return True
    min_len = min(len(ta), len(tb))
    if min_len >= 3 and (inter / min_len) >= LEXICAL_CONTAINMENT_THRESHOLD:
        return True
    return False


class LearningEngine:

    def __init__(self):
        self.log_path = PROJECT_ROOT / "logs" / "jarvis.log"
        self.last_position = 0
        self._init_runtime_state()
        self._init_db()

    def _init_runtime_state(self, idle_grace_seconds: float = 5.0) -> None:
        # The interactive-chat counter now lives in engine.core.activity_gate so
        # every background job can consult it, not just this engine.
        from engine.core import activity_gate
        self._gate = activity_gate.get_gate()
        self._idle_grace_seconds = idle_grace_seconds
        self._learning_queue = None
        self._learning_worker_task = None
        self._active_learning_task = None
        self._learning_preempted = False
        self._evolution_tasks: set[asyncio.Task] = set()
        self._just_learned: dict[int, dict] = {}  # mục do lượt học gần nhất ghi, {id: {"previous": nội dung cũ | None}}

    def _ensure_runtime_state(self) -> None:
        if not hasattr(self, "_gate"):
            self._init_runtime_state()

    @property
    def _interactive_chats(self) -> int:
        self._ensure_runtime_state()
        return self._gate.interactive_chats

    def begin_interactive_chat(self) -> None:
        """Give WebUI/Telegram priority over every background job."""
        self._ensure_runtime_state()
        self._gate.begin()
        if self._active_learning_task is not None and not self._active_learning_task.done():
            self._learning_preempted = True
            self._active_learning_task.cancel()
            log.info("Conversation learning deferred: interactive chat started")

    def end_interactive_chat(self) -> None:
        self._ensure_runtime_state()
        self._gate.end()

    async def _wait_until_chat_idle(self) -> None:
        self._ensure_runtime_state()
        await self._gate.wait_until_idle(self._idle_grace_seconds)

    def schedule_conversation_learning(
        self,
        user_message: str,
        assistant_message: str,
    ) -> asyncio.Future:
        """Queue one completed turn; processing starts only while chat is idle."""
        self._ensure_runtime_state()
        loop = asyncio.get_running_loop()
        completion = loop.create_future()
        if self._learning_queue is None:
            self._learning_queue = asyncio.Queue()
        self._learning_queue.put_nowait((user_message, assistant_message, completion))
        if self._learning_worker_task is None or self._learning_worker_task.done():
            self._learning_worker_task = asyncio.create_task(
                self._learning_worker(), name="conversation-learning-worker"
            )
        return completion

    async def _learning_worker(self) -> None:
        while True:
            item = await self._learning_queue.get()
            user_message, assistant_message, completion = item
            try:
                while True:
                    await self._wait_until_chat_idle()
                    run_task = asyncio.create_task(
                        self._process_scheduled_learning(user_message, assistant_message)
                    )
                    self._active_learning_task = run_task
                    try:
                        result = await run_task
                        if not completion.done():
                            completion.set_result(result)
                        break
                    except asyncio.CancelledError:
                        if self._learning_preempted:
                            self._learning_preempted = False
                            continue
                        raise
                    finally:
                        if self._active_learning_task is run_task:
                            self._active_learning_task = None
            except Exception as exc:
                log.warning("Scheduled conversation learning failed: %s", exc)
                if not completion.done():
                    completion.set_result({"stored": 0, "error": str(exc), "items": []})
            finally:
                self._learning_queue.task_done()

    async def _process_scheduled_learning(self, user_message: str, assistant_message: str) -> dict:
        learning_result = await self.process_conversation_learning(user_message, assistant_message)
        # Chỉ kích hoạt Evolution Engine khi lượt này thực sự học được điều gì mới;
        # tránh gọi LLM phân tích lại toàn bộ Learning.md/Preferences.md một cách vô ích.
        learned_something_new = learning_result.get("stored", 0) > 0
        if learned_something_new:
            try:
                from engine.core.evolution import trigger_cognitive_evolution
                evo_task = asyncio.create_task(trigger_cognitive_evolution())
                self._evolution_tasks.add(evo_task)
                evo_task.add_done_callback(self._on_evolution_task_done)
                log.info("🧬 Cognitive evolution triggered after idle conversation learning")
            except Exception as evo_err:
                log.warning("Failed to trigger cognitive evolution: %s", evo_err)

        log.info(
            "Conversation learning complete: conversation_stored=%s conversation_discarded=%s",
            learning_result.get("stored", 0),
            learning_result.get("discarded", False),
        )
        return {"learning": learning_result}

    def _on_evolution_task_done(self, task: asyncio.Task) -> None:
        self._evolution_tasks.discard(task)
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            log.warning("Cognitive evolution task failed: %s", exc)

    async def shutdown_learning_scheduler(self) -> None:
        self._ensure_runtime_state()
        tasks = [
            task for task in (self._active_learning_task, self._learning_worker_task)
            if task is not None and not task.done()
        ]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._active_learning_task = None
        self._learning_worker_task = None

    # ------------------------------------------------------------------
    # DB helpers
    # ------------------------------------------------------------------

    def _get_learning_db(self) -> sqlite3.Connection:
        MEMORY_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(MEMORY_DB_PATH))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _get_memory_db(self) -> sqlite3.Connection:
        MEMORY_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(MEMORY_DB_PATH))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self):
        conn = self._get_learning_db()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS learnings (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                type        TEXT NOT NULL DEFAULT 'lesson',
                semantic_key TEXT NOT NULL DEFAULT '',
                content     TEXT NOT NULL,
                source      TEXT DEFAULT '',
                importance  INTEGER DEFAULT 5,
                created_at  REAL NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_learn_type ON learnings(type);
            CREATE INDEX IF NOT EXISTS idx_learn_created ON learnings(created_at DESC);

            CREATE TABLE IF NOT EXISTS outcomes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tools TEXT NOT NULL,
                query TEXT NOT NULL,
                status TEXT NOT NULL,
                result TEXT DEFAULT '',
                traces TEXT DEFAULT '[]',
                created_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_outcomes_tools_status ON outcomes(tools, status);

            CREATE TABLE IF NOT EXISTS workflows (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tools TEXT NOT NULL,
                intent TEXT NOT NULL,
                tool_chain TEXT NOT NULL UNIQUE,
                sample_queries TEXT NOT NULL DEFAULT '[]',
                success_evidence TEXT NOT NULL,
                validation_count INTEGER NOT NULL DEFAULT 1,
                wiki_path TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_workflows_tools ON workflows(tools);

            CREATE TABLE IF NOT EXISTS corrections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                query TEXT NOT NULL,
                query_norm TEXT NOT NULL,
                wrong_tool TEXT NOT NULL,
                right_tool TEXT NOT NULL,
                count INTEGER NOT NULL DEFAULT 1,
                embedding TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                UNIQUE(query_norm, wrong_tool, right_tool)
            );
        """)
        learning_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(learnings)").fetchall()
        }
        if "semantic_key" not in learning_columns:
            conn.execute(
                "ALTER TABLE learnings ADD COLUMN semantic_key TEXT NOT NULL DEFAULT ''"
            )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_learn_semantic_key "
            "ON learnings(type, semantic_key)"
        )
        conn.commit()
        conn.close()
        self._migrate_legacy_learnings()
        self._migrate_outcomes_workflows()
        self._migrate_add_embedding_column()
        self._migrate_add_embedding_model_column()
        self._sync_learning_wiki()

    def _migrate_outcomes_workflows(self) -> None:
        """2026-10-13: không còn agent — agent_outcomes → outcomes (giữ dữ liệu); validated_workflows định dạng
        agent cũ không phát lại được → bỏ, kèm tệp wiki của agent cũ."""
        conn = self._get_learning_db()
        try:
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "agent_outcomes" in tables:
                conn.execute("INSERT INTO outcomes (tools, query, status, result, traces, created_at) "
                             "SELECT agent, query, status, result, traces, created_at FROM agent_outcomes")
                conn.execute("DROP TABLE agent_outcomes")
            old_agents: list[str] = []
            if "validated_workflows" in tables:
                old_agents = [r[0] for r in conn.execute("SELECT DISTINCT agent FROM validated_workflows")]
                conn.execute("DROP TABLE validated_workflows")
            conn.commit()
        finally:
            conn.close()
        for agent in old_agents:
            try:
                (WORKFLOWS_WIKI_DIR / f"{agent}.md").unlink(missing_ok=True)
            except OSError as exc:
                log.warning("Không xoá được wiki workflow cũ %s: %s", agent, exc)
        if old_agents:
            self._sync_workflow_hub()

    def _migrate_add_embedding_column(self):
        """Add embedding column (JSON float list) for semantic duplicate detection."""
        conn = None
        try:
            conn = self._get_learning_db()
            conn.execute("ALTER TABLE learnings ADD COLUMN embedding TEXT NOT NULL DEFAULT ''")
            conn.commit()
        except sqlite3.OperationalError:
            pass  # Column already exists
        finally:
            if conn is not None:
                conn.close()

    def _migrate_add_embedding_model_column(self):
        """Add embedding_model column to track which embedder was used."""
        conn = None
        try:
            conn = self._get_learning_db()
            conn.execute("ALTER TABLE learnings ADD COLUMN embedding_model TEXT NOT NULL DEFAULT ''")
            conn.commit()
        except sqlite3.OperationalError:
            pass  # Column already exists
        finally:
            if conn is not None:
                conn.close()

    @staticmethod
    def _normalise_key(value: str) -> str:
        # Fold Vietnamese diacritics first: the bare regex used to turn every
        # accented letter into "_" ("Chỉ chạy khi cần" -> "ch__ch_y_khi_c_n").
        folded = unicodedata.normalize("NFKD", value.lower().replace("đ", "d"))
        folded = "".join(c for c in folded if not unicodedata.combining(c))
        return re.sub(r"[^a-z0-9_-]+", "_", folded).strip("_")[:80]


    @staticmethod
    def _sync_managed_wiki_entries(
        path: Path, title: str, entries: list[tuple[str, str]]
    ) -> None:
        """Replace only Jarvis-managed entries; preserve handwritten Wiki content."""
        marker = "<!-- JARVIS-MANAGED-LEARNING -->"
        heading = "## Distilled entries"
        path.parent.mkdir(parents=True, exist_ok=True)
        existing = path.read_text(encoding="utf-8") if path.exists() else f"# {title}\n"
        lines = existing.splitlines()
        managed_lines = [f"- [`{key}`] {content.strip()}" for key, content in entries]

        if marker not in lines:
            prefix = lines
            suffix: list[str] = []
        else:
            marker_index = lines.index(marker)
            prefix = lines[:marker_index]
            suffix = [
                line
                for line in lines[marker_index + 1 :]
                if not re.match(r"^- \[`[^`]+`\] .*$", line)
            ]
            if heading in suffix:
                suffix.remove(heading)

        updated_lines = prefix
        while updated_lines and not updated_lines[-1].strip():
            updated_lines.pop()
        updated_lines.extend(["", marker, heading, *managed_lines])
        if suffix:
            while suffix and not suffix[0].strip():
                suffix.pop(0)
            if suffix:
                updated_lines.extend(["", *suffix])
        path.write_text("\n".join(updated_lines).rstrip() + "\n", encoding="utf-8")

    def _sync_learning_wiki(self) -> None:
        """Make jarvis.db the source of truth for Jarvis-managed Wiki entries."""
        conn = self._get_learning_db()
        rows = conn.execute(
            """SELECT id, type, semantic_key, content
               FROM learnings ORDER BY id ASC"""
        ).fetchall()
        conn.close()
        preferences: list[tuple[str, str]] = []
        lessons: list[tuple[str, str]] = []
        for row in rows:
            key = str(row["semantic_key"] or f"learning_{row['id']}")
            entry = (key, str(row["content"]))
            if row["type"] in ("preference", "user_fact"):
                preferences.append(entry)
            else:
                lessons.append(entry)
        self._sync_managed_wiki_entries(
            PREFERENCES_WIKI_PATH, "User preferences", preferences
        )
        conn = self._get_learning_db()
        fixes = conn.execute("SELECT id, query, wrong_tool, right_tool, count FROM corrections ORDER BY id").fetchall()
        conn.close()
        lessons += [(f"sua_cong_cu_{r['id']}", f"\"{r['query']}\": không dùng {r['wrong_tool']}, dùng {r['right_tool']} "
                     f"({r['count']} lần)" if r["wrong_tool"] else f"{r['query']}: dùng {r['right_tool']}") for r in fixes]
        self._sync_managed_wiki_entries(
            LESSONS_WIKI_PATH, "Jarvis learning", lessons
        )
        _sync_learning_hub()

    def consolidate_learnings(self) -> int:
        """Delete older lexically similar learnings (same type), keeping the newest,
        then rebuild the wiki notes. Dedupe sử dụng lexical, không cosine (e5-small không phân biệt ý).
        Returns how many rows were removed."""
        conn = self._get_learning_db()
        rows = conn.execute(
            "SELECT id, type, content FROM learnings ORDER BY id DESC"
        ).fetchall()
        rows = [dict(r) for r in rows]
        kept: list = []
        doomed: list[int] = []
        for row in rows:
            for other in kept:
                if other["type"] != row["type"]:
                    continue
                if _lexically_similar(row["content"], other["content"]):
                    doomed.append(row["id"])
                    break
            else:
                kept.append(row)
        if doomed:
            conn.executemany("DELETE FROM learnings WHERE id=?", [(i,) for i in doomed])
            conn.commit()
        conn.close()
        if doomed:
            self._sync_learning_wiki()
            log.info("🧹 Consolidated learnings: removed %d duplicate(s)", len(doomed))
        return len(doomed)

    # ------------------------------------------------------------------
    # Embedding của bài học: chỉ để xem/sửa trong Memory Center. KHÔNG dùng để so trùng:
    # e5-small nén thang cosine (chủ đề khác vẫn 0.88-0.95, cùng ý 0.94-0.97; đo 2026-10-01),
    # nên trùng lặp do chữ (Jaccard) và bước phản biện quyết định.
    # ------------------------------------------------------------------

    @staticmethod
    def _embed_text(content: str) -> Optional[list]:
        """Nhúng văn bản qua embedder sẵn có; trả None nếu embedder chưa sẵn sàng."""
        try:
            from engine.core.memory import SemanticMemoryEngine
            vec = SemanticMemoryEngine.get_instance()._get_embedding(content)
            return vec.tolist() if vec is not None else None
        except Exception as exc:
            log.info("Embedding unavailable for semantic dedup: %s", exc)
            return None

    @staticmethod
    def _embedding_fields(content: str) -> tuple[str, str]:
        """Tính embedding và trả (embedding_json, model).
        embedding_json: chuỗi JSON mảng số hoặc chuỗi rỗng
        model: tên embedder hoặc chuỗi rỗng"""
        import os
        embedding = LearningEngine._embed_text(content)
        embedding_json = json.dumps(embedding, ensure_ascii=False) if embedding else ""
        model = os.getenv("LOCAL_EMBED_MODEL", "") if embedding else ""
        return embedding_json, model

    def _store_learning(self, content: str, kind: str, key: str) -> bool:
        if kind in {"feedback_lesson", "behaviour_lesson"} and not _is_valid_learning_text(content):
            return False
        if kind not in {"feedback_lesson", "behaviour_lesson", "fact", "user_fact", "preference"}:
            return False
        key = self._normalise_key(key)
        if not key:
            return False
        learn_type = {
            "feedback_lesson": "lesson",
            "behaviour_lesson": "lesson",
            "fact": "user_fact",
            "user_fact": "user_fact",
            "preference": "preference",
        }.get(kind, "lesson")
        importance = 8 if kind == "preference" else 7
        # Emoji chỉ thể hiện lúc chat trực tiếp; dữ liệu học lưu vào DB/wiki không giữ emoji.
        from engine.core.memory import strip_emojis
        normalized_content = strip_examples(strip_emojis(content.strip()))
        embedding_json, embedding_model = self._embedding_fields(normalized_content)
        conn = self._get_learning_db()
        existing_content = conn.execute(
            "SELECT id FROM learnings WHERE LOWER(TRIM(content)) = LOWER(TRIM(?))",
            (normalized_content,),
        ).fetchone()
        if existing_content:
            conn.close()
            log.info("⏭️ Duplicate learning content skipped: '%s'", normalized_content)
            return False

        existing = conn.execute(
            """SELECT id, content FROM learnings
               WHERE type=? AND semantic_key=? ORDER BY id ASC LIMIT 1""",
            (learn_type, key),
        ).fetchone()
        if existing:
            changed = existing["content"].strip() != normalized_content
            if changed:
                conn.execute(
                    """UPDATE learnings
                       SET content=?, source=?, importance=?, embedding=?, embedding_model=?
                       WHERE id=?""",
                    (
                        normalized_content,
                        "explicit_conversation_learning",
                        importance,
                        embedding_json,
                        embedding_model,
                        existing["id"],
                    ),
                )
        else:
            duplicate_id = None
            for row in conn.execute("SELECT id, content FROM learnings WHERE type=?", (learn_type,)):
                if _lexically_similar(normalized_content, row["content"]):
                    duplicate_id = row["id"]
                    break
            if duplicate_id is not None:
                conn.close()
                log.info(
                    "⏭️ Duplicate learning skipped (matches id=%s): '%s'",
                    duplicate_id,
                    normalized_content,
                )
                return False
            insert_with_lowest_free_id(
                conn,
                "learnings",
                ("type", "semantic_key", "content", "source", "importance", "created_at", "embedding", "embedding_model"),
                (
                    learn_type,
                    key,
                    normalized_content,
                    "explicit_conversation_learning",
                    importance,
                    time.time(),
                    embedding_json,
                    embedding_model,
                ),
            )
            changed = True
        conn.commit()
        conn.close()
        self._sync_learning_wiki()
        return changed

    _FORBIDDEN_KEYWORDS = ("<ask_user>", "<action_run>", "<offer_protocol>")

    @staticmethod
    def _normalize_kind(kind: str) -> str:
        if not kind:
            return ""
        k = kind.split("|")[0].strip().lower()
        if k in ("user_preference", "pref"):
            return "preference"
        if k in ("feedback_lesson", "lesson", "behaviour"):
            return "behaviour_lesson"
        if k in ("fact",):
            return "user_fact"
        return k

    @staticmethod
    def _norm_evidence(text: str) -> str:
        """Chuẩn hoá bằng chứng: casefold, normalize unicode, bỏ dấu câu."""
        text = str(text or "").strip()
        # casefold
        text = text.casefold()
        # normalize unicode (NFC)
        text = unicodedata.normalize("NFC", text)
        # bỏ tiền tố role
        text = re.sub(r"^(?:user|người dùng|assistant|jarvis):\s*", "", text, flags=re.IGNORECASE)
        # thay ký tự không phải chữ/số bằng khoảng trắng, gộp khoảng trắng
        text = re.sub(r"[^\w]+", " ", text)
        text = " ".join(text.split()).strip()
        return text

    def _validate_proposal_evidence(self, item: dict, user_text: str, conversation_text: str = "") -> bool:
        evidence = str(item.get("evidence", "")).strip()
        evidence = self._norm_evidence(evidence)
        if not evidence:
            return False
        kind = self._normalize_kind(item.get("kind", ""))
        if kind in ("user_fact", "preference", "fact"):
            norm_user = self._norm_evidence(user_text)
            return evidence in norm_user
        all_text = f"{user_text} {conversation_text}"
        norm_all = self._norm_evidence(all_text)
        return evidence in norm_all

    @staticmethod
    def _is_explicit_learning_request(text: str) -> bool:
        """Kiểm tra xem tin nhắn có yêu cầu học rõ ràng không (ghi nhớ, học, hạn chế, đổi hành vi)."""
        if not text:
            return False
        t_low = text.lower()
        patterns = [
            r"ghi nhớ",
            r"hãy nhớ",
            r"nhớ\s+(?:giùm|giúp|nhé|lại)",
            r"học hỏi",
            r"hãy học",
            r"học\s+(?:đi|lấy|nhé)",
            r"nhớ\s+(?:lấy|kỹ|là)",
            r"lần sau",
            r"từ giờ",
            r"từ nay",
            r"về sau",
            r"hạn chế",
            r"đừng\s+.{0,40}?\s+nữa",
            r"không được\s+.{0,40}?\s+nữa",
        ]
        for pattern in patterns:
            if re.search(pattern, t_low):
                return True
        return False

    def _is_forbidden_topic(self, text: str, kind: str = "behaviour_lesson") -> bool:
        """Luật hành vi/sở thích không được bàn chuyện hỏi, xin phép, công cụ, agent, thẻ.
        Sự thật về ngài (user_fact) không phải luật hành vi nên không lọc."""
        if not text or kind == "user_fact":
            return False
        t_low = text.lower()
        return any(re.search(rf"(?<!\w){re.escape(kw)}(?!\w)", t_low) for kw in self._FORBIDDEN_KEYWORDS)

    def _embedding_duplicate(self, kind: str, content: str) -> int | None:
        """id mục cùng loại có cosine ≥ DEDUPE_SIM; embedder lỗi/khác chiều → None (để critique quyết)."""
        vec = self._embed_text(content)
        if not vec:
            return None
        learn_type = {"behaviour_lesson": "lesson", "user_fact": "user_fact", "preference": "preference"}.get(kind, "lesson")
        conn = self._get_learning_db()
        try:
            rows = conn.execute("SELECT id, embedding FROM learnings WHERE type=?", (learn_type,)).fetchall()
        finally:
            conn.close()
        for r in rows:
            sim = _cosine(vec, json.loads(r["embedding"]) if r["embedding"] else None)
            if sim is not None and sim >= DEDUPE_SIM:
                return r["id"]
        return None

    def _find_closest_existing_learning(self, kind: str, key: str, content: str) -> dict | None:
        """Tìm mục học hiện có gần nhất (khớp semantic_key, tương đồng key, sau đó tương đồng văn bản)."""
        learn_type = {"behaviour_lesson": "lesson", "user_fact": "user_fact", "preference": "preference"}.get(kind, "lesson")
        conn = self._get_learning_db()

        # 1. Khớp tuyệt đối semantic_key cùng loại
        row = conn.execute(
            "SELECT id, type, semantic_key, content FROM learnings WHERE type=? AND semantic_key=? LIMIT 1",
            (learn_type, key),
        ).fetchone()
        if row:
            conn.close()
            return dict(row)

        # 2. Quét toàn bộ learnings để tính độ tương đồng từ vựng và key
        rows = conn.execute(
            "SELECT id, type, semantic_key, content FROM learnings"
        ).fetchall()

        best_match = None
        best_score = 0.0
        ta_content = _lexical_tokens(content)
        ta_key = _lexical_tokens(key.replace("_", " "))

        for r in rows:
            tb_content = _lexical_tokens(r["content"])
            tb_key = _lexical_tokens(str(r["semantic_key"] or "").replace("_", " "))

            score_content = 0.0
            if ta_content and tb_content:
                inter = len(ta_content & tb_content)
                if inter:
                    jaccard = inter / len(ta_content | tb_content)
                    containment = inter / min(len(ta_content), len(tb_content))
                    score_content = max(jaccard, containment * 0.85)

            score_key = 0.0
            if ta_key and tb_key:
                inter_k = len(ta_key & tb_key)
                if inter_k:
                    score_key = inter_k / len(ta_key | tb_key)

            base_score = max(score_content, score_key * 0.9)
            if base_score > 0:
                type_bonus = 0.1 if r["type"] == learn_type else 0.0
                total_score = base_score + type_bonus
            else:
                total_score = 0.0

            if total_score > best_score:
                best_score, best_match = total_score, dict(r)

        conn.close()

        # Chỉ trả nếu đạt LEXICAL_CLOSEST_MIN
        if best_match and best_score >= LEXICAL_CLOSEST_MIN:
            return best_match
        return None

    def _apply_critique_decision(
        self,
        decision: str,
        target_item: dict | None,
        proposal: dict,
        merged_content: str = "",
    ) -> bool:
        if decision == "skip":
            log.info("⏭️ Critique quyết định bỏ qua: %s", proposal.get("content"))
            return False

        kind = proposal.get("kind", "")
        learn_type = {"behaviour_lesson": "lesson", "user_fact": "user_fact", "preference": "preference"}.get(kind, "lesson")
        key = self._normalise_key(proposal.get("key", ""))

        if decision in ("merge", "replace"):
            if not target_item or "id" not in target_item:
                log.warning("Critique merge/replace thất bại: không có target_item hợp lệ")
                return False

            target_id = target_item["id"]
            conn = self._get_learning_db()
            row = conn.execute("SELECT id, content FROM learnings WHERE id=?", (target_id,)).fetchone()
            if not row:
                conn.close()
                log.warning("Critique merge/replace thất bại: target_id=%s không tồn tại trong DB", target_id)
                return False

            new_text = merged_content.strip() if decision == "merge" and merged_content else proposal.get("content", "").strip()
            from engine.core.memory import strip_emojis
            normalized_content = strip_emojis(new_text)
            embedding_json, embedding_model = self._embedding_fields(normalized_content)

            conn.execute(
                """UPDATE learnings
                   SET content=?, embedding=?, embedding_model=?, source=?
                   WHERE id=?""",
                (normalized_content, embedding_json, embedding_model, f"reflective_{decision}", target_id),
            )
            conn.commit()
            conn.close()
            self._sync_learning_wiki()
            self._just_learned[target_id] = {"previous": row["content"]}
            log.info("🔄 Critique %s thành công trên id=%s: '%s'", decision, target_id, normalized_content)
            return True

        if decision == "new":
            before = self._learning_row(learn_type, key)
            stored = self._store_learning(proposal.get("content", ""), kind, key)
            if stored:
                from engine.core.memory import strip_emojis
                row = self._learning_row(learn_type, content=strip_emojis(proposal.get("content", "").strip()))
                if row:
                    self._just_learned[row["id"]] = {"previous": before["content"] if before and before["id"] == row["id"] else None}
            return stored

        return False

    def _learning_row(self, learn_type: str, key: str = "", content: str = "") -> dict | None:
        conn = self._get_learning_db()
        if content:
            row = conn.execute("SELECT id, content FROM learnings WHERE content=? ORDER BY id DESC LIMIT 1", (content,)).fetchone()
        else:
            row = conn.execute(
                "SELECT id, content FROM learnings WHERE type=? AND semantic_key=? ORDER BY id ASC LIMIT 1", (learn_type, key)
            ).fetchone()
        conn.close()
        return dict(row) if row else None

    def reembed_learnings(self, record_id: int | None = None) -> dict:
        """Tính lại embedding cho một bản ghi hoặc tất cả bản ghi.
        record_id=None: tính lại tất cả
        Embedder không trả vector ⇒ KHÔNG đụng vào bản ghi đó (giữ vector cũ); không bản ghi nào tính được
        ⇒ {"updated": 0, "error": "embedder_unavailable"}."""
        conn = self._get_learning_db()
        try:
            if record_id is not None:
                rows = conn.execute("SELECT id, content FROM learnings WHERE id=?", (record_id,)).fetchall()
            else:
                rows = conn.execute("SELECT id, content FROM learnings").fetchall()
            updated = 0
            for row in rows:
                emb_json, emb_model = self._embedding_fields(row["content"])
                if not emb_json:
                    continue
                conn.execute(
                    "UPDATE learnings SET embedding=?, embedding_model=? WHERE id=?",
                    (emb_json, emb_model, row["id"]),
                )
                updated += 1
            conn.commit()
        finally:
            conn.close()
        if rows and not updated:
            return {"updated": 0, "error": "embedder_unavailable"}
        return {"updated": updated}

    def _retract_learning(self, proposal: dict, user_text: str, just: dict) -> bool:
        """Gỡ bài học (spec §4): ngài phàn nàn đúng điều vừa học ở lượt trước → hoàn tác qua hàm của Memory Center.
        Chỉ đụng mục do chính lượt học trước ghi; mục gộp/thay thế được trả về nội dung cũ."""
        try:
            target_id = int(proposal.get("target_id"))
        except (TypeError, ValueError):
            return False
        if target_id not in just:
            log.info("⏭️ Retract rejected: id=%s không phải mục vừa học", target_id)
            return False
        if not self._validate_proposal_evidence({**proposal, "kind": "user_fact"}, user_text):
            log.info("⏭️ Retract rejected: evidence không nằm trong lời ngài")
            return False
        previous = just.pop(target_id)["previous"]
        if previous is None:
            done = self.delete_learning_control_record("learning", target_id)
        else:
            done = self.update_learning_control_record("learning", target_id, {"content": previous})
        log.info("↩️ Retract learning id=%s (%s): %s", target_id, "restore" if previous else "delete", done)
        return bool(done)

    async def process_conversation_learning(self, user_message: str, assistant_message: str) -> dict:
        """Quy trình học tự phản tư 2 vòng (spec 2026-09-25 §4):
        Vòng 1: Đề xuất (learning_propose.md)
        Vòng 2: Phản biện (learning_critique.md) với mục cũ gần nhất
        """
        if not user_message or not user_message.strip():
            return {"stored": 0, "discarded": True, "items": []}

        # Ngài 2026-10-14: chỉ học khi ngài dạy rõ (ghi nhớ, học đi, từ giờ…) hoặc sửa tool; trò chuyện, chê trách → không học.
        # Lượt trước vừa học: cho qua để ngài rút lại (retract) điều vừa ghi.
        if not (self._is_explicit_learning_request(user_message) or _CORRECTION.search(user_message.lower())
                or self._just_learned):
            return {"stored": 0, "discarded": True, "items": []}

        # 3–5 lượt gần nhất từ DB (cùng nguồn với chat), lượt hiện tại luôn ở cuối
        turns: list[dict] = []
        try:
            from engine.core.memory import get_messages
            turns = [m for m in await asyncio.to_thread(get_messages, 8) if m.get("content")]
        except Exception as exc:
            log.warning("Learning: không đọc được lịch sử DB: %s", exc)
        current = [{"role": "user", "content": user_message}, {"role": "assistant", "content": assistant_message}]
        tail = [(t.get("role"), t.get("content")) for t in turns[-2:]]
        if tail != [(c["role"], c["content"]) for c in current]:
            if tail and tail[-1] == ("user", user_message):
                turns.append(current[1])
            else:
                turns += current
        turns = turns[-10:]
        user_text = "\n".join(t["content"] for t in turns if t["role"] == "user")
        transcript = "\n".join(
            f"{'User' if t['role'] == 'user' else 'Assistant'}: {str(t['content']).strip()}" for t in turns
        )
        # Mục do lượt học trước ghi — chỉ những mục này mới được gỡ (retract)
        previous_run = self._just_learned
        self._just_learned = {}
        just_learned_str = ""
        if previous_run:
            conn = self._get_learning_db()
            rows = conn.execute(
                f"SELECT id, content FROM learnings WHERE id IN ({','.join('?' * len(previous_run))})", list(previous_run)
            ).fetchall()
            conn.close()
            just_learned_str = "\n".join(f"#{r['id']}: {r['content']}" for r in rows)

        from engine.prompts.learning import build_learning_propose_prompt, build_learning_critique_prompt
        from engine.prompts.learning import json_format, propose_schema
        from engine.tools import registry
        names = registry.names()
        used = self.list_outcome_records(limit=5)["items"]
        user_last_message = next((t["content"] for t in reversed(turns) if t.get("role") == "user"), user_message)
        propose_prompt = build_learning_propose_prompt(
            context=transcript, latest=user_last_message, just_learned=just_learned_str,
            tools="\n".join(f"- {n}: {registry.description(n)}" for n in names),
            used_tools="\n".join(f"{o['query']} → {o['tools']}" for o in used),
        )

        try:
            from engine.server.llm_server import call_llm
            from engine.core.json_parser import safe_json_loads
            response = await call_llm(
                messages=[{"role": "user", "content": propose_prompt}],
                temperature=0.0, thinking=True, thinking_budget=128, max_tokens=1200,
                response_format=json_format("learning_propose", propose_schema(names)),
            )
            parsed = safe_json_loads(response.choices[0].message.content.strip())
        except Exception as exc:
            log.warning("Learning propose call failed: %s", exc)
            return {"stored": 0, "error": str(exc), "items": []}

        raw_proposals = parsed.get("proposals", []) if isinstance(parsed, dict) else []
        if not isinstance(raw_proposals, list):
            raw_proposals = []

        stored = 0
        accepted: list[dict] = []

        is_explicit = self._is_explicit_learning_request(user_last_message)

        for proposal in raw_proposals[:MAX_PROPOSALS]:
            if not isinstance(proposal, dict):
                continue
            kind = proposal.get("kind", "")
            content = proposal.get("content", "")
            key = self._normalise_key(str(proposal.get("key", "")))
            evidence = proposal.get("evidence", "")

            if kind == "retract":
                if await asyncio.to_thread(self._retract_learning, proposal, user_text, previous_run):
                    stored += 1
                    accepted.append(proposal)
                continue
            if kind == "tool_fix":
                # evidence phải là lời ngài nói SAU câu yêu cầu gốc (review 2026-10-14: model bịa tool_fix lấy chính câu hỏi
                # làm evidence); kind user_fact để _validate_proposal_evidence chỉ so lời ngài
                users = [t["content"] for t in turns if t.get("role") == "user"]
                q = normalize_query(str(proposal.get("query", "")))
                at = next((i for i, u in enumerate(users) if normalize_query(u) == q), None)
                later = " ".join(users[at + 1:]) if at is not None else ""
                if later and self._validate_proposal_evidence({**proposal, "kind": "user_fact"}, later) and await asyncio.to_thread(
                        self.record_correction, str(proposal.get("query", "")),
                        str(proposal.get("wrong_tool", "")), str(proposal.get("right_tool", ""))):
                    stored += 1
                    accepted.append(proposal)
                continue
            if kind == "tool_rule":
                if self._validate_proposal_evidence({**proposal, "kind": "user_fact"}, user_last_message) and \
                        await asyncio.to_thread(self.record_tool_rule, str(proposal.get("topic", "")),
                                                str(proposal.get("right_tool", ""))):
                    stored += 1
                    accepted.append(proposal)
                continue
            kind = self._normalize_kind(kind)
            proposal = {**proposal, "kind": kind}
            if kind not in {"user_fact", "preference", "behaviour_lesson"}:
                continue
            if not key or not content:
                continue

            # bằng chứng phải nằm trong lượt mới nhất: lượt trước chỉ là ngữ cảnh (log 19:33 đề xuất lại bài cũ)
            if not self._validate_proposal_evidence(proposal, user_last_message):
                log.info("⏭️ Learning rejected: evidence not verbatim in text: %s", evidence)
                continue

            if self._is_forbidden_topic(content, kind):
                log.info("⏭️ Learning rejected: forbidden topic: %s", content)
                continue

            dup = await asyncio.to_thread(self._embedding_duplicate, kind, content)
            if dup is not None:
                log.info("⏭️ Bài học trùng ý id=%s (cosine ≥ %.2f): %s", dup, DEDUPE_SIM, content)
                continue
            closest = await asyncio.to_thread(self._find_closest_existing_learning, kind, key, content)
            proposal_str = json.dumps(proposal, ensure_ascii=False)
            existing_str = json.dumps(closest, ensure_ascii=False) if closest else "Không có mục nào tương tự."

            critique_prompt = build_learning_critique_prompt(proposal=proposal_str, existing_item=existing_str)
            try:
                from engine.prompts.learning import CRITIQUE_SCHEMA, json_format
                c_resp = await call_llm(
                    messages=[{"role": "user", "content": critique_prompt}],
                    temperature=0.0, thinking=True, thinking_budget=128, max_tokens=800,
                    response_format=json_format("learning_critique", CRITIQUE_SCHEMA),
                )
                c_parsed = safe_json_loads(c_resp.choices[0].message.content.strip())
            except Exception as c_exc:
                log.warning("Learning critique call failed: %s", c_exc)
                continue

            decision = c_parsed.get("decision", "skip") if isinstance(c_parsed, dict) else "skip"
            merged_content = c_parsed.get("merged_content", "") if isinstance(c_parsed, dict) else ""

            # Xử lý quyết định phản biện & chống trùng lặp:
            if decision == "skip":
                if is_explicit:
                    # Người dùng yêu cầu ghi nhớ rõ ràng và trong DB chưa có bài nào tương tự ⇒ vẫn ghi nhận
                    decision = "new"
                    log.info("Critique skip bị bỏ qua: ngài yêu cầu học rõ ràng (trùng ý đã loại bằng cosine)")
                else:
                    log.info("⏭️ Critique bỏ qua bài học trùng lặp/không bền vững: %s", content)
            elif decision == "new" and closest:
                # Nếu Critique trả về new nhưng trong DB đã có bài học tương đồng từ vựng/bao hàm ⇒ viết chồng lên thay vì tạo bản ghi trùng
                if _lexically_similar(content, closest.get("content", "")):
                    decision = "merge"
                    merged_content = content
                    log.info("🔄 Tự động chuyển new thành merge để viết chồng lên bài học cũ id=%s", closest.get("id"))
            # Gộp/thêm mà không có ý mới so với mục cũ = nói lại điều đã học: không ghi (replace = đổi ý, vẫn cho qua).
            if decision in ("merge", "new") and closest and not adds_new_information(
                    merged_content or content, closest.get("content", "")):
                log.info("⏭️ Bài học không thêm ý mới so với id=%s: %s", closest.get("id"), content)
                decision = "skip"

            applied = await asyncio.to_thread(
                self._apply_critique_decision,
                decision=decision,
                target_item=closest,
                proposal=proposal,
                merged_content=merged_content,
            )
            if applied:
                stored += 1
                accepted.append(proposal)

        if not accepted:
            log.info("⏭️ Conversation learning discarded: no durable item")
        else:
            log.info("📚 Conversation learning stored: items=%s changes=%s", len(accepted), stored)
        return {"stored": stored, "discarded": not accepted, "items": accepted}


    def _migrate_legacy_learnings(self):
        """Nhập lesson cũ một lần; runtime không còn đọc hoặc ghi learn.db."""
        if not LEGACY_LEARN_DB_PATH.exists():
            return
        try:
            legacy = sqlite3.connect(str(LEGACY_LEARN_DB_PATH))
            rows = legacy.execute(
                "SELECT type, content, source, importance, created_at FROM learnings"
            ).fetchall()
            legacy.close()
        except sqlite3.Error:
            return

        conn = self._get_learning_db()
        conn.execute("BEGIN IMMEDIATE")
        for row in rows:
            exists = conn.execute(
                """SELECT 1 FROM learnings
                   WHERE type = ? AND LOWER(TRIM(content)) = LOWER(TRIM(?))""",
                (row[0], row[1]),
            ).fetchone()
            if not exists:
                insert_with_lowest_free_id(
                    conn,
                    "learnings",
                    ("type", "content", "source", "importance", "created_at"),
                    tuple(row),
                )
        conn.commit()
        conn.close()
        log.info("📚 Learning database initialized (query jarvis.db for conversations)")

    # ------------------------------------------------------------------
    # Truy vấn hội thoại từ jarvis.db (messages table — dùng chung memory)
    # ------------------------------------------------------------------

    def get_recent_interactions(self, limit: int = 20) -> list[dict]:
        """Lấy N cặp user+assistant gần nhất từ jarvis.db messages table."""
        conn = self._get_memory_db()
        rows = conn.execute(
            "SELECT id, role, content, created_at FROM messages ORDER BY id DESC LIMIT ?",
            (limit * 2,)
        ).fetchall()
        conn.close()

        pairs = []
        user_msg = None
        for r in reversed(rows):
            d = dict(r)
            if d["role"] == "user":
                user_msg = d
            elif d["role"] == "assistant" and user_msg is not None:
                pairs.append({
                    "user_input": user_msg["content"],
                    "assistant_response": d["content"],
                    "created_at": d["created_at"],
                })
                user_msg = None
        return pairs[-limit:]

    def get_interactions_in_range(self, since: float, until: float) -> list[dict]:
        """Lấy cặp user+assistant trong khoảng thời gian."""
        conn = self._get_memory_db()
        rows = conn.execute(
            "SELECT id, role, content, created_at FROM messages "
            "WHERE created_at >= ? AND created_at <= ? ORDER BY id ASC",
            (since, until)
        ).fetchall()
        conn.close()

        pairs = []
        user_msg = None
        for r in rows:
            d = dict(r)
            if d["role"] == "user":
                user_msg = d
            elif d["role"] == "assistant" and user_msg is not None:
                pairs.append({
                    "user_input": user_msg["content"],
                    "assistant_response": d["content"],
                    "created_at": d["created_at"],
                })
                user_msg = None
        return pairs

    # ------------------------------------------------------------------
    # Truy xuất learnings
    # ------------------------------------------------------------------

    def recall_learnings(self, query: str, limit: int = 5, agent: str = "") -> list[dict]:
        if not query or len(query.strip()) < 3:
            return []

        keywords = [w.lower() for w in query.split() if len(w) > 2]
        if not keywords:
            return self.get_recent_learnings(limit)

        conn = self._get_learning_db()
        if agent:
            rows = conn.execute(
                "SELECT * FROM learnings WHERE source IN (?, 'session_reflection') ORDER BY importance DESC LIMIT 80",
                (f"agent_outcome:{agent}",),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM learnings ORDER BY importance DESC LIMIT 80").fetchall()
        conn.close()

        scored: list[dict] = []
        for row in rows:
            d = dict(row)
            haystack = d["content"].lower()
            hits = sum(1 for kw in keywords if kw in haystack)
            if hits:
                d["score"] = (hits / len(keywords)) * 0.7 + (d["importance"] / 10) * 0.3
                scored.append(d)

        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:limit]

    def get_recent_learnings(self, limit: int = 5) -> list[dict]:
        conn = self._get_learning_db()
        rows = conn.execute(
            "SELECT * FROM learnings ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    @staticmethod
    def _bounded_page(limit: int, offset: int) -> tuple[int, int]:
        return max(1, min(int(limit), 200)), max(0, int(offset))

    def _list_learning_table(
        self,
        table: str,
        columns: str,
        search_columns: tuple[str, ...],
        order_column: str,
        q: str,
        limit: int,
        offset: int,
    ) -> dict:
        if table not in {"learnings", "workflows", "outcomes", "corrections"}:
            raise ValueError("Unsupported learning table")
        page_limit, page_offset = self._bounded_page(limit, offset)
        query = (q or "").strip().lower()
        params: list[object] = []
        where = ""
        if query:
            where = " WHERE " + " OR ".join(
                f"LOWER(CAST({column} AS TEXT)) LIKE ?"
                for column in search_columns
            )
            params = [f"%{query}%"] * len(search_columns)
        conn = self._get_learning_db()
        total = conn.execute(
            f"SELECT COUNT(*) FROM {table}{where}", params
        ).fetchone()[0]
        rows = conn.execute(
            f"""SELECT {columns} FROM {table}{where}
                ORDER BY {order_column} DESC LIMIT ? OFFSET ?""",
            [*params, page_limit, page_offset],
        ).fetchall()
        conn.close()
        return {
            "items": [dict(row) for row in rows],
            "total": total,
            "limit": page_limit,
            "offset": page_offset,
        }

    def list_learning_records(
        self, q: str = "", limit: int = 50, offset: int = 0
    ) -> dict:
        result = self._list_learning_table(
            "learnings",
            "id, type, semantic_key, content, source, importance, created_at, embedding, embedding_model",
            ("type", "semantic_key", "content", "source"),
            "created_at",
            q,
            limit,
            offset,
        )
        # Thêm embedding_dim cho mỗi item
        for item in result["items"]:
            try:
                vec = json.loads(item.get("embedding", "")) if item.get("embedding") else None
                item["embedding_dim"] = len(vec) if vec and isinstance(vec, list) else 0
            except (TypeError, json.JSONDecodeError):
                item["embedding_dim"] = 0
        return result

    def list_workflow_records(
        self, q: str = "", limit: int = 50, offset: int = 0
    ) -> dict:
        return self._list_learning_table(
            "workflows",
            (
                "id, tools, intent, tool_chain, sample_queries, success_evidence, "
                "validation_count, wiki_path, created_at, updated_at"
            ),
            ("tools", "intent", "tool_chain", "sample_queries", "success_evidence"),
            "updated_at",
            q,
            limit,
            offset,
        )

    def list_outcome_records(
        self,
        q: str = "",
        limit: int = 50,
        offset: int = 0,
        tool: str = "",
    ) -> dict:
        page_limit, page_offset = self._bounded_page(limit, offset)
        search_query = (q or "").strip().lower()
        tool_name = (tool or "").strip().lower()
        clauses: list[str] = []
        params: list[object] = []
        if search_query:
            search_columns = ("query", "status", "result", "traces")
            clauses.append(
                "("
                + " OR ".join(
                    f"LOWER(CAST({column} AS TEXT)) LIKE ?"
                    for column in search_columns
                )
                + ")"
            )
            params.extend([f"%{search_query}%"] * len(search_columns))
        if tool_name:
            clauses.append("LOWER(tools) = ?")
            params.append(tool_name)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        conn = self._get_learning_db()
        total = conn.execute(
            f"SELECT COUNT(*) FROM outcomes{where}", params
        ).fetchone()[0]
        rows = conn.execute(
            f"""SELECT id, tools, query, status, result, traces, created_at
                FROM outcomes{where}
                ORDER BY created_at DESC LIMIT ? OFFSET ?""",
            [*params, page_limit, page_offset],
        ).fetchall()
        conn.close()
        return {
            "items": [dict(row) for row in rows],
            "total": total,
            "limit": page_limit,
            "offset": page_offset,
        }

    def record_outcome(self, tools: str, query: str, status: str, result: str, traces: list[dict]) -> int:
        conn = self._get_learning_db()
        try:
            cur = insert_with_lowest_free_id(
                conn, "outcomes", ("tools", "query", "status", "result", "traces", "created_at"),
                (tools, query, status, result, json.dumps(traces, ensure_ascii=False), time.time()))
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    def save_workflow(self, query: str, tool_chain: list[dict], evidence: str) -> int | None:
        """Lưu/gộp workflow theo chuỗi tool; một câu chuẩn hoá chỉ thuộc một workflow (spec mục 3)."""
        q = normalize_query(query)
        if not q or not tool_chain:
            return None
        chain_json = json.dumps(tool_chain, ensure_ascii=False, sort_keys=True)
        tools = "+".join(str(step.get("tool", "")) for step in tool_chain)
        now = time.time()
        conn = self._get_learning_db()
        try:
            for row in conn.execute("SELECT id, sample_queries FROM workflows WHERE tool_chain<>?",
                                    (chain_json,)).fetchall():
                samples = json.loads(row["sample_queries"] or "[]")
                if q in samples:
                    conn.execute("UPDATE workflows SET sample_queries=? WHERE id=?",
                                 (json.dumps([s for s in samples if s != q], ensure_ascii=False), row["id"]))
            row = conn.execute("SELECT id, sample_queries FROM workflows WHERE tool_chain=?", (chain_json,)).fetchone()
            if row:
                samples = [s for s in json.loads(row["sample_queries"] or "[]") if s != q] + [q]
                conn.execute(
                    "UPDATE workflows SET sample_queries=?, validation_count=validation_count+1, "
                    "success_evidence=?, updated_at=? WHERE id=?",
                    (json.dumps(samples[-20:], ensure_ascii=False), evidence[:300], now, row["id"]))
                workflow_id = row["id"]
            else:
                workflow_id = insert_with_lowest_free_id(
                    conn, "workflows",
                    ("tools", "intent", "tool_chain", "sample_queries", "success_evidence", "validation_count",
                     "wiki_path", "created_at", "updated_at"),
                    (tools, query.strip(), chain_json, json.dumps([q], ensure_ascii=False), evidence[:300], 1,
                     str(WORKFLOWS_WIKI_DIR / f"{tools}.md"), now, now)).lastrowid
            conn.commit()
        finally:
            conn.close()
        self._sync_workflow_wiki(tools)
        return workflow_id

    def find_workflow(self, text: str) -> dict | None:
        q = normalize_query(text)
        if not q:
            return None
        conn = self._get_learning_db()
        try:
            rows = conn.execute("SELECT id, tools, tool_chain, sample_queries FROM workflows "
                                "ORDER BY updated_at DESC").fetchall()
            # log 2026-10-14: câu ngài đã sửa tool vẫn phát lại workflow cũ (bỏ qua model + corrections) → sai mãi
            wrong = {r["wrong_tool"] for r in conn.execute("SELECT wrong_tool FROM corrections WHERE query_norm=?", (q,))}
        finally:
            conn.close()
        for row in rows:
            if q in json.loads(row["sample_queries"] or "[]"):
                if wrong & set(row["tools"].split("+")):
                    log.info("⏭️ không phát lại workflow #%s cho '%s': ngài đã sửa %s", row["id"], q, sorted(wrong))
                    return None
                return {"id": row["id"], "tools": row["tools"], "tool_chain": json.loads(row["tool_chain"])}
        return None

    def record_correction(self, query: str, wrong_tool: str, right_tool: str) -> bool:
        """Ngài sửa chọn tool (spec 2026-10-13 §1): chỉ lưu khi outcomes 24 giờ qua có đúng câu đó chạy wrong_tool."""
        from engine.tools import registry
        q = normalize_query(query)
        if not q or wrong_tool == right_tool or right_tool not in registry.names():
            return False
        conn = self._get_learning_db()
        try:
            recent = conn.execute("SELECT query, tools, created_at FROM outcomes WHERE created_at >= ?",
                                  (time.time() - _CORRECTION_WINDOW,)).fetchall()
            if not any(normalize_query(r["query"]) == q and wrong_tool in r["tools"].split("+") for r in recent):
                log.info("⏭️ tool_fix bỏ: không có lượt '%s' dùng %s trong 24 giờ", q, wrong_tool)
                return False
            now = time.time()
            row = conn.execute("SELECT id, updated_at FROM corrections WHERE query_norm=? AND wrong_tool=? AND right_tool=?",
                               (q, wrong_tool, right_tool)).fetchone()
            if row:
                # count = số lần TÁI PHẠM: phải có lượt mới dùng tool sai sau lần sửa trước (review 2026-10-14: transcript học
                # đọc lại lời sửa cũ → count 2 → ép tool dù ngài chỉ sửa một lần)
                if not any(normalize_query(r["query"]) == q and wrong_tool in r["tools"].split("+")
                           and r["created_at"] > row["updated_at"] for r in recent):
                    return False
                conn.execute("UPDATE corrections SET count=count+1, updated_at=? WHERE id=?", (now, row["id"]))
            else:
                emb = self._embed_text(q)
                insert_with_lowest_free_id(
                    conn, "corrections",
                    ("query", "query_norm", "wrong_tool", "right_tool", "count", "embedding", "created_at", "updated_at"),
                    (query.strip(), q, wrong_tool, right_tool, 1, json.dumps(emb) if emb else "", now, now))
            conn.commit()
        finally:
            conn.close()
        log.info("🔧 Ghi sửa công cụ: '%s' %s → %s", q, wrong_tool, right_tool)
        self._sync_learning_wiki()
        return True

    def record_tool_rule(self, topic: str, right_tool: str) -> bool:
        """Luật chung ngài dạy ("giá thực phẩm → search_products"): dòng corrections có wrong_tool rỗng, không ép tool
        (similar_corrections bỏ qua), chỉ nạp vào mô tả tool ở vòng chọn tool (tool_rules)."""
        from engine.tools import registry
        q = normalize_query(topic)
        if not q or right_tool not in registry.names():
            return False
        now = time.time()
        conn = self._get_learning_db()
        try:
            if conn.execute("SELECT 1 FROM corrections WHERE query_norm=? AND wrong_tool='' AND right_tool=?",
                            (q, right_tool)).fetchone():
                return False
            insert_with_lowest_free_id(
                conn, "corrections",
                ("query", "query_norm", "wrong_tool", "right_tool", "count", "embedding", "created_at", "updated_at"),
                (topic.strip(), q, "", right_tool, 1, "", now, now))
            conn.commit()
        finally:
            conn.close()
        log.info("🔧 Ghi luật công cụ: '%s' → %s", q, right_tool)
        self._sync_learning_wiki()
        return True

    def tool_rules(self) -> dict[str, list[str]]:
        conn = self._get_learning_db()
        try:
            rows = conn.execute("SELECT query, right_tool FROM corrections WHERE wrong_tool='' ORDER BY id").fetchall()
        finally:
            conn.close()
        out: dict[str, list[str]] = {}
        for r in rows:
            out.setdefault(r["right_tool"], []).append(r["query"])
        return out

    def similar_corrections(self, text: str, min_sim: float, limit: int) -> list[dict]:
        vec = self._embed_text(normalize_query(text))
        if not vec:
            return []
        conn = self._get_learning_db()
        try:
            rows = conn.execute("SELECT id, query, wrong_tool, right_tool, count, embedding FROM corrections "
                                "WHERE wrong_tool<>''").fetchall()
        finally:
            conn.close()
        hits = []
        for r in rows:
            sim = _cosine(vec, json.loads(r["embedding"]) if r["embedding"] else None)
            if sim is not None and sim >= min_sim:
                hits.append({"id": r["id"], "query": r["query"], "wrong_tool": r["wrong_tool"],
                             "right_tool": r["right_tool"], "count": r["count"], "sim": sim})
        return sorted(hits, key=lambda h: h["sim"], reverse=True)[:limit]

    def list_correction_records(self, q: str = "", limit: int = 50, offset: int = 0) -> dict:
        return self._list_learning_table(
            "corrections", "id, query, wrong_tool, right_tool, count, created_at, updated_at",
            ("query", "wrong_tool", "right_tool"), "updated_at", q, limit, offset)

    def evolution_items(self) -> list[dict]:
        conn = self._get_learning_db()
        try:
            rows = conn.execute("SELECT id, type, content, created_at, embedding FROM learnings "
                                "WHERE type IN ('lesson', 'preference') ORDER BY id").fetchall()
        finally:
            conn.close()
        return [dict(r) for r in rows]

    def get_memory_control_counts(self) -> dict[str, int]:
        conn = self._get_learning_db()
        try:
            return {
                "learnings": conn.execute(
                    "SELECT COUNT(*) FROM learnings"
                ).fetchone()[0],
                "workflows": conn.execute(
                    "SELECT COUNT(*) FROM workflows"
                ).fetchone()[0],
                "outcomes": conn.execute(
                    "SELECT COUNT(*) FROM outcomes"
                ).fetchone()[0],
                "corrections": conn.execute("SELECT COUNT(*) FROM corrections").fetchone()[0],
            }
        finally:
            conn.close()

    @staticmethod
    def _validated_workflow_wiki_path(path: Path) -> Path:
        root = WORKFLOWS_WIKI_DIR.resolve()
        resolved = path.resolve()
        if resolved != root and root not in resolved.parents:
            raise ValueError("invalid_wiki_path")
        return resolved

    def _sync_workflow_wiki(self, tools: str, requested_path: Path | None = None) -> None:
        path = self._validated_workflow_wiki_path(requested_path or (WORKFLOWS_WIKI_DIR / f"{tools}.md"))
        conn = self._get_learning_db()
        rows = conn.execute(
            "SELECT * FROM workflows WHERE tools=? ORDER BY validation_count DESC, updated_at DESC", (tools,)
        ).fetchall()
        conn.close()
        if not rows:
            if path.exists():
                path.unlink()
            self._sync_workflow_hub()
            return
        lines = [f"# Workflows: {tools}", ""]
        for row in rows:
            chain = json.loads(row["tool_chain"] or "[]")
            samples = json.loads(row["sample_queries"] or "[]")
            steps = "; ".join(
                f"{s.get('tool')}({json.dumps(s.get('args', {}), ensure_ascii=False)})"
                + (f" + {len(s['cua_steps'])} thao tác cua" if s.get("cua_steps") else "")
                for s in chain
            )
            lines.extend([
                f"## {row['intent']}",
                f"- Tools: {row['tools']}",
                f"- Tool chain: {steps}",
                f"- Sample queries: {'; '.join(samples[:5]) or '(none)'}",
                f"- Success evidence: {row['success_evidence']}",
                f"- Validations: {row['validation_count']}",
                "",
            ])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines), encoding="utf-8")
        self._sync_workflow_hub()

    def _sync_workflow_hub(self) -> None:
        conn = self._get_learning_db()
        names = [row["tools"] for row in conn.execute("SELECT DISTINCT tools FROM workflows ORDER BY tools").fetchall()]
        conn.close()
        _write_wiki_link_index(WORKFLOWS_HUB_WIKI_PATH, names)

    def _update_correction(self, record_id: int, values: dict) -> bool:
        """Memory Control sửa một dòng corrections (ngài 2026-10-16). Câu đổi → query_norm + vector theo câu mới
        (similar_corrections so bằng vector); luật chung (wrong_tool rỗng) không dùng vector."""
        from engine.tools import registry
        allowed = {"query", "wrong_tool", "right_tool", "count"}
        if not values or set(values) - allowed:
            raise ValueError("invalid_payload")
        conn = self._get_learning_db()
        try:
            row = conn.execute("SELECT * FROM corrections WHERE id=?", (record_id,)).fetchone()
            if not row:
                return False
            new = {**dict(row), **values}
            wrong, right = str(new["wrong_tool"] or "").strip(), str(new["right_tool"] or "").strip()
            names = registry.names()
            if right not in names or (wrong and wrong not in names) or wrong == right:
                raise ValueError("invalid_tool")
            try:
                count = int(new["count"])
            except (TypeError, ValueError):
                raise ValueError("invalid_count")
            if count < 1:
                raise ValueError("invalid_count")
            query = str(new["query"] or "").strip()
            q = normalize_query(query)
            if not q:
                raise ValueError("invalid_query")
            embedding = row["embedding"]
            if q != row["query_norm"] or (wrong and not embedding):
                vec = self._embed_text(q) if wrong else None
                if wrong and not vec:  # embedder tắt: không ghi dòng mất vector (similar_corrections sẽ bỏ qua nó)
                    raise ValueError("embedder_unavailable")
                embedding = json.dumps(vec) if vec else ""
            try:
                conn.execute("UPDATE corrections SET query=?, query_norm=?, wrong_tool=?, right_tool=?, count=?, "
                             "embedding=?, updated_at=? WHERE id=?",
                             (query, q, wrong, right, count, embedding, time.time(), record_id))
            except sqlite3.IntegrityError:
                raise ValueError("duplicate_key")
            conn.commit()
        finally:
            conn.close()
        self._sync_learning_wiki()
        return True

    def update_learning_control_record(
        self, kind: str, record_id: int, values: dict
    ) -> bool:
        if kind == "correction":
            return self._update_correction(record_id, values)
        schemas = {
            "learning": (
                "learnings",
                {"type", "semantic_key", "content", "source", "importance", "embedding", "embedding_model"},
            ),
            "workflow": (
                "workflows",
                {"tools", "intent", "tool_chain", "sample_queries", "success_evidence", "validation_count", "wiki_path"},
            ),
            "outcome": (
                "outcomes",
                {"tools", "query", "status", "result", "traces"},
            ),
        }
        if kind not in schemas:
            raise ValueError("unsupported_kind")
        table, allowed = schemas[kind]

        # Xử lý embedding riêng biệt nếu có (chỉ cho learning)
        embedding_value = values.get("embedding")
        embedding_model_value = values.get("embedding_model")

        # Nếu có embedding parameter, xử lý nó
        if kind == "learning" and "embedding" in values:
            if embedding_value == "recompute":
                # Sẽ tính lại dưới đây khi có content mới
                pass
            elif embedding_value == "":
                # Xoá embedding
                values = {k: v for k, v in values.items() if k != "embedding_model"}
                values["embedding"] = ""
                values["embedding_model"] = ""
            elif isinstance(embedding_value, str):
                # Validate JSON
                try:
                    parsed = json.loads(embedding_value)
                    if not isinstance(parsed, list):
                        raise ValueError("invalid_embedding")
                    # Kiểm tra phần tử là số hữu hạn
                    if not all(isinstance(x, (int, float)) and -1e6 < x < 1e6 for x in parsed):
                        raise ValueError("invalid_embedding")
                    if not (1 <= len(parsed) <= 4096):
                        raise ValueError("invalid_embedding")
                    # OK, set embedding_model="manual"
                    values["embedding"] = embedding_value
                    values["embedding_model"] = "manual"
                except (json.JSONDecodeError, TypeError):
                    raise ValueError("invalid_embedding")

        clean = {key: value for key, value in values.items() if key in allowed}
        if not clean:
            raise ValueError("invalid_payload")
        # Nếu có embedding hoặc embedding_model và không nằm trong clean, đó là lỗi
        has_extra_keys = set(values.keys()) - set(clean.keys())
        if has_extra_keys and "embedding" not in has_extra_keys and "embedding_model" not in has_extra_keys:
            raise ValueError("invalid_payload")
        for json_field in {
            "tool_chain",
            "sample_queries",
            "traces",
        }:
            if json_field in clean:
                parsed = json.loads(str(clean[json_field]))
                if not isinstance(parsed, list):
                    raise ValueError(f"{json_field}_must_be_array")
                clean[json_field] = json.dumps(parsed, ensure_ascii=False)
        if "semantic_key" in clean:
            clean["semantic_key"] = self._normalise_key(
                str(clean["semantic_key"])
            )
            if not clean["semantic_key"]:
                raise ValueError("invalid_semantic_key")
        if "wiki_path" in clean:
            clean["wiki_path"] = str(
                self._validated_workflow_wiki_path(Path(str(clean["wiki_path"])))
            )

        # Xử lý embedding="recompute" hoặc nếu content thay đổi mà embedding không được cung cấp
        if kind == "learning":
            if embedding_value == "recompute":
                # Lấy content hiện tại (nếu có trong clean) hoặc từ DB
                content_to_embed = clean.get("content")
                if not content_to_embed:
                    conn = self._get_learning_db()
                    row = conn.execute("SELECT content FROM learnings WHERE id=?", (record_id,)).fetchone()
                    conn.close()
                    if row:
                        content_to_embed = row["content"]
                if content_to_embed:
                    emb_json, emb_model = self._embedding_fields(content_to_embed)
                    if not emb_json:  # embedder tắt: giữ nguyên vector cũ, không ghi đè bằng chuỗi rỗng
                        raise ValueError("embedder_unavailable")
                    clean["embedding"] = emb_json
                    clean["embedding_model"] = emb_model
                # Xoá embedding khỏi clean vì đã xử lý
                if "embedding" in clean and clean["embedding"] == "recompute":
                    del clean["embedding"]
            elif "content" in clean and "embedding" not in clean:
                # Content thay đổi mà embedding không được cung cấp → tính lại
                emb_json, emb_model = self._embedding_fields(clean["content"])
                clean["embedding"] = emb_json
                clean["embedding_model"] = emb_model

        conn = self._get_learning_db()
        if kind == "learning" and "semantic_key" in clean:
            duplicate = conn.execute(
                """SELECT 1 FROM learnings
                   WHERE semantic_key=? AND id<>?""",
                (clean["semantic_key"], record_id),
            ).fetchone()
            if duplicate:
                conn.close()
                raise ValueError("duplicate_key")
        old_workflow = (
            conn.execute(
                """SELECT * FROM workflows
                   WHERE id=?""",
                (record_id,),
            ).fetchone()
            if kind == "workflow"
            else None
        )
        old_learning = (
            conn.execute(
                "SELECT * FROM learnings WHERE id=?", (record_id,)
            ).fetchone()
            if kind == "learning"
            else None
        )
        assignments = ", ".join(f"{field}=?" for field in clean)
        affected = conn.execute(
            f"UPDATE {table} SET {assignments} WHERE id=?",
            [*clean.values(), record_id],
        ).rowcount
        if kind == "workflow" and affected:
            conn.execute(
                "UPDATE workflows SET updated_at=? WHERE id=?",
                (time.time(), record_id),
            )
        conn.commit()
        new_workflow = (
            conn.execute(
                """SELECT tools, wiki_path FROM workflows
                   WHERE id=?""",
                (record_id,),
            ).fetchone()
            if kind == "workflow" and affected
            else None
        )
        conn.close()
        wiki_paths: set[Path] = set()
        if kind == "learning" and affected:
            wiki_paths.update({PREFERENCES_WIKI_PATH, LESSONS_WIKI_PATH})
        if old_workflow and affected:
            wiki_paths.add(Path(old_workflow["wiki_path"]))
        if new_workflow:
            wiki_paths.add(Path(new_workflow["wiki_path"]))
        wiki_backups = {
            path: (
                path.read_text(encoding="utf-8")
                if path.exists()
                else None
            )
            for path in wiki_paths
        }
        try:
            if kind == "learning" and affected:
                self._sync_learning_wiki()
            if old_workflow and affected:
                self._sync_workflow_wiki(
                    old_workflow["tools"], Path(old_workflow["wiki_path"])
                )
            if new_workflow and (
                not old_workflow
                or new_workflow["tools"] != old_workflow["tools"]
                or new_workflow["wiki_path"] != old_workflow["wiki_path"]
            ):
                self._sync_workflow_wiki(
                    new_workflow["tools"], Path(new_workflow["wiki_path"])
                )
        except Exception:
            original_row = old_workflow or old_learning
            restore_table = (
                "workflows"
                if old_workflow
                else "learnings"
            )
            if original_row:
                original = dict(original_row)
                restore_fields = [
                    field for field in original if field != "id"
                ]
                restore_conn = self._get_learning_db()
                restore_conn.execute(
                    f"""UPDATE {restore_table}
                        SET {', '.join(f'{field}=?' for field in restore_fields)}
                        WHERE id=?""",
                    [*[original[field] for field in restore_fields], record_id],
                )
                restore_conn.commit()
                restore_conn.close()
            for path, content in wiki_backups.items():
                if content is None:
                    path.unlink(missing_ok=True)
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(content, encoding="utf-8")
            raise
        return affected > 0

    def preview_learning_dependencies(
        self, kind: str, record_id: int
    ) -> dict:
        conn = self._get_learning_db()
        if kind == "learning":
            row = conn.execute(
                "SELECT * FROM learnings WHERE id=?", (record_id,)
            ).fetchone()
            conn.close()
            if not row:
                raise LookupError("not_found")
            wiki_path = (
                PREFERENCES_WIKI_PATH
                if row["type"] == "preference"
                else LESSONS_WIKI_PATH
            )
            # Không chứa embedding full (quá dài), thay bằng embedding_dim
            preview_record = dict(row)
            try:
                vec = json.loads(preview_record.get("embedding", "")) if preview_record.get("embedding") else None
                embedding_dim = len(vec) if vec and isinstance(vec, list) else 0
            except (TypeError, json.JSONDecodeError):
                embedding_dim = 0
            preview_record["embedding_dim"] = embedding_dim
            # Bỏ embedding khỏi preview để JSON không quá lớn
            if "embedding" in preview_record:
                del preview_record["embedding"]

            return {
                "will_delete": {
                    "records": [preview_record],
                    "wiki_paths": [str(wiki_path)],
                },
                "will_update": [],
                "related_only": [],
            }
        if kind == "workflow":
            row = conn.execute(
                "SELECT * FROM workflows WHERE id=?", (record_id,)
            ).fetchone()
            if not row:
                conn.close()
                raise LookupError("not_found")
            outcomes = conn.execute(
                """SELECT id, tools, query, status FROM outcomes
                   WHERE tools=? ORDER BY created_at DESC LIMIT 20""",
                (row["tools"],),
            ).fetchall()
            conn.close()
            return {
                "will_delete": {
                    "records": [dict(row)],
                    "wiki_paths": [row["wiki_path"]],
                },
                "will_update": [],
                "related_only": [dict(item) for item in outcomes],
            }
        if kind == "outcome":
            row = conn.execute(
                "SELECT * FROM outcomes WHERE id=?", (record_id,)
            ).fetchone()
            conn.close()
            if not row:
                raise LookupError("not_found")
            return {
                "will_delete": {
                    "records": [dict(row)],
                    "wiki_paths": [],
                },
                "will_update": [],
                "related_only": [],
            }
        if kind == "correction":
            row = conn.execute("SELECT * FROM corrections WHERE id=?", (record_id,)).fetchone()
            conn.close()
            if not row:
                raise LookupError("not_found")
            record = {k: v for k, v in dict(row).items() if k != "embedding"}  # vector làm hộp xác nhận dài hàng nghìn ký tự
            return {"will_delete": {"records": [record], "wiki_paths": [str(LESSONS_WIKI_PATH)]},
                    "will_update": [], "related_only": []}
        conn.close()
        raise ValueError("unsupported_kind")

    def delete_learning_control_record(
        self, kind: str, record_id: int
    ) -> bool:
        preview = self.preview_learning_dependencies(kind, record_id)  # workflow/outcome dùng bên dưới
        if kind == "learning":
            # Preview đã bỏ embedding (để hộp xác nhận gọn): đọc lại toàn bộ dòng TRƯỚC khi xoá để khôi phục khi lỗi
            conn = self._get_learning_db()
            full_row = conn.execute(
                "SELECT * FROM learnings WHERE id=?", (record_id,)
            ).fetchone()
            if not full_row:
                conn.close()
                raise LookupError("not_found")
            learning = dict(full_row)
            conn.close()

            wiki_paths = {PREFERENCES_WIKI_PATH, LESSONS_WIKI_PATH}
            wiki_backups = {
                path: (
                    path.read_text(encoding="utf-8")
                    if path.exists()
                    else None
                )
                for path in wiki_paths
            }
            conn = self._get_learning_db()
            affected = conn.execute(
                "DELETE FROM learnings WHERE id=?", (record_id,)
            ).rowcount
            conn.commit()
            conn.close()
            try:
                if affected:
                    self._sync_learning_wiki()
            except Exception as exc:
                restore = self._get_learning_db()
                columns = list(learning.keys())
                restore.execute(
                    f"""INSERT INTO learnings ({', '.join(columns)})
                        VALUES ({', '.join('?' for _ in columns)})""",
                    [learning[column] for column in columns],
                )
                restore.commit()
                restore.close()
                for path, content in wiki_backups.items():
                    if content is None:
                        path.unlink(missing_ok=True)
                    else:
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_text(content, encoding="utf-8")
                log.error("Failed to delete learning: %s", exc)
                return False
            return affected > 0
        table = {
            "workflow": "workflows",
            "outcome": "outcomes",
            "correction": "corrections",
        }.get(kind)
        if not table:
            raise ValueError("unsupported_kind")
        workflow = (
            preview["will_delete"]["records"][0]
            if kind == "workflow"
            else None
        )
        wiki_backup: tuple[Path, str | None] | None = None
        if workflow and workflow.get("wiki_path"):
            wiki_path = self._validated_workflow_wiki_path(
                Path(workflow["wiki_path"])
            )
            wiki_backup = (
                wiki_path,
                wiki_path.read_text(encoding="utf-8")
                if wiki_path.exists()
                else None,
            )
        conn = self._get_learning_db()
        affected = conn.execute(
            f"DELETE FROM {table} WHERE id=?", (record_id,)
        ).rowcount
        conn.commit()
        conn.close()
        try:
            if workflow and affected:
                self._sync_workflow_wiki(
                    workflow["tools"], Path(workflow["wiki_path"])
                )
        except Exception:
            restore = self._get_learning_db()
            columns = list(workflow.keys())
            restore.execute(
                f"""INSERT INTO workflows
                    ({', '.join(columns)}) VALUES
                    ({', '.join('?' for _ in columns)})""",
                [workflow[column] for column in columns],
            )
            restore.commit()
            restore.close()
            if wiki_backup and wiki_backup[1] is not None:
                wiki_backup[0].parent.mkdir(parents=True, exist_ok=True)
                wiki_backup[0].write_text(
                    wiki_backup[1], encoding="utf-8"
                )
            raise
        if kind == "correction" and affected:
            self._sync_learning_wiki()
        return affected > 0

    # Gate chỉ hiểu 3 bucket này. Từng có correction ghi expected_route là
    # câu tiếng Việt ("chỉ trả lời hội thoại") khiến gate in nguyên văn vào
    # prompt mà model nhỏ không map được — phải ép về bucket hợp lệ lúc ghi.
    VALID_CORRECTION_ROUTES = {"general", "general_knowledge", "orchestrator"}

    @staticmethod
    def _truncate_trace_output(val: Any, max_len: int = 500) -> Any:
        """Cắt output/args trong trace để JSON không bị corrupt."""
        if isinstance(val, str):
            return val[:max_len] + "..." if len(val) > max_len else val
        if isinstance(val, dict):
            return {k: LearningEngine._truncate_trace_output(v, max_len) for k, v in val.items()}
        if isinstance(val, list):
            return [LearningEngine._truncate_trace_output(v, max_len) for v in val]
        return val

    def get_stats(self) -> dict:

        conn = self._get_memory_db()
        total_messages = conn.execute("SELECT COUNT(*) AS c FROM messages").fetchone()["c"]
        last_24h = conn.execute(
            "SELECT COUNT(*) AS c FROM messages WHERE created_at >= ?",
            (time.time() - 86400,)
        ).fetchone()["c"]
        conn.close()

        conn2 = self._get_learning_db()
        by_type = dict(conn2.execute(
            "SELECT type, COUNT(*) AS cnt FROM learnings GROUP BY type"
        ).fetchall())
        total_learnings = conn2.execute("SELECT COUNT(*) AS c FROM learnings").fetchone()["c"]
        conn2.close()

        return {
            "total_messages": total_messages,
            "messages_last_24h": last_24h,
            "total_learnings": total_learnings,
            "learnings_by_type": by_type,
        }

_learning_engine: Optional[LearningEngine] = None

def get_learning_engine() -> LearningEngine:
    global _learning_engine
    if _learning_engine is None:
        _learning_engine = LearningEngine()
    return _learning_engine
