"""
JARVIS RAG Folder Watcher - Auto-index documents khi them file moi.

Watch thu muc data/wiki/Documents/ (hoac RAG_WATCH_FOLDER env) - nguon duy nhat cua RAG.
Supports: .pdf, .docx, .pptx, .xlsx, .txt, .md, .csv
"""

import asyncio
import logging
import os
import sqlite3
import time
from pathlib import Path
from typing import Optional

log = logging.getLogger("jarvis.rag_watcher")

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".pptx", ".xlsx", ".txt", ".md", ".csv", ".html", ".htm"}
_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def watch_folder() -> Path:
    """Thư mục RAG theo dõi; nằm trong vault Obsidian (data/wiki) để Obsidian đọc được tệp gốc."""
    folder = Path(os.getenv("RAG_WATCH_FOLDER") or "data/wiki/Documents")
    return folder if folder.is_absolute() else _PROJECT_ROOT / folder

# DB luu vet file da index de tranh re-index
WATCH_DB_PATH = Path(__file__).parent.parent.parent / "data" / "rag_watch.db"


def _get_watch_db() -> sqlite3.Connection:
    WATCH_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(WATCH_DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS indexed_files (
            file_path   TEXT PRIMARY KEY,
            filename    TEXT NOT NULL,
            file_size   INTEGER DEFAULT 0,
            indexed_at  REAL NOT NULL,
            chunks      INTEGER DEFAULT 0,
            status      TEXT DEFAULT 'ok'
        )
    """)
    conn.commit()
    return conn


# Obsidian tự lưu liên tục khi đang gõ: chờ tệp yên chừng này rồi mới nạp, khỏi nhúng lại từng phím
_SETTLE_SECONDS = 2.0


def _indexed_row(file_path: str) -> Optional[sqlite3.Row]:
    conn = _get_watch_db()
    row = conn.execute("SELECT file_size, indexed_at FROM indexed_files WHERE file_path = ?", (file_path,)).fetchone()
    conn.close()
    return row


def _is_current(row: Optional[sqlite3.Row], path: Path) -> bool:
    """Đã nạp và tệp chưa đổi (cùng kích thước, không sửa sau lần nạp)."""
    st = path.stat()
    return row is not None and row["file_size"] == st.st_size and row["indexed_at"] >= st.st_mtime


def _mark_indexed(file_path: str, filename: str, chunks: int, file_size: int = 0):
    conn = _get_watch_db()
    conn.execute("""
        INSERT OR REPLACE INTO indexed_files (file_path, filename, file_size, indexed_at, chunks, status)
        VALUES (?, ?, ?, ?, ?, 'ok')
    """, (file_path, filename, file_size, time.time(), chunks))
    conn.commit()
    conn.close()


def mark_removed(file_path: str):
    conn = _get_watch_db()
    conn.execute("DELETE FROM indexed_files WHERE file_path = ?", (file_path,))
    conn.commit()
    conn.close()


def get_watch_stats() -> dict:
    """Tra ve thong ke tat ca file da index."""
    conn = _get_watch_db()
    rows = conn.execute(
        "SELECT file_path, filename, file_size, indexed_at, chunks, status FROM indexed_files ORDER BY indexed_at DESC"
    ).fetchall()
    conn.close()
    files = [dict(r) for r in rows]
    total_chunks = sum(f["chunks"] for f in files)
    return {"files": files, "total_files": len(files), "total_chunks": total_chunks}


class RAGFolderWatcher:
    """
    Giam sat thu muc va tu dong index file moi vao RAG engine.
    Su dung watchdog de nhan su kien filesystem.
    """

    def __init__(self, watch_folder: str, loop: Optional[asyncio.AbstractEventLoop] = None):
        self.watch_folder = Path(watch_folder)
        self.watch_folder.mkdir(parents=True, exist_ok=True)
        self._loop = loop
        self._observer = None
        self._indexing_queue: asyncio.Queue = asyncio.Queue()
        self._running = False
        log.info(f"RAG Watcher init: watching {self.watch_folder}")

    def _schedule_index(self, file_path: str):
        """Gui file vao asyncio queue tu watchdog thread."""
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(
                self._indexing_queue.put(file_path),
                self._loop
            )

    def _schedule_remove(self, file_path: str):
        """Gui yeu cau xoa file khoi RAG tu watchdog thread."""
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(
                self._indexing_queue.put(f"__REMOVE__:{file_path}"),
                self._loop
            )

    def start(self, loop: asyncio.AbstractEventLoop):
        """Khoi dong watchdog observer trong background thread."""
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler

        self._loop = loop
        watcher_self = self

        class _Handler(FileSystemEventHandler):
            def on_created(self, event):
                if not event.is_directory:
                    p = Path(event.src_path)
                    if p.suffix.lower() in SUPPORTED_EXTENSIONS:
                        log.info(f"RAG Watcher: new file detected: {p.name}")
                        watcher_self._schedule_index(str(p.resolve()))

            def on_modified(self, event):  # tệp tạo rỗng rồi mới ghi nội dung (ghi chú Obsidian)
                if not event.is_directory and Path(event.src_path).suffix.lower() in SUPPORTED_EXTENSIONS:
                    watcher_self._schedule_index(str(Path(event.src_path).resolve()))

            def on_deleted(self, event):
                if not event.is_directory:
                    p = Path(event.src_path)
                    if p.suffix.lower() in SUPPORTED_EXTENSIONS:
                        log.info(f"RAG Watcher: file removed: {p.name}")
                        watcher_self._schedule_remove(str(p.resolve()))

            def on_moved(self, event):
                if not event.is_directory:
                    # Xoa old, index new
                    p_old = Path(event.src_path)
                    p_new = Path(event.dest_path)
                    if p_old.suffix.lower() in SUPPORTED_EXTENSIONS:
                        watcher_self._schedule_remove(str(p_old.resolve()))
                    if p_new.suffix.lower() in SUPPORTED_EXTENSIONS:
                        watcher_self._schedule_index(str(p_new.resolve()))

        self._observer = Observer()
        self._observer.schedule(_Handler(), str(self.watch_folder), recursive=True)
        self._observer.start()
        self._running = True
        log.info(f"RAG Watcher started: {self.watch_folder}")

    def stop(self):
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=5)
        self._running = False
        log.info("RAG Watcher stopped")

    async def _index_file(self, file_path: str):
        """Chay index trong asyncio context."""
        path = Path(file_path)
        if not path.exists():
            log.warning(f"RAG Watcher: file not found: {file_path}")
            return

        await asyncio.sleep(max(0.0, _SETTLE_SECONDS - (time.time() - path.stat().st_mtime)))
        if not path.exists():
            return
        row = _indexed_row(file_path)
        if _is_current(row, path):
            log.debug(f"RAG Watcher: already indexed, skipping: {path.name}")
            return

        from engine.core.rag_engine import get_rag_engine
        rag = get_rag_engine()

        # Cho embed_client sẵn sàng bằng VÒNG LẶP, không đệ quy — đệ quy ở
        # đây từng khiến độ sâu stack tăng thêm mỗi 30s nếu embed_client
        # không bao giờ sẵn sàng, cuối cùng RecursionError giết chết hẳn tác
        # vụ xử lý hàng đợi này, không có gì tự khởi động lại sau đó.
        max_wait_retries = 60  # ~30 phút (60 lần chờ 30s)
        for _ in range(max_wait_retries):
            if rag.embed_client is not None:
                break
            log.warning("RAG Watcher: embed_client not set yet, waiting 30s before retry")
            await asyncio.sleep(30)
        else:
            log.error(
                f"RAG Watcher: embed_client vẫn chưa sẵn sàng sau "
                f"{max_wait_retries * 30}s, bỏ qua {path.name} cho chu kỳ sau"
            )
            return

        log.info(f"RAG Watcher: indexing {path.name}...")
        try:
            if row is not None:  # tệp đã sửa: process_document bỏ qua tệp còn chunk cũ, nên xoá trước
                await rag.remove_document(file_path)
            result = await rag.process_document(file_path)
            if result.get("success"):
                chunks = result.get("chunks", 0)
                file_size = path.stat().st_size if path.exists() else 0
                _mark_indexed(file_path, path.name, chunks, file_size)
                log.info(f"RAG Watcher: indexed {path.name} -> {chunks} chunks")
            else:
                log.warning(f"RAG Watcher: failed to index {path.name}: {result.get('error')}")
        except Exception as e:
            log.error(f"RAG Watcher: error indexing {path.name}: {e}")

    async def _remove_file(self, file_path: str):
        """Xoa file khoi RAG index."""
        try:
            from engine.core.rag_engine import get_rag_engine
            rag = get_rag_engine()
            removed = await rag.remove_document(file_path)
            mark_removed(file_path)
            log.info(f"RAG Watcher: removed {removed} chunks for {Path(file_path).name}")
        except Exception as e:
            log.error(f"RAG Watcher: error removing {file_path}: {e}")

    async def process_queue(self):
        """Xu ly hang doi indexing trong asyncio loop - goi nhu 1 background task."""
        log.info("RAG Watcher: queue processor started")
        while self._running:
            try:
                item = await asyncio.wait_for(self._indexing_queue.get(), timeout=2.0)
                if item.startswith("__REMOVE__:"):
                    file_path = item[len("__REMOVE__:"):]
                    await self._remove_file(file_path)
                else:
                    await self._index_file(item)
                self._indexing_queue.task_done()
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                log.error(f"RAG Watcher queue error: {e}")

    async def scan_existing(self):
        """Scan thu muc lan dau, dong bo vong doi va index tat ca file chua duoc index."""
        files = [
            f for f in self.watch_folder.rglob("*")
            if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS
        ]
        active_paths = [str(f.resolve()) for f in files]
        
        # Dong bo vong doi RAG: Xoa cac chunk mo coi khong con file ton tai tren o dia
        try:
            from engine.core.rag_engine import get_rag_engine
            rag = get_rag_engine()
            # sync_lifecycle xoá mọi chunk không nằm trong danh sách: chỉ được dọn chunk của CHÍNH thư mục
            # thả file, không đụng tài liệu lưu qua @rag (nằm ngoài thư mục này).
            watch_root = self.watch_folder.resolve()
            outside = [
                c["file_path"] for c in rag.chunks
                if c.get("file_path") and watch_root not in Path(c["file_path"]).resolve().parents
            ]
            await rag.sync_lifecycle(active_paths + outside)
            
            # Dong bo DB watch
            conn = _get_watch_db()
            db_rows = conn.execute("SELECT file_path FROM indexed_files").fetchall()
            active_set = set(active_paths)
            for row in db_rows:
                if row["file_path"] not in active_set:
                    conn.execute("DELETE FROM indexed_files WHERE file_path = ?", (row["file_path"],))
            conn.commit()
            conn.close()
        except Exception as sync_err:
            log.warning(f"RAG Watcher lifecycle sync warning: {sync_err}")

        if not files:
            log.info(f"RAG Watcher: no files found in {self.watch_folder}")
            return
        log.info(f"RAG Watcher: scanning {len(files)} existing files...")
        for f in files:
            fp = str(f.resolve())
            if not _is_current(_indexed_row(fp), f):  # cả tệp sửa lúc JARVIS tắt
                await self._index_file(fp)
                await asyncio.sleep(0.5)  # Tranh overload embedding server


# Singleton
_watcher_instance: Optional[RAGFolderWatcher] = None


def get_rag_watcher(watch_folder: Optional[str] = None) -> Optional[RAGFolderWatcher]:
    global _watcher_instance
    if _watcher_instance is None and watch_folder:
        _watcher_instance = RAGFolderWatcher(watch_folder)
    return _watcher_instance