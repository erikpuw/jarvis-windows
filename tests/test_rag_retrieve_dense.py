"""Truy xuất RAG xếp theo điểm gần nghĩa của vector (2026-10-17: rerank cũ BM25+RRF+trùng âm tiết làm phần nghĩa
chỉ còn ~4% điểm → "thực đơn thứ 5" ra sách AI vì đủ chữ "thực/đơn/thứ/5"; đo tests/live/probes/rag_probe.py).
Run: python -m pytest tests/test_rag_retrieve_dense.py -q"""
import asyncio
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.core.rag_engine import RAGEngine  # noqa: E402
from engine.rag import runner  # noqa: E402


class _Index:
    """turbovec giả: trả điểm dựng sẵn theo id (cao → thấp như turbovec)."""

    def __init__(self, scores: dict[int, float]):
        self.scores = scores

    def __len__(self):
        return len(self.scores)

    def search(self, q, k):
        top = sorted(self.scores.items(), key=lambda kv: kv[1], reverse=True)[:k]
        return np.array([[s for _, s in top]], dtype=np.float32), np.array([[i for i, _ in top]], dtype=np.int64)


def _engine(rows):
    """rows: [(id, filename, content, score)]"""
    rag = RAGEngine(persistent=False)
    rag.chunks = [{"id": i, "doc_index": i, "filename": f, "file_path": f, "content": c, "token_est": 50}
                  for i, f, c, _ in rows]
    rag.vector_index = _Index({i: s for i, _, _, s in rows})

    async def emb(text):
        return [0.0] * rag.dim
    rag._get_embedding = emb
    return rag


ROWS = [
    (0, "ai.pdf", "Bước thứ 5: thực hiện đơn giản hoá thực đơn công cụ", 0.70),   # đủ âm tiết, khác nghĩa
    (1, "food.pdf", "Bữa 2 Ngày 4: cơm gà, rau luộc", 0.76),
    (2, "food.pdf", "Bữa phụ: sữa chua, chuối", 0.74),
    (3, "gym.pdf", "Upper B: ngực, lưng", 0.69),
]


def test_ranking_follows_meaning_not_shared_syllables():
    out = asyncio.run(_engine(ROWS).retrieve("thực đơn thứ 5", top_k=5))
    assert [c["id"] for c in out] == [1, 2, 0, 3]
    assert out[0]["score"] == 0.76


def test_rel_cut_keeps_only_chunks_close_to_the_best():
    out = asyncio.run(_engine(ROWS).retrieve("thực đơn thứ 5", top_k=5, rel_cut=0.05))
    assert [c["id"] for c in out] == [1, 2]


def test_answer_gets_nothing_when_even_the_best_chunk_is_off_topic():
    rows = [(0, "ai.pdf", "Agent gọi công cụ", 0.72), (1, "food.pdf", "Bữa 2", 0.70)]
    assert asyncio.run(runner.retrieve_for_answer(_engine(rows), "giá vàng hôm nay")) == []


def test_answer_keeps_a_low_scoring_chunk_that_contains_the_exact_term():
    rows = [(0, "gym.pdf", "Làm McGill Big 3 mỗi sáng", 0.67), (1, "ai.pdf", "Agent", 0.64)]
    out = asyncio.run(runner.retrieve_for_answer(_engine(rows), "McGill Big 3"))
    assert [c["filename"] for c in out] == ["gym.pdf"]


def test_answer_sources_list_only_the_close_chunks():
    out = asyncio.run(runner.retrieve_for_answer(_engine(ROWS), "thực đơn thứ 5"))
    assert {c["filename"] for c in out} == {"food.pdf"}


def test_exact_term_match_drops_close_but_unrelated_chunks():
    rows = [(0, "ghi_chu.md", 'Mật khẩu khách là "khachquy2026"', 0.78), (1, "ai.pdf", "Agent bảo mật", 0.75)]
    out = asyncio.run(runner.retrieve_for_answer(_engine(rows), "khachquy2026"))
    assert [c["filename"] for c in out] == ["ghi_chu.md"]
