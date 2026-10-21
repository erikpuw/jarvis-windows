"""Regression tests for RAGEngine._get_embedding dimension-mismatch handling.

Bug: on a dimension mismatch, _get_embedding() unconditionally replaced
self.vector_index with a brand-new EMPTY IdMapIndex(dim=new_dim). If this
happened after self.chunks already held entries (either from earlier
documents, or from earlier chunks in the same process_document() loop -
process_document appends to self.chunks right after each add_with_ids call),
those chunks' vectors were silently discarded from the vector index while
their metadata stayed in self.chunks - permanently orphaned, dense search
would never find them again, with no error raised anywhere.

Fix: only auto-adapt self.dim/self.vector_index when the index is still
empty (nothing to lose). Once chunks already exist, a mismatch means the
embedding backend changed dimension underneath an already-populated index -
that must raise loudly instead of silently wiping data.

Run: python tests/test_rag_engine_embedding_dim_guard.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np

from engine.core.rag_engine import RAGEngine


class _FakeEmbeddingData:
    def __init__(self, embedding):
        self.embedding = embedding


class _FakeEmbeddingResponse:
    def __init__(self, embedding):
        self.data = [_FakeEmbeddingData(embedding)]


class FixedDimEmbedClient:
    """Always returns a vector of `dim` floats, regardless of self.dim on the
    engine - simulates an embedding backend whose model dimension doesn't
    match what the RAGEngine was configured/previously indexed with."""

    def __init__(self, dim: int):
        self.dim = dim

    class _Embeddings:
        def __init__(self, outer):
            self.outer = outer

        def create(self, input, model=None, timeout=None):
            return _FakeEmbeddingResponse([0.1] * self.outer.dim)

    @property
    def embeddings(self):
        return FixedDimEmbedClient._Embeddings(self)


def test_dimension_mismatch_on_empty_index_adapts_silently():
    """A fresh engine with no chunks yet has nothing to lose - adopting the
    real embedding dimension here is the intended convenience behavior."""
    rag = RAGEngine(dim=8, persistent=False)
    rag.set_embed_client(FixedDimEmbedClient(dim=16))

    embedding = asyncio.run(rag._get_embedding("hello"))

    assert len(embedding) == 16
    assert rag.dim == 16


def test_dimension_mismatch_with_populated_vector_index_raises_instead_of_wiping_it():
    rag = RAGEngine(dim=8, persistent=False)
    rag.chunks = [{"id": 0, "content": "already indexed", "filename": "a.txt"}]
    rag.vector_index.add_with_ids(
        np.array([[0.1] * 8], dtype=np.float32), np.array([0], dtype=np.uint64)
    )
    original_vector_index = rag.vector_index
    rag.set_embed_client(FixedDimEmbedClient(dim=16))

    raised = False
    try:
        asyncio.run(rag._get_embedding("hello"))
    except RuntimeError:
        raised = True

    assert raised, "a dimension change against a populated vector index must raise"
    assert rag.dim == 8, "dim must not change when refusing the mismatch"
    assert rag.vector_index is original_vector_index, (
        "existing vector index must not be discarded - that orphans the "
        "entries already indexed under the old dimension"
    )
    assert len(rag.chunks) == 1


def test_dimension_mismatch_with_metadata_but_fresh_empty_index_still_adapts():
    """Mirrors _rebuild_vector_index(): self.chunks holds metadata to
    re-embed, but self.vector_index was just (re)created empty - a mismatch
    here is the expected "index was configured with the wrong dim" case and
    must still self-heal, not raise."""
    rag = RAGEngine(dim=8, persistent=False)
    rag.chunks = [{"id": 0, "content": "already indexed", "filename": "a.txt"}]
    rag.set_embed_client(FixedDimEmbedClient(dim=16))

    embedding = asyncio.run(rag._get_embedding("hello"))

    assert len(embedding) == 16
    assert rag.dim == 16


if __name__ == "__main__":
    test_dimension_mismatch_on_empty_index_adapts_silently()
    test_dimension_mismatch_with_populated_vector_index_raises_instead_of_wiping_it()
    test_dimension_mismatch_with_metadata_but_fresh_empty_index_still_adapts()
    print("OK: dimension-mismatch guard protects a populated vector index")
