import asyncio
import json
import sqlite3
import time
import logging
import re
import sys
import unicodedata
from pathlib import Path
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


def _sync_learning_hub() -> None:
    _write_wiki_link_index(
        LEARNING_HUB_WIKI_PATH,
        ("Errors", "Learning", "Preferences", "Evolution"),
    )


def _is_valid_learning_text(content: Any, min_len: int = 10, max_len: int = 1200) -> bool:
    """Kiểm tra tính hợp lệ cơ bản của chuỗi văn bản tri thức/bài học."""
    if not isinstance(content, str):
        return False
    normalized = " ".join(content.split()).strip()
    return min_len <= len(normalized) <= max_len


def outcome_for_turn(session, turn_started_at: float) -> tuple[int | None, str | None]:
    """Return the agent outcome recorded during the current turn, else (None, None).

    The old route_agents.py stamped the session with its last outcome and never
    cleared it. engine.router does not depend on that (it reads recent outcomes
    from the DB), but learning did: every later turn was treated as that old
    tool run, so the old workflow was re-validated each time and conversation
    learning was skipped for the rest of the session.
    """
    recorded_at = getattr(session, "last_agent_outcome_at", None)
    if recorded_at is None or recorded_at < turn_started_at:
        return None, None
    return (
        getattr(session, "last_agent_outcome_id", None),
        getattr(session, "last_agent_outcome_status", None),
    )


LEXICAL_DUPLICATE_THRESHOLD = 0.55
LEXICAL_CLOSEST_MIN = 0.2


def _lexical_tokens(text: str) -> set[str]:
    folded = unicodedata.normalize("NFKD", (text or "").lower().replace("đ", "d"))
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    return {w for w in re.findall(r"[a-z0-9]+", folded) if len(w) > 1}


