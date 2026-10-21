"""Regression test: process_document() must not duplicate chunks when called
more than once for the same file (any caller other than the folder watcher
has no protection - rag_watch.db only guards RAGFolderWatcher._index_file()).

Run: python tests/test_rag_process_document_dedup.py
"""
import asyncio
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np

import engine.core.rag_engine as rag_engine_mod
from engine.core.rag_engine import RAGEngine


class _FakeEmbeddingData:
    def __init__(self, embedding):
        self.embedding = embedding


class _FakeEmbeddingResponse:
    def __init__(self, embedding):
        self.data = [_FakeEmbeddingData(embedding)]


class FakeEmbedClient:
    def __init__(self, dim=64):
        self.dim = dim

    class _Embeddings:
        def __init__(self, outer):
            self.outer = outer

        def create(self, input, model=None, timeout=None):
            vec = np.ones(self.outer.dim, dtype=np.float32)
            return _FakeEmbeddingResponse(vec.tolist())

    @property
    def embeddings(self):
        return FakeEmbedClient._Embeddings(self)


def test_process_document_twice_on_unchanged_file_does_not_duplicate():
    tmp = Path(tempfile.mkdtemp(prefix="jarvis_rag_dedup_test_"))
    original = (
        rag_engine_mod.RAG_DATA_DIR,
        rag_engine_mod.INDEX_FILE_PATH,
        rag_engine_mod.METADATA_FILE_PATH,
    )
    rag_engine_mod.RAG_DATA_DIR = tmp
    rag_engine_mod.INDEX_FILE_PATH = tmp / "v.tq"
    rag_engine_mod.METADATA_FILE_PATH = tmp / "m.json"
    try:
        doc = tmp / "a.txt"
        doc.write_text("noi dung lap lai nhieu lan de test trung lap chunk", encoding="utf-8")
        rag = RAGEngine(dim=64, persistent=True)
        rag.set_embed_client(FakeEmbedClient(dim=64))

        r1 = asyncio.run(rag.process_document(str(doc)))
        r2 = asyncio.run(rag.process_document(str(doc)))
        r3 = asyncio.run(rag.process_document(str(doc)))

        assert r1["success"] and r1["chunks"] == 1, r1
        assert r2["success"] and r2.get("reused") is True and r2["chunks"] == 0, r2
        assert r3["success"] and r3.get("reused") is True and r3["chunks"] == 0, r3
        assert len(rag.chunks) == 1, f"expected 1 chunk, got {len(rag.chunks)}: {rag.chunks}"
    finally:
        (
            rag_engine_mod.RAG_DATA_DIR,
            rag_engine_mod.INDEX_FILE_PATH,
            rag_engine_mod.METADATA_FILE_PATH,
        ) = original
        shutil.rmtree(tmp, ignore_errors=True)


def test_process_document_reindexes_after_explicit_removal():
    """Dedup must not permanently block re-indexing after the file was
    explicitly removed via remove_document()."""
    tmp = Path(tempfile.mkdtemp(prefix="jarvis_rag_dedup_test2_"))
    original = (
        rag_engine_mod.RAG_DATA_DIR,
        rag_engine_mod.INDEX_FILE_PATH,
        rag_engine_mod.METADATA_FILE_PATH,
    )
    rag_engine_mod.RAG_DATA_DIR = tmp
    rag_engine_mod.INDEX_FILE_PATH = tmp / "v.tq"
    rag_engine_mod.METADATA_FILE_PATH = tmp / "m.json"
    try:
        doc = tmp / "a.txt"
        doc.write_text("noi dung a", encoding="utf-8")
        rag = RAGEngine(dim=64, persistent=True)
        rag.set_embed_client(FakeEmbedClient(dim=64))

        asyncio.run(rag.process_document(str(doc)))
        asyncio.run(rag.remove_document(str(doc)))
        assert len(rag.chunks) == 0

        r_again = asyncio.run(rag.process_document(str(doc)))

        assert r_again["success"] and r_again["chunks"] == 1 and not r_again.get("reused"), r_again
        assert len(rag.chunks) == 1
    finally:
        (
            rag_engine_mod.RAG_DATA_DIR,
            rag_engine_mod.INDEX_FILE_PATH,
            rag_engine_mod.METADATA_FILE_PATH,
        ) = original
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    test_process_document_twice_on_unchanged_file_does_not_duplicate()
    test_process_document_reindexes_after_explicit_removal()
    print("OK: process_document no longer duplicates chunks on repeated calls")
