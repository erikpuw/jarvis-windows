from __future__ import annotations

import hashlib
import json
import shutil
import threading
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).parent.parent.parent
DEFAULT_RAG_ROOT = PROJECT_ROOT / "data" / "rag_index"

# write_page()/mark_page_failed() do an unlocked read-modify-write of
# manifest.json; concurrent ingestion of the same document (RAGDocumentStore
# instances are created ad-hoc per call, not shared) could lose a
# page-completion record. Keyed module-level locks so concurrent writers to
# the same manifest path serialize, regardless of which store instance
# they're going through.
_manifest_locks: dict[str, threading.Lock] = {}
_manifest_locks_guard = threading.Lock()


def _get_manifest_lock(path: Path) -> threading.Lock:
    key = str(path.resolve())
    with _manifest_locks_guard:
        lock = _manifest_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _manifest_locks[key] = lock
        return lock


@dataclass(frozen=True)
class PreparedDocument:
    document_id: str
    source_path: Path
    source_filename: str
    root: Path

    @property
    def manifest_path(self) -> Path:
        return self.root / "manifest.json"

    def page_path(self, page_number: int) -> Path:
        if page_number < 1:
            raise ValueError("page_number must be positive")
        return self.root / "pages" / f"page-{page_number:04d}.md"


class RAGDocumentStore:
    """Chỗ làm việc tạm cho một lần đọc tệp đính kèm (từng trang). Không giữ gì lâu dài:
    lưu lâu dài là copy tệp vào thư mục watcher (xem engine/rag/runner.py)."""

    def __init__(self, rag_root: Path = DEFAULT_RAG_ROOT):
        self.rag_root = Path(rag_root).resolve()
        self.staging_root = self.rag_root / "staging"
        self.staging_root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def document_id(path: Path) -> str:
        digest = hashlib.sha256()
        with Path(path).open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()[:24]

    @staticmethod
    def _inside(path: Path, root: Path) -> Path:
        resolved = path.resolve()
        resolved_root = root.resolve()
        if resolved != resolved_root and resolved_root not in resolved.parents:
            raise ValueError("path is outside configured RAG roots")
        return resolved

    def atomic_write(self, path: Path, text: str) -> None:
        target = self._inside(path, self.rag_root)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(target)

    def open_staging(
        self,
        source_path: Path,
        source_filename: str,
    ) -> PreparedDocument:
        source = Path(source_path).resolve(strict=True)
        document_id = self.document_id(source)
        root = self._inside(self.staging_root / document_id, self.rag_root)
        (root / "pages").mkdir(parents=True, exist_ok=True)
        return PreparedDocument(
            document_id=document_id,
            source_path=source,
            source_filename=Path(source_filename).name,
            root=root,
        )

    def initialize_manifest(
        self,
        prepared: PreparedDocument,
        total_pages: int,
    ) -> dict:
        if total_pages < 1:
            raise ValueError("total_pages must be positive")
        if prepared.manifest_path.exists():
            return json.loads(
                prepared.manifest_path.read_text(encoding="utf-8")
            )
        manifest = {
            "schema_version": 1,
            "document_id": prepared.document_id,
            "source_hash": prepared.document_id,
            "source_filename": prepared.source_filename,
            "status": "processing",
            "total_pages": total_pages,
            "completed_pages": 0,
            "failed_pages": [],
            "pages": [],
        }
        self._write_manifest(prepared.manifest_path, manifest)
        return manifest

    def _write_manifest(self, path: Path, manifest: dict) -> None:
        self.atomic_write(
            path,
            json.dumps(manifest, ensure_ascii=False, indent=2),
        )

    def write_page(
        self,
        prepared: PreparedDocument,
        page_number: int,
        markdown: str,
        method: str,
    ) -> None:
        if method not in {"native", "ocr"}:
            raise ValueError("unsupported conversion method")
        self.atomic_write(
            prepared.page_path(page_number),
            markdown.rstrip() + "\n",
        )
        with _get_manifest_lock(prepared.manifest_path):
            manifest = json.loads(
                prepared.manifest_path.read_text(encoding="utf-8")
            )
            manifest["pages"] = [
                item
                for item in manifest["pages"]
                if item["page"] != page_number
            ]
            manifest["pages"].append(
                {
                    "page": page_number,
                    "method": method,
                    "status": "done",
                }
            )
            manifest["pages"].sort(key=lambda item: item["page"])
            manifest["completed_pages"] = len(manifest["pages"])
            if manifest["completed_pages"] == manifest["total_pages"]:
                manifest["status"] = "ready"
            self._write_manifest(prepared.manifest_path, manifest)

    def mark_page_failed(
        self,
        prepared: PreparedDocument,
        page_number: int,
    ) -> None:
        with _get_manifest_lock(prepared.manifest_path):
            manifest = json.loads(
                prepared.manifest_path.read_text(encoding="utf-8")
            )
            failed_pages = {
                int(item) for item in manifest.get("failed_pages", [])
            }
            failed_pages.add(page_number)
            manifest["failed_pages"] = sorted(failed_pages)
            manifest["status"] = "processing"
            self._write_manifest(prepared.manifest_path, manifest)

    def discard_staging(self, prepared: PreparedDocument) -> None:
        candidate = self._inside(prepared.root, self.staging_root)
        staging_root = self.staging_root.resolve()
        if (
            candidate.parent != staging_root
            or candidate.name != prepared.document_id
        ):
            raise ValueError(
                f"Refusing to remove unexpected staging path: {candidate}"
            )
        if candidate.exists():
            shutil.rmtree(candidate)