def _lexically_similar(a: str, b: str) -> bool:
    """Jaccard on accent-folded words. Fallback for when embeddings are off or
    the two phrasings differ too much for cosine to reach the threshold."""
    ta, tb = _lexical_tokens(a), _lexical_tokens(b)
    return bool(ta and tb) and len(ta & tb) / len(ta | tb) >= LEXICAL_DUPLICATE_THRESHOLD


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
        outcome_id: int | None = None,
        outcome_status: str | None = None,
    ) -> asyncio.Future:
        """Queue one completed turn; processing starts only while chat is idle."""
        self._ensure_runtime_state()
        loop = asyncio.get_running_loop()
        completion = loop.create_future()
        if outcome_status in {"failed", "cancelled"}:
            completion.set_result({"stored": 0, "discarded": True, "reason": "unsuccessful outcome"})
            return completion
        if self._learning_queue is None:
            self._learning_queue = asyncio.Queue()
        self._learning_queue.put_nowait(
            (user_message, assistant_message, outcome_id, completion)
        )
        if self._learning_worker_task is None or self._learning_worker_task.done():
            self._learning_worker_task = asyncio.create_task(
                self._learning_worker(), name="conversation-learning-worker"
            )
        return completion

    async def _learning_worker(self) -> None:
        while True:
            item = await self._learning_queue.get()
            user_message, assistant_message, outcome_id, completion = item
            try:
                while True:
                    await self._wait_until_chat_idle()
                    run_task = asyncio.create_task(
                        self._process_scheduled_learning(
                            user_message, assistant_message, outcome_id
                        )
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

    async def _process_scheduled_learning(
        self, user_message: str, assistant_message: str, outcome_id: int | None
    ) -> dict:
        learning_result = await self.process_conversation_learning(
            user_message, assistant_message, outcome_id=outcome_id
        )
        reflection_result = await self.reflect_on_session(
            [
                {"role": "user", "content": user_message},
                {"role": "assistant", "content": assistant_message},
            ],
            outcome_id=outcome_id,
        )
        # Chỉ kích hoạt Evolution Engine khi lượt này thực sự học được điều gì mới;
        # tránh gọi LLM phân tích lại toàn bộ Learning.md/Preferences.md một cách vô ích.
        learned_something_new = (
            learning_result.get("stored", 0) > 0 or bool(reflection_result.get("workflow"))
        )
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
            "Conversation learning complete: conversation_stored=%s "
            "conversation_discarded=%s workflow_stored=%s",
            learning_result.get("stored", 0),
            learning_result.get("discarded", False),
            bool(reflection_result.get("workflow")),
        )
        return {"learning": learning_result, "reflection": reflection_result}

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

            CREATE TABLE IF NOT EXISTS agent_outcomes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent TEXT NOT NULL,
                query TEXT NOT NULL,
                status TEXT NOT NULL,
                result TEXT DEFAULT '',
                traces TEXT DEFAULT '[]',
                created_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_outcome_agent_status ON agent_outcomes(agent, status);

            CREATE TABLE IF NOT EXISTS validated_workflows (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent TEXT NOT NULL,
                intent TEXT NOT NULL,
                tool_chain TEXT NOT NULL,
                argument_keys TEXT NOT NULL,
                success_evidence TEXT NOT NULL,
                validation_count INTEGER NOT NULL DEFAULT 1,
                status TEXT NOT NULL DEFAULT 'validated',
                wiki_path TEXT NOT NULL,
                sample_queries TEXT NOT NULL DEFAULT '[]',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                UNIQUE(agent, tool_chain)
            );
            CREATE INDEX IF NOT EXISTS idx_workflow_agent ON validated_workflows(agent, status);
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
        self._migrate_add_sample_queries_column()
        self._migrate_add_embedding_column()
        self._migrate_add_embedding_model_column()
        self._sync_learning_wiki()

    def _migrate_add_sample_queries_column(self):
        """Add sample_queries column to existing databases (safe to re-run)."""
        conn = None
        try:
            conn = self._get_learning_db()
            conn.execute("ALTER TABLE validated_workflows ADD COLUMN sample_queries TEXT NOT NULL DEFAULT '[]'")
            conn.commit()
        except sqlite3.OperationalError:
            pass  # Column already exists
        finally:
            if conn is not None:
                conn.close()

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
        normalized_content = strip_emojis(content.strip())
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
            conn.execute(
                """INSERT INTO learnings
                   (type, semantic_key, content, source, importance, created_at, embedding, embedding_model)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
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

    _TEMPORARY_WORDS = ("lười", "mệt", "buồn ngủ", "đang bận", "thời tiết", "giá vàng", "xổ số", "mấy giờ")

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

    def _is_temporary_state_or_tool_query(self, evidence: str, content: str) -> bool:
        ev_low = evidence.lower()
        if any(w in ev_low for w in ("lười", "mệt", "buồn ngủ", "bận", "thời tiết", "giá vàng", "xổ số", "mấy giờ")):
            return True
        cnt_low = content.lower()
        if any(w in cnt_low for w in ("khi lười", "cảm thấy lười", "mệt mỏi", "buồn ngủ", "thời tiết", "giá vàng", "xổ số")):
            return True
        return False

    def _is_forbidden_topic(self, text: str, kind: str = "behaviour_lesson") -> bool:
        """Luật hành vi/sở thích không được bàn chuyện hỏi, xin phép, công cụ, agent, thẻ.
        Sự thật về ngài (user_fact) không phải luật hành vi nên không lọc."""
        if not text or kind == "user_fact":
            return False
        t_low = text.lower()
        return any(re.search(rf"(?<!\w){re.escape(kw)}(?!\w)", t_low) for kw in self._FORBIDDEN_KEYWORDS)

    def _handle_routing_note_proposal(self, proposal: dict) -> bool:
        """routing_note chỉ được ghi thành đề xuất trong Evolution.md, không bao giờ tự áp dụng (spec §4)."""
        evo_path = PROJECT_ROOT / "data" / "wiki" / "System" / "Evolution.md"
        evo_path.parent.mkdir(parents=True, exist_ok=True)
        content = proposal.get("content", "").strip()
        evidence = proposal.get("evidence", "").strip()
        if not content:
            return False
        line = f"- [ĐỀ XUẤT] {content} (Bằng chứng: {evidence})\n" if evidence else f"- [ĐỀ XUẤT] {content}\n"
        try:
            existing = evo_path.read_text(encoding="utf-8") if evo_path.exists() else ""
            if line.strip() not in existing:
                with open(evo_path, "a", encoding="utf-8") as f:
                    if "# Proposed Routing Notes" not in existing:
                        f.write("\n\n# Proposed Routing Notes\n")
                    f.write(line)
            log.info("🧭 Ghi nhận đề xuất routing_note vào Evolution.md: %s", content)
            return True
        except Exception as e:
            log.warning("Ghi đề xuất routing_note vào Evolution.md thất bại: %s", e)
            return False

    def _find_closest_existing_learning(self, kind: str, key: str, content: str) -> dict | None:
        """Tìm mục học hiện có gần nhất (khớp semantic_key, sau đó Jaccard)."""
        learn_type = {"behaviour_lesson": "lesson", "user_fact": "user_fact", "preference": "preference"}.get(kind, "lesson")
        conn = self._get_learning_db()

        # Kiểm tra khớp semantic_key trước
        row = conn.execute(
            "SELECT id, type, semantic_key, content FROM learnings WHERE type=? AND semantic_key=? LIMIT 1",
            (learn_type, key),
        ).fetchone()
        if row:
            conn.close()
            return dict(row)

        # Không có semantic_key trùng, kiểm tra lexical similarity
        rows = conn.execute(
            "SELECT id, type, semantic_key, content FROM learnings WHERE type=?",
            (learn_type,),
        ).fetchall()

        best_match = None
        best_score = 0.0
        for r in rows:
            ta = _lexical_tokens(content)
            tb = _lexical_tokens(r["content"])
            if ta and tb:
                score = len(ta & tb) / len(ta | tb)
                if score > best_score:
                    best_score, best_match = score, dict(r)

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

    async def process_conversation_learning(
        self, user_message: str, assistant_message: str, outcome_id: int | None = None
    ) -> dict:
        """Quy trình học tự phản tư 2 vòng (spec 2026-09-25 §4):
        Vòng 1: Đề xuất (learning_propose.md)
        Vòng 2: Phản biện (learning_critique.md) với mục cũ gần nhất
        """
        if not user_message or not user_message.strip():
            return {"stored": 0, "discarded": True, "items": []}

        if outcome_id is not None:
            return {
                "stored": 0,
                "discarded": True,
                "items": [],
                "reason": "verified outcome uses workflow learning",
            }

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
        try:
            outcomes = await asyncio.to_thread(self.get_recent_agent_outcomes, 3)
        except Exception:
            outcomes = []
        agent_outcomes_str = "\n".join(
            f"- [{o['agent']}] \"{str(o['query'])[:200]}\" → thành công" for o in reversed(outcomes) if o.get("status") == "success"
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
        propose_prompt = build_learning_propose_prompt(
            context=transcript, agent_outcomes=agent_outcomes_str, just_learned=just_learned_str
        )

        try:
            from engine.server.llm_server import call_llm
            from engine.core.json_parser import safe_json_loads
            response = await call_llm(
                messages=[{"role": "user", "content": propose_prompt}],
                temperature=0.0,
                thinking=False,
                response_format={"type": "json_object"},
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

        # Lấy tin nhắn cuối của người dùng để kiểm tra yêu cầu học tường minh
        user_last_message = next((t["content"] for t in reversed(turns) if t.get("role") == "user"), user_text)

        for proposal in raw_proposals[:2]:
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
            if kind not in {"user_fact", "preference", "behaviour_lesson", "routing_note"}:
                continue
            if not key or not content:
                continue

            if not self._validate_proposal_evidence(proposal, user_text, transcript):
                log.info("⏭️ Learning rejected: evidence not verbatim in text: %s", evidence)
                continue

            if kind == "routing_note":
                if self._handle_routing_note_proposal(proposal):
                    accepted.append(proposal)
                continue

            if self._is_forbidden_topic(content, kind):
                log.info("⏭️ Learning rejected: forbidden topic: %s", content)
                continue

            # Kiểm tra yêu cầu học tường minh
            is_explicit = self._is_explicit_learning_request(user_last_message)

            # Nếu không phải yêu cầu tường minh, kiểm tra trạng thái tạm thời
            if not is_explicit and self._is_temporary_state_or_tool_query(evidence, content):
                log.info("⏭️ Learning rejected: temporary state: %s", content)
                continue

            closest = await asyncio.to_thread(self._find_closest_existing_learning, kind, key, content)
            proposal_str = json.dumps(proposal, ensure_ascii=False)
            existing_str = json.dumps(closest, ensure_ascii=False) if closest else "Không có mục nào tương tự."

            critique_prompt = build_learning_critique_prompt(proposal=proposal_str, existing_item=existing_str)
            try:
                c_resp = await call_llm(
                    messages=[{"role": "user", "content": critique_prompt}],
                    temperature=0.0,
                    thinking=False,
                    response_format={"type": "json_object"},
                )
                c_parsed = safe_json_loads(c_resp.choices[0].message.content.strip())
            except Exception as c_exc:
                log.warning("Learning critique call failed: %s", c_exc)
                continue

            decision = c_parsed.get("decision", "skip") if isinstance(c_parsed, dict) else "skip"
            merged_content = c_parsed.get("merged_content", "") if isinstance(c_parsed, dict) else ""

            # Nếu yêu cầu học tường minh, kiểm tra ngoài lệnh
            if is_explicit and decision == "skip":
                # Kiểm tra xem mục cũ có trùng từ vựng không
                if closest:
                    is_lexical_dup = _lexically_similar(content, closest.get("content", ""))
                    if not is_lexical_dup:
                        # Mục cũ không trùng ⇒ đổi quyết định thành new
                        decision = "new"
                        log.info("Critique skip bị bỏ qua: ngài yêu cầu học rõ ràng")
                else:
                    # Không có mục cũ ⇒ đổi thành new
                    decision = "new"
                    log.info("Critique skip bị bỏ qua: ngài yêu cầu học rõ ràng")

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
        for row in rows:
            conn.execute(
                """INSERT INTO learnings (type, content, source, importance, created_at)
                   SELECT ?, ?, ?, ?, ?
                   WHERE NOT EXISTS (
                       SELECT 1 FROM learnings
                       WHERE type = ? AND LOWER(TRIM(content)) = LOWER(TRIM(?))
                   )""",
                (*row, row[0], row[1]),
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

    def get_behaviour_rules(self, limit: int = 5, max_chars: int = 600) -> list[str]:
        """Lấy các bài học hành vi (type='lesson') theo importance DESC, id DESC.
        Trả danh sách nội dung (content), cộng dồn độ dài, dừng TRƯỚC khi vượt max_chars, tối đa limit bài.
        Không dùng embedding, không lọc theo từ khoá."""
        conn = self._get_learning_db()
        rows = conn.execute(
            "SELECT id, content FROM learnings WHERE type=? ORDER BY importance DESC, id DESC LIMIT ?",
            ("lesson", limit),
        ).fetchall()
        conn.close()

        rules: list[str] = []
        total_len = 0
        for row in rows:
            content = row["content"]
            content_len = len(content)
            if total_len + content_len > max_chars:
                break
            rules.append(content)
            total_len += content_len
        return rules

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
        if table not in {"learnings", "validated_workflows", "agent_outcomes"}:
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
            "validated_workflows",
            (
                "id, agent, intent, tool_chain, argument_keys, sample_queries, "
                "success_evidence, validation_count, status, wiki_path, "
                "created_at, updated_at"
            ),
            (
                "agent",
                "intent",
                "tool_chain",
                "sample_queries",
                "success_evidence",
                "status",
            ),
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
        agent: str = "",
    ) -> dict:
        page_limit, page_offset = self._bounded_page(limit, offset)
        search_query = (q or "").strip().lower()
        agent_name = (agent or "").strip().lower()
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
        if agent_name:
            clauses.append("LOWER(agent) = ?")
            params.append(agent_name)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        conn = self._get_learning_db()
        total = conn.execute(
            f"SELECT COUNT(*) FROM agent_outcomes{where}", params
        ).fetchone()[0]
        rows = conn.execute(
            f"""SELECT id, agent, query, status, result, traces, created_at
                FROM agent_outcomes{where}
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

    def get_memory_control_counts(self) -> dict[str, int]:
        conn = self._get_learning_db()
        try:
            return {
                "learnings": conn.execute(
                    "SELECT COUNT(*) FROM learnings"
                ).fetchone()[0],
                "workflows": conn.execute(
                    "SELECT COUNT(*) FROM validated_workflows"
                ).fetchone()[0],
                "outcomes": conn.execute(
                    "SELECT COUNT(*) FROM agent_outcomes"
                ).fetchone()[0],
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

    def _sync_workflow_wiki(
        self, agent: str, requested_path: Path | None = None
    ) -> None:
        path = self._validated_workflow_wiki_path(
            requested_path or (WORKFLOWS_WIKI_DIR / f"{agent}.md")
        )
        conn = self._get_learning_db()
        rows = conn.execute(
            """SELECT * FROM validated_workflows
               WHERE agent=?
               ORDER BY validation_count DESC, updated_at DESC""",
            (agent,),
        ).fetchall()
        conn.close()
        if not rows:
            if path.exists():
                path.unlink()
            self._sync_workflow_hub()
            return
        lines = [f"# Validated workflows: {agent}", ""]
        for row in rows:
            tool_chain = json.loads(row["tool_chain"] or "[]")
            argument_keys = json.loads(row["argument_keys"] or "[]")
            sample_queries = json.loads(row["sample_queries"] or "[]")
            lines.extend(
                [
                    f"## {row['intent']}",
                    f"- Route: {row['agent']}",
                    f"- Tool chain: {', '.join(tool_chain)}",
                    f"- Argument keys: {', '.join(argument_keys) or 'none'}",
                    (
                        f"- Sample queries: {'; '.join(sample_queries[:5])}"
                        if sample_queries
                        else "- Sample queries: (none)"
                    ),
                    f"- Success evidence: {row['success_evidence']}",
                    f"- Validations: {row['validation_count']}",
                    "",
                ]
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines), encoding="utf-8")
        self._sync_workflow_hub()

    def _sync_workflow_hub(self) -> None:
        conn = self._get_learning_db()
        agents = [
            row["agent"]
            for row in conn.execute(
                "SELECT DISTINCT agent FROM validated_workflows ORDER BY agent"
            ).fetchall()
        ]
        conn.close()
        _write_wiki_link_index(WORKFLOWS_HUB_WIKI_PATH, agents)

    def update_learning_control_record(
        self, kind: str, record_id: int, values: dict
    ) -> bool:
        schemas = {
            "learning": (
                "learnings",
                {"type", "semantic_key", "content", "source", "importance", "embedding", "embedding_model"},
            ),
            "workflow": (
                "validated_workflows",
                {
                    "agent",
                    "intent",
                    "tool_chain",
                    "argument_keys",
                    "sample_queries",
                    "success_evidence",
                    "validation_count",
                    "status",
                    "wiki_path",
                },
            ),
            "outcome": (
                "agent_outcomes",
                {"agent", "query", "status", "result", "traces"},
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
            "argument_keys",
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
                """SELECT * FROM validated_workflows
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
                "UPDATE validated_workflows SET updated_at=? WHERE id=?",
                (time.time(), record_id),
            )
        conn.commit()
        new_workflow = (
            conn.execute(
                """SELECT agent, wiki_path FROM validated_workflows
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
                    old_workflow["agent"], Path(old_workflow["wiki_path"])
                )
            if new_workflow and (
                not old_workflow
                or new_workflow["agent"] != old_workflow["agent"]
                or new_workflow["wiki_path"] != old_workflow["wiki_path"]
            ):
                self._sync_workflow_wiki(
                    new_workflow["agent"], Path(new_workflow["wiki_path"])
                )
        except Exception:
            original_row = old_workflow or old_learning
            restore_table = (
                "validated_workflows"
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
                "SELECT * FROM validated_workflows WHERE id=?", (record_id,)
            ).fetchone()
            if not row:
                conn.close()
                raise LookupError("not_found")
            outcomes = conn.execute(
                """SELECT id, agent, query, status FROM agent_outcomes
                   WHERE agent=? ORDER BY created_at DESC LIMIT 20""",
                (row["agent"],),
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
                "SELECT * FROM agent_outcomes WHERE id=?", (record_id,)
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
            "workflow": "validated_workflows",
            "outcome": "agent_outcomes",
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
                    workflow["agent"], Path(workflow["wiki_path"])
                )
        except Exception:
            restore = self._get_learning_db()
            columns = list(workflow.keys())
            restore.execute(
                f"""INSERT INTO validated_workflows
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
        return affected > 0

    def get_recent_agent_outcomes(self, limit: int = 2) -> list[dict]:
        safe_limit = max(1, min(int(limit), 10))
        conn = self._get_learning_db()
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, agent, query, status, result, traces, created_at "
            "FROM agent_outcomes ORDER BY id DESC LIMIT ?",
            (safe_limit,),
        ).fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def get_active_routing_corrections(self, limit: int = 8) -> list[dict]:
        safe_limit = max(1, min(int(limit), 20))
        conn = self._get_learning_db()
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, content, source, created_at FROM learnings "
            "WHERE type='routing_correction' ORDER BY created_at DESC LIMIT ?",
            (safe_limit,),
        ).fetchall()
        conn.close()
        corrections: list[dict] = []
        for row in rows:
            try:
                item = json.loads(row["content"])
            except (TypeError, json.JSONDecodeError):
                log.warning("Skipping malformed routing correction id=%s", row["id"])
                continue
            if not isinstance(item, dict) or item.get("active") is not True:
                continue
            item["id"] = row["id"]
            item["source"] = row["source"]
            corrections.append(item)
        return corrections

    # Gate chỉ hiểu 3 bucket này. Từng có correction ghi expected_route là
    # câu tiếng Việt ("chỉ trả lời hội thoại") khiến gate in nguyên văn vào
    # prompt mà model nhỏ không map được — phải ép về bucket hợp lệ lúc ghi.
    VALID_CORRECTION_ROUTES = {"general", "general_knowledge", "orchestrator"}

    def store_routing_correction(
        self,
        correction_text: str,
        evidence: str,
        expected_route: str,
        max_age_seconds: int = 600,
    ) -> bool:
        expected_route = (expected_route or "").strip().lower()
        if expected_route not in self.VALID_CORRECTION_ROUTES:
            log.warning(
                "Routing correction expected_route %r invalid, coercing to 'general'",
                expected_route,
            )
            expected_route = "general"
        conn = self._get_learning_db()
        conn.row_factory = sqlite3.Row
        outcome = conn.execute(
            "SELECT id, agent, query, created_at FROM agent_outcomes "
            "WHERE status='success' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if not outcome or time.time() - float(outcome["created_at"]) > max_age_seconds:
            conn.close()
            return False
        from engine.core.memory import strip_emojis
        payload = json.dumps({
            "user_query": strip_emojis(outcome["query"]),
            "selected_route": outcome["agent"],
            "expected_route": expected_route,
            "correction_text": strip_emojis(correction_text),
            "evidence": strip_emojis(evidence),
            "active": True,
        }, ensure_ascii=False)
        conn.execute(
            "UPDATE agent_outcomes SET status='misrouted' WHERE id=?",
            (outcome["id"],),
        )
        cur = conn.execute(
            "INSERT INTO learnings "
            "(type, content, source, importance, created_at) VALUES (?, ?, ?, ?, ?)",
            (
                "routing_correction",
                payload,
                f"agent_outcome:{outcome['id']}",
                9,
                time.time(),
            ),
        )
        conn.commit()
        conn.close()
        return cur.rowcount == 1

    def forget_workflow_sample(self, query: str) -> int:
        """Remove `query` from every validated workflow's sample_queries — the exact-match
        keys engine.router.replay replays without asking the LLM. Returns how many workflows
        changed."""
        key = self._normalize_workflow_query(query)
        if not key:
            return 0
        conn = self._get_learning_db()
        agents = set()
        for row in conn.execute("SELECT id, agent, sample_queries FROM validated_workflows").fetchall():
            samples = json.loads(row["sample_queries"] or "[]")
            kept = [s for s in samples if self._normalize_workflow_query(s) != key]
            if len(kept) != len(samples):
                conn.execute(
                    "UPDATE validated_workflows SET sample_queries=? WHERE id=?",
                    (json.dumps(kept, ensure_ascii=False), row["id"]),
                )
                agents.add(row["agent"])
        conn.commit()
        conn.close()
        for agent in agents:
            try:
                self._sync_workflow_wiki(agent)
            except Exception as exc:
                log.warning("Workflow wiki resync failed for %s: %s", agent, exc)
        return len(agents)

    def unlearn_last_route(self, complaint_text: str, max_age_seconds: int = 600) -> bool:
        """The user just complained that the last agent call was wrong (it should have been plain
        chat). A tool that merely ran without error is not proof the route was right, so forget
        that request as a reusable workflow and record a correction: engine.router then stops
        replaying it."""
        conn = self._get_learning_db()
        outcome = conn.execute(
            "SELECT query FROM agent_outcomes WHERE status='success' AND created_at >= ? "
            "ORDER BY id DESC LIMIT 1",
            (time.time() - max_age_seconds,),
        ).fetchone()
        conn.close()
        if not outcome:
            return False
        self.forget_workflow_sample(outcome["query"])
        return self.store_routing_correction(complaint_text, complaint_text, "general", max_age_seconds)

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

    def record_agent_outcome(self, agent: str, query: str, status: str, result: str, traces: list[dict]) -> int:
        """Lưu kết quả thực tế của agent; chỉ success mới đủ điều kiện thành lesson."""
        if status not in ("success", "failed", "cancelled"):
            raise ValueError("Invalid agent outcome status")
        import json
        # store_validated_workflow chỉ cần action_name + outcome từ traces.
        n = max(len(traces), 1)
        per_trace_limit = max(200, min(500, 5000 // n))
        safe_traces = []
        for t in traces[:12]:
            safe = {}
            for k, v in t.items():
                if k in ("output", "result"):
                    safe[k] = self._truncate_trace_output(v, per_trace_limit)
                elif k in ("error_message",):
                    safe[k] = self._truncate_trace_output(v, 300)
                elif k == "args":
                    safe[k] = self._truncate_trace_output(v, 200)
                else:
                    safe[k] = v
            safe_traces.append(safe)
        traces_json = json.dumps(safe_traces, ensure_ascii=False)
        if len(traces_json) > 8000:
            traces_json = json.dumps(safe_traces[:8], ensure_ascii=False)
        conn = self._get_learning_db()
        cur = conn.execute(
            "INSERT INTO agent_outcomes (agent, query, status, result, traces, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (agent, query[:1000], status, result[:4000], traces_json, time.time()),
        )
        conn.commit()
        conn.close()
        return cur.lastrowid

    @staticmethod
    def _normalize_workflow_query(text: str) -> str:
        return re.sub(r"\s+", " ", (text or "").strip()).casefold()

    def get_exact_workflow_candidates(self, text: str) -> list[dict]:
        """Return every validated workflow whose saved command exactly matches text."""
        normalized_text = self._normalize_workflow_query(text)
        if not normalized_text:
            return []
        corrections = self.get_active_routing_corrections(limit=8)
        if any(
            self._normalize_workflow_query(item.get("user_query", ""))
            == normalized_text
            and item.get("expected_route") in {"general", "general_knowledge"}
            for item in corrections
        ):
            return []
        return [
            candidate
            for candidate in self.get_validated_workflow_candidates(limit=None)
            if any(
                self._normalize_workflow_query(sample) == normalized_text
                for sample in candidate["sample_queries"]
            )
        ]

    def get_validated_workflow_candidates(self, limit: int | None = 5) -> list[dict]:
        """Return workflow metadata for engine.router.replay; no similarity score is applied."""
        import json
        safe_limit = None if limit is None else max(1, min(int(limit), 20))
        conn = self._get_learning_db()
        select_sql = (
            "SELECT id, agent, intent, tool_chain, argument_keys, success_evidence, "
            "sample_queries, validation_count FROM validated_workflows "
            "WHERE status='validated' ORDER BY validation_count DESC, updated_at DESC"
        )
        rows = (
            conn.execute(select_sql).fetchall()
            if safe_limit is None
            else conn.execute(select_sql + " LIMIT ?", (safe_limit,)).fetchall()
        )
        conn.close()
        candidates = []
        for row in rows:
            try:
                tool_chain = json.loads(row["tool_chain"] or "[]")
                argument_keys = json.loads(row["argument_keys"] or "[]")
                sample_queries = json.loads(row["sample_queries"] or "[]")
            except (TypeError, json.JSONDecodeError):
                log.warning("Skipping malformed validated workflow id=%s", row["id"])
                continue
            if not row["agent"] or not tool_chain:
                continue
            candidates.append({
                "id": row["id"],
                "agent": row["agent"],
                "intent": row["intent"],
                "tool_chain": tool_chain,
                "argument_keys": argument_keys,
                "success_evidence": row["success_evidence"],
                "sample_queries": sample_queries,
                "validation_count": row["validation_count"],
            })
        return candidates

    async def store_validated_workflow(self, outcome_id: int) -> dict | None:
        """Distill a verified agent/tool execution into DB metadata and a concise Wiki playbook."""
        import json
        conn = self._get_learning_db()
        outcome = conn.execute("SELECT agent, query, status, result, traces FROM agent_outcomes WHERE id=?", (outcome_id,)).fetchone()
        if not outcome or outcome["status"] != "success":
            conn.close()
            return None
        try:
            traces = json.loads(outcome["traces"] or "[]")
        except json.JSONDecodeError:
            conn.close()
            return None
        if not traces or not all(trace.get("outcome") == "success" for trace in traces):
            conn.close()
            return None
        from engine.core.memory import strip_emojis
        agent = outcome["agent"]
        original_query = strip_emojis((outcome["query"] or "").strip())

        # Execution traces are the source of truth for what ran successfully.
        # The LLM only distils descriptive metadata; it must not veto a
        # verified tool execution or replace the executed agent/tool chain.
        tool_chain = [str(trace.get("action_name", "")) for trace in traces if trace.get("action_name")]
        if not tool_chain:
            conn.close()
            return None
        from engine.prompts.learning import build_learning_workflow_prompt
        distillation_prompt = build_learning_workflow_prompt(
            original_query[:1500],
            agent,
            json.dumps(tool_chain, ensure_ascii=False),
            (outcome["result"] or "")[:2000],
            json.dumps(traces, ensure_ascii=False)[:2500],
        )
        try:
            from engine.server.llm_server import call_llm
            from engine.core.json_parser import safe_json_loads
            response = await call_llm(
                messages=[{"role": "user", "content": distillation_prompt}],
                temperature=0.0,
                thinking=False,
                response_format={"type": "json_object"}
            )
            decision = safe_json_loads(response.choices[0].message.content.strip())
        except Exception as distillation_err:
            log.warning(
                "Workflow distillation failed; storing verified trace with fallback metadata "
                "outcome_id=%s: %s",
                outcome_id,
                distillation_err,
            )
            decision = {}
        learned_intent = strip_emojis(str(decision.get("intent") or "").strip()) if isinstance(decision, dict) else ""
        placeholder_intents = {
            "concise canonical user intent",
            "canonical user intent",
            "user intent",
            "n/a",
        }
        contract_is_grounded = (
            isinstance(decision, dict)
            and decision.get("agent") == agent
            and decision.get("tools") == tool_chain
        )
        if (
            not learned_intent
            or learned_intent.casefold() in placeholder_intents
            or not contract_is_grounded
        ):
            learned_intent = original_query or f"{agent}: {', '.join(tool_chain)}"
            log.warning(
                "Workflow distillation metadata was incomplete; using verified trace metadata "
                "outcome_id=%s",
                outcome_id,
            )
        argument_keys = sorted({key for trace in traces for key in (trace.get("args") or {}).keys()})
        intent = learned_intent
        now = time.time()
        wiki_path = str(WORKFLOWS_WIKI_DIR / f"{agent}.md")
        encoded_chain = json.dumps(tool_chain, ensure_ascii=False)
        existing = conn.execute(
            "SELECT id, validation_count, sample_queries FROM validated_workflows WHERE agent=? AND tool_chain=?", (agent, encoded_chain)
        ).fetchone()
        if existing:
            workflow_id = existing["id"]
            validation_count = existing["validation_count"] + 1
            sample_queries = json.loads(existing["sample_queries"] or "[]")
            if original_query and original_query.lower() not in (s.lower() for s in sample_queries):
                sample_queries.append(original_query)
            conn.execute(
                "UPDATE validated_workflows SET validation_count=?, updated_at=?, sample_queries=? WHERE id=?",
                (validation_count, now, json.dumps(sample_queries, ensure_ascii=False), workflow_id)
            )
        else:
            sample_queries = [original_query] if original_query else []
            cur = conn.execute(
                "INSERT INTO validated_workflows (agent, intent, tool_chain, argument_keys, success_evidence, wiki_path, sample_queries, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (agent, intent, encoded_chain, json.dumps(argument_keys, ensure_ascii=False),
                 "all tool traces returned success", wiki_path, json.dumps(sample_queries, ensure_ascii=False), now, now),
            )
            workflow_id = cur.lastrowid
            validation_count = 1
        conn.commit()
        rows = conn.execute("SELECT * FROM validated_workflows WHERE agent=? ORDER BY validation_count DESC, updated_at DESC", (agent,)).fetchall()
        conn.close()
        WORKFLOWS_WIKI_DIR.mkdir(parents=True, exist_ok=True)
        lines = [f"# Validated workflows: {agent}", ""]
        for row in rows:
            sq = json.loads(row["sample_queries"] or "[]")
            lines.extend([
                f"## {row['intent']}",
                f"- Route: {row['agent']}",
                f"- Tool chain: {', '.join(json.loads(row['tool_chain']))}",
                f"- Argument keys: {', '.join(json.loads(row['argument_keys'])) or 'none'}",
                f"- Sample queries: {'; '.join(sq)}" if sq else "- Sample queries: (none)",
                f"- Success evidence: {row['success_evidence']}",
                f"- Validations: {row['validation_count']}",
                "",
            ])
        Path(wiki_path).write_text("\n".join(lines), encoding="utf-8")
        self._sync_workflow_hub()
        log.info(
            "🧪 Validated workflow stored id=%s agent=%s tools=%s validations=%s "
            "queries=%d db=stored wiki=synced path=%s",
            workflow_id,
            agent,
            ','.join(tool_chain),
            validation_count,
            len(sample_queries),
            wiki_path,
        )
        return {"agent": agent, "tool_chain": tool_chain, "argument_keys": argument_keys}

    async def reflect_on_session(self, session_messages: list, outcome_id: int | None = None) -> dict:
        """Phản tư về một phiên hội thoại; chỉ lesson chất lượng mới được lưu vào jarvis.db."""
        if not session_messages or len(session_messages) < 2:
            return {"success": False, "reason": "No messages or too few messages to reflect on"}

        # Chat text is not evidence. Only verified execution becomes a reusable workflow;
        # conversation improvement requires explicit user feedback and is handled separately.
        if outcome_id:
            workflow = await self.store_validated_workflow(outcome_id)
            return {"success": bool(workflow), "workflow": workflow, "reason": "validated outcome required"}
        return {"success": False, "reason": "conversation requires explicit feedback"}

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
