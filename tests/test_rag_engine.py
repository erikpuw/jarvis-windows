"""Regression tests for the core RAGEngine document pipeline
(engine.core.rag_engine): indexing, hybrid retrieval, persistence, removal
and lifecycle sync. Uses a deterministic fake embedding client so no
embedding server is required.

There was previously zero automated coverage for this module - these tests
codify the behavior verified manually during a RAG system audit.

Run: python tests/test_rag_engine.py
"""
import asyncio
import shutil
import sys
import tempfile
from contextlib import contextmanager
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
    """Deterministic bag-of-words hash embedding: semantically similar text
    (shared words) lands closer in vector space, without needing a real
    embedding server."""

    def __init__(self, dim=64):
        self.dim = dim
        self.calls = 0

    class _Embeddings:
        def __init__(self, outer):
            self.outer = outer

        def create(self, input, model=None, timeout=None):
            self.outer.calls += 1
            text = input[0]
            vec = np.zeros(self.outer.dim, dtype=np.float32)
            for word in text.lower().split():
                vec[hash(word) % self.outer.dim] += 1.0
            norm = np.linalg.norm(vec)
            if norm > 0:
                vec = vec / norm
            return _FakeEmbeddingResponse(vec.tolist())

    @property
    def embeddings(self):
        return FakeEmbedClient._Embeddings(self)


@contextmanager
def _isolated_rag_data_dir():
    """Redirects the module-level persistence paths to a throwaway temp dir
    for the duration of one test, so tests never touch data/rag_index and
    never see each other's state."""
    tmp = Path(tempfile.mkdtemp(prefix="jarvis_rag_test_"))
    original = (
        rag_engine_mod.RAG_DATA_DIR,
        rag_engine_mod.INDEX_FILE_PATH,
        rag_engine_mod.METADATA_FILE_PATH,
    )
    rag_engine_mod.RAG_DATA_DIR = tmp
    rag_engine_mod.INDEX_FILE_PATH = tmp / "rag_vectors.tq"
    rag_engine_mod.METADATA_FILE_PATH = tmp / "rag_metadata.json"
    try:
        yield tmp
    finally:
        (
            rag_engine_mod.RAG_DATA_DIR,
            rag_engine_mod.INDEX_FILE_PATH,
            rag_engine_mod.METADATA_FILE_PATH,
        ) = original
        shutil.rmtree(tmp, ignore_errors=True)


def _write_doc(tmp: Path, name: str, text: str) -> Path:
    doc = tmp / name
    doc.write_text(text, encoding="utf-8")
    return doc


def test_process_document_indexes_and_hybrid_search_ranks_relevant_doc_first():
    with _isolated_rag_data_dir() as tmp:
        cats_doc = _write_doc(
            tmp, "cats.txt",
            "Meo la mot loai dong vat nuoi pho bien. Meo thich choi voi bong len. " * 3,
        )
        python_doc = _write_doc(
            tmp, "python.txt",
            "Python la ngon ngu lap trinh bac cao. Ham async cho phep lap trinh bat dong bo. " * 3,
        )

        rag = RAGEngine(dim=64, persistent=True)
        rag.set_embed_client(FakeEmbedClient(dim=64))

        r1 = asyncio.run(rag.process_document(str(cats_doc)))
        r2 = asyncio.run(rag.process_document(str(python_doc)))
        assert r1["success"] and r1["chunks"] >= 1, r1
        assert r2["success"] and r2["chunks"] >= 1, r2
        assert rag.enabled is True
        assert len(rag.get_indexed_files()) == 2

        cat_results = asyncio.run(rag.retrieve("meo thich choi gi", top_k=3))
        assert cat_results and cat_results[0]["filename"] == "cats.txt", cat_results

        python_results = asyncio.run(rag.retrieve("ham async python", top_k=3))
        assert python_results and python_results[0]["filename"] == "python.txt", python_results


def test_persistent_engine_reloads_chunks_from_disk():
    with _isolated_rag_data_dir() as tmp:
        doc = _write_doc(tmp, "note.txt", "noi dung can luu qua lan khoi dong lai")
        rag = RAGEngine(dim=64, persistent=True)
        rag.set_embed_client(FakeEmbedClient(dim=64))
        asyncio.run(rag.process_document(str(doc)))
        chunk_count = len(rag.chunks)
        assert chunk_count >= 1

        reloaded = RAGEngine(dim=64, persistent=True)
        assert len(reloaded.chunks) == chunk_count
        assert reloaded.enabled is True


