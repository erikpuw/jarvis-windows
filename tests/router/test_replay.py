import asyncio, sys
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from engine.router import replay


def _engine(cands):
    return SimpleNamespace(get_exact_workflow_candidates=lambda text: list(cands),
                           get_recent_agent_outcomes=lambda limit=3: [])


def _find(cands, attachment=None, monkeypatch=None):
    monkeypatch.setattr(replay, "_learning", lambda: _engine(cands))
    return asyncio.run(replay.find_replay("mở steam", attachment))


W = lambda agent, i=1: {"id": i, "agent": agent, "tool_chain": ["open_app"]}


def test_single_exact_workflow_is_replayed(monkeypatch):
    assert _find([W("desktop")], monkeypatch=monkeypatch) == {"id": 1, "agent": "desktop", "tool_chain": ["open_app"]}


def test_ambiguous_workflows_are_not_replayed(monkeypatch):
    assert _find([W("desktop", 1), W("search", 2)], monkeypatch=monkeypatch) is None


def test_office_and_rag_need_an_attachment(monkeypatch):
    assert _find([W("office")], monkeypatch=monkeypatch) is None
    assert _find([W("rag")], monkeypatch=monkeypatch) is None  # lỗi #7 của spec
    assert _find([W("rag")], attachment=object(), monkeypatch=monkeypatch) is None  # có đính kèm: không replay (đi gate)


def test_legacy_agent_names_are_normalized(monkeypatch):
    wf = lambda agent, tool: {"id": 1, "agent": agent, "tool_chain": [tool]}
    assert _find([wf("check_project", "check_project")], monkeypatch=monkeypatch)["agent"] == "project"
    assert _find([wf("learning", "query_history")], monkeypatch=monkeypatch)["agent"] == "history"


def test_legacy_search_agent_maps_to_the_agent_of_its_first_tool(monkeypatch):
    wf = {"id": 3, "agent": "search", "tool_chain": ["get_market_data"]}
    assert _find([wf], monkeypatch=monkeypatch) == {"id": 3, "agent": "market", "tool_chain": ["get_market_data"]}


def test_learning_failure_means_no_replay(monkeypatch):
    def boom():
        raise RuntimeError("db locked")
    monkeypatch.setattr(replay, "_learning", boom)
    assert asyncio.run(replay.find_replay("mở steam", None)) is None
