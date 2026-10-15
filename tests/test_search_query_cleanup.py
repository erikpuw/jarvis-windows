"""Tests for engine.tools.search_engine.strip_conversational_filler. Run: python tests/test_search_query_cleanup.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.tools.search_engine import strip_conversational_filler


def test_real_log_case_drops_pronoun_and_question_tail():
    """jarvis.log 06:43: the whole sentence went to Google News and returned 0 news URLs."""
    got = strip_conversational_filler("bạn tìm tin tức về nvidia rtx spark có gì nổi bật không?")
    assert got == "tìm tin tức về nvidia rtx spark", got


def test_polite_padding_on_both_sides():
    got = strip_conversational_filler("Jarvis, giúp tôi tìm tin tức bão số 5 nhé")
    assert got == "tìm tin tức bão số 5", got


def test_already_clean_queries_are_unchanged():
    for q in ("tìm tin tức nvidia rtx spark", "tin tức nóng thời sự hôm nay"):  # 2nd = query tin tức nóng (cũ của greeting đã xoá)
        assert strip_conversational_filler(q) == q, q


def test_never_returns_empty():
    assert strip_conversational_filler("bạn .") == "bạn .", "stripping everything must fall back to the input"
    assert strip_conversational_filler("") == ""


if __name__ == "__main__":
    test_real_log_case_drops_pronoun_and_question_tail()
    test_polite_padding_on_both_sides()
    test_already_clean_queries_are_unchanged()
    test_never_returns_empty()
    print("OK: all search query cleanup tests passed")