def test_remove_document_deletes_only_matching_chunks():
    with _isolated_rag_data_dir() as tmp:
        doc_a = _write_doc(tmp, "a.txt", "noi dung tai lieu a")
        doc_b = _write_doc(tmp, "b.txt", "noi dung tai lieu b")
        rag = RAGEngine(dim=64, persistent=True)
        rag.set_embed_client(FakeEmbedClient(dim=64))
        asyncio.run(rag.process_document(str(doc_a)))
        asyncio.run(rag.process_document(str(doc_b)))
        total_before = len(rag.chunks)

        removed = asyncio.run(rag.remove_document(str(doc_a)))

        assert removed >= 1
        assert len(rag.chunks) == total_before - removed
        assert all(c["filename"] != "a.txt" for c in rag.chunks)
        assert any(c["filename"] == "b.txt" for c in rag.chunks)


def test_sync_lifecycle_prunes_orphaned_chunks_for_deleted_files():
    with _isolated_rag_data_dir() as tmp:
        doc_a = _write_doc(tmp, "a.txt", "noi dung tai lieu a")
        doc_b = _write_doc(tmp, "b.txt", "noi dung tai lieu b")
        rag = RAGEngine(dim=64, persistent=True)
        rag.set_embed_client(FakeEmbedClient(dim=64))
        asyncio.run(rag.process_document(str(doc_a)))
        asyncio.run(rag.process_document(str(doc_b)))

        doc_a.unlink()  # file gone from disk, but engine doesn't know yet
        pruned = asyncio.run(rag.sync_lifecycle([str(doc_b)]))

        assert pruned >= 1
        assert all(c["filename"] != "a.txt" for c in rag.chunks)
        assert any(c["filename"] == "b.txt" for c in rag.chunks)


def test_process_document_missing_file_returns_error_without_raising():
    with _isolated_rag_data_dir() as tmp:
        rag = RAGEngine(dim=64, persistent=True)
        rag.set_embed_client(FakeEmbedClient(dim=64))

        result = asyncio.run(rag.process_document(str(tmp / "does_not_exist.txt")))

        assert result["success"] is False
        assert "error" in result


def test_process_document_empty_content_returns_error_without_raising():
    with _isolated_rag_data_dir() as tmp:
        empty_doc = _write_doc(tmp, "empty.txt", "")
        rag = RAGEngine(dim=64, persistent=True)
        rag.set_embed_client(FakeEmbedClient(dim=64))

        result = asyncio.run(rag.process_document(str(empty_doc)))

        assert result["success"] is False
        assert "error" in result


def test_retrieve_with_no_indexed_chunks_returns_empty_list():
    with _isolated_rag_data_dir():
        rag = RAGEngine(dim=64, persistent=True)
        rag.set_embed_client(FakeEmbedClient(dim=64))

        results = asyncio.run(rag.retrieve("cau hoi bat ky"))

        assert results == []


def test_retrieve_min_score_drops_irrelevant_chunks():
    """Without a floor retrieve() always returns top_k, even for chunks that
    share nothing with the query - the LLM then gets junk as "evidence"."""
    with _isolated_rag_data_dir() as tmp:
        cats_doc = _write_doc(tmp, "cats.txt", "Meo thich choi voi bong len. " * 3)
        python_doc = _write_doc(tmp, "python.txt", "Python la ngon ngu lap trinh. " * 3)
        rag = RAGEngine(dim=64, persistent=True)
        rag.set_embed_client(FakeEmbedClient(dim=64))
        asyncio.run(rag.process_document(str(cats_doc)))
        asyncio.run(rag.process_document(str(python_doc)))

        unfiltered = asyncio.run(rag.retrieve("meo thich choi", top_k=5))
        filtered = asyncio.run(rag.retrieve("meo thich choi", top_k=5, min_score=0.2))

        assert {r["filename"] for r in unfiltered} == {"cats.txt", "python.txt"}
        assert [r["filename"] for r in filtered] == ["cats.txt"], filtered

def test_clean_document_text():
    from engine.core.rag_engine import clean_document_text

    raw = "Mục tiêu 68\x0070kg với 12\x0015% mỡ trong 5\x007 tháng.\x00Bữa phụ 16\x0000\x00ăn\x0cngon.\u200b"
    cleaned = clean_document_text(raw)
    assert "\x00" not in cleaned
    assert "\x0c" not in cleaned
    assert "\u200b" not in cleaned
    assert "68-70kg" in cleaned
    assert "12-15%" in cleaned
    assert "5-7 tháng" in cleaned
    assert "16-00" in cleaned


if __name__ == "__main__":
    test_retrieve_min_score_drops_irrelevant_chunks()
    test_process_document_indexes_and_hybrid_search_ranks_relevant_doc_first()
    test_persistent_engine_reloads_chunks_from_disk()
    test_remove_document_deletes_only_matching_chunks()
    test_sync_lifecycle_prunes_orphaned_chunks_for_deleted_files()
    test_process_document_missing_file_returns_error_without_raising()
    test_process_document_empty_content_returns_error_without_raising()
    test_retrieve_with_no_indexed_chunks_returns_empty_list()
    print("OK: RAGEngine core pipeline (index/retrieve/persist/remove/sync) all pass")
