"""Tests for the Wikipedia path in engine.core.mcp_context. Run: python tests/test_mcp_wiki.py"""
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.core import mcp_context as mc


def test_question_scaffolding_is_stripped():
    """The exact question from the log: the whole sentence matched nothing."""
    assert mc._wiki_search_query("lịch sử việt nam năm 1945 có những thay đổi nào") == "lịch sử việt nam năm 1945"


def test_who_and_what_questions():
    assert mc._wiki_search_query("Hồ Chí Minh là ai?") == "hồ chí minh"
    assert mc._wiki_search_query("cho tôi biết vịnh Hạ Long là gì") == "vịnh hạ long"


def test_query_is_capped():
    q = mc._wiki_search_query("một hai ba bốn năm sáu bảy tám chín mười")
    assert len(q.split()) == mc._WIKI_MAX_TERMS, q


class Result:
    def __init__(self, payload):
        self.structuredContent = payload
        self.content = []


class FakeHub:
    """Only answers searches for queries in `known`; records every call."""
    def __init__(self, known, summary_delay=0.0, search_delay=0.0):
        self.known = known
        self.summary_delay = summary_delay
        self.search_delay = search_delay
        self.calls = []

    async def call_tool(self, srv, tool, args):
        self.calls.append((tool, dict(args)))
        if tool == "search_wikipedia":
            if self.search_delay:
                await asyncio.sleep(self.search_delay)
            hits = self.known.get(args["query"], [])
            return Result({"query": args["query"], "results": hits, "status": "success" if hits else "no_results"})
        if tool == "get_summary":
            if self.summary_delay:
                await asyncio.sleep(self.summary_delay)
            return Result({"title": args["title"], "summary": f"Tóm tắt {args['title']}"})
        raise AssertionError(f"unexpected tool {tool}")


HITS = [
    {"title": "Cách mạng Tháng Tám", "snippet": "<span>1945</span>"},
    {"title": "Tuyên ngôn độc lập", "snippet": "2/9/1945"},
]


def test_keyword_search_then_summaries():
    hub = FakeHub({"lịch sử việt nam năm 1945": HITS})
    ctx = asyncio.run(mc._build_wikipedia_context(hub, "wikipedia-vi", "lịch sử việt nam năm 1945 có những thay đổi nào", 1200))
    assert "Cách mạng Tháng Tám" in ctx and "Tóm tắt Tuyên ngôn độc lập" in ctx, ctx
    searched = [a["query"] for t, a in hub.calls if t == "search_wikipedia"]
    assert searched == ["lịch sử việt nam năm 1945"], searched
    assert all(t != "test_wikipedia_connectivity" for t, _ in hub.calls)


def test_falls_back_to_a_shorter_query():
    hub = FakeHub({"lịch sử việt": HITS[:1]})
    ctx = asyncio.run(mc._build_wikipedia_context(hub, "wikipedia-vi", "lịch sử việt nam năm 1945 có những thay đổi nào", 1200))
    assert "Cách mạng Tháng Tám" in ctx, ctx


def test_nothing_found_returns_empty_so_the_model_answers_itself():
    hub = FakeHub({})
    ctx = asyncio.run(mc._build_wikipedia_context(hub, "wikipedia-vi", "câu hỏi không ai biết xyz", 1200))
    assert ctx == ""


def test_summaries_are_fetched_in_parallel():
    hub = FakeHub({"lịch sử việt nam năm 1945": HITS}, summary_delay=0.4)
    started = time.monotonic()
    asyncio.run(mc._build_wikipedia_context(hub, "wikipedia-vi", "lịch sử việt nam năm 1945", 1200))
    elapsed = time.monotonic() - started
    assert elapsed < 0.7, f"two 0.4s summaries took {elapsed:.2f}s — not parallel"


def test_a_stalled_server_is_cut_off():
    original = mc._WIKI_CALL_TIMEOUT
    mc._WIKI_CALL_TIMEOUT = 0.2
    try:
        hub = FakeHub({"lịch sử việt nam năm 1945": HITS}, search_delay=5.0)
        started = time.monotonic()
        ctx = asyncio.run(mc._build_wikipedia_context(hub, "wikipedia-vi", "lịch sử việt nam năm 1945", 1200))
        elapsed = time.monotonic() - started
    finally:
        mc._WIKI_CALL_TIMEOUT = original
    assert ctx == ""
    assert elapsed < 1.5, f"a stalled search held the turn for {elapsed:.1f}s"


if __name__ == "__main__":
    test_question_scaffolding_is_stripped()
    test_who_and_what_questions()
    test_query_is_capped()
    test_keyword_search_then_summaries()
    test_falls_back_to_a_shorter_query()
    test_nothing_found_returns_empty_so_the_model_answers_itself()
    test_summaries_are_fetched_in_parallel()
    test_a_stalled_server_is_cut_off()
    print("OK: all MCP Wikipedia tests passed")
